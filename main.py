"""
Основний скрипт моніторингу графіків ДТЕК
"""
import asyncio
import json
import random
import re
from datetime import datetime, timezone
from time import sleep

import pytz
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

from config import (
    SHUTDOWNS_URL,
    YOUR_QUEUE,
    CHECK_INTERVAL_MINUTES, CHECK_INTERVAL_JITTER_PERCENT,
    TIMEZONE, REDIS_HOST, REDIS_PORT, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, ALERT_TELEGRAM_CHAT_ID,
    PLAYWRIGHT_BROWSER, PLAYWRIGHT_PROFILE_DIR, PLAYWRIGHT_HEADLESS, PLAYWRIGHT_USER_AGENT,
    AUTO_HEADFUL_ON_BLOCK, MAX_BACKOFF_MINUTES, MIN_BLOCK_BACKOFF_MINUTES, DEGRADED_MIN_MINUTES, DEGRADED_MAX_MINUTES,
    BLOCK_ALERT_COOLDOWN_MINUTES,
    PLAYWRIGHT_GOTO_TIMEOUT_MS, DTEK_COOKIE
)
from logger import logger
from senders import send_telegram_message, generate_schedule_message
from storage import ScheduleStorage


def _looks_like_blocked_page(content: str) -> bool:
    return "Incapsula incident ID" in content or "_Incapsula_Resource" in content


def _calculate_backoff_seconds(error_count: int) -> int:
    # Exponential backoff with cap, but never faster than the normal interval.
    base = 60
    max_backoff = max(1, MAX_BACKOFF_MINUTES) * 60
    backoff = min(base * (2 ** (error_count - 1)), max_backoff)
    return max(backoff, CHECK_INTERVAL_MINUTES * 60)


def _with_jitter(seconds: int, jitter_percent: int) -> int:
    """Додає випадковий jitter до інтервалу очікування."""
    if jitter_percent <= 0:
        return max(1, int(seconds))
    spread = int(seconds * (jitter_percent / 100.0))
    return max(1, int(seconds + random.randint(-spread, spread)))


def _calculate_degraded_wait_seconds(error_count: int, degraded_level: int) -> int:
    """Розрахунок базового інтервалу degraded-polling без jitter."""
    degraded_base_seconds = max(DEGRADED_MIN_MINUTES * 60, MIN_BLOCK_BACKOFF_MINUTES * 60)
    degraded_wait = degraded_base_seconds * (2 ** (max(1, degraded_level) - 1))
    degraded_wait = min(degraded_wait, max(DEGRADED_MIN_MINUTES, DEGRADED_MAX_MINUTES) * 60)
    return max(_calculate_backoff_seconds(error_count), degraded_wait)


def get_shutdowns_html(force_headful: bool = False):
    """Отримує HTML сторінки через Playwright"""
    with sync_playwright() as p:
        browser_type = getattr(p, PLAYWRIGHT_BROWSER, p.chromium)
        context = browser_type.launch_persistent_context(
            PLAYWRIGHT_PROFILE_DIR,
            headless=PLAYWRIGHT_HEADLESS if not force_headful else False,
            viewport={"width": 1280, "height": 720},
            locale="uk-UA",
            timezone_id=TIMEZONE,
        )

        try:
            if DTEK_COOKIE:
                cookies = []
                for part in DTEK_COOKIE.split(";"):
                    part = part.strip()
                    if not part or "=" not in part:
                        continue
                    name, value = part.split("=", 1)
                    cookies.append(
                        {
                            "name": name.strip(),
                            "value": value.strip(),
                            "domain": "www.dtek-krem.com.ua",
                            "path": "/",
                        }
                    )
                if cookies:
                    logger.info(f"🍪 Передаю cookies у browser context: {len(cookies)} шт.")
                    context.add_cookies(cookies)
            page = context.new_page()
            if PLAYWRIGHT_USER_AGENT:
                logger.info("🧭 Використовую кастомний User-Agent для Playwright.")
                page.set_extra_http_headers({"User-Agent": PLAYWRIGHT_USER_AGENT})
            page.set_default_navigation_timeout(PLAYWRIGHT_GOTO_TIMEOUT_MS)

            logger.info(f"🔄 Завантажую {SHUTDOWNS_URL}...")
            try:
                page.goto(SHUTDOWNS_URL, wait_until="domcontentloaded", timeout=PLAYWRIGHT_GOTO_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                logger.warning(f"⚠️ Timeout {PLAYWRIGHT_GOTO_TIMEOUT_MS}ms при завантаженні, пробую взяти content.")
            except PlaywrightError as e:
                logger.error(f"❌ Помилка завантаження сторінки: {e}")
                return None, "error"

            page.wait_for_timeout(3000)
            try:
                page.wait_for_function(
                    "() => document.body && document.body.innerText.includes('DisconSchedule.fact')",
                    timeout=20000
                )
            except Exception:
                pass

            try:
                content = page.content()
            except PlaywrightError as e:
                logger.error(f"❌ Не вдалося прочитати content сторінки: {e}")
                return None, "error"

            if _looks_like_blocked_page(content):
                logger.error("❌ Сайт повернув Incapsula challenge.")
                # Give the JS challenge a chance to set cookies, then retry once in the same context.
                logger.info("⏳ Очікую 15с і роблю повторний запит у тому ж контексті...")
                page.wait_for_timeout(15000)
                try:
                    page.reload(wait_until="domcontentloaded", timeout=PLAYWRIGHT_GOTO_TIMEOUT_MS)
                    page.wait_for_timeout(3000)
                    content = page.content()
                except PlaywrightError as e:
                    logger.error(f"❌ Retry після challenge завершився помилкою: {e}")
                    return None, "blocked"

                if _looks_like_blocked_page(content):
                    return None, "blocked"

            logger.info(f"✅ Отримано {len(content)} байт")
            return content, "ok"
        finally:
            context.close()


def extract_schedule_data(html):
    """Витягує дані з DisconSchedule.fact"""
    try:
        start_pattern = r'DisconSchedule\.fact\s*=\s*'
        start_match = re.search(start_pattern, html)

        if not start_match:
            logger.error("❌ Не знайдено 'DisconSchedule.fact ='")
            return None

        start_pos = start_match.end()
        json_str = _extract_balanced_json(html, start_pos)

        if not json_str:
            logger.error("❌ Не вдалося витягнути JSON об'єкт")
            return None

        # Очищаємо від коментарів
        json_str = re.sub(r'//.*?\n', '\n', json_str)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)

        fact_data = json.loads(json_str)

        if 'data' not in fact_data:
            logger.error("❌ Поле 'data' не знайдено")
            return None

        schedule_data = fact_data['data']
        logger.info(f"✅ Знайдено {len(schedule_data)} дат(и) з графіками")

        update = fact_data.get('update', "")
        if update:
            logger.info(f"ℹ️  Оновлено на сайті: {update}")

        return {
            'data': schedule_data,
            'update': update,
            'today': fact_data.get('today')
        }

    except json.JSONDecodeError as e:
        logger.error(f"❌ Помилка парсингу JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Помилка: {e}")
        return None


def _extract_balanced_json(text, start_pos):
    """Витягує JSON об'єкт з балансуванням дужок"""
    if start_pos >= len(text) or text[start_pos] != '{':
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start_pos, len(text)):
        char = text[i]

        if escape:
            escape = False
            continue

        if char == '\\':
            escape = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[start_pos:i + 1]

    return None


def parse_shutdowns(data, queue_name):
    """
    Парсить графік відключень для конкретної черги

    Args:
        data: Дані з DisconSchedule.fact.data
        queue_name: Назва черги (наприклад 'GPV3.2')

    Returns:
        Dict з датами та часами відключень
        Формат: {'2024-11-23': ['5:00', '5:30', '6:00'], ...}
    """
    result = {}
    tz = pytz.timezone(TIMEZONE)

    for utc_timestamp, groups in data.items():
        # Конвертуємо timestamp в локальну дату
        try:
            if not str(utc_timestamp).isdigit():
                continue

            utc_date = datetime.fromtimestamp(int(utc_timestamp), tz=timezone.utc)
            local_date = utc_date.astimezone(tz).strftime('%Y-%m-%d')

            if queue_name not in groups:
                continue

            hours = groups[queue_name]
            # Представляємо відключення як 30-хвилинні слоти (час початку слоту)
            half_hour_slots = []

            for hour, status in hours.items():
                hour_int = int(hour)
                if hour_int < 1 or hour_int > 24:
                    continue

                hour_start_minutes = (hour_int - 1) * 60

                # yes: світло є увесь слот
                # first: відключення у першій половині години (XX:00-XX:30)
                # second: відключення у другій половині години (XX:30-XX+1:00)
                # no: відключення увесь слот (дві половини)
                if status == "no":
                    half_hour_slots.extend([hour_start_minutes, hour_start_minutes + 30])
                elif status == "first":
                    half_hour_slots.append(hour_start_minutes)
                elif status == "second":
                    half_hour_slots.append(hour_start_minutes + 30)
        except ValueError:
            continue

        unique_sorted_slots = sorted(set(half_hour_slots))
        result[local_date] = [f"{slot // 60}:{slot % 60:02d}" for slot in unique_sorted_slots]

    return result


def main():
    """Головна функція моніторингу"""
    print("=" * 60)
    print("🚀 ДТЕК Моніторинг Графіків Відключень")
    print("=" * 60)
    print(f"📍 Черга: {YOUR_QUEUE}")
    print(f"⏱️  Інтервал: {CHECK_INTERVAL_MINUTES} хв")
    print(f"💾 Redis: redis://{REDIS_HOST}:{REDIS_PORT}/0")
    print("=" * 60)
    print(f"🌐 Browser: {PLAYWRIGHT_BROWSER} | headless: {PLAYWRIGHT_HEADLESS}")
    print(
        f"⏳ Backoff: max={MAX_BACKOFF_MINUTES} хв | "
        f"min_block={MIN_BLOCK_BACKOFF_MINUTES} хв | "
        f"auto_headful_on_block={AUTO_HEADFUL_ON_BLOCK}"
    )
    print(
        f"🎲 Jitter: {CHECK_INTERVAL_JITTER_PERCENT}% | "
        f"degraded={DEGRADED_MIN_MINUTES}-{DEGRADED_MAX_MINUTES} хв | "
        f"block_alert_cooldown={BLOCK_ALERT_COOLDOWN_MINUTES} хв"
    )
    print(
        f"🍪 DTEK_COOKIE: {'set' if bool(DTEK_COOKIE) else 'empty'} | "
        f"UA: {'set' if bool(PLAYWRIGHT_USER_AGENT) else 'empty'}"
    )
    print(
        f"📣 Alerts chat: {'custom' if bool(ALERT_TELEGRAM_CHAT_ID) else 'default TELEGRAM_CHAT_ID'}"
    )
    print()

    # Ініціалізуємо Redis
    storage = ScheduleStorage(f'redis://{REDIS_HOST}:{REDIS_PORT}/0')

    # Перевіряємо підключення
    if not storage.ping():
        logger.error("❌ Не вдалося підключитися до Redis!")
        print("Запустіть Redis: docker run -d -p 6379:6379 redis")
        return

    logger.info("✅ З'єднання з Redis успішне\n")

    iteration = 0
    error_count = 0
    block_count = 0
    attempted_headful = False
    last_block_alert_ts = None
    degraded_level = 0

    while True:
        try:
            iteration += 1
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            print(f"\n{'=' * 60}")
            print(f"🔄 Ітерація #{iteration} - {current_time}")
            print(f"{'=' * 60}")

            # 1. Отримуємо HTML
            force_headful = AUTO_HEADFUL_ON_BLOCK and not attempted_headful and block_count > 0
            if force_headful:
                logger.warning("⚠️ Спроба headful-режиму через xvfb для проходження Incapsula.")
            html, status = get_shutdowns_html(force_headful=force_headful)
            if force_headful:
                attempted_headful = True

            if not html:
                error_count += 1
                if status == "blocked":
                    if AUTO_HEADFUL_ON_BLOCK:
                        block_count += 1
                    alert_chat_id = ALERT_TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID
                    if TELEGRAM_TOKEN and alert_chat_id:
                        now_ts = datetime.now().timestamp()
                        cooldown_sec = max(1, BLOCK_ALERT_COOLDOWN_MINUTES) * 60
                        should_send_alert = (
                            last_block_alert_ts is None or (now_ts - last_block_alert_ts) >= cooldown_sec
                        )
                        if should_send_alert:
                            sent = asyncio.run(
                                send_telegram_message(
                                    TELEGRAM_TOKEN,
                                    alert_chat_id,
                                    "⚠️ Сайт вимагає перевірку людини (Incapsula). "
                                    "Потрібно оновити cookies або пройти перевірку вручну.",
                                )
                            )
                            if sent:
                                last_block_alert_ts = now_ts
                        else:
                            remaining_min = int((cooldown_sec - (now_ts - last_block_alert_ts)) // 60)
                            logger.info(f"ℹ️ Alert про блок вже надіслано, повтор через ~{remaining_min} хв.")
                    degraded_level += 1
                    wait_seconds = _calculate_degraded_wait_seconds(error_count, degraded_level)
                    wait_seconds = _with_jitter(wait_seconds, CHECK_INTERVAL_JITTER_PERCENT)
                    logger.error(
                        f"⛔ Заблоковано Incapsula, спроба №{error_count}, degraded-рівень={degraded_level}, "
                        f"наступна через {wait_seconds // 60} хв"
                    )
                else:
                    wait_seconds = _calculate_backoff_seconds(error_count)
                    wait_seconds = _with_jitter(wait_seconds, CHECK_INTERVAL_JITTER_PERCENT)
                    logger.error(
                        f"⚠️ Помилка завантаження, спроба №{error_count}, наступна через {wait_seconds // 60} хв"
                    )
                sleep(wait_seconds)
                continue

            # 2. Парсимо дані
            payload = extract_schedule_data(html)

            if not payload:
                logger.error("❌ Не вдалося розпарсити дані")
                error_count += 1
                wait_seconds = _calculate_backoff_seconds(error_count)
                logger.error(
                    f"⚠️ Помилка парсингу, спроба №{error_count}, наступна через {wait_seconds // 60} хв"
                )
                sleep(wait_seconds)
                continue

            raw_data = payload['data']

            # 3. Обробляємо графік для нашої черги
            schedule = parse_shutdowns(raw_data, YOUR_QUEUE)

            if not schedule:
                logger.info(f"⚠️  Графік для черги {YOUR_QUEUE} порожній")
                error_count = 0
                sleep(_with_jitter(CHECK_INTERVAL_MINUTES * 60, CHECK_INTERVAL_JITTER_PERCENT))
                continue

            logger.info(f"\n📊 Графік відключень для {YOUR_QUEUE}:")
            for date, times in schedule.items():
                logger.info(f"   {date}: {', '.join(times)}")

            # 4. Перевіряємо зміни
            if storage.has_changes(YOUR_QUEUE, schedule):
                logger.info("\n🔔 ЗНАЙДЕНО ЗМІНИ В ГРАФІКУ!")

                message = generate_schedule_message(schedule)
                if payload.get('update'):
                    message += f"\nОстаннє оновлення: {payload['update']}"

                # Відправляємо повідомлення. Зберігаємо стан тільки після успішної доставки.
                sent = asyncio.run(send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, message))
                if sent:
                    storage.save_schedule(YOUR_QUEUE, schedule)
                    storage.save_history(YOUR_QUEUE, schedule)
                else:
                    logger.error("❌ Графік не збережено, бо повідомлення не доставлено")

            else:
                logger.info("\nℹ️  Графік не змінився")

            # 5. Чекаємо до наступної перевірки
            print(f"\n⏳ Наступна перевірка через {CHECK_INTERVAL_MINUTES} хв...")
            error_count = 0
            block_count = 0
            attempted_headful = False
            degraded_level = 0
            sleep(_with_jitter(CHECK_INTERVAL_MINUTES * 60, CHECK_INTERVAL_JITTER_PERCENT))

        except KeyboardInterrupt:
            logger.info("\n\n⛔ Моніторинг зупинено користувачем")
            break

        except Exception as e:
            logger.error(f"\n❌ Неочікувана помилка: {e}")
            import traceback
            traceback.print_exc()
            error_count += 1
            wait_seconds = _with_jitter(_calculate_backoff_seconds(error_count), CHECK_INTERVAL_JITTER_PERCENT)
            logger.error(f"\n⏳ Повторна спроба через {wait_seconds // 60} хвилин...")
            sleep(wait_seconds)


if __name__ == "__main__":
    main()
