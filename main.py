"""
Основний скрипт моніторингу графіків ДТЕК
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from time import sleep

import pytz
from playwright.sync_api import sync_playwright

from config import (
    SHUTDOWNS_URL,
    YOUR_QUEUE,
    CHECK_INTERVAL_MINUTES,
    TIMEZONE, REDIS_HOST, REDIS_PORT, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
)
from senders import send_telegram_message, generate_schedule_message
from storage import ScheduleStorage


def get_shutdowns_html():
    """Отримує HTML сторінки через Playwright"""
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        page = browser.new_page()

        print(f"🔄 Завантажую {SHUTDOWNS_URL}...")
        page.goto(SHUTDOWNS_URL)

        content = page.content()
        browser.close()

        print(f"✅ Отримано {len(content)} байт")
        return content


def extract_schedule_data(html):
    """Витягує дані з DisconSchedule.fact"""
    try:
        start_pattern = r'DisconSchedule\.fact\s*=\s*'
        start_match = re.search(start_pattern, html)

        if not start_match:
            print("❌ Не знайдено 'DisconSchedule.fact ='")
            return None

        start_pos = start_match.end()
        json_str = _extract_balanced_json(html, start_pos)

        if not json_str:
            print("❌ Не вдалося витягнути JSON об'єкт")
            return None

        # Очищаємо від коментарів
        json_str = re.sub(r'//.*?\n', '\n', json_str)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)

        fact_data = json.loads(json_str)

        if 'data' not in fact_data:
            print("❌ Поле 'data' не знайдено")
            return None

        schedule_data = fact_data['data']
        print(f"✅ Знайдено {len(schedule_data)} дат(и) з графіками")
        schedule_data['update'] = ""

        if 'update' in fact_data:
            schedule_data['update'] = fact_data['update']
            print(f"ℹ️  Оновлено на сайті: {fact_data['update']}")

        return schedule_data

    except json.JSONDecodeError as e:
        print(f"❌ Помилка парсингу JSON: {e}")
        return None
    except Exception as e:
        print(f"❌ Помилка: {e}")
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
            utc_date = datetime.fromtimestamp(int(utc_timestamp), tz=timezone.utc)
            local_date = utc_date.astimezone(tz).strftime('%Y-%m-%d')

            if queue_name not in groups:
                continue

            hours = groups[queue_name]
            shutdown_times = []

            for hour, status in hours.items():
                hour_int = int(hour)

                # "no" = відключення всю годину
                if status == "no":
                    shutdown_times.append(f"{hour_int - 1}:00")

                elif status in ["first", "second"]:
                    shutdown_times.append(f"{hour_int - 1}:30")
        except ValueError:
            continue

        result[local_date] = sorted(shutdown_times, key=lambda t: tuple(map(int, t.split(':'))))

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
    print()

    # Ініціалізуємо Redis
    storage = ScheduleStorage(f'redis://{REDIS_HOST}:{REDIS_PORT}/0')

    # Перевіряємо підключення
    if not storage.ping():
        print("❌ Не вдалося підключитися до Redis!")
        print("Запустіть Redis: docker run -d -p 6379:6379 redis")
        return

    print("✅ З'єднання з Redis успішне\n")

    iteration = 0

    while True:
        try:
            iteration += 1
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            print(f"\n{'=' * 60}")
            print(f"🔄 Ітерація #{iteration} - {current_time}")
            print(f"{'=' * 60}")

            # 1. Отримуємо HTML
            html = get_shutdowns_html()

            if not html:
                print("❌ Не вдалося отримати HTML")
                sleep(60)
                continue

            # 2. Парсимо дані
            raw_data = extract_schedule_data(html)

            if not raw_data:
                print("❌ Не вдалося розпарсити дані")
                sleep(60)
                continue

            # 3. Обробляємо графік для нашої черги
            schedule = parse_shutdowns(raw_data, YOUR_QUEUE)

            if not schedule:
                print(f"⚠️  Графік для черги {YOUR_QUEUE} порожній")
                sleep(CHECK_INTERVAL_MINUTES * 60)
                continue

            print(f"\n📊 Графік відключень для {YOUR_QUEUE}:")
            for date, times in schedule.items():
                print(f"   {date}: {', '.join(times)}")

            # 4. Перевіряємо зміни
            if storage.has_changes(YOUR_QUEUE, schedule):
                print("\n🔔 ЗНАЙДЕНО ЗМІНИ В ГРАФІКУ!")

                message = generate_schedule_message(schedule)
                message += f"\nОстаннє оновлення: {raw_data['update']}"

                # Відправляємо повідомлення
                asyncio.run(send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, message))

                # Зберігаємо новий графік
                storage.save_schedule(YOUR_QUEUE, schedule)  # Вкажіть ваші дані для Telegram
                storage.save_history(YOUR_QUEUE, schedule)

            else:
                print("\nℹ️  Графік не змінився")

            # 5. Чекаємо до наступної перевірки
            print(f"\n⏳ Наступна перевірка через {CHECK_INTERVAL_MINUTES} хв...")
            sleep(CHECK_INTERVAL_MINUTES * 60)

        except KeyboardInterrupt:
            print("\n\n⛔ Моніторинг зупинено користувачем")
            break

        except Exception as e:
            print(f"\n❌ Неочікувана помилка: {e}")
            import traceback
            traceback.print_exc()
            print("\n⏳ Повторна спроба через 1 хвилину...")
            sleep(60)


if __name__ == "__main__":
    main()
