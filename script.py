import requests
from bs4 import BeautifulSoup
import re
import json


def get_power_outage_info_python_with_headers(url):
    headers = {
        "cookie": "Domain=dtek-krem.com.ua; incap_ses_686_2398465=z0HXT3eAWAXwWUNPzSmFCQxHI2kAAAAAB%2B8KJ1DvMqYAy2wQ6ZUnsQ%3D%3D; _language=3eb69d58ec89e92ef3dafa6c5ddfe948ae4ccc42f3f8fc9cd1b9568ed22f10a3a%253A2%253A%257Bi%253A0%253Bs%253A9%253A%2522_language%2522%253Bi%253A1%253Bs%253A2%253A%2522uk%2522%253B%257D",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.5",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Cookie": "Domain=dtek-krem.com.ua; _language=3eb69d58ec89e92ef3dafa6c5ddfe948ae4ccc42f3f8fc9cd1b9568ed22f10a3a%3A2%3A%7Bi%3A0%3Bs%3A9%3A%22_language%22%3Bi%3A1%3Bs%3A2%3A%22uk%22%3B%7D; visid_incap_2398465=5vuQLJnNR1mrcKFKitYWYtHCImkAAAAAQUIPAAAAAACGBmDhXyHhZc9l3942aHIe; _csrf-dtek-krem=db93bb6c8e33811bb09dd8f0ba88c5bc04dd3f9a1a619fe3bc58115a6fda8952a%3A2%3A%7Bi%3A0%3Bs%3A15%3A%22_csrf-dtek-krem%22%3Bi%3A1%3Bs%3A32%3A%22Pq67cUOE2BmvgRqqrkkjZUfnnRGkjA2r%22%3B%7D; incap_ses_686_2398465=mE07MxpwfSGTsYROzSmFCdHCImkAAAAASlDEO5hxu65oT7DtipvtJA==; dtek-krem=loiausrqjkd7kqlkt9076tqseg; incap_wrt_378=/0YjaQAAAAAa7QB1GgAI+gIQ95ezjLABGKuQjckGIAIo0I2NyQYwA1/U5Et8fviUuTx33af0HRY=; Domain=dtek-krem.com.ua",
        "GET /ua/shutdowns HTTP/2": "",
        "Host": "www.dtek-krem.com.ua",
        "Pragma": "no-cache",
        "Priority": "u=0, i",
        "Referer": "https://www.google.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "TE": "trailers",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0",
        "content-type": "multipart/form-data; boundary=---011000010111000001101001"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)  # Додайте таймаут
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Помилка при завантаженні сторінки або заблоковано Incapsula: {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')

    # Знаходимо всі script-теги
    script_tags = soup.find_all('script')

    gpv32_data = None

    for script in script_tags:
        script_content = script.string
        if script_content:
            # Спробуємо знайти патерн, який вказує на DisconSchedule або схожий об'єкт
            # Цей регулярний вираз спробує знайти присвоєння змінної, яка починається на "DisconSchedule"
            # або шукатиме пряме визначення GPV3.2

            # Приклад 1: Якщо це схоже на JSON-об'єкт, присвоєний змінній.
            # Наприклад: var someVar = {"GPV3.2": "інфо про відключення", ...};
            match_json_var = re.search(r'var\s+\w+\s*=\s*(\{.*?\});', script_content, re.DOTALL)
            if match_json_var:
                try:
                    js_object_str = match_json_var.group(1)
                    # JavaScript-об'єкти можуть мати ключі без лапок, JSON вимагає лапок.
                    # Можливо, знадобиться більш складний парсинг або заміна одинарних лапок на подвійні,
                    # якщо це не строгий JSON.
                    # Для простоти спробуємо парсити як JSON, якщо це можливо.
                    data = json.loads(js_object_str)
                    if "GPV3.2" in data:
                        gpv32_data = data["GPV3.2"]
                        print(f"Знайдено GPV3.2 як частину JSON-змінної: {gpv32_data}")
                        return gpv32_data
                except json.JSONDecodeError:
                    pass  # Це не був коректний JSON

            # Приклад 2: Якщо це пряме присвоєння значення GPV3.2 або частини об'єкта.
            # Наприклад: DisconSchedule.GPV3_2 = "інфо про відключення";
            # Або: var data = {}; data["GPV3.2"] = "інфо";
            # Цей регулярний вираз шукатиме рядок 'GPV3.2' та його значення
            match_gpv32 = re.search(r'(?:GPV3\.2|GPV3_2)["\']?\s*:\s*["\'](.*?)["\']', script_content)
            if match_gpv32:
                gpv32_data = match_gpv32.group(1)
                print(f"Знайдено GPV3.2 за допомогою регулярного виразу: {gpv32_data}")
                return gpv32_data

            # Додатковий патерн для пошуку DisconSchedule.data = { ... }
            # і потім парсинг цього об'єкта.
            match_discon_schedule = re.search(r'DisconSchedule\.(\w+)\s*=\s*(\{.*?\});', script_content, re.DOTALL)
            if match_discon_schedule:
                # print(f"Знайдено DisconSchedule.{match_discon_schedule.group(1)} = {match_discon_schedule.group(2)[:100]}...")
                try:
                    # JSON-об'єкти в JS часто можуть мати ключі без лапок, що не є валідним JSON.
                    # library 'demjson' or manual string manipulation can help here.
                    # For simplicity, if it's mostly JSON-like, we can try to fix it.
                    js_obj_str = match_discon_schedule.group(2)
                    # Спрощена заміна одинарних лапок на подвійні та додавання лапок до ключів
                    # Це дуже спрощено і може не працювати для всіх випадків!
                    js_obj_str = re.sub(r"(['\"])?([a-zA-Z0-9_]+)(['\"])?:", r'"\2":', js_obj_str)
                    js_obj_str = js_obj_str.replace("'", '"')

                    data_obj = json.loads(js_obj_str)
                    if "GPV3.2" in data_obj:
                        gpv32_data = data_obj["GPV3.2"]
                        print(f"Знайдено GPV3.2 як частину об'єкта DisconSchedule: {gpv32_data}")
                        return gpv32_data
                    elif "GPV3_2" in data_obj:  # Спробуємо GPV3_2
                        gpv32_data = data_obj["GPV3_2"]
                        print(f"Знайдено GPV3_2 як частину об'єкта DisconSchedule: {gpv32_data}")
                        return gpv32_data
                except json.JSONDecodeError as e:
                    # print(f"Не вдалося розпарсити JS-об'єкт як JSON: {e}")
                    pass  # Це не був коректний JSON або потребує більш складного парсингу

    print("Інформацію GPV3.2 не знайдено в жодному script-тегу.")
    return None

# Використання функції
# Замініть 'your_page_url_here' на фактичну URL-адресу сторінки, яку ви аналізуєте
url = 'https://www.dtek-krem.com.ua/ua/shutdowns'
info = get_power_outage_info_python_with_headers(url)
if info:
    print(f"Отримана інформація про GPV3.2: {info}")
