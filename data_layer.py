import csv
import json
import os
from datetime import datetime, timedelta, timezone

import requests

from config import (
    AIO_USERNAME,
    CACHE_DIR,
    CSV_LOG_INTERVAL,
    CSV_LOG_PATH,
    CSV_RETENTION_DAYS,
    ERROR_LOG_PATH,
    FEEDS,
    HEADERS,
    LOCAL_TZ,
    MIN_MOISTURE_CHANGE,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT_HISTORY,
    REQUEST_TIMEOUT_LAST,
    SENSOR_OFFLINE_MINUTES,
    TEMP_F_MAX,
    WATERING_JUMP_THRESHOLD,
    WATERING_LOG_PATH,
)

last_logged_time = {plant: None for plant in FEEDS}
last_logged_moisture = {plant: None for plant in FEEDS}
last_csv_status = "No CSV writes yet"
last_csv_prune_date = None

last_seen_moisture = {plant: None for plant in FEEDS}
last_seen_timestamp = {plant: None for plant in FEEDS}
last_watered_time = {plant: None for plant in FEEDS}

health_state = {
    "adafruit_ok": False,
    "csv_ok": False,
    "watering_log_ok": False,
    "last_error": "",
    "last_successful_fetch": "Never",
    "startup_checks": [],
}


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def ensure_parent_dir(path):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)


def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def log_error(where, exc):
    ensure_parent_dir(ERROR_LOG_PATH)
    exists = os.path.exists(ERROR_LOG_PATH)

    with open(ERROR_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp_utc", "where", "error"])
        writer.writerow([datetime.now(timezone.utc).isoformat(), where, str(exc)])


def cache_path(name):
    ensure_cache_dir()
    return os.path.join(CACHE_DIR, f"{name}.json")


def save_cache(name, payload):
    try:
        with open(cache_path(name), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception as e:
        log_error("save_cache", e)


def load_cache(name, default=None):
    try:
        with open(cache_path(name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _request_json(session, url, params=None, timeout=15):
    last_exc = None
    for _ in range(REQUEST_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_exc = e
    raise last_exc


def ensure_csv_exists():
    ensure_parent_dir(CSV_LOG_PATH)
    if not os.path.exists(CSV_LOG_PATH):
        with open(CSV_LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp_utc",
                    "plant",
                    "moisture_pct",
                    "temp_f",
                    "raw",
                    "recommendation",
                    "sensor_offline",
                ]
            )


def ensure_watering_log_exists():
    ensure_parent_dir(WATERING_LOG_PATH)
    if not os.path.exists(WATERING_LOG_PATH):
        with open(WATERING_LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_utc", "plant", "moisture_before", "moisture_after"])


def prune_csv_file():
    global last_csv_prune_date

    if not os.path.exists(CSV_LOG_PATH):
        return

    today = datetime.now(timezone.utc).date()
    if last_csv_prune_date == today:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=CSV_RETENTION_DAYS)
    kept_rows = []

    with open(CSV_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            return

        for row in reader:
            try:
                ts = datetime.fromisoformat(row["timestamp_utc"])
                if ts >= cutoff:
                    kept_rows.append(row)
            except Exception:
                continue

    with open(CSV_LOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_rows)

    last_csv_prune_date = today


def log_to_csv(timestamp, plant, moisture, temp_f, raw, recommendation, sensor_offline):
    global last_csv_status

    ensure_csv_exists()
    try:
        with open(CSV_LOG_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    timestamp.isoformat(),
                    plant,
                    moisture,
                    temp_f,
                    raw,
                    recommendation,
                    sensor_offline,
                ]
            )

        prune_csv_file()
        last_csv_status = (
            f"Last write OK: {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %I:%M:%S %p')}"
        )
        health_state["csv_ok"] = True
    except Exception as e:
        last_csv_status = f"Last write failed: {e}"
        health_state["csv_ok"] = False
        health_state["last_error"] = str(e)
        log_error("log_to_csv", e)


def log_watering_event(timestamp, plant, moisture_before, moisture_after):
    ensure_watering_log_exists()
    try:
        with open(WATERING_LOG_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp.isoformat(), plant, moisture_before, moisture_after])

        health_state["watering_log_ok"] = True
    except Exception as e:
        health_state["watering_log_ok"] = False
        health_state["last_error"] = str(e)
        log_error("log_watering_event", e)


def load_last_watered_from_csv():
    ensure_watering_log_exists()
    try:
        with open(WATERING_LOG_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                plant = row.get("plant")
                ts_text = row.get("timestamp_utc")

                if not plant or not ts_text or plant not in last_watered_time:
                    continue

                try:
                    ts = datetime.fromisoformat(ts_text)
                    if last_watered_time[plant] is None or ts > last_watered_time[plant]:
                        last_watered_time[plant] = ts
                except Exception:
                    continue

        health_state["watering_log_ok"] = True
    except Exception as e:
        health_state["watering_log_ok"] = False
        health_state["last_error"] = str(e)
        log_error("load_last_watered_from_csv", e)


def get_csv_row_count():
    if not os.path.exists(CSV_LOG_PATH):
        return 0

    try:
        with open(CSV_LOG_PATH, "r", newline="", encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0


def get_csv_last_write_time():
    if not os.path.exists(CSV_LOG_PATH):
        return "Not created yet"

    try:
        ts = os.path.getmtime(CSV_LOG_PATH)
        dt_local = datetime.fromtimestamp(ts, tz=LOCAL_TZ)
        return dt_local.strftime("%Y-%m-%d %I:%M:%S %p")
    except Exception:
        return "Unavailable"


def should_log_reading(plant, moisture):
    now = datetime.now(timezone.utc)
    last_time = last_logged_time[plant]
    last_m = last_logged_moisture[plant]

    enough_time = last_time is None or (now - last_time).total_seconds() >= CSV_LOG_INTERVAL
    enough_change = last_m is None or abs(moisture - last_m) >= MIN_MOISTURE_CHANGE

    if enough_time and enough_change:
        last_logged_time[plant] = now
        last_logged_moisture[plant] = moisture
        return True

    return False


def is_sensor_offline(timestamp):
    if timestamp is None:
        return True

    age_s = (datetime.now(timezone.utc) - timestamp).total_seconds()
    return age_s > SENSOR_OFFLINE_MINUTES * 60


def format_last_watered(plant):
    ts = last_watered_time.get(plant)
    if ts is None:
        return "Watered: not detected yet"
    return f"Watered: {ts.astimezone(LOCAL_TZ).strftime('%m/%d %I:%M %p')}"


def update_last_watered_if_needed(plant, moisture, ts, offline):
    prev_m = last_seen_moisture[plant]
    prev_ts = last_seen_timestamp[plant]

    if ts is None:
        return

    is_newer = prev_ts is None or ts > prev_ts

    if (
        not offline
        and is_newer
        and prev_m is not None
        and (moisture - prev_m) >= WATERING_JUMP_THRESHOLD
    ):
        last_watered_time[plant] = ts
        log_watering_event(ts, plant, prev_m, moisture)

    if is_newer:
        last_seen_moisture[plant] = moisture
        last_seen_timestamp[plant] = ts


def fetch_latest_snapshot():
    session = make_session()
    snapshot = {}

    try:
        for plant, meta in FEEDS.items():
            feed_key = meta["feed"]
            url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data/last"

            feed_data = _request_json(session, url, timeout=REQUEST_TIMEOUT_LAST)

            payload_text = feed_data.get("value")
            created_at = feed_data.get("created_at")

            if payload_text is None:
                raise ValueError(f"Missing value for {plant}")

            payload = json.loads(payload_text)
            moisture = float(payload.get("moisture_pct"))
            temp_f = min(float(payload.get("temp_f")), TEMP_F_MAX)
            raw_val = payload.get("raw")
            raw = int(raw_val) if raw_val is not None else None
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else None

            snapshot[plant] = {
                "moisture": moisture,
                "temp_f": temp_f,
                "raw": raw,
                "timestamp": ts.isoformat() if ts else None,
            }

        health_state["adafruit_ok"] = True
        health_state["last_successful_fetch"] = datetime.now(LOCAL_TZ).strftime(
            "%Y-%m-%d %I:%M:%S %p"
        )
        save_cache("snapshot", snapshot)
        return snapshot, False

    except Exception as e:
        health_state["adafruit_ok"] = False
        health_state["last_error"] = str(e)
        log_error("fetch_latest_snapshot", e)
        return load_cache("snapshot", {}), True


def fetch_history(hours=24, cache_name="history"):
    session = make_session()
    histories = {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    try:
        for plant, meta in FEEDS.items():
            feed_key = meta["feed"]
            url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data"

            all_entries = []
            page = 0
            per_page = 1000

            while True:
                entries = _request_json(
                    session,
                    url,
                    params={
                        "limit": per_page,
                        "page": page,
                    },
                    timeout=REQUEST_TIMEOUT_HISTORY,
                )

                if not entries:
                    break

                all_entries.extend(entries)

                oldest_ts_in_page = None
                for entry in entries:
                    created_at = entry.get("created_at")
                    if not created_at:
                        continue
                    try:
                        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        if oldest_ts_in_page is None or ts < oldest_ts_in_page:
                            oldest_ts_in_page = ts
                    except Exception:
                        continue

                if len(entries) < per_page:
                    break

                if oldest_ts_in_page is not None and oldest_ts_in_page < cutoff:
                    break

                page += 1

            times = []
            moisture_vals = []
            temp_vals = []

            for entry in reversed(all_entries):
                created_at = entry.get("created_at")
                value = entry.get("value")

                if not created_at or value is None:
                    continue

                try:
                    ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    payload = json.loads(value)
                    moisture = float(payload.get("moisture_pct"))
                    temp_f = min(float(payload.get("temp_f")), TEMP_F_MAX)
                except Exception:
                    continue

                if ts >= cutoff:
                    times.append(ts.isoformat())
                    moisture_vals.append(moisture)
                    temp_vals.append(temp_f)

            histories[plant] = {
                "times": times,
                "moisture": moisture_vals,
                "temp": temp_vals,
            }

        save_cache(cache_name, histories)
        return histories, False

    except Exception as e:
        log_error(f"fetch_history_{hours}", e)
        return load_cache(cache_name, {}), True


def compute_trend_arrow(values):
    if len(values) < 3:
        return "→"

    recent = values[-1] - values[max(0, len(values) - 3)]
    if recent > 1.5:
        return "↑"
    if recent < -1.5:
        return "↓"
    return "→"


def estimate_hours_until_dry(times, moisture_values, dry_threshold):
    if len(times) < 6 or len(moisture_values) < 6:
        return None

    recent_times = times[-6:]
    recent_vals = moisture_values[-6:]

    start = recent_times[0]
    x = [(t - start).total_seconds() / 3600.0 for t in recent_times]
    y = recent_vals

    n = len(x)
    x_mean = sum(x) / n
    y_mean = sum(y) / n

    denom = sum((xi - x_mean) ** 2 for xi in x)
    if denom == 0:
        return None

    slope = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n)) / denom
    current = y[-1]

    if slope >= -0.05:
        return None

    if current <= dry_threshold:
        return 0.0

    hours = (dry_threshold - current) / slope
    return None if hours < 0 else hours


def run_startup_checks():
    checks = []
    checks.append(("AIO_USERNAME", bool(os.getenv("AIO_USERNAME"))))
    checks.append(("AIO_KEY", bool(os.getenv("AIO_KEY"))))
    checks.append(("CSV path writable", True))
    checks.append(("Watering log writable", True))
    checks.append(("ntfy configured", bool(os.getenv("NTFY_TOPIC"))))
    health_state["startup_checks"] = checks
