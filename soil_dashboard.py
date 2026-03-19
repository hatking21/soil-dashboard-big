import os
import json
import csv
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from flask import send_file
from dash import Dash, html, dcc, Input, Output, State, ALL, no_update
import plotly.graph_objects as go

# -----------------------------
# Adafruit IO settings
# -----------------------------
AIO_USERNAME = os.getenv("AIO_USERNAME")
AIO_KEY = os.getenv("AIO_KEY")

# ntfy notifications
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
NTFY_BASE_URL = os.getenv("NTFY_BASE_URL", "https://ntfy.sh")

# CSV logging (Render/server-side path)
CSV_LOG_PATH = os.getenv("CSV_LOG_PATH", "/opt/render/project/src/plant_readings.csv")

if not AIO_USERNAME or not AIO_KEY:
    raise ValueError("Missing AIO_USERNAME or AIO_KEY environment variables")

FEEDS = {
    "Amy Dieffenbachia": "amy-dieffenbachia",
    "Peace Lily": "peace-lily",
    "Periwinkle": "periwinkle",
    "Rex Begonia": "rex-begonia",
}

HEADERS = {"X-AIO-Key": AIO_KEY}
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# -----------------------------
# Logging / notification settings
# -----------------------------
CSV_LOG_INTERVAL = 300
MIN_MOISTURE_CHANGE = 2.0
CSV_RETENTION_DAYS = 35

NTFY_MIN_INTERVAL = 60
SENSOR_OFFLINE_MINUTES = 60

# Watering detection
WATERING_JUMP_THRESHOLD = 8.0

last_logged_time = {plant: None for plant in FEEDS}
last_logged_moisture = {plant: None for plant in FEEDS}

last_seen_moisture = {plant: None for plant in FEEDS}
last_seen_timestamp = {plant: None for plant in FEEDS}
last_watered_time = {plant: None for plant in FEEDS}

alert_state = {plant: False for plant in FEEDS}
offline_alert_state = {plant: False for plant in FEEDS}
last_daily_summary_date = None
last_ntfy_sent_at = None
last_csv_prune_date = None
last_csv_status = "No CSV writes yet"

if not NTFY_TOPIC:
    print("Warning: NTFY_TOPIC not set — ntfy notifications disabled", flush=True)

# -----------------------------
# Default plant rules
# -----------------------------
DEFAULT_RULE = {"dry": 20, "ideal_low": 35, "ideal_high": 80}
DEFAULT_PLANT_RULES = {plant: DEFAULT_RULE.copy() for plant in FEEDS}

# -----------------------------
# Reusable styles
# -----------------------------
PAGE_STYLE = {
    "fontFamily": "Arial, sans-serif",
    "background": "linear-gradient(180deg, #f5fbf7 0%, #eef4f8 100%)",
    "minHeight": "100vh",
    "padding": "24px",
}

CONTAINER_STYLE = {
    "maxWidth": "1280px",
    "margin": "0 auto",
}

HEADER_PANEL_STYLE = {
    "background": "linear-gradient(135deg, #2e7d5a 0%, #4e9c78 100%)",
    "color": "white",
    "borderRadius": "20px",
    "padding": "24px 26px",
    "boxShadow": "0 10px 28px rgba(46,125,90,0.18)",
    "marginBottom": "18px",
}

SECTION_STYLE = {
    "backgroundColor": "rgba(255,255,255,0.75)",
    "backdropFilter": "blur(4px)",
    "border": "1px solid rgba(0,0,0,0.06)",
    "borderRadius": "18px",
    "padding": "16px",
    "boxShadow": "0 6px 20px rgba(0,0,0,0.05)",
}

BUTTON_STYLE = {
    "padding": "10px 16px",
    "borderRadius": "10px",
    "border": "1px solid #b8c6bf",
    "cursor": "pointer",
    "backgroundColor": "#ffffff",
    "color": "#1f2b24",
    "fontWeight": "600",
    "boxShadow": "0 2px 8px rgba(0,0,0,0.04)",
}

CHIP_STYLE = {
    "display": "inline-block",
    "padding": "10px 14px",
    "borderRadius": "999px",
    "backgroundColor": "white",
    "border": "1px solid rgba(0,0,0,0.08)",
    "boxShadow": "0 2px 8px rgba(0,0,0,0.04)",
    "fontSize": "0.95rem",
    "marginRight": "10px",
    "marginBottom": "10px",
}

# -----------------------------
# Helpers
# -----------------------------
def make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_latest_feed_value(feed_key, session):
    url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data/last"
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_feed_history(feed_key, session, limit=1000):
    url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data"
    resp = session.get(url, params={"limit": limit}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_history_for_days(feed_key, session, days, limit=1000):
    entries = fetch_feed_history(feed_key, session, limit=limit)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    times = []
    moisture_vals = []
    temp_vals = []

    for entry in reversed(entries):
        created_at = entry.get("created_at")
        value = entry.get("value")

        if not created_at or value is None:
            continue

        try:
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            payload = json.loads(value)
            moisture = float(payload.get("moisture_pct"))
            temp_f = float(payload.get("temp_f"))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue

        if ts >= cutoff:
            times.append(ts)
            moisture_vals.append(moisture)
            temp_vals.append(temp_f)

    return times, moisture_vals, temp_vals


def get_axis_range(values, pad=5, min_floor=0, max_cap=None):
    if not values:
        return None

    vmin = min(values)
    vmax = max(values)

    low = max(min_floor, vmin - pad)
    high = vmax + pad

    if max_cap is not None:
        high = min(max_cap, high)

    if high <= low:
        high = low + 1

    return [low, high]


def downsample_data(times, values, step=5):
    if len(times) <= step:
        return times, values
    return times[::step], values[::step]


def get_watering_recommendation(plant, moisture, rules_dict):
    if moisture is None:
        return "No data", "#6b7280", "#f3f4f6"

    rules = rules_dict[plant]

    if moisture < rules["dry"]:
        return "Water now", "#c0392b", "#fff1ef"
    elif moisture < rules["ideal_low"]:
        return "Check soon", "#d9822b", "#fff7eb"
    elif moisture <= rules["ideal_high"]:
        return "Moisture looks good", "#2e8b57", "#f2fff7"
    else:
        return "Wet / hold off", "#2f7ea1", "#eef9ff"


def ensure_csv_directory_exists():
    directory = os.path.dirname(CSV_LOG_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)


def ensure_csv_exists():
    ensure_csv_directory_exists()
    if not os.path.exists(CSV_LOG_PATH):
        with open(CSV_LOG_PATH, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp_utc",
                "plant",
                "moisture_pct",
                "temp_f",
                "raw",
                "recommendation",
                "sensor_offline",
            ])


def prune_csv_file():
    if not os.path.exists(CSV_LOG_PATH):
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=CSV_RETENTION_DAYS)
    kept_rows = []

    try:
        with open(CSV_LOG_PATH, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if not fieldnames:
                return

            for row in reader:
                ts_text = row.get("timestamp_utc")
                if not ts_text:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_text)
                except ValueError:
                    continue
                if ts >= cutoff:
                    kept_rows.append(row)

        with open(CSV_LOG_PATH, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(kept_rows)

    except Exception as e:
        print(f"Failed to prune CSV file: {e}", flush=True)


def maybe_prune_csv_file():
    global last_csv_prune_date
    today = datetime.now(timezone.utc).date()
    if last_csv_prune_date == today:
        return
    prune_csv_file()
    last_csv_prune_date = today


def log_to_csv(timestamp, plant, moisture, temp_f, raw, recommendation, sensor_offline):
    global last_csv_status
    ensure_csv_exists()

    try:
        with open(CSV_LOG_PATH, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp.isoformat(),
                plant,
                moisture,
                temp_f,
                raw,
                recommendation,
                sensor_offline,
            ])
        maybe_prune_csv_file()
        last_csv_status = f"Last write OK: {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %I:%M:%S %p')}"
    except Exception as e:
        last_csv_status = f"Last write failed: {e}"
        print(f"Failed to log to CSV for {plant}: {e}", flush=True)


def get_csv_row_count():
    if not os.path.exists(CSV_LOG_PATH):
        return 0
    try:
        with open(CSV_LOG_PATH, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            return max(0, len(rows) - 1)
    except Exception as e:
        print(f"Failed to count CSV rows: {e}", flush=True)
        return 0


def get_csv_last_write_time():
    if not os.path.exists(CSV_LOG_PATH):
        return "Not created yet"
    try:
        ts = os.path.getmtime(CSV_LOG_PATH)
        dt_local = datetime.fromtimestamp(ts, tz=LOCAL_TZ)
        return dt_local.strftime("%Y-%m-%d %I:%M:%S %p")
    except Exception as e:
        print(f"Failed to get CSV last write time: {e}", flush=True)
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


def update_last_watered_if_needed(plant, moisture, ts, offline):
    previous_moisture = last_seen_moisture[plant]
    previous_ts = last_seen_timestamp[plant]

    if ts is None:
        return

    is_newer = previous_ts is None or ts > previous_ts

    if (
        not offline
        and is_newer
        and previous_moisture is not None
        and (moisture - previous_moisture) >= WATERING_JUMP_THRESHOLD
    ):
        last_watered_time[plant] = ts

    if is_newer:
        last_seen_moisture[plant] = moisture
        last_seen_timestamp[plant] = ts


def format_last_watered(plant):
    ts = last_watered_time[plant]
    if ts is None:
        return "Last watered: not detected yet"
    return f"Last watered: {ts.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %I:%M:%S %p')}"


def send_ntfy_alert(title, message, priority="default", tags=None):
    global last_ntfy_sent_at

    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set — ntfy notifications disabled", flush=True)
        return False

    now = datetime.now(timezone.utc)
    if last_ntfy_sent_at is not None:
        seconds_since_last = (now - last_ntfy_sent_at).total_seconds()
        if seconds_since_last < NTFY_MIN_INTERVAL:
            print(f"ntfy send skipped due to cooldown ({seconds_since_last:.1f}s since last send)", flush=True)
            return False

    url = f"{NTFY_BASE_URL.rstrip('/')}/{NTFY_TOPIC}"
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=20)
        print(f"ntfy status: {resp.status_code}", flush=True)
        print(f"ntfy response: {resp.text}", flush=True)

        if resp.status_code >= 400:
            print(f"ntfy send failed: {resp.status_code} {resp.text}", flush=True)
            return False

        last_ntfy_sent_at = now
        return True
    except Exception as e:
        print(f"Failed to send ntfy notification: {e}", flush=True)
        return False


def is_sensor_offline(timestamp, offline_minutes=SENSOR_OFFLINE_MINUTES):
    if timestamp is None:
        return True
    now_utc = datetime.now(timezone.utc)
    age_seconds = (now_utc - timestamp).total_seconds()
    return age_seconds > offline_minutes * 60


def maybe_send_offline_alert(plant, timestamp):
    was_offline = offline_alert_state[plant]
    is_offline = is_sensor_offline(timestamp)

    print(
        f"offline check | {plant} | timestamp={timestamp} | "
        f"was_offline={was_offline} | is_offline={is_offline}",
        flush=True
    )

    if is_offline and not was_offline:
        age_text = "unknown"
        if timestamp is not None:
            age_minutes = (datetime.now(timezone.utc) - timestamp).total_seconds() / 60.0
            age_text = f"{age_minutes:.0f} minutes"

        print(f"Sending offline alert for {plant}", flush=True)
        send_ntfy_alert(
            title=f"Sensor offline: {plant}",
            message=(
                f"No recent sensor update for {plant}.\n\n"
                f"Last reading age: {age_text}\n"
                f"Offline threshold: {SENSOR_OFFLINE_MINUTES} minutes"
            ),
            priority="high",
            tags=["warning", "satellite"],
        )

    offline_alert_state[plant] = is_offline
    return is_offline


def maybe_send_urgent_alert(plant, moisture, recommendation):
    was_alerting = alert_state[plant]
    is_alerting = (recommendation == "Water now")

    print(
        f"ntfy check | {plant} | moisture={moisture} | "
        f"recommendation={recommendation} | was_alerting={was_alerting} | "
        f"is_alerting={is_alerting}",
        flush=True
    )

    if is_alerting and not was_alerting:
        print(f"Sending ntfy urgent alert for {plant}", flush=True)
        send_ntfy_alert(
            title=f"Water alert: {plant}",
            message=(
                f"{plant} is dry.\n\n"
                f"Moisture: {moisture:.1f}%\n"
                f"Recommendation: Water now"
            ),
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

    lines = []
    urgent = []
    offline_plants = []

    for plant, entry in latest_snapshot.items():
        moisture = entry.get("moisture")
        temp_f = entry.get("temp_f")
        rec = entry.get("recommendation")
        offline = entry.get("offline", False)

        if moisture is None or temp_f is None:
            line = f"- {plant}: no data"
        else:
            line = f"- {plant}: {moisture:.1f}% | {temp_f:.1f}°F | {rec}"

        lines.append(line)

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


def add_ideal_band(fig, plant, rules_dict):
    rules = rules_dict[plant]
    fig.add_hrect(
        y0=rules["ideal_low"],
        y1=rules["ideal_high"],
        fillcolor="rgba(46,139,87,0.10)",
        line_width=0,
    )


def style_figure(fig, title, yaxis_title, yaxis_range=None):
    fig.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        xaxis_title="Time",
        yaxis_title=yaxis_title,
        template="plotly_white",
        height=460,
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(0,0,0,0.08)")
    if yaxis_range is not None:
        fig.update_yaxes(range=yaxis_range)
    return fig


def make_card(plant):
    return html.Div(
        id=f"card-{plant}",
        style={
            "width": "270px",
            "borderRadius": "18px",
            "backgroundColor": "white",
            "boxShadow": "0 10px 24px rgba(0,0,0,0.06)",
            "border": "1px solid rgba(0,0,0,0.06)",
            "overflow": "hidden",
        },
    )


def build_moisture_bar(moisture, rec_color):
    safe_moisture = max(0, min(100, moisture))
    return html.Div(
        [
            html.Div("Moisture level", style={"color": "#5b6b63", "fontSize": "0.85rem", "marginBottom": "6px"}),
            html.Div(
                [
                    html.Div(
                        style={
                            "width": f"{safe_moisture}%",
                            "height": "100%",
                            "background": f"linear-gradient(90deg, {rec_color}, {rec_color})",
                            "borderRadius": "999px",
                            "transition": "width 0.4s ease",
                        }
                    )
                ],
                style={
                    "height": "12px",
                    "backgroundColor": "#e9efeb",
                    "borderRadius": "999px",
                    "overflow": "hidden",
                    "border": "1px solid rgba(0,0,0,0.06)",
                },
            ),
        ],
        style={"marginBottom": "14px"},
    )


def build_settings_panel(rules_dict):
    children = [
        html.H3("Plant Threshold Settings", style={"marginTop": "0"}),
        html.P("These settings are stored in this browser.", style={"color": "#5b6b63"}),
        html.Div(
            [
                html.Span(f"Sensor offline threshold: {SENSOR_OFFLINE_MINUTES} min", style=CHIP_STYLE),
                html.Span(f"Watering jump threshold: {WATERING_JUMP_THRESHOLD:.1f}%", style=CHIP_STYLE),
                html.Span(f"CSV retention: {CSV_RETENTION_DAYS} days", style=CHIP_STYLE),
                html.Span(f"CSV rows: {get_csv_row_count()}", style=CHIP_STYLE),
            ]
        ),
        html.P(f"CSV file: {CSV_LOG_PATH}", style={"color": "#5b6b63"}),
        html.P(f"CSV last write: {get_csv_last_write_time()}", style={"color": "#5b6b63"}),
        html.P(f"CSV status: {last_csv_status}", style={"color": "#2d3c35", "fontWeight": "600"}),
    ]

    for plant in FEEDS:
        plant_rules = rules_dict.get(plant, DEFAULT_RULE)

        children.append(
            html.Div(
                [
                    html.H4(plant, style={"marginTop": "0", "marginBottom": "12px"}),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Dry threshold", style={"fontWeight": "600"}),
                                    dcc.Input(
                                        id={"type": "dry-input", "plant": plant},
                                        type="number",
                                        value=plant_rules["dry"],
                                        min=0,
                                        max=100,
                                        step=1,
                                        style={"width": "100%", "padding": "10px", "borderRadius": "10px", "border": "1px solid #ccd7d0"},
                                    ),
                                ],
                                style={"flex": "1"},
                            ),
                            html.Div(
                                [
                                    html.Label("Ideal low", style={"fontWeight": "600"}),
                                    dcc.Input(
                                        id={"type": "ideal-low-input", "plant": plant},
                                        type="number",
                                        value=plant_rules["ideal_low"],
                                        min=0,
                                        max=100,
                                        step=1,
                                        style={"width": "100%", "padding": "10px", "borderRadius": "10px", "border": "1px solid #ccd7d0"},
                                    ),
                                ],
                                style={"flex": "1"},
                            ),
                            html.Div(
                                [
                                    html.Label("Ideal high", style={"fontWeight": "600"}),
                                    dcc.Input(
                                        id={"type": "ideal-high-input", "plant": plant},
                                        type="number",
                                        value=plant_rules["ideal_high"],
                                        min=0,
                                        max=100,
                                        step=1,
                                        style={"width": "100%", "padding": "10px", "borderRadius": "10px", "border": "1px solid #ccd7d0"},
                                    ),
                                ],
                                style={"flex": "1"},
                            ),
                        ],
                        style={"display": "flex", "gap": "12px", "marginBottom": "8px"},
                    ),
                ],
                style={**SECTION_STYLE, "marginBottom": "14px"},
            )
        )

    children.append(
        html.Div(
            [
                html.Button("Save Rules", id="save-rules-button", n_clicks=0, style={**BUTTON_STYLE, "marginRight": "12px"}),
                html.Button("Send ntfy Test Message", id="ntfy-test-button", n_clicks=0, style={**BUTTON_STYLE, "marginRight": "12px"}),
                html.A(
                    "Download CSV",
                    href="/download-csv",
                    target="_blank",
                    style={
                        **BUTTON_STYLE,
                        "display": "inline-block",
                        "textDecoration": "none",
                        "color": "#1f2b24",
                    },
                ),
            ],
            style={"marginBottom": "12px"},
        )
    )

    children.append(html.Div(id="save-rules-status", style={"marginTop": "10px", "fontWeight": "600"}))
    children.append(html.Div(id="ntfy-test-status", style={"marginTop": "10px", "fontWeight": "600"}))

    return html.Div(children, style=SECTION_STYLE)


def build_live_figures(session, rules_dict):
    moisture_fig = go.Figure()
    temp_fig = go.Figure()
    added_band = False
    all_moisture = []
    all_temp = []

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=(1 / 24), limit=300)

            if times:
                moisture_fig.add_trace(go.Scatter(x=times, y=moisture_vals, mode="lines", name=plant))
                temp_fig.add_trace(go.Scatter(x=times, y=temp_vals, mode="lines", name=plant))
                all_moisture.extend(moisture_vals)
                all_temp.extend(temp_vals)

                if not added_band:
                    add_ideal_band(moisture_fig, plant, rules_dict)
                    added_band = True
        except Exception as e:
            print(f"Failed live history for {plant}: {e}", flush=True)

    moisture_range = get_axis_range(all_moisture, pad=5, min_floor=0, max_cap=100)
    temp_range = get_axis_range(all_temp, pad=5, min_floor=0, max_cap=None)

    return (
        style_figure(moisture_fig, "Live Moisture (Last Hour)", "Moisture (%)", moisture_range),
        style_figure(temp_fig, "Live Temperature (Last Hour)", "Temperature (°F)", temp_range),
    )


def build_weekly_figures(session, rules_dict):
    weekly_moisture_fig = go.Figure()
    weekly_temp_fig = go.Figure()
    added_band = False
    all_moisture = []
    all_temp = []

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=7, limit=1000)
            times_m, moisture_vals_ds = downsample_data(times, moisture_vals, step=2)
            times_t, temp_vals_ds = downsample_data(times, temp_vals, step=2)

            if times_m:
                weekly_moisture_fig.add_trace(go.Scatter(x=times_m, y=moisture_vals_ds, mode="lines", name=plant))
                all_moisture.extend(moisture_vals_ds)
                if not added_band:
                    add_ideal_band(weekly_moisture_fig, plant, rules_dict)
                    added_band = True

            if times_t:
                weekly_temp_fig.add_trace(go.Scatter(x=times_t, y=temp_vals_ds, mode="lines", name=plant))
                all_temp.extend(temp_vals_ds)
        except Exception as e:
            print(f"Failed weekly history for {plant}: {e}", flush=True)

    moisture_range = get_axis_range(all_moisture, pad=5, min_floor=0, max_cap=100)
    temp_range = get_axis_range(all_temp, pad=5, min_floor=0, max_cap=None)

    return (
        style_figure(weekly_moisture_fig, "Weekly Moisture Trend", "Moisture (%)", moisture_range),
        style_figure(weekly_temp_fig, "Weekly Temperature Trend", "Temperature (°F)", temp_range),
    )


def build_monthly_figures(session, rules_dict):
    monthly_moisture_fig = go.Figure()
    monthly_temp_fig = go.Figure()
    added_band = False
    all_moisture = []
    all_temp = []

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=30, limit=1000)
            times_m, moisture_vals_ds = downsample_data(times, moisture_vals, step=10)
            times_t, temp_vals_ds = downsample_data(times, temp_vals, step=10)

            if times_m:
                monthly_moisture_fig.add_trace(go.Scatter(x=times_m, y=moisture_vals_ds, mode="lines", name=plant))
                all_moisture.extend(moisture_vals_ds)
                if not added_band:
                    add_ideal_band(monthly_moisture_fig, plant, rules_dict)
                    added_band = True

            if times_t:
                monthly_temp_fig.add_trace(go.Scatter(x=times_t, y=temp_vals_ds, mode="lines", name=plant))
                all_temp.extend(temp_vals_ds)
        except Exception as e:
            print(f"Failed monthly history for {plant}: {e}", flush=True)

    moisture_range = get_axis_range(all_moisture, pad=5, min_floor=0, max_cap=100)
    temp_range = get_axis_range(all_temp, pad=5, min_floor=0, max_cap=None)

    return (
        style_figure(monthly_moisture_fig, "Monthly Moisture Trend", "Moisture (%)", moisture_range),
        style_figure(monthly_temp_fig, "Monthly Temperature Trend", "Temperature (°F)", temp_range),
    )


app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server
app.title = "Soil Monitor Dashboard"

@server.route("/download-csv")
def download_csv():
    ensure_csv_exists()
    maybe_prune_csv_file()
    return send_file(
        CSV_LOG_PATH,
        mimetype="text/csv",
        as_attachment=True,
        download_name="plant_readings.csv",
    )

plant_names = list(FEEDS.keys())

app.layout = html.Div(
    style=PAGE_STYLE,
    children=[
        html.Div(
            style=CONTAINER_STYLE,
            children=[
                html.Div(
                    style=HEADER_PANEL_STYLE,
                    children=[
                        html.H1("Plant Soil Monitor", style={"margin": "0 0 8px 0", "fontSize": "2rem"}),
                        html.P(
                            "Track moisture, temperature, alerts, and logging for all plants in one place.",
                            style={"margin": "0", "opacity": "0.92", "fontSize": "1.05rem"},
                        ),
                    ],
                ),

                dcc.Store(
                    id="plant-rules-store",
                    storage_type="local",
                    data=DEFAULT_PLANT_RULES,
                ),

                html.Div(id="system-status"),
                html.Div(id="alert-banner"),

                dcc.Interval(id="refresh", interval=30000, n_intervals=0),

                html.Div(
                    [make_card(plant) for plant in plant_names],
                    style={
                        "display": "flex",
                        "flexWrap": "wrap",
                        "gap": "14px",
                        "marginBottom": "18px",
                    },
                ),

                dcc.Tabs(
                    id="view-tabs",
                    value="live",
                    colors={
                        "border": "#d7e2dc",
                        "primary": "#2e7d5a",
                        "background": "#f7faf8",
                    },
                    children=[
                        dcc.Tab(label="Live", value="live", style={"padding": "12px", "fontWeight": "600"}, selected_style={"padding": "12px", "fontWeight": "700"}),
                        dcc.Tab(label="Weekly", value="weekly", style={"padding": "12px", "fontWeight": "600"}, selected_style={"padding": "12px", "fontWeight": "700"}),
                        dcc.Tab(label="Monthly", value="monthly", style={"padding": "12px", "fontWeight": "600"}, selected_style={"padding": "12px", "fontWeight": "700"}),
                        dcc.Tab(label="Settings", value="settings", style={"padding": "12px", "fontWeight": "600"}, selected_style={"padding": "12px", "fontWeight": "700"}),
                    ],
                ),

                html.Div(id="tab-content", style={"marginTop": "16px"}),
            ],
        )
    ],
)


@app.callback(
    Output("plant-rules-store", "data"),
    Output("save-rules-status", "children"),
    Input("save-rules-button", "n_clicks"),
    State({"type": "dry-input", "plant": ALL}, "value"),
    State({"type": "ideal-low-input", "plant": ALL}, "value"),
    State({"type": "ideal-high-input", "plant": ALL}, "value"),
    prevent_initial_call=True,
)
def save_rules(n_clicks, dry_values, low_values, high_values):
    global alert_state, offline_alert_state

    plants = list(FEEDS.keys())
    new_rules = {}

    for i, plant in enumerate(plants):
        dry = dry_values[i]
        low = low_values[i]
        high = high_values[i]

        if dry is None or low is None or high is None:
            return no_update, "All values are required."

        if not (0 <= dry <= low <= high <= 100):
            return no_update, f"Invalid values for {plant}. Must satisfy dry ≤ ideal low ≤ ideal high."

        new_rules[plant] = {"dry": dry, "ideal_low": low, "ideal_high": high}

    alert_state = {plant: False for plant in FEEDS}
    offline_alert_state = {plant: False for plant in FEEDS}

    return new_rules, "Rules saved in this browser. Alert state reset."


@app.callback(
    Output("ntfy-test-status", "children"),
    Input("ntfy-test-button", "n_clicks"),
    prevent_initial_call=True,
)
def send_test_ntfy_message(n_clicks):
    if not NTFY_TOPIC:
        return "ntfy is not configured. Add NTFY_TOPIC in Render."

    now_local = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %I:%M:%S %p")
    ok = send_ntfy_alert(
        title="Soil Monitor Test",
        message=(
            f"Soil Monitor test notification\n\n"
            f"Time: {now_local}\n"
            f"If you received this, ntfy alerts are working."
        ),
        priority="default",
        tags=["white_check_mark", "seedling"],
    )

    return "ntfy test notification sent." if ok else "ntfy test failed. Check Render logs."


@app.callback(
    [Output(f"card-{plant}", "children") for plant in plant_names]
    + [Output("system-status", "children"), Output("alert-banner", "children")],
    [Input("refresh", "n_intervals"), Input("plant-rules-store", "data")],
)
def update_cards(n, rules_dict):
    if not rules_dict:
        rules_dict = DEFAULT_PLANT_RULES

    session = make_session()
    cards = []
    dry_alerts = []
    offline_alerts = []
    successful_fetches = 0
    refresh_time = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %I:%M:%S %p")
    latest_snapshot = {}

    for plant, feed_key in FEEDS.items():
        try:
            feed_data = fetch_latest_feed_value(feed_key, session)
            payload_text = feed_data.get("value")
            created_at = feed_data.get("created_at")

            if payload_text is None:
                raise ValueError("Latest feed entry missing value")

            payload = json.loads(payload_text)
            moisture = float(payload.get("moisture_pct"))
            temp_f = float(payload.get("temp_f"))

            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else None
            offline = maybe_send_offline_alert(plant, ts)

            update_last_watered_if_needed(plant, moisture, ts, offline)

            recommendation, rec_color, bg_color = get_watering_recommendation(plant, moisture, rules_dict)

            if offline:
                recommendation = "Sensor offline"
                rec_color = "#6c757d"
                bg_color = "#f1f1f1"

            latest_snapshot[plant] = {
                "moisture": moisture,
                "temp_f": temp_f,
                "recommendation": recommendation,
                "offline": offline,
                "timestamp": ts.isoformat() if ts else None,
            }

            if should_log_reading(plant, moisture):
                raw_val = payload.get("raw")
                raw = int(raw_val) if raw_val is not None else None
                log_to_csv(
                    timestamp=ts or datetime.now(timezone.utc),
                    plant=plant,
                    moisture=moisture,
                    temp_f=temp_f,
                    raw=raw,
                    recommendation=recommendation,
                    sensor_offline=offline,
                )

            if not offline:
                maybe_send_urgent_alert(plant, moisture, recommendation)
            else:
                alert_state[plant] = False

            if recommendation == "Water now" and not offline:
                dry_alerts.append(plant)
            if offline:
                offline_alerts.append(plant)

            successful_fetches += 1

            last_update_text = ts.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %I:%M:%S %p") if ts else "--"

            cards.append([
                html.Div(
                    [
                        html.Div(
                            [
                                html.H3(plant, style={"margin": "0", "fontSize": "1.15rem"}),
                                html.Div(
                                    recommendation,
                                    style={
                                        "padding": "6px 10px",
                                        "borderRadius": "999px",
                                        "backgroundColor": "rgba(255,255,255,0.7)",
                                        "border": f"1px solid {rec_color}",
                                        "color": rec_color,
                                        "fontWeight": "700",
                                        "fontSize": "0.85rem",
                                    },
                                ),
                            ],
                            style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "14px"},
                        ),
                        html.Div(
                            [
                                html.Div([html.Div("Moisture", style={"color": "#5b6b63", "fontSize": "0.85rem"}), html.Div(f"{moisture:.1f} %", style={"fontSize": "1.3rem", "fontWeight": "700"})], style={"flex": "1"}),
                                html.Div([html.Div("Temp", style={"color": "#5b6b63", "fontSize": "0.85rem"}), html.Div(f"{temp_f:.2f} °F", style={"fontSize": "1.3rem", "fontWeight": "700"})], style={"flex": "1"}),
                            ],
                            style={"display": "flex", "gap": "12px", "marginBottom": "12px"},
                        ),
                        build_moisture_bar(moisture, rec_color),
                        html.Div(format_last_watered(plant), style={"marginBottom": "8px", "color": "#4c5d55", "fontSize": "0.92rem", "fontWeight": "600"}),
                        html.Div(f"Last update: {last_update_text}", style={"color": "#5b6b63", "fontSize": "0.92rem"}),
                    ],
                    style={
                        "backgroundColor": bg_color,
                        "border": f"2px solid {rec_color}",
                        "borderRadius": "18px",
                        "padding": "16px",
                        "minHeight": "235px",
                    },
                )
            ])

        except Exception as e:
            print(f"Failed latest card fetch for {plant}: {e}", flush=True)
            offline_alert_state[plant] = True
            latest_snapshot[plant] = {
                "moisture": None,
                "temp_f": None,
                "recommendation": "No data",
                "offline": True,
                "timestamp": None,
            }
            offline_alerts.append(plant)

            cards.append([
                html.Div(
                    [
                        html.H3(plant, style={"marginTop": "0"}),
                        html.Div("No data", style={"fontWeight": "700", "color": "#666666", "marginBottom": "10px"}),
                        html.Div("Moisture: --"),
                        html.Div("Temperature: --"),
                        html.Div(format_last_watered(plant), style={"marginTop": "10px", "marginBottom": "8px", "color": "#4c5d55", "fontSize": "0.92rem", "fontWeight": "600"}),
                        html.Div("Last update: --", style={"color": "#666", "fontSize": "0.92rem"}),
                    ],
                    style={
                        "backgroundColor": "#f5f5f5",
                        "border": "2px solid #cccccc",
                        "borderRadius": "18px",
                        "padding": "16px",
                        "minHeight": "235px",
                    },
                )
            ])

    maybe_send_daily_summary(latest_snapshot)

    notify_text = "ready"
    now_utc = datetime.now(timezone.utc)
    if last_ntfy_sent_at is not None:
        seconds_since = (now_utc - last_ntfy_sent_at).total_seconds()
        remaining = max(0, int(NTFY_MIN_INTERVAL - seconds_since))
        if remaining > 0:
            notify_text = f"cooldown {remaining}s"

    status = html.Div(
        [
            html.Div(f"Last refresh: {refresh_time}", style=CHIP_STYLE),
            html.Div(f"Plants fetched: {successful_fetches}/{len(FEEDS)}", style=CHIP_STYLE),
            html.Div(f"Notifications: {notify_text}", style=CHIP_STYLE),
            html.Div(f"CSV: {last_csv_status}", style=CHIP_STYLE),
        ],
        style={**SECTION_STYLE, "marginBottom": "16px"},
    )

    if offline_alerts and dry_alerts:
        alert_banner = html.Div(
            [
                html.Div(f"Offline sensors: {', '.join(offline_alerts)}"),
                html.Div(f"Water alerts: {', '.join(dry_alerts)}", style={"marginTop": "6px"}),
            ],
            style={
                "backgroundColor": "#fff4e5",
                "color": "#8a5a00",
                "border": "1px solid #f0d9a7",
                "padding": "14px 18px",
                "borderRadius": "16px",
                "marginBottom": "16px",
                "fontWeight": "700",
                "boxShadow": "0 6px 16px rgba(0,0,0,0.04)",
            },
        )
    elif offline_alerts:
        alert_banner = html.Div(
            f"Offline sensors: {', '.join(offline_alerts)}",
            style={
                "backgroundColor": "#f2f2f2",
                "color": "#555",
                "border": "1px solid #d6d6d6",
                "padding": "14px 18px",
                "borderRadius": "16px",
                "marginBottom": "16px",
                "fontWeight": "700",
                "boxShadow": "0 6px 16px rgba(0,0,0,0.04)",
            },
        )
    elif dry_alerts:
        alert_banner = html.Div(
            f"Water alert: {', '.join(dry_alerts)}",
            style={
                "backgroundColor": "#ffeaea",
                "color": "#a94442",
                "border": "1px solid #ebccd1",
                "padding": "14px 18px",
                "borderRadius": "16px",
                "marginBottom": "16px",
                "fontWeight": "700",
                "boxShadow": "0 6px 16px rgba(0,0,0,0.04)",
            },
        )
    else:
        alert_banner = html.Div(
            "No urgent watering alerts or offline sensors.",
            style={
                "backgroundColor": "#eef9ee",
                "color": "#2f6b2f",
                "border": "1px solid #cfe9cf",
                "padding": "14px 18px",
                "borderRadius": "16px",
                "marginBottom": "16px",
                "fontWeight": "700",
                "boxShadow": "0 6px 16px rgba(0,0,0,0.04)",
            },
        )

    return cards + [status, alert_banner]


@app.callback(
    Output("tab-content", "children"),
    [Input("view-tabs", "value"), Input("refresh", "n_intervals"), Input("plant-rules-store", "data")],
)
def render_tab(tab, n, rules_dict):
    if not rules_dict:
        rules_dict = DEFAULT_PLANT_RULES

    if tab == "settings":
        return build_settings_panel(rules_dict)

    session = make_session()

    if tab == "live":
        moisture_fig, temp_fig = build_live_figures(session, rules_dict)
        return html.Div(
            [
                html.Div(dcc.Graph(figure=moisture_fig), style=SECTION_STYLE),
                html.Div(dcc.Graph(figure=temp_fig), style={**SECTION_STYLE, "marginTop": "16px"}),
            ]
        )

    if tab == "weekly":
        weekly_moisture_fig, weekly_temp_fig = build_weekly_figures(session, rules_dict)
        return html.Div(
            [
                html.Div(dcc.Graph(figure=weekly_moisture_fig), style=SECTION_STYLE),
                html.Div(dcc.Graph(figure=weekly_temp_fig), style={**SECTION_STYLE, "marginTop": "16px"}),
            ]
        )

    monthly_moisture_fig, monthly_temp_fig = build_monthly_figures(session, rules_dict)
    return html.Div(
        [
            html.Div(dcc.Graph(figure=monthly_moisture_fig), style=SECTION_STYLE),
            html.Div(dcc.Graph(figure=monthly_temp_fig), style={**SECTION_STYLE, "marginTop": "16px"}),
        ]
    )


if __name__ == "__main__":
    ensure_csv_exists()
    maybe_prune_csv_file()
    app.run(host="0.0.0.0", port=10000, debug=False)
