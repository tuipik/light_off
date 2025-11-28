from datetime import datetime, timedelta

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


def generate_schedule_message(schedule):
    """
    Формує текст повідомлення для графіка відключень.

    Args:
        schedule: Словник з графіком відключень.
                  Формат: {'2025-11-28': ['10:00', '11:00', '12:00'], ...}

    Returns:
        str: Текст повідомлення.
    """
    message = "🔔 Новий графік відключень:\n"
    for date, times in schedule.items():
        if not times:
            message += f"\n📅 {datetime.strptime(date, '%Y-%m-%d').strftime('%d-%m-%Y')}: відключення не плануються, або ще не заплановані\n"
            continue

        intervals = []
        start_time = times[0]
        prev_time = times[0]

        for time in times[1:]:
            # Якщо час не є послідовним, завершуємо поточний інтервал
            if datetime.strptime(time, "%H:%M") - datetime.strptime(
                prev_time, "%H:%M"
            ) > timedelta(hours=1):
                end_time = (
                    datetime.strptime(prev_time, "%H:%M") + timedelta(hours=1)
                ).strftime("%H:%M")
                intervals.append(f"{start_time} по {end_time}")
                start_time = time
            prev_time = time

        # Додаємо останній інтервал
        if datetime.strptime(prev_time, "%H:%M") - datetime.strptime(
            start_time, "%H:%M"
        ) < timedelta(hours=1):
            # Якщо інтервал складається з одного часу, додаємо +1 годину
            end_time = (
                datetime.strptime(prev_time, "%H:%M") + timedelta(hours=1)
            ).strftime("%H:%M")
            intervals.append(f"{start_time} по {end_time}")
        else:
            end_time = (
                datetime.strptime(prev_time, "%H:%M") + timedelta(hours=1)
            ).strftime("%H:%M")
            intervals.append(f"{start_time} по {end_time}")

        message += f"\n📅 {datetime.strptime(date, '%Y-%m-%d').strftime('%d-%m-%Y')}: відключення будуть з {', '.join(intervals)}\n"

    return message
