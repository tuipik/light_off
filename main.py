"""
Основний скрипт моніторингу графіків ДТЕК
"""
import asyncio
import json
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Dict, List, Optional

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
    PLAYWRIGHT_GOTO_TIMEOUT_MS, DTEK_COOKIE,
    BLOCK_DEBUG_ENABLED, BLOCK_DEBUG_DIR, BLOCK_DEBUG_MAX_ARTIFACTS
)
from logger import logger
from senders import send_telegram_message, generate_schedule_message
from storage import ScheduleStorage


@dataclass
class FetchResult:
    content: Optional[str]
    status: str
    mode: str
    attempt: int = 1
    used_headful: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


def _looks_like_blocked_page(content: str) -> bool:
    return "Incapsula incident ID" in content or "_Incapsula_Resource" in content


def _calculate_backoff_seconds(error_count: int) -> int:
    # Exponential backoff with cap, but never faster than the normal interval.
    base = 60
    max_backoff = max(1, MAX_BACKOFF_MINUTES) * 60
    backoff = min(base * (2 ** (error_count - 1)), max_backoff)
    return max(backoff, CHECK_INTERVAL_MINUTES * 60)


def _with_jitter(seconds: int, jitter_percent: int) -> int:
    """Додає випадковий jitter до інтервалу очікування, не зменшуючи базу."""
    if jitter_percent <= 0:
        return max(1, int(seconds))
    spread = int(seconds * (jitter_percent / 100.0))
    return max(1, int(seconds + random.randint(0, spread)))


def _format_wait(seconds: int) -> str:
    minutes = seconds // 60
    rem_seconds = seconds % 60
    if rem_seconds == 0:
        return f"{minutes} хв"
    return f"{minutes} хв {rem_seconds} с"


def _calculate_degraded_wait_seconds(error_count: int, degraded_level: int) -> int:
    """Розрахунок базового інтервалу degraded-polling без jitter."""
    degraded_base_seconds = max(DEGRADED_MIN_MINUTES * 60, MIN_BLOCK_BACKOFF_MINUTES * 60)
    degraded_wait = degraded_base_seconds * (2 ** (max(1, degraded_level) - 1))
    degraded_wait = min(degraded_wait, max(DEGRADED_MIN_MINUTES, DEGRADED_MAX_MINUTES) * 60)
    return max(_calculate_backoff_seconds(error_count), degraded_wait)


def _normalize_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._") or "artifact"


def _trim_debug_artifacts(debug_dir: Path, keep_count: int) -> None:
    if keep_count <= 0 or not debug_dir.exists():
        return

    entries = sorted(debug_dir.iterdir(), key=lambda entry: entry.stat().st_mtime, reverse=True)
    for old_entry in entries[keep_count:]:
        if old_entry.is_file():
            old_entry.unlink(missing_ok=True)


def _save_block_debug_artifacts(fetch_result: FetchResult, queue_name: str) -> Optional[Path]:
    if not BLOCK_DEBUG_ENABLED:
        return None

    debug_dir = Path(BLOCK_DEBUG_DIR)
    debug_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = _normalize_filename(f"{timestamp}_{queue_name}_{fetch_result.mode}_try{fetch_result.attempt}")

    metadata = {
        "timestamp": datetime.now().isoformat(),
        "queue": queue_name,
        "status": fetch_result.status,
        "mode": fetch_result.mode,
        "attempt": fetch_result.attempt,
        "used_headful": fetch_result.used_headful,
        "details": fetch_result.details,
    }

    meta_path = debug_dir / f"{prefix}.json"
    html_path = debug_dir / f"{prefix}.html"

    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(fetch_result.content or "", encoding="utf-8")
    _trim_debug_artifacts(debug_dir, BLOCK_DEBUG_MAX_ARTIFACTS * 2)
    return meta_path


def _can_run_headful() -> bool:
    """Перевіряє, чи можна запускати headful (є DISPLAY або вимкнений headless)."""
    if not PLAYWRIGHT_HEADLESS:
        return True
    return bool(os.getenv("DISPLAY"))


def _parse_cookie_header(cookie_header: Optional[str]) -> List[Dict[str, str]]:
    cookies = []
    if not cookie_header:
        return cookies

    for part in cookie_header.split(";"):
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
    return cookies


def _read_page_content_with_retries(page, attempts: int = 4, delay_ms: int = 1500) -> str:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return page.content()
        except PlaywrightError as e:
            last_error = e
            if "page is navigating and changing the content" not in str(e).lower() or attempt == attempts:
                raise
            logger.warning(
                f"⚠️ Сторінка ще навігується під час читання content, повтор {attempt}/{attempts}."
            )
            page.wait_for_timeout(delay_ms)

    raise last_error


def _playwright_fetch_shutdowns(force_headful: bool = False, same_context_retries: int = 1) -> FetchResult:
    """Отримує HTML сторінки через Playwright"""
    cookies = _parse_cookie_header(DTEK_COOKIE)

    with sync_playwright() as p:
        browser_type = getattr(p, PLAYWRIGHT_BROWSER, p.chromium)
        try:
            context = browser_type.launch_persistent_context(
                PLAYWRIGHT_PROFILE_DIR,
                headless=PLAYWRIGHT_HEADLESS if not force_headful else False,
                viewport={"width": 1280, "height": 720},
                locale="uk-UA",
                timezone_id=TIMEZONE,
            )
        except PlaywrightError as e:
            logger.error(f"❌ Не вдалося запустити browser context: {e}")
            return FetchResult(
                content=None,
                status="error",
                mode="playwright_headful" if force_headful else "playwright_headless",
                used_headful=force_headful,
                details={
                    "headful": force_headful,
                    "profile_dir": PLAYWRIGHT_PROFILE_DIR,
                    "exception": str(e),
                },
            )

        try:
            if cookies:
                logger.info(f"🍪 Передаю cookies у browser context: {len(cookies)} шт.")
                context.add_cookies(cookies)
            page = context.new_page()
            if PLAYWRIGHT_USER_AGENT:
                logger.info("🧭 Використовую кастомний User-Agent для Playwright.")
                page.set_extra_http_headers({"User-Agent": PLAYWRIGHT_USER_AGENT})
            page.set_default_navigation_timeout(PLAYWRIGHT_GOTO_TIMEOUT_MS)

            browser_name = getattr(browser_type, "name", PLAYWRIGHT_BROWSER)
            base_details = {
                "browser": browser_name,
                "headful": force_headful,
                "profile_dir": PLAYWRIGHT_PROFILE_DIR,
                "configured_cookie_count": len(cookies),
            }

            for attempt in range(1, same_context_retries + 2):
                logger.info(f"🔄 Завантажую {SHUTDOWNS_URL}... (mode=playwright, attempt={attempt})")
                try:
                    if attempt == 1:
                        response = page.goto(
                            SHUTDOWNS_URL,
                            wait_until="domcontentloaded",
                            timeout=PLAYWRIGHT_GOTO_TIMEOUT_MS,
                        )
                    else:
                        response = page.reload(
                            wait_until="domcontentloaded",
                            timeout=PLAYWRIGHT_GOTO_TIMEOUT_MS,
                        )
                except PlaywrightTimeoutError:
                    logger.warning(
                        f"⚠️ Timeout {PLAYWRIGHT_GOTO_TIMEOUT_MS}ms при завантаженні, пробую взяти content."
                    )
                    response = None
                except PlaywrightError as e:
                    logger.error(f"❌ Помилка завантаження сторінки: {e}")
                    return FetchResult(
                        content=None,
                        status="error",
                        mode="playwright_headful" if force_headful else "playwright_headless",
                        attempt=attempt,
                        used_headful=force_headful,
                        details={**base_details, "exception": str(e)},
                    )

                page.wait_for_timeout(3000)
                try:
                    page.wait_for_function(
                        "() => document.body && document.body.innerText.includes('DisconSchedule.fact')",
                        timeout=20000
                    )
                except Exception:
                    pass

                try:
                    content = _read_page_content_with_retries(page)
                except PlaywrightError as e:
                    logger.error(f"❌ Не вдалося прочитати content сторінки: {e}")
                    return FetchResult(
                        content=None,
                        status="error",
                        mode="playwright_headful" if force_headful else "playwright_headless",
                        attempt=attempt,
                        used_headful=force_headful,
                        details={**base_details, "exception": str(e)},
                    )

                context_cookies = context.cookies()
                details = {
                    **base_details,
                    "response_status": response.status if response else None,
                    "response_url": response.url if response else page.url,
                    "response_headers": response.all_headers() if response else {},
                    "context_cookie_count": len(context_cookies),
                    "context_cookies": context_cookies,
                    "page_title": page.title(),
                }

                if _looks_like_blocked_page(content):
                    logger.error("❌ Сайт повернув Incapsula challenge.")
                    if attempt <= same_context_retries:
                        logger.info("⏳ Очікую 15с і роблю повторний запит у тому ж контексті...")
                        page.wait_for_timeout(15000)
                        continue

                    return FetchResult(
                        content=content,
                        status="blocked",
                        mode="playwright_headful" if force_headful else "playwright_headless",
                        attempt=attempt,
                        used_headful=force_headful,
                        details=details,
                    )

                logger.info(f"✅ Отримано {len(content)} байт")
                return FetchResult(
                    content=content,
                    status="ok",
                    mode="playwright_headful" if force_headful else "playwright_headless",
                    attempt=attempt,
                    used_headful=force_headful,
                    details=details,
                )
        finally:
            context.close()


def get_shutdowns_html(recovery_step: int = 0) -> FetchResult:
    if recovery_step == 0:
        return _playwright_fetch_shutdowns(force_headful=False, same_context_retries=1)
    if recovery_step == 1:
        logger.warning("⚠️ Перезапускаю браузерний процес з тим самим профілем.")
        return _playwright_fetch_shutdowns(force_headful=False, same_context_retries=0)
    if recovery_step == 2:
        if not AUTO_HEADFUL_ON_BLOCK:
            return FetchResult(content=None, status="error", mode="headful_disabled")
        if not _can_run_headful():
            return FetchResult(content=None, status="error", mode="headful_unavailable")
        logger.warning("⚠️ Переходжу в headful-режим через xvfb для відновлення сесії.")
        return _playwright_fetch_shutdowns(force_headful=True, same_context_retries=0)

    return FetchResult(content=None, status="error", mode="recovery_exhausted", details={"step": recovery_step})


def _fetch_with_recovery_ladder(queue_name: str) -> FetchResult:
    attempts = []
    max_recovery_steps = 3 if AUTO_HEADFUL_ON_BLOCK else 2

    for recovery_step in range(max_recovery_steps):
        result = get_shutdowns_html(recovery_step=recovery_step)
        attempts.append({"step": recovery_step, "status": result.status, "mode": result.mode})

        if result.status == "ok":
            result.details["recovery_attempts"] = attempts
            return result

        if result.status == "blocked":
            artifact_path = _save_block_debug_artifacts(result, queue_name)
            if artifact_path:
                result.details["artifact_path"] = str(artifact_path)
                logger.warning(f"🧾 Збережено debug artifact: {artifact_path}")
            continue

        if result.status == "error" and recovery_step < (max_recovery_steps - 1):
            logger.warning(f"⚠️ Fetch завершився помилкою в режимі {result.mode}, пробую наступний крок recovery.")
            continue

        result.details["recovery_attempts"] = attempts
        return result

    return FetchResult(
        content=None,
        status="blocked",
        mode="recovery_exhausted",
        details={"recovery_attempts": attempts},
    )


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
            fetch_result = _fetch_with_recovery_ladder(YOUR_QUEUE)
            html = fetch_result.content

            if not html:
                error_count += 1
                if fetch_result.status == "blocked":
                    alert_chat_id = ALERT_TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID
                    if TELEGRAM_TOKEN and alert_chat_id:
                        now_ts = datetime.now().timestamp()
                        cooldown_sec = max(1, BLOCK_ALERT_COOLDOWN_MINUTES) * 60
                        should_send_alert = (
                            last_block_alert_ts is None or (now_ts - last_block_alert_ts) >= cooldown_sec
                        )
                        if should_send_alert:
                            artifact_note = ""
                            artifact_path = fetch_result.details.get("artifact_path")
                            if artifact_path:
                                artifact_note = f"\nDebug artifact: {artifact_path}"
                            sent = asyncio.run(
                                send_telegram_message(
                                    TELEGRAM_TOKEN,
                                    alert_chat_id,
                                    "⚠️ Сайт вимагає перевірку людини (Incapsula). "
                                    "Потрібно оновити cookies або пройти перевірку вручну."
                                    f"\nРежим: {fetch_result.mode}{artifact_note}",
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
                        f"⛔ Заблоковано Incapsula, режим={fetch_result.mode}, "
                        f"спроба №{error_count}, degraded-рівень={degraded_level}, "
                        f"наступна через {_format_wait(wait_seconds)}"
                    )
                else:
                    wait_seconds = _calculate_backoff_seconds(error_count)
                    wait_seconds = _with_jitter(wait_seconds, CHECK_INTERVAL_JITTER_PERCENT)
                    logger.error(
                        f"⚠️ Помилка завантаження ({fetch_result.mode}), "
                        f"спроба №{error_count}, наступна через {_format_wait(wait_seconds)}"
                    )
                sleep(wait_seconds)
                continue

            # 2. Парсимо дані
            payload = extract_schedule_data(html)

            if not payload:
                logger.error("❌ Не вдалося розпарсити дані")
                error_count += 1
                wait_seconds = _calculate_backoff_seconds(error_count)
                wait_seconds = _with_jitter(wait_seconds, CHECK_INTERVAL_JITTER_PERCENT)
                logger.error(
                    f"⚠️ Помилка парсингу, спроба №{error_count}, наступна через {_format_wait(wait_seconds)}"
                )
                sleep(wait_seconds)
                continue

            raw_data = payload['data']

            # 3. Обробляємо графік для нашої черги
            schedule = parse_shutdowns(raw_data, YOUR_QUEUE)

            if not schedule:
                logger.info(f"⚠️  Графік для черги {YOUR_QUEUE} порожній")
                error_count = 0
                next_wait_seconds = _with_jitter(CHECK_INTERVAL_MINUTES * 60, CHECK_INTERVAL_JITTER_PERCENT)
                logger.info(f"⏳ Наступна перевірка порожнього графіка через {_format_wait(next_wait_seconds)}")
                sleep(next_wait_seconds)
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
            next_wait_seconds = _with_jitter(CHECK_INTERVAL_MINUTES * 60, CHECK_INTERVAL_JITTER_PERCENT)
            print(f"\n⏳ Наступна перевірка через {_format_wait(next_wait_seconds)}...")
            error_count = 0
            degraded_level = 0
            sleep(next_wait_seconds)

        except KeyboardInterrupt:
            logger.info("\n\n⛔ Моніторинг зупинено користувачем")
            break

        except Exception as e:
            logger.error(f"\n❌ Неочікувана помилка: {e}")
            import traceback
            traceback.print_exc()
            error_count += 1
            wait_seconds = _with_jitter(_calculate_backoff_seconds(error_count), CHECK_INTERVAL_JITTER_PERCENT)
            logger.error(f"\n⏳ Повторна спроба через {_format_wait(wait_seconds)}...")
            sleep(wait_seconds)


if __name__ == "__main__":
    main()
