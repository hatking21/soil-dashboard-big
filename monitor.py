"""Single-process monitoring, independent of Dash/browser callbacks."""
import copy
import json
import logging
import os
import threading
from datetime import datetime, timezone

from config import CACHE_DIR, CARD_REFRESH_MS, DEFAULT_PLANT_RULES, FEEDS, SENSOR_OFFLINE_MINUTES
import data_layer as data
import notifications as notifications
import calibration

lock = threading.RLock()
_stop = threading.Event()
_thread = None
_snapshot = {"snapshot": {}, "used_fallback": False}


def load_rules():
    with lock:
        rules = copy.deepcopy(DEFAULT_PLANT_RULES)
        rules.update(data.load_cache("plant_rules", {}))
        return rules


def save_rules(rules):
    # Atomic replacement prevents a polling cycle from reading a partial file.
    with lock:
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, "plant_rules.json")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(rules, f)
        os.replace(path + ".tmp", path)


def snapshot_for_browser():
    with lock:
        return copy.deepcopy(_snapshot)


def poll_once():
    global _snapshot
    snapshot, fallback = data.fetch_latest_snapshot()
    # Reference sampling is independent of CSV change-based logging.
    try:
        calibration.record_snapshot(snapshot, fallback)
    except (OSError, ValueError):
        logging.exception("Could not save watering reference samples")
    rules = load_rules()
    summary = {}
    for plant in FEEDS:
        row = snapshot.get(plant) or {}
        ts = datetime.fromisoformat(row["timestamp"]) if row.get("timestamp") else None
        offline = data.is_sensor_offline(ts)
        notifications.maybe_send_offline_alert(plant, offline, ts, SENSOR_OFFLINE_MINUTES)
        moisture = row.get("moisture")
        temp = row.get("temp_f")
        rec = "Offline"
        if moisture is not None and temp is not None:
            rule = rules[plant]
            if not offline:
                rec = ("Water now" if moisture <= rule["dry"] else
                       "Check soon" if moisture < rule["ideal_low"] else
                       "Healthy" if moisture <= rule["ideal_high"] else "Wet")
                notifications.maybe_send_urgent_alert(plant, moisture, rec)
            # Cached API responses may drive offline alerts, but are not new readings.
            if not fallback:
                data.update_last_watered_if_needed(plant, moisture, ts, offline)
                if data.should_log_reading(plant, moisture):
                    data.log_to_csv(ts or datetime.now(timezone.utc), plant, moisture,
                                    temp, row.get("raw"), rec, offline)
        summary[plant] = {"moisture": moisture, "temp_f": temp,
                          "recommendation": rec, "offline": offline}
    notifications.maybe_send_daily_summary(summary)
    data.save_cache("notification_state", {
        "dry": notifications.alert_state, "offline": notifications.offline_alert_state,
        "summary_date": (notifications.last_daily_summary_date.isoformat()
                         if notifications.last_daily_summary_date else None),
    })
    with lock:
        _snapshot = {"snapshot": snapshot, "used_fallback": fallback}


def _run():
    while not _stop.is_set():
        try:
            poll_once()
        except Exception:
            logging.exception("Background plant monitoring cycle failed; will retry")
        _stop.wait(max(1, CARD_REFRESH_MS / 1000))


def start():
    global _thread
    with lock:
        if _thread is not None and _thread.is_alive():
            return
        data.ensure_csv_exists()
        data.load_last_watered_from_csv()
        notifications.init_notification_state(FEEDS)
        saved = data.load_cache("notification_state", {})
        notifications.alert_state.update(saved.get("dry", {}))
        notifications.offline_alert_state.update(saved.get("offline", {}))
        if saved.get("summary_date"):
            from datetime import date
            notifications.last_daily_summary_date = date.fromisoformat(saved["summary_date"])
        _stop.clear()
        _thread = threading.Thread(target=_run, name="plant-monitor", daemon=True)
        _thread.start()


def stop():
    _stop.set()
