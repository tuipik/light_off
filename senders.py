from datetime import datetime, timedelta
from typing import Dict, List

from telegram import Bot

from logger import logger


async def send_telegram_message(token, chat_id, message):
    """
    Відправляє повідомлення в Telegram.

    Args:
        token: Токен вашого Telegram-бота.
        chat_id: ID чату або користувача.
        message: Текст повідомлення.
    """
    try:
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=message)
        logger.info("✅ Повідомлення успішно відправлено в Telegram")
    except Exception as e:
        logger.error(f"❌ Помилка відправки повідомлення в Telegram: {e}")


def calculate_total_outage_hours(times: List[str]) -> float:
    """
    Підраховує кількість годин без світла для однієї дати.

    Кожен елемент у списку часу — це початок 30-хвилинного слоту.
    Тому загальна кількість годин = (кількість унікальних слотів) * 0.5
    """
    return len(set(times)) * 0.5


def _format_hours_and_minutes(total_minutes: int) -> str:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours} год {minutes} хв"


def generate_schedule_message(schedule: Dict[str, List[str]]) -> str:
    """
    Генерує повідомлення про відключення світла на основі графіка,
    з логікою групування послідовних точок відключення та коректним
    визначенням кінцевого часу (додавання +1 години для кінцівки о :00).

    :param schedule: Словник, де ключ - дата (str 'YYYY-MM-DD'),
                     значення - список часів відключень (list[str 'H:MM' або 'HH:MM']).
    :return: Сформоване повідомлення (str).
    """
    messages = ["🔔 Новий графік відключень\n"]

    for date_str, times in schedule.items():
        # Форматуємо дату для повідомлення
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        display_date = date_obj.strftime('%d-%m-%Y')

        # 1. Обробка випадку з порожнім списком
        if not times:
            messages.append(f"📅 {display_date} відключення не плануються, або ще не заплановані\n")
            continue

        # 2. Перетворення рядків часу на об'єкти datetime
        # Використовуємо %H для гнучкого парсингу H:MM або HH:MM
        dt_times = [datetime.strptime(f"{date_str} {t}", '%Y-%m-%d %H:%M') for t in times]

        grouped_intervals = []

        # Ініціалізація першої групи
        current_start_dt = dt_times[0]
        current_end_dt = dt_times[0]

        for i in range(1, len(dt_times)):
            # Кожна точка = початок 30-хв слоту відключення.
            # Інтервал продовжується лише якщо наступний слот суміжний.
            expected_next = current_end_dt + timedelta(minutes=30)
            if dt_times[i] == expected_next:
                current_end_dt = dt_times[i]
            else:
                final_end_dt = current_end_dt + timedelta(minutes=30)
                start_str = current_start_dt.strftime('%H:%M')
                end_str = final_end_dt.strftime('%H:%M')
                grouped_intervals.append(f"      з {start_str} по {end_str}")

                # Починаємо нову послідовність
                current_start_dt = dt_times[i]
                current_end_dt = dt_times[i]

        # 3. Запис останньої (або єдиної) послідовності
        final_end_dt = current_end_dt + timedelta(minutes=30)

        start_str = current_start_dt.strftime('%H:%M')
        end_str = final_end_dt.strftime('%H:%M')
        grouped_intervals.append(f"      з {start_str} по {end_str}")

        # 4. Формування фінального блоку для дати: кожен інтервал з нового рядка
        intervals_str = "\n".join(grouped_intervals)
        total_minutes = len(set(times)) * 30
        messages.append(
            f"📅 {display_date} відключення будуть:\n{intervals_str}\n\n"
            f"⏱️ Без світла: {_format_hours_and_minutes(total_minutes)}\n"
        )

    return "\n".join(messages)
