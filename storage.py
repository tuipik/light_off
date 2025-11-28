import redis
import json
from datetime import datetime


class ScheduleStorage:
    def __init__(self, redis_url="redis://localhost:6379/0"):
        self.redis = redis.from_url(redis_url)

    def get_current_schedule(self, queue_name):
        """Отримує поточний графік з Redis"""
        key = f"schedule:{queue_name}"
        data = self.redis.get(key)
        return json.loads(data) if data else None

    def save_schedule(self, queue_name, schedule_data):
        """Зберігає графік в Redis"""
        key = f"schedule:{queue_name}"
        self.redis.set(key, json.dumps(schedule_data))

    def has_changes(self, queue_name, new_schedule):
        """Перевіряє чи є зміни"""
        old = self.get_current_schedule(queue_name)
        return old != new_schedule
