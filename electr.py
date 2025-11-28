import json
import re
from datetime import datetime, timezone
from time import sleep

import pytz
from playwright.sync_api import sync_playwright

SHUTDOWNS_URL = 'https://www.dtek-krem.com.ua/ua/shutdowns'

def get_shutdowns_html():
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        page = browser.new_page()

        page.goto(SHUTDOWNS_URL)

        content = page.content()
        browser.close()

        return content


def extract_schedule_data(html):
    """Витягує дані з DisconSchedule.fact"""
    try:
        # Метод 1: Шукаємо DisconSchedule.fact = {...}; з балансуванням дужок
        start_pattern = r'DisconSchedule\.fact\s*=\s*'
        start_match = re.search(start_pattern, html)

        if not start_match:
            print("❌ Не знайдено 'DisconSchedule.fact ='")
            return None

        # Знаходимо початок JSON об'єкта
        start_pos = start_match.end()

        # Витягуємо JSON з балансуванням дужок
        json_str = _extract_balanced_json(html, start_pos)

        if not json_str:
            print("❌ Не вдалося витягнути JSON об'єкт")
            return None

        # Очищаємо від коментарів
        json_str = re.sub(r'//.*?\n', '\n', json_str)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)

        try:
            fact_data = json.loads(json_str)

            if 'data' not in fact_data:
                print("❌ Поле 'data' не знайдено у DisconSchedule.fact")
                return None

            schedule_data = fact_data['data']
            print(f"✅ Знайдено {len(schedule_data)} дат(и) з графіками")

            # Показуємо додаткову інформацію якщо є
            if 'update' in fact_data:
                print(f"ℹ️  Оновлено: {fact_data['update']}")
            if 'today' in fact_data:
                today_ts = int(fact_data['today'])
                today_date_utc = datetime.fromtimestamp(today_ts, tz=timezone.utc)
                today_date = today_date_utc.astimezone(pytz.timezone('Europe/Kyiv')).strftime('%Y-%m-%d')
                print(f"ℹ️  Поточна дата з сайту: {today_date}")

            return schedule_data

        except json.JSONDecodeError as e:
            print(f"❌ Помилка парсингу JSON: {e}")
            print(f"   Перші 300 символів: {json_str[:300]}")
            print(f"   Останні 100 символів: ...{json_str[-100:]}")
            return None

    except Exception as e:
        print(f"❌ Помилка витягування даних: {e}")
        import traceback
        traceback.print_exc()
        return None

def _extract_balanced_json(text, start_pos):
    """
    Витягує JSON об'єкт з тексту, починаючи з start_pos,
    балансуючи фігурні дужки
    """
    if start_pos >= len(text) or text[start_pos] != '{':
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start_pos, len(text)):
        char = text[i]

        # Обробка escape-послідовностей в рядках
        if escape:
            escape = False
            continue

        if char == '\\':
            escape = True
            continue

        # Обробка рядків
        if char == '"':
            in_string = not in_string
            continue

        # Якщо всередині рядка, ігноруємо дужки
        if in_string:
            continue

        # Підрахунок глибини вкладеності
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1

            # Коли глибина стає 0, ми знайшли кінець об'єкта
            if depth == 0:
                return text[start_pos:i + 1]

    return None

def show_shootdowns(data):
    result = {}
    for utc_date, groups in data.items():
        local_date = datetime.fromtimestamp(int(utc_date), tz=timezone.utc).astimezone(pytz.timezone('Europe/Kyiv')).strftime('%Y-%m-%d')
        result[local_date] = []
        for group, hours in groups.items():
            if group == "GPV3.2":
                for hour, status in hours.items():
                    if status in ["first", "second"]:
                        result[local_date].append(f"{int(hour) - 1}:30")
                    elif status == "no":
                        result[local_date].append(f"{int(hour) - 1}:00")
    return result

while True:
    res = get_shutdowns_html()
    extr = extract_schedule_data(res)
    shootdowns = show_shootdowns(extr)

    sleep(60 * 20)