# Light Off Monitor

Моніторить графіки відключень світла, зберігає стан у Redis та надсилає оновлення в Telegram.

**Розробка з консолі**

1. Створіть віртуальне оточення та встановіть залежності:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium
```

2. Запустіть Redis локально або в Docker:
```bash
docker run -d -p 6379:6379 redis:7.2-alpine
```

3. Задайте змінні середовища:
```bash
export TELEGRAM_TOKEN=your_telegram_bot_token
export TELEGRAM_CHAT_ID=your_chat_id
export ALERT_TELEGRAM_CHAT_ID=your_personal_chat_id
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

**Перший запуск (Incapsula + без дисплея)**

1. Разовий старт у headful через `xvfb`:
```bash
PLAYWRIGHT_HEADLESS=0 docker compose up -d --build
```

2. Зачекайте 1–2 хвилини, щоб профіль з cookies зберігся.
3. Поверніть headless:
```bash
PLAYWRIGHT_HEADLESS=1 docker compose up -d
```

**Якщо сайт вимагає “поставити галочку, що я людина”**

У такому випадку Incapsula не пропускає автоматичні запити. Найпростіший варіант:
1. Відкрити сайт у звичайному браузері, пройти перевірку.
2. Скопіювати cookies `visid_incap_*` і `incap_ses_*` для домену `www.dtek-krem.com.ua`.
3. Додати їх у `.env` як одну стрічку:
```
DTEK_COOKIE=visid_incap_...; incap_ses_...=...
```
4. Перезапустити контейнер.
5. Не додавайте службові атрибути (`Domain=...`, `Path=...`) та зайві аналітичні cookies (`_ga*`) — вони не потрібні для обходу блокування.

**Примітки**

- За замовчуванням Redis для консолі очікується на `localhost:6379`. Якщо ви підняли Redis на іншому порту, задайте `REDIS_PORT`.
- У Docker Redis зберігає дані у volume `redis_data`.
- Для обходу Incapsula потрібно один раз пройти перевірку в браузері з профілем. Профіль зберігається у volume `pw_profile`.
- Якщо Incapsula блокує, запустіть контейнер разово з `PLAYWRIGHT_HEADLESS=0` — в Docker використовується `xvfb`, тому дисплей не потрібен. Після проходження перевірки поверніть `PLAYWRIGHT_HEADLESS=1`.
- Для технічних алертів (Incapsula) можна задати окремий чат `ALERT_TELEGRAM_CHAT_ID`; якщо не задано, алерти йдуть у `TELEGRAM_CHAT_ID`.
- Доступні параметри керування повторними спробами: `AUTO_HEADFUL_ON_BLOCK=1` (разова спроба headful при блокуванні), `ENABLE_HTTP_PREFETCH=0` (попередній HTTP-запит без браузера), `MAX_BACKOFF_MINUTES=60` (максимальний інтервал між спробами), `MIN_BLOCK_BACKOFF_MINUTES=60` (мінімальна пауза при блокуванні), `BLOCK_ALERT_COOLDOWN_MINUTES=360` (період між алертами про блок), `PLAYWRIGHT_GOTO_TIMEOUT_MS=60000` (таймаут завантаження сторінки) і `HTTP_TIMEOUT_SECONDS=20` (таймаут HTTP-запиту без браузера).
