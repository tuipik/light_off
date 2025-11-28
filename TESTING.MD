# 🧪 Тестування ДТЕК Моніторингу

## 📋 Що тестується

### ✅ Storage (Redis)
- Підключення до Redis
- Збереження та отримання графіків
- Виявлення змін
- Деталі змін
- Історія змін
- Очищення даних

### ✅ Parser (Парсинг даних)
- Парсинг різних статусів (`yes`, `no`, `first`, `second`)
- Обробка порожніх даних
- Сортування часу
- Неіснуючі черги

### ✅ JSON Extractor
- Витягування простого JSON
- Вкладені об'єкти
- Дужки в рядках
- Екрановані символи
- Складні структури

## 🚀 Запуск тестів

### Підготовка

```bash
# Встановіть залежності
pip install -r requirements.txt

# Запустіть Redis для тестів
docker run -d -p 6379:6379 redis
```

### Запуск всіх тестів

```bash
# Базовий запуск
pytest

# З детальним виводом
pytest -v

# З покриттям коду
pytest --cov=. --cov-report=html

# Тільки швидкі тести
pytest -m "not slow"
```

### Запуск конкретних тестів

```bash
# Тільки тести Storage
pytest test_dtek.py::TestStorage

# Тільки тести Parser
pytest test_dtek.py::TestParser

# Один конкретний тест
pytest test_dtek.py::TestStorage::test_redis_connection

# Тести що містять слово "changes"
pytest -k "changes"
```

### Запуск з виводом print

```bash
pytest -s
```

## 📊 Покриття коду

```bash
# Генерація HTML звіту
pytest --cov=. --cov-report=html

# Відкрити звіт
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

## 🎯 Структура тестів

```
test_dtek.py
├── Fixtures (підготовка даних)
│   ├── redis_storage - тестове Redis підключення
│   ├── sample_schedule_1 - тестовий графік 1
│   ├── sample_schedule_2 - тестовий графік 2 (зміни)
│   └── sample_raw_data - сирі дані з сайту
│
├── TestStorage (13 тестів)
│   ├── test_redis_connection
│   ├── test_save_and_get_schedule
│   ├── test_has_changes_*
│   ├── test_get_changes_*
│   └── test_*_history
│
├── TestParser (8 тестів)
│   ├── test_parse_shutdowns_basic
│   ├── test_parse_shutdowns_*_status
│   └── test_parse_shutdowns_edge_cases
│
└── TestExtractJSON (7 тестів)
    ├── test_extract_simple_json
    ├── test_extract_nested_json
    └── test_extract_json_edge_cases
```

## ⚠️ Важливо

### Redis для тестів
Тести використовують **DB 1** (не DB 0), щоб не конфліктувати з робочими даними:
```python
storage = ScheduleStorage('redis://localhost:6379/1')
```

### Очищення після тестів
Всі тести автоматично очищають за собою дані через fixtures.

### CI/CD
Для CI/CD потрібно запускати Redis:
```yaml
services:
  redis:
    image: redis
    ports:
      - 6379:6379
```

## 🐛 Дебаг тестів

### Запуск з дебагером
```bash
pytest --pdb  # Зупинка на помилці
pytest --pdb-trace  # Зупинка на початку
```

### Детальний traceback
```bash
pytest --tb=long  # Повний traceback
pytest --tb=short  # Короткий traceback
pytest --tb=line  # Тільки рядок помилки
```

### Логи
```bash
pytest --log-cli-level=DEBUG
```

## ✅ Очікувані результати

```
test_dtek.py::TestStorage::test_redis_connection PASSED
test_dtek.py::TestStorage::test_save_and_get_schedule PASSED
test_dtek.py::TestStorage::test_has_changes_first_save PASSED
...
test_dtek.py::TestParser::test_parse_shutdowns_basic PASSED
...
test_dtek.py::TestExtractJSON::test_extract_simple_json PASSED
...

======================== 28 passed in 2.34s ========================
```

## 📝 Додавання нових тестів

```python
def test_your_feature(redis_storage, sample_schedule_1):
    """Опис тесту"""
    # Arrange (підготовка)
    redis_storage.save_schedule('TEST', sample_schedule_1)
    
    # Act (дія)
    result = redis_storage.get_current_schedule('TEST')
    
    # Assert (перевірка)
    assert result is not None
    assert result['schedule'] == sample_schedule_1
```

## 🔧 Налаштування

Редагуйте `pytest.ini` для зміни поведінки тестів:
```ini
[pytest]
addopts = -v --tb=short --color=yes
```