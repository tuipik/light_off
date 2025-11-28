"""
Робота з Redis для зберігання графіків відключень
"""
import json
from datetime import datetime
from typing import Dict, Optional, List

import redis

from logger import logger


class ScheduleStorage:
    """Клас для роботи з Redis"""

    def __init__(self, redis_url: str):
        """
        Args:
            redis_url: URL для підключення до Redis (наприклад, 'redis://localhost:6379/0')
        """
        self.redis = redis.from_url(redis_url, decode_responses=True)

    def get_current_schedule(self, queue_name: str) -> Optional[Dict]:
        """
        Отримує поточний графік з Redis

        Args:
            queue_name: Назва черги (наприклад, 'GPV3.2')

        Returns:
            Dict з графіком або None якщо немає
        """
        key = f"schedule:{queue_name}"
        data = self.redis.get(key)

        if data:
            return json.loads(data)
        return None

    def save_schedule(self, queue_name: str, schedule_data: Dict) -> None:
        """
        Зберігає графік в Redis

        Args:
            queue_name: Назва черги
            schedule_data: Дані графіка (формат: {date: [hours]})
        """
        key = f"schedule:{queue_name}"

        # Додаємо timestamp збереження
        data_to_save = {
            'schedule': schedule_data,
            'saved_at': datetime.now().isoformat()
        }

        self.redis.set(key, json.dumps(data_to_save))
        logger.info(f"💾 Збережено графік для {queue_name}")

    def has_changes(self, queue_name: str, new_schedule: Dict) -> bool:
        """
        Перевіряє чи є зміни в графіку

        Args:
            queue_name: Назва черги
            new_schedule: Новий графік

        Returns:
            True якщо є зміни, False якщо немає
        """
        current = self.get_current_schedule(queue_name)

        # Якщо немає збереженого графіка - це зміна
        if current is None:
            return True

        # Порівнюємо тільки schedule, ігноруючи saved_at
        old_schedule = current.get('schedule', {})

        return old_schedule != new_schedule

    def get_changes(self, queue_name: str, new_schedule: Dict) -> Dict:
        """
        Повертає деталі змін в графіку

        Args:
            queue_name: Назва черги
            new_schedule: Новий графік (формат: {'2024-11-23': ['5:00', '6:00'], ...})

        Returns:
            Dict з інформацією про зміни:
            {
                'type': 'new' | 'updated',
                'message': str,  # для type='new'
                'changes': {...}  # для type='updated'
            }
        """
        current = self.get_current_schedule(queue_name)

        if current is None:
            return {
                'type': 'new',
                'message': 'Перший запис графіка'
            }

        old_schedule = current.get('schedule', {})
        changes = {}

        # Порівнюємо по датах
        all_dates = set(old_schedule.keys()) | set(new_schedule.keys())

        for date in all_dates:
            old_hours = set(old_schedule.get(date, []))
            new_hours = set(new_schedule.get(date, []))

            if old_hours != new_hours:
                added = new_hours - old_hours
                removed = old_hours - new_hours

                changes[date] = {
                    'added': sorted(list(added)),
                    'removed': sorted(list(removed))
                }

        if not changes:
            return {
                'type': 'no_changes',
                'message': 'Графік не змінився'
            }

        return {
            'type': 'updated',
            'changes': changes
        }

    def save_history(self, queue_name: str, schedule_data: Dict) -> None:
        """
        Зберігає історію змін графіка

        Args:
            queue_name: Назва черги
            schedule_data: Дані графіка
        """
        key = f"history:{queue_name}"

        history_entry = {
            'schedule': schedule_data,
            'timestamp': datetime.now().isoformat()
        }

        # Додаємо в список (зберігаємо останні 100 записів)
        self.redis.lpush(key, json.dumps(history_entry))
        self.redis.ltrim(key, 0, 99)

        logger.info(f"📚 Збережено в історію для {queue_name}")

    def get_history(self, queue_name: str, limit: int = 10) -> List[Dict]:
        """
        Отримує історію змін

        Args:
            queue_name: Назва черги
            limit: Кількість записів

        Returns:
            Список історичних записів
        """
        key = f"history:{queue_name}"
        items = self.redis.lrange(key, 0, limit - 1)

        return [json.loads(item) for item in items]

    def clear_schedule(self, queue_name: str) -> None:
        """
        Видаляє графік з Redis

        Args:
            queue_name: Назва черги
        """
        key = f"schedule:{queue_name}"
        self.redis.delete(key)
        logger.info(f"🗑️  Видалено графік для {queue_name}")

    def clear_history(self, queue_name: str) -> None:
        """
        Видаляє історію

        Args:
            queue_name: Назва черги
        """
        key = f"history:{queue_name}"
        self.redis.delete(key)
        logger.info(f"🗑️  Видалено історію для {queue_name}")

    def ping(self) -> bool:
        """
        Перевіряє з'єднання з Redis

        Returns:
            True якщо з'єднання активне
        """
        try:
            return self.redis.ping()
        except redis.ConnectionError:
            return False


# Тестування
if __name__ == "__main__":
    print("=" * 60)
    print("🧪 ТЕСТУВАННЯ STORAGE")
    print("=" * 60)
    print()

    # Тест підключення
    storage = ScheduleStorage('redis://localhost:6379/0')

    if not storage.ping():
        print("❌ Не вдалося підключитися до Redis")
        print("Запустіть Redis: docker run -d -p 6379:6379 redis")
        exit(1)

    print("✅ З'єднання з Redis успішне\n")

    # Очищаємо тестові дані
    storage.clear_schedule('TEST_QUEUE')
    storage.clear_history('TEST_QUEUE')
    print()

    # Тест 1: Перше збереження
    print("📝 Тест 1: Перше збереження")
    print("-" * 60)
    test_schedule_1 = {
        '2024-11-23': ['5:00', '5:30', '6:00', '6:30', '7:00'],
        '2024-11-24': ['8:00', '8:30']
    }

    storage.save_schedule('TEST_QUEUE', test_schedule_1)
    storage.save_history('TEST_QUEUE', test_schedule_1)

    saved = storage.get_current_schedule('TEST_QUEUE')
    print(f"📖 Збережений графік: {saved['schedule']}")
    print()

    # Тест 2: Перевірка без змін
    print("📝 Тест 2: Перевірка без змін")
    print("-" * 60)
    has_changes = storage.has_changes('TEST_QUEUE', test_schedule_1)
    print(f"🔄 Є зміни: {has_changes}")
    print()

    # Тест 3: Зміни в графіку
    print("📝 Тест 3: Зміни в графіку")
    print("-" * 60)
    test_schedule_2 = {
        '2024-11-23': ['5:00', '6:00', '7:00'],  # Видалено 5:30, 6:30
        '2024-11-24': ['8:00', '8:30', '9:00'],  # Додано 9:00
        '2024-11-25': ['10:00']  # Нова дата
    }

    has_changes = storage.has_changes('TEST_QUEUE', test_schedule_2)
    print(f"🔄 Є зміни: {has_changes}")

    if has_changes:
        changes = storage.get_changes('TEST_QUEUE', test_schedule_2)
        print(f"📊 Тип: {changes['type']}")
        print("📊 Деталі змін:")
        for date, change in changes.get('changes', {}).items():
            if change['added']:
                print(f"   ➕ {date}: додано {', '.join(change['added'])}")
            if change['removed']:
                print(f"   ➖ {date}: видалено {', '.join(change['removed'])}")

        # Зберігаємо нові зміни
        storage.save_schedule('TEST_QUEUE', test_schedule_2)
        storage.save_history('TEST_QUEUE', test_schedule_2)
    print()

    # Тест 4: Історія
    print("📝 Тест 4: Історія змін")
    print("-" * 60)
    history = storage.get_history('TEST_QUEUE', limit=5)
    print(f"📚 Записів в історії: {len(history)}")
    for i, entry in enumerate(history, 1):
        print(f"   {i}. {entry['timestamp']}")
    print()

    # Очищаємо тестові дані
    print("📝 Очищення тестових даних")
    print("-" * 60)
    storage.clear_schedule('TEST_QUEUE')
    storage.clear_history('TEST_QUEUE')
    print()

    print("=" * 60)
    print("✅ ВСІ ТЕСТИ ПРОЙДЕНО")
    print("=" * 60)
