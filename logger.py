import logging
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import TIMEZONE


class TimezoneFormatter(logging.Formatter):
    """Formatter that always renders timestamps in the configured timezone."""

    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt=fmt, datefmt=datefmt)
        try:
            self.tz = ZoneInfo(TIMEZONE)
        except Exception:
            self.tz = timezone.utc

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=self.tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


logger = logging.getLogger("light_off")
logger.setLevel(logging.INFO)

if not logger.hasHandlers():
    handler = logging.StreamHandler(sys.stdout)
    formatter = TimezoneFormatter(
        '[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S %z'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
