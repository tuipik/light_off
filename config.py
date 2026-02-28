import os

SHUTDOWNS_URL = "https://www.dtek-krem.com.ua/ua/shutdowns"


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


CHECK_INTERVAL_MINUTES = _get_int_env("CHECK_INTERVAL_MINUTES", 20)
YOUR_QUEUE = os.getenv("YOUR_QUEUE", "GPV3.2")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)
TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
