import subprocess
import json
import re
from datetime import datetime, timezone
from time import sleep
import os
import sys


class DTEKScheduleParser:
    def __init__(self, cookies_file=None):
        """
        Парсер графіків відключень ДТЕК через curl з cookies

        Args:
            cookies_file: Шлях до файлу з cookies (формат Netscape)
        """
        self.url = "https://www.dtek-krem.com.ua/ua/shutdowns"
        self.cookies_file = cookies_file

    def get_page(self):
        """Отримує HTML сторінки через curl"""
        try:
            # Базова curl команда
            curl_command = [
                'curl',
                '--compressed',
                '--silent',
                '--location',
                '--request', 'GET',
                self.url,
                '-H', 'User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0',
                '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                '-H', 'Accept-Language: uk,en-US;q=0.7,en;q=0.3',
                '-H', 'Connection: keep-alive',
                '-H', 'Upgrade-Insecure-Requests: 1',
                '-H', 'Cache-Control: max-age=0'
            ]

            # Додаємо cookies якщо вказано
            if self.cookies_file and os.path.exists(self.cookies_file):
                curl_command.extend(['--cookie', self.cookies_file])
                print(f"🍪 Використовую cookies з файлу: {self.cookies_file}")
            else:
                print("⚠️  Cookies не знайдено, спробую без них...")

            print("🔄 Завантажую сторінку через curl...")
            result = subprocess.run(
                curl_command,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                print(f"❌ Помилка curl: {result.stderr}")
                return None

            html = result.stdout

            # Перевірка на Incapsula блокування
            if 'Incapsula incident ID' in html:
                print("❌ Incapsula заблокував запит")
                print("\n💡 РІШЕННЯ:")
                print("1. Відкрийте https://www.dtek-krem.com.ua/ua/shutdowns у Firefox")
                print("2. Натисніть F12 > вкладка 'Storage' (Сховище)")
                print("3. Скопіюйте cookies і збережіть у файл cookies.txt")
                print("4. Або використайте розширення 'Get cookies.txt LOCALLY'")
                print("\nАбо спробуйте запустити:")
                print("  curl --compressed https://www.dtek-krem.com.ua/ua/shutdowns > page.html")
                print("  python dtek_checker.py --file page.html")
                return None

            if len(html) < 1000:
                print("⚠️  Отримано занадто мало даних")
            else:
                print(f"✅ Сторінка завантажена ({len(html)} байт)")

            return html

        except subprocess.TimeoutExpired:
            print("❌ Час очікування curl минув (30 сек)")
            return None
        except FileNotFoundError:
            print("❌ curl не знайдено. Встановіть: sudo apt install curl")
            return None
        except Exception as e:
            print(f"❌ Помилка: {e}")
            return None

    def get_page_from_file(self, filepath):
        """Завантажує HTML з файлу"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                html = f.read()
            print(f"✅ HTML завантажено з файлу: {filepath}")
            return html
        except Exception as e:
            print(f"❌ Помилка читання файлу: {e}")
            return None

    def extract_schedule_data(self, html):
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
            json_str = self._extract_balanced_json(html, start_pos)

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
                    today_date = datetime.fromtimestamp(today_ts, tz=timezone.utc).strftime('%Y-%m-%d')
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

    def _extract_balanced_json(self, text, start_pos):
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

    def get_current_schedule(self, queue_name=None, from_file=None):
        """
        Отримує графік на поточну дату

        Args:
            queue_name: Назва черги або None для всіх
            from_file: Шлях до HTML файлу (якщо потрібно завантажити з файлу)
        """
        if from_file:
            html = self.get_page_from_file(from_file)
        else:
            html = self.get_page()

        if not html:
            return None

        schedule_data = self.extract_schedule_data(html)
        if not schedule_data:
            return None

        # Timestamp поточної дати
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_timestamp = int(today.timestamp())

        print(f"🔍 Поточна дата: {today.strftime('%Y-%m-%d')} (timestamp: {today_timestamp})")

        # Конвертуємо ключі
        available_timestamps = [int(ts) for ts in schedule_data.keys()]
        available_timestamps.sort()

        dates_str = [datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d') for ts in available_timestamps]
        print(f"📅 Доступні дати: {', '.join(dates_str)}")

        # Шукаємо найближчу дату >= сьогодні
        future_timestamps = [ts for ts in available_timestamps if ts >= today_timestamp]
        if future_timestamps:
            closest_timestamp = min(future_timestamps)
        else:
            closest_timestamp = max(available_timestamps)

        closest_date = datetime.fromtimestamp(closest_timestamp, tz=timezone.utc).strftime('%Y-%m-%d')
        print(f"✅ Використовую дату: {closest_date}")

        day_schedule = schedule_data.get(str(closest_timestamp), {})

        if not day_schedule:
            print(f"❌ Графік порожній")
            return None

        if queue_name:
            if queue_name not in day_schedule:
                print(f"⚠️  Черга '{queue_name}' не знайдена")
                print(f"   Доступні: {', '.join(day_schedule.keys())}")
                return None

            return {
                'timestamp': closest_timestamp,
                'date': closest_date,
                'queue': queue_name,
                'schedule': day_schedule[queue_name]
            }
        else:
            return {
                'timestamp': closest_timestamp,
                'date': closest_date,
                'queues': day_schedule
            }

    def format_schedule(self, schedule_data):
        """Форматує графік"""
        if not schedule_data:
            return "Немає даних"

        output = []
        output.append("=" * 60)
        output.append(f"📅 ГРАФІК ВІДКЛЮЧЕНЬ НА {schedule_data['date']}")
        output.append("=" * 60)

        if 'queue' in schedule_data:
            output.append(f"🔢 Черга: {schedule_data['queue']}")
            output.append("")
            output.append(self._format_queue_schedule(schedule_data['schedule']))
        else:
            for queue_name, queue_schedule in schedule_data['queues'].items():
                output.append(f"\n🔢 Черга: {queue_name}")
                output.append("-" * 60)
                output.append(self._format_queue_schedule(queue_schedule))

        output.append("=" * 60)
        return "\n".join(output)

    def _format_queue_schedule(self, schedule):
        """Форматує графік однієї черги"""
        if not schedule:
            return "  Дані відсутні"

        lines = []
        try:
            sorted_items = sorted(schedule.items(), key=lambda x: int(x[0]))
        except:
            sorted_items = sorted(schedule.items())

        prev_status = None

        for hour, status in sorted_items:
            try:
                hour_int = int(hour)
            except:
                hour_int = hour

            status_str = str(status).lower()

            # Визначаємо що означає first/second на основі попереднього статусу
            if status_str == "first":
                # Перша половина години (00-30) - зміна статусу
                # Якщо попередній статус був "yes" -> світло до 30 хв, потім відключення
                # Якщо попередній статус був "no" -> відключення до 30 хв, потім світло
                if prev_status == "yes" or prev_status is None:
                    emoji = "🟡"
                    text = f"Світло до {hour_int:02d}:30, потім відключення"
                else:  # prev_status == "no"
                    emoji = "🟡"
                    text = f"Відключення до {hour_int:02d}:30, потім світло"

            elif status_str == "second":
                # Друга половина години (30-60) - зміна статусу
                # Якщо попередній статус був "yes" -> світло до 30 хв, потім відключення
                # Якщо попередній статус був "no" -> відключення до 30 хв, потім світло
                if prev_status == "yes" or prev_status is None:
                    emoji = "🟡"
                    text = f"Світло до {hour_int:02d}:30, відключення з {hour_int:02d}:30"
                else:  # prev_status == "no"
                    emoji = "🟡"
                    text = f"Відключення до {hour_int:02d}:30, світло з {hour_int:02d}:30"

            elif status_str == "yes":
                emoji = "✅"
                text = "Світло Є"

            elif status_str == "no":
                emoji = "❌"
                text = "Відключення"

            else:
                emoji = "❓"
                text = f"Невідомо ({status})"

            time_range = f"{hour_int:02d}:00-{hour_int + 1:02d}:00"
            lines.append(f"  {emoji} {time_range} - {text}")

            # Зберігаємо попередній статус
            prev_status = status_str

        return "\n".join(lines) if lines else "  Дані відсутні"

    def save_schedule(self, schedule_data, filename='schedule.json'):
        """Зберігає графік"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(schedule_data, f, ensure_ascii=False, indent=2)
            print(f"💾 Збережено: {filename}")
            return True
        except Exception as e:
            print(f"❌ Помилка: {e}")
            return False

    def load_schedule(self, filename='schedule.json'):
        """Завантажує графік"""
        try:
            if not os.path.exists(filename):
                return None
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None

    def has_changes(self, old, new):
        """Перевіряє зміни"""
        if not old or not new:
            return True

        if 'schedule' in old and 'schedule' in new:
            return old['schedule'] != new['schedule']
        elif 'queues' in old and 'queues' in new:
            return old['queues'] != new['queues']

        return True

    def send_telegram(self, message, bot_token, chat_id):
        """Telegram повідомлення"""
        try:
            import requests
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            r = requests.post(url, data={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}, timeout=10)
            r.raise_for_status()
            print("✅ Відправлено в Telegram")
            return True
        except:
            print("❌ Помилка Telegram")
            return False

    def monitor(self, queue_name, interval_hours=2, telegram_config=None):
        """Моніторинг"""
        print(f"🚀 Моніторинг черги: {queue_name}")
        print(f"⏱️  Інтервал: {interval_hours} год\n")

        last = self.load_schedule()

        while True:
            try:
                print(f"🔄 Перевірка... ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
                current = self.get_current_schedule(queue_name)

                if current:
                    print(self.format_schedule(current))

                    if self.has_changes(last, current):
                        print("\n🔔 ЗМІНИ В ГРАФІКУ!")

                        if telegram_config:
                            msg = f"🔔 <b>Оновлення графіка</b>\n\n"
                            msg += f"📅 Дата: {current['date']}\n"
                            msg += f"🔢 Черга: {queue_name}\n\n"
                            msg += "<b>Графік:</b>\n"

                            prev_status = None
                            for h, s in sorted(current['schedule'].items(), key=lambda x: int(x[0])):
                                h_int = int(h)
                                s_str = str(s).lower()

                                if s_str == "first":
                                    if prev_status == "yes" or prev_status is None:
                                        e, t = "🟡", f"Світло→Відкл о {h_int:02d}:30"
                                    else:
                                        e, t = "🟡", f"Відкл→Світло о {h_int:02d}:30"
                                elif s_str == "second":
                                    if prev_status == "yes" or prev_status is None:
                                        e, t = "🟡", f"Світло→Відкл о {h_int:02d}:30"
                                    else:
                                        e, t = "🟡", f"Відкл→Світло о {h_int:02d}:30"
                                elif s_str == "yes":
                                    e, t = "✅", "Світло"
                                elif s_str == "no":
                                    e, t = "❌", "Відкл"
                                else:
                                    e, t = "❓", str(s)

                                msg += f"{e} {h_int:02d}:00 - {t}\n"
                                prev_status = s_str

                            self.send_telegram(msg, telegram_config['bot_token'], telegram_config['chat_id'])

                        self.save_schedule(current)
                        last = current
                    else:
                        print("\nℹ️  Без змін")

                print(f"\n⏳ Наступна перевірка через {interval_hours} год...\n")
                sleep(interval_hours * 3600)

            except KeyboardInterrupt:
                print("\n⛔ Зупинено")
                break
            except Exception as e:
                print(f"\n❌ {e}")
                sleep(300)


# ============= ВИКОРИСТАННЯ =============

if __name__ == "__main__":
    import argparse

    arg_parser = argparse.ArgumentParser(description='ДТЕК парсер графіків відключень')
    arg_parser.add_argument('--file', help='HTML файл замість curl')
    arg_parser.add_argument('--cookies', help='Файл cookies.txt', default=r"/home/tuipik/Downloads/cookies.txt")
    arg_parser.add_argument('--queue', help='Черга для моніторингу')
    args = arg_parser.parse_args()

    # Ініціалізація
    parser = DTEKScheduleParser(cookies_file=args.cookies)

    YOUR_QUEUE = args.queue or "GPV3.2"  # Змініть на свою

    TELEGRAM_CONFIG = None  # Або вкажіть bot_token і chat_id
    # TELEGRAM_CONFIG = {'bot_token': '...', 'chat_id': '...'}

    print("🔍 ДТЕК - Графіки відключень\n")

    # Показати всі черги
    print("=" * 60)
    print("ДОСТУПНІ ЧЕРГИ")
    print("=" * 60)
    all_schedules = parser.get_current_schedule(from_file=args.file)
    if all_schedules:
        print(parser.format_schedule(all_schedules))
    print()

    # Показати конкретну чергу
    if YOUR_QUEUE:
        print("=" * 60)
        print(f"ЧЕРГА: {YOUR_QUEUE}")
        print("=" * 60)
        schedule = parser.get_current_schedule(YOUR_QUEUE, from_file=args.file)
        if schedule:
            print(parser.format_schedule(schedule))
        print()

    # Моніторинг (якщо не з файлу)
    if not args.file:
        choice = input("Запустити моніторинг? (y/n): ")
        if choice.lower() == 'y':
            interval = input("Інтервал (год, default=2): ")
            interval = int(interval) if interval.strip() else 2
            parser.monitor(YOUR_QUEUE, interval, TELEGRAM_CONFIG)





