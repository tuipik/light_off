"""
Тести для ДТЕК моніторингу
"""
import json

import pytest

from config import REDIS_PORT, REDIS_HOST
from main import parse_shutdowns, _extract_balanced_json
from senders import generate_schedule_message
from storage import ScheduleStorage


# ============= ФІКСТУРИ =============

@pytest.fixture
def redis_storage():
    """Фікстура для тестового Redis storage"""
    storage = ScheduleStorage(f'redis://{REDIS_HOST}:{REDIS_PORT}/1')  # Використовуємо DB 1 для тестів

    # Очищаємо перед тестом
    storage.clear_schedule('TEST_QUEUE')
    storage.clear_history('TEST_QUEUE')

    yield storage

    # Очищаємо після тесту
    storage.clear_schedule('TEST_QUEUE')
    storage.clear_history('TEST_QUEUE')


@pytest.fixture
def sample_schedule_1():
    """Тестовий графік 1"""
    return {
        '2024-11-23': ['5:00', '5:30', '6:00', '6:30', '7:00'],
        '2024-11-24': ['8:00', '8:30']
    }


@pytest.fixture
def sample_schedule_2():
    """Тестовий графік 2 (з змінами)"""
    return {
        '2024-11-23': ['5:00', '6:00', '7:00'],  # Видалено 5:30, 6:30
        '2024-11-24': ['8:00', '8:30', '9:00'],  # Додано 9:00
        '2024-11-25': ['10:00']  # Нова дата
    }


@pytest.fixture
def sample_raw_data():
    """Тестові сирі дані з сайту ДТЕК"""
    return {
        "1732320000": {  # 2024-11-23 00:00:00 UTC
            "GPV3.2": {
                "1": "yes",
                "2": "yes",
                "3": "yes",
                "4": "yes",
                "5": "no",
                "6": "no",
                "7": "no",
                "8": "first",
                "9": "yes",
                "10": "yes",
                "11": "yes",
                "12": "yes",
                "13": "yes",
                "14": "yes",
                "15": "second",
                "16": "no",
                "17": "no",
                "18": "no",
                "19": "yes",
                "20": "yes",
                "21": "yes",
                "22": "yes",
                "23": "yes",
                "24": "yes"
            }
        }
    }


# ============= ТЕСТИ STORAGE =============

class TestStorage:
    """Тести для ScheduleStorage"""

    def test_redis_connection(self, redis_storage):
        """Тест підключення до Redis"""
        assert redis_storage.ping() == True

    def test_save_and_get_schedule(self, redis_storage, sample_schedule_1):
        """Тест збереження та отримання графіка"""
        redis_storage.save_schedule('TEST_QUEUE', sample_schedule_1)

        saved = redis_storage.get_current_schedule('TEST_QUEUE')
        assert saved is not None
        assert 'schedule' in saved
        assert 'saved_at' in saved
        assert saved['schedule'] == sample_schedule_1

    def test_get_nonexistent_schedule(self, redis_storage):
        """Тест отримання неіснуючого графіка"""
        result = redis_storage.get_current_schedule('NONEXISTENT_QUEUE')
        assert result is None

    def test_has_changes_first_save(self, redis_storage, sample_schedule_1):
        """Тест виявлення змін при першому збереженні"""
        has_changes = redis_storage.has_changes('TEST_QUEUE', sample_schedule_1)
        assert has_changes == True

    def test_has_changes_no_changes(self, redis_storage, sample_schedule_1):
        """Тест виявлення змін коли їх немає"""
        redis_storage.save_schedule('TEST_QUEUE', sample_schedule_1)
        has_changes = redis_storage.has_changes('TEST_QUEUE', sample_schedule_1)
        assert has_changes == False

    def test_has_changes_with_changes(self, redis_storage, sample_schedule_1, sample_schedule_2):
        """Тест виявлення змін коли вони є"""
        redis_storage.save_schedule('TEST_QUEUE', sample_schedule_1)
        has_changes = redis_storage.has_changes('TEST_QUEUE', sample_schedule_2)
        assert has_changes == True

    def test_get_changes_new(self, redis_storage, sample_schedule_1):
        """Тест деталей змін для нового графіка"""
        changes = redis_storage.get_changes('TEST_QUEUE', sample_schedule_1)
        assert changes['type'] == 'new'
        assert 'message' in changes

    def test_get_changes_updated(self, redis_storage, sample_schedule_1, sample_schedule_2):
        """Тест деталей змін для оновленого графіка"""
        redis_storage.save_schedule('TEST_QUEUE', sample_schedule_1)
        changes = redis_storage.get_changes('TEST_QUEUE', sample_schedule_2)

        assert changes['type'] == 'updated'
        assert 'changes' in changes

        # Перевіряємо зміни для 2024-11-23
        assert '2024-11-23' in changes['changes']
        assert '5:30' in changes['changes']['2024-11-23']['removed']
        assert '6:30' in changes['changes']['2024-11-23']['removed']

        # Перевіряємо зміни для 2024-11-24
        assert '2024-11-24' in changes['changes']
        assert '9:00' in changes['changes']['2024-11-24']['added']

        # Перевіряємо нову дату
        assert '2024-11-25' in changes['changes']
        assert '10:00' in changes['changes']['2024-11-25']['added']

    def test_save_history(self, redis_storage, sample_schedule_1, sample_schedule_2):
        """Тест збереження історії"""
        redis_storage.save_history('TEST_QUEUE', sample_schedule_1)
        redis_storage.save_history('TEST_QUEUE', sample_schedule_2)

        history = redis_storage.get_history('TEST_QUEUE', limit=10)

        assert len(history) == 2
        assert history[0]['schedule'] == sample_schedule_2  # Найновіший
        assert history[1]['schedule'] == sample_schedule_1  # Старіший
        assert 'timestamp' in history[0]

    def test_get_history_limit(self, redis_storage, sample_schedule_1):
        """Тест обмеження кількості записів в історії"""
        # Додаємо 5 записів
        for i in range(5):
            modified_schedule = {**sample_schedule_1}
            modified_schedule[f'2024-11-2{i}'] = ['10:00']
            redis_storage.save_history('TEST_QUEUE', modified_schedule)

        # Отримуємо тільки 3
        history = redis_storage.get_history('TEST_QUEUE', limit=3)
        assert len(history) == 3

    def test_clear_schedule(self, redis_storage, sample_schedule_1):
        """Тест видалення графіка"""
        redis_storage.save_schedule('TEST_QUEUE', sample_schedule_1)
        redis_storage.clear_schedule('TEST_QUEUE')

        result = redis_storage.get_current_schedule('TEST_QUEUE')
        assert result is None

    def test_clear_history(self, redis_storage, sample_schedule_1):
        """Тест видалення історії"""
        redis_storage.save_history('TEST_QUEUE', sample_schedule_1)
        redis_storage.clear_history('TEST_QUEUE')

        history = redis_storage.get_history('TEST_QUEUE')
        assert len(history) == 0


# ============= ТЕСТИ ПАРСЕРА =============

class TestParser:
    """Тести для парсингу даних"""

    def test_parse_shutdowns_basic(self, sample_raw_data):
        """Тест базового парсингу графіка"""
        result = parse_shutdowns(sample_raw_data, 'GPV3.2')

        assert isinstance(result, dict)
        assert len(result) > 0

        # Перевіряємо що є дата
        dates = list(result.keys())
        assert len(dates) > 0

        # Перевіряємо що є години
        first_date = dates[0]
        assert isinstance(result[first_date], list)
        assert len(result[first_date]) > 0

    def test_parse_shutdowns_no_status(self, sample_raw_data):
        """Тест парсингу статусу 'no' (повне відключення)"""
        result = parse_shutdowns(sample_raw_data, 'GPV3.2')

        first_date = list(result.keys())[0]
        times = result[first_date]

        assert '4:00' in times
        assert '5:00' in times
        assert '6:00' in times

    def test_parse_shutdowns_first_status(self, sample_raw_data):
        """Тест парсингу статусу 'first' (відключення до :30)"""
        result = parse_shutdowns(sample_raw_data, 'GPV3.2')

        first_date = list(result.keys())[0]
        times = result[first_date]

        assert '7:00' in times

    def test_parse_shutdowns_second_status(self, sample_raw_data):
        """Тест парсингу статусу 'second' (відключення з :30)"""
        result = parse_shutdowns(sample_raw_data, 'GPV3.2')

        first_date = list(result.keys())[0]
        times = result[first_date]
        assert '14:30' in times

    def test_parse_shutdowns_yes_status(self, sample_raw_data):
        """Тест парсингу статусу 'yes' (світло є)"""
        result = parse_shutdowns(sample_raw_data, 'GPV3.2')

        first_date = list(result.keys())[0]
        times = result[first_date]

        # Години 1-4 мають статус "yes" - відключень немає
        # Цих годин не має бути в результаті
        assert '0:00' not in times
        assert '0:30' not in times
        assert '1:00' not in times
        assert '1:30' not in times

    def test_parse_shutdowns_nonexistent_queue(self, sample_raw_data):
        """Тест парсингу неіснуючої черги"""
        result = parse_shutdowns(sample_raw_data, 'NONEXISTENT_QUEUE')
        assert result == {}

    def test_parse_shutdowns_empty_data(self):
        """Тест парсингу порожніх даних"""
        result = parse_shutdowns({}, 'GPV3.2')
        assert result == {}

    def test_parse_shutdowns_sorted_times(self, sample_raw_data):
        """Тест що час відсортовано"""
        result = parse_shutdowns(sample_raw_data, 'GPV3.2')

        first_date = list(result.keys())[0]
        times = result[first_date]

        # Перевіряємо що список відсортовано
        sorted_times = sorted(times, key=lambda t: tuple(map(int, t.split(':'))))
        assert times == sorted_times

    def test_parse_shutdowns_real_case_intervals(self):
        """Тест реального кейсу GPV3.2 з розривами між інтервалами"""
        raw_data = {
            "1772143200": {
                "GPV3.2": {
                    "1": "second", "2": "no", "3": "no", "4": "no",
                    "5": "yes", "6": "yes", "7": "yes", "8": "yes",
                    "9": "yes", "10": "yes", "11": "yes", "12": "no",
                    "13": "no", "14": "no", "15": "first", "16": "yes",
                    "17": "no", "18": "no", "19": "yes", "20": "yes",
                    "21": "yes", "22": "second", "23": "no", "24": "no"
                }
            }
        }

        schedule = parse_shutdowns(raw_data, 'GPV3.2')
        first_date = list(schedule.keys())[0]
        message = generate_schedule_message({first_date: schedule[first_date]})

        assert "з 00:30 по 04:00" in message
        assert "з 11:00 по 14:30" in message
        assert "з 16:00 по 18:00" in message
        assert "з 21:30 по 00:00" in message


# ============= ТЕСТИ EXTRACT JSON =============

class TestExtractJSON:
    """Тести для витягування JSON"""

    def test_extract_simple_json(self):
        """Тест витягування простого JSON"""
        text = 'var data = {"key": "value"};'
        result = _extract_balanced_json(text, text.index('{'))

        assert result == '{"key": "value"}'
        assert json.loads(result) == {"key": "value"}

    def test_extract_nested_json(self):
        """Тест витягування вкладеного JSON"""
        text = 'var data = {"outer": {"inner": "value"}};'
        result = _extract_balanced_json(text, text.index('{'))

        assert result == '{"outer": {"inner": "value"}}'
        parsed = json.loads(result)
        assert parsed['outer']['inner'] == 'value'

    def test_extract_json_with_string_braces(self):
        """Тест витягування JSON з дужками в рядках"""
        text = 'var data = {"key": "value with { and }"};'
        result = _extract_balanced_json(text, text.index('{'))

        assert result == '{"key": "value with { and }"}'
        parsed = json.loads(result)
        assert parsed['key'] == 'value with { and }'

    def test_extract_json_with_escaped_quotes(self):
        """Тест витягування JSON з екранованими лапками"""
        text = r'var data = {"key": "value with \" quote"};'
        result = _extract_balanced_json(text, text.index('{'))

        assert result is not None
        assert '"key"' in result

    def test_extract_json_complex(self):
        """Тест витягування складного JSON"""
        text = '''
        DisconSchedule.fact = {
            "data": {
                "1732320000": {
                    "GPV3.2": {"1": "yes", "2": "no"}
                }
            },
            "update": "23.11.2025 19:15"
        };
        '''
        start_pos = text.index('{')
        result = _extract_balanced_json(text, start_pos)

        assert result is not None
        parsed = json.loads(result)
        assert 'data' in parsed
        assert 'update' in parsed
        assert parsed['data']['1732320000']['GPV3.2']['1'] == 'yes'

    def test_extract_json_invalid_start(self):
        """Тест витягування з невалідної позиції"""
        text = 'var data = {"key": "value"};'
        result = _extract_balanced_json(text, 0)  # Не починається з {

        assert result is None

    def test_extract_json_out_of_bounds(self):
        """Тест витягування з позиції за межами"""
        text = 'var data = {"key": "value"};'
        result = _extract_balanced_json(text, len(text) + 10)

        assert result is None


# ============= ЗАПУСК ТЕСТІВ =============

if __name__ == '__main__':
    # Запуск тестів з детальним виводом
    pytest.main([
        __file__,
        '-v',  # Verbose
        '-s',  # Показувати print
        '--tb=short',  # Коротший traceback
        '--color=yes'  # Кольоровий вивід
    ])
