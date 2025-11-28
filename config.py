import os

SHUTDOWNS_URL = "https://www.dtek-krem.com.ua/ua/shutdowns"
CHECK_INTERVAL_MINUTES = 20
YOUR_QUEUE = os.getenv("YOUR_QUEUE", "GPV3.2")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)
TIMEZONE = "Europe/Kyiv"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
