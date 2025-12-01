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


def generate_schedule_message(schedule: dict) -> str:
    """
    Генерує повідомлення про відключення світла на основі графіка,
    з логікою групування послідовних точок відключення та коректним
    визначенням кінцевого часу (додавання +1 години для кінцівки о :00).

    :param schedule: Словник, де ключ - дата (str 'YYYY-MM-DD'),
                     значення - список часів відключень (list[str 'H:MM' або 'HH:MM']).
    :return: Сформоване повідомлення (str).
    """
    messages = ["🔔 Новий графік відключень\n"]

    # Максимальна допустима різниця між послідовними часами для групування
    # 13:30 - 12:00 = 1:30. Цей інтервал має бути включений в групу.
    MAX_DIFF_FOR_GROUPING = timedelta(hours=1, minutes=30)

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
            time_diff = dt_times[i] - current_end_dt

            # Перевіряємо, чи поточний час знаходиться в межах MAX_DIFF_FOR_GROUPING
            # від попереднього часу (current_end_dt)
            if time_diff <= MAX_DIFF_FOR_GROUPING:
                # Послідовність продовжується, оновлюємо кінець групи
                current_end_dt = dt_times[i]
            else:
                # Послідовність перервалася, записуємо попередній інтервал

                # ************ ОНОВЛЕНА ЛОГІКА ************
                final_end_dt = current_end_dt

                # Якщо кінцевий час на цілій годині (наприклад, 21:00), додаємо 1 годину
                # відповідно до правила "21:00 - це початок відключення, яке триває до 22:00"
                if final_end_dt.minute == 0:
                    final_end_dt += timedelta(hours=1)
                # ******************************************

                # Додавання інтервалу
                start_str = current_start_dt.strftime('%H:%M')
                end_str = final_end_dt.strftime('%H:%M')
                grouped_intervals.append(f"з {start_str} по {end_str}")

                # Починаємо нову послідовність
                current_start_dt = dt_times[i]
                current_end_dt = dt_times[i]

        # 3. Запис останньої (або єдиної) послідовності

        # ************ ОНОВЛЕНА ЛОГІКА ************
        final_end_dt = current_end_dt

        # Якщо кінцевий час на цілій годині (наприклад, 21:00), додаємо 1 годину
        if final_end_dt.minute == 0:
            final_end_dt += timedelta(hours=1)
        # ******************************************

        start_str = current_start_dt.strftime('%H:%M')
        end_str = final_end_dt.strftime('%H:%M')
        grouped_intervals.append(f"з {start_str} по {end_str}")

        # 4. Формування фінального рядка для дати
        intervals_str = ", ".join(grouped_intervals)
        messages.append(f"📅 {display_date} відключення будуть {intervals_str}\n")

    return "\n".join(messages)
