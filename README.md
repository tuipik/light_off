# Light Off Monitor

Моніторить графіки відключень світла, зберігає стан у Redis та надсилає оновлення в Telegram.

**Розробка з консолі**

1. Створіть віртуальне оточення та встановіть залежності:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install firefox
```

2. Запустіть Redis локально або в Docker:
```bash
docker run -d -p 6379:6379 redis:7.2-alpine
```

3. Задайте змінні середовища:
```bash
export TELEGRAM_TOKEN=your_telegram_bot_token
export TELEGRAM_CHAT_ID=your_chat_id
export YOUR_QUEUE=GPV3.2
export CHECK_INTERVAL_MINUTES=20
export TIMEZONE=Europe/Kyiv
```

4. Запуск:
```bash
python main.py
```

**Продакшен через Docker**

1. Створіть файл `.env` на основі `.env.example`.
2. Запуск:
```bash
docker compose up -d --build
```

3. Логи:
```bash
docker compose logs -f
```

**Примітки**

- За замовчуванням Redis для консолі очікується на `localhost:6379`. Якщо ви підняли Redis на іншому порту, задайте `REDIS_PORT`.
- У Docker Redis зберігає дані у volume `redis_data`.
