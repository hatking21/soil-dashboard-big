from datetime import datetime, timezone
import requests

from config import LOCAL_TZ, NTFY_BASE_URL, NTFY_MIN_INTERVAL, NTFY_TOPIC

last_ntfy_sent_at = None
last_daily_summary_date = None
alert_state = {}
offline_alert_state = {}


def init_notification_state(plants):
    global alert_state, offline_alert_state
    alert_state = {plant: False for plant in plants}
    offline_alert_state = {plant: False for plant in plants}


def send_ntfy_alert(title, message, priority="default", tags=None):
    global last_ntfy_sent_at

    if not NTFY_TOPIC:
        return False

    now = datetime.now(timezone.utc)
    if last_ntfy_sent_at is not None:
        seconds_since = (now - last_ntfy_sent_at).total_seconds()
        if seconds_since < NTFY_MIN_INTERVAL:
            return False

    url = f"{NTFY_BASE_URL.rstrip('/')}/{NTFY_TOPIC}"
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=20)
        if resp.status_code >= 400:
            return False
        last_ntfy_sent_at = now
        return True
    except Exception:
        return False


def maybe_send_offline_alert(plant, is_offline, timestamp, offline_minutes):
    was_offline = offline_alert_state.get(plant, False)

    if is_offline and not was_offline:
        if timestamp is not None:
            age_minutes = (datetime.now(timezone.utc) - timestamp).total_seconds() / 60.0
            age_text = f"{age_minutes:.0f} minutes"
        else:
            age_text = "unknown"

        send_ntfy_alert(
            title=f"Sensor offline: {plant}",
            message=(
                f"No recent sensor update for {plant}.\n\n"
                f"Last reading age: {age_text}\n"
                f"Offline threshold: {offline_minutes} minutes"
            ),
            priority="high",
            tags=["warning", "satellite"],
        )

    offline_alert_state[plant] = is_offline


def maybe_send_urgent_alert(plant, moisture, recommendation):
    was_alerting = alert_state.get(plant, False)
    is_alerting = recommendation == "Water now"

    if is_alerting and not was_alerting:
        send_ntfy_alert(
            title=f"Water alert: {plant}",
            message=f"{plant} is dry.\n\nMoisture: {moisture:.1f}%\nRecommendation: Water now",
            priority="high",
            tags=["warning", "seedling"],
        )

    alert_state[plant] = is_alerting


def maybe_send_daily_summary(latest_snapshot):
    global last_daily_summary_date

    now_local = datetime.now(LOCAL_TZ)
    today = now_local.date()

    if now_local.hour < 18 or last_daily_summary_date == today:
        return

    urgent = []
    offline_plants = []
    lines = []

    for plant, entry in latest_snapshot.items():
        moisture = entry.get("moisture")
        temp_f = entry.get("temp_f")
        rec = entry.get("recommendation")
        offline = entry.get("offline", False)

        if moisture is None or temp_f is None:
            lines.append(f"- {plant}: no data")
        else:
            lines.append(f"- {plant}: {moisture:.1f}% | {temp_f:.1f}°F | {rec}")

        if rec == "Water now" and not offline:
            urgent.append(plant)
        if offline:
            offline_plants.append(plant)

    body = f"Daily Plant Summary ({now_local.strftime('%Y-%m-%d %I:%M %p')})\n\n"
    if urgent:
        body += f"Water alerts: {', '.join(urgent)}\n"
    if offline_plants:
        body += f"Offline sensors: {', '.join(offline_plants)}\n"
    if urgent or offline_plants:
        body += "\n"
    body += "\n".join(lines)

    sent = send_ntfy_alert(
        title=f"Daily Plant Summary - {now_local.strftime('%Y-%m-%d')}",
        message=body,
        priority="default",
        tags=["seedling"],
    )
    if sent:
        last_daily_summary_date = today
