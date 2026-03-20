import os
from zoneinfo import ZoneInfo

AIO_USERNAME = os.getenv("AIO_USERNAME")
AIO_KEY = os.getenv("AIO_KEY")

NTFY_TOPIC = os.getenv("NTFY_TOPIC")
NTFY_BASE_URL = os.getenv("NTFY_BASE_URL", "https://ntfy.sh")

CSV_LOG_PATH = os.getenv("CSV_LOG_PATH", "/opt/render/project/src/plant_readings.csv")
WATERING_LOG_PATH = os.getenv("WATERING_LOG_PATH", "/opt/render/project/src/watering_events.csv")

LOCAL_TZ = ZoneInfo(os.getenv("LOCAL_TIMEZONE", "America/Los_Angeles"))

CARD_REFRESH_MS = int(os.getenv("CARD_REFRESH_MS", "30000"))
HISTORY_REFRESH_MS = int(os.getenv("HISTORY_REFRESH_MS", "180000"))

CSV_LOG_INTERVAL = int(os.getenv("CSV_LOG_INTERVAL", "300"))
MIN_MOISTURE_CHANGE = float(os.getenv("MIN_MOISTURE_CHANGE", "2.0"))
CSV_RETENTION_DAYS = int(os.getenv("CSV_RETENTION_DAYS", "35"))

NTFY_MIN_INTERVAL = int(os.getenv("NTFY_MIN_INTERVAL", "60"))
SENSOR_OFFLINE_MINUTES = int(os.getenv("SENSOR_OFFLINE_MINUTES", "60"))
TEMP_F_MAX = float(os.getenv("TEMP_F_MAX", "120"))
WATERING_JUMP_THRESHOLD = float(os.getenv("WATERING_JUMP_THRESHOLD", "8.0"))

REQUEST_RETRIES = int(os.getenv("REQUEST_RETRIES", "2"))
REQUEST_TIMEOUT_LAST = int(os.getenv("REQUEST_TIMEOUT_LAST", "15"))
REQUEST_TIMEOUT_HISTORY = int(os.getenv("REQUEST_TIMEOUT_HISTORY", "30"))

FEEDS = {
    "Amy Dieffenbachia": {"feed": "amy-dieffenbachia", "emoji": "🌿"},
    "Peace Lily": {"feed": "peace-lily", "emoji": "🪴"},
    "Periwinkle": {"feed": "periwinkle", "emoji": "🌸"},
    "Rex Begonia": {"feed": "rex-begonia", "emoji": "🍃"},
}

DEFAULT_RULE = {"dry": 20, "ideal_low": 35, "ideal_high": 80}
DEFAULT_PLANT_RULES = {plant: DEFAULT_RULE.copy() for plant in FEEDS}

HEADERS = {"X-AIO-Key": AIO_KEY}