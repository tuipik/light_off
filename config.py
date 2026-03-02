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


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value not in ("0", "false", "False")


CHECK_INTERVAL_MINUTES = _get_int_env("CHECK_INTERVAL_MINUTES", 20)
YOUR_QUEUE = os.getenv("YOUR_QUEUE", "GPV3.2")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)
TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PLAYWRIGHT_BROWSER = os.getenv("PLAYWRIGHT_BROWSER", "chromium")
PLAYWRIGHT_PROFILE_DIR = os.getenv("PLAYWRIGHT_PROFILE_DIR", "pw_profile")
PLAYWRIGHT_HEADLESS = _get_bool_env("PLAYWRIGHT_HEADLESS", True)
PLAYWRIGHT_USER_AGENT = os.getenv("PLAYWRIGHT_USER_AGENT")
AUTO_HEADFUL_ON_BLOCK = _get_bool_env("AUTO_HEADFUL_ON_BLOCK", True)
ENABLE_HTTP_PREFETCH = _get_bool_env("ENABLE_HTTP_PREFETCH", False)
MAX_BACKOFF_MINUTES = _get_int_env("MAX_BACKOFF_MINUTES", 60)
MIN_BLOCK_BACKOFF_MINUTES = _get_int_env("MIN_BLOCK_BACKOFF_MINUTES", 60)
BLOCK_ALERT_COOLDOWN_MINUTES = _get_int_env("BLOCK_ALERT_COOLDOWN_MINUTES", 360)
PLAYWRIGHT_GOTO_TIMEOUT_MS = _get_int_env("PLAYWRIGHT_GOTO_TIMEOUT_MS", 60000)
HTTP_TIMEOUT_SECONDS = _get_int_env("HTTP_TIMEOUT_SECONDS", 20)
DTEK_COOKIE = os.getenv("DTEK_COOKIE")
