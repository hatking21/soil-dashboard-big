import os
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dash import Dash, html, dcc, Input, Output
import plotly.graph_objects as go

# -----------------------------
# Adafruit IO settings
# -----------------------------
AIO_USERNAME = os.getenv("AIO_USERNAME")
AIO_KEY = os.getenv("AIO_KEY")
SHEETS_WEBHOOK_URL = os.getenv("SHEETS_WEBHOOK_URL")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not AIO_USERNAME or not AIO_KEY:
    raise ValueError("Missing AIO_USERNAME or AIO_KEY environment variables")

FEEDS = {
    "Amy Dieffenbachia": "amy-dieffenbachia",
    "Peace Lily": "peace-lily",
    "Periwinkle": "periwinkle",
    "Rex Begonia": "rex-begonia",
}

HEADERS = {
    "X-AIO-Key": AIO_KEY,
}

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# -----------------------------
# Logging / notification settings
# -----------------------------
SHEETS_LOG_INTERVAL = 300   # 5 min
MIN_MOISTURE_CHANGE = 2.0   # percent

last_logged_time = {plant: None for plant in FEEDS}
last_logged_moisture = {plant: None for plant in FEEDS}

# Discord anti-spam state
alert_state = {plant: False for plant in FEEDS}
last_daily_summary_date = None

if not SHEETS_WEBHOOK_URL:
    print("Warning: SHEETS_WEBHOOK_URL not set — Google Sheets backup disabled", flush=True)

if not DISCORD_WEBHOOK_URL:
    print("Warning: DISCORD_WEBHOOK_URL not set — Discord notifications disabled", flush=True)

# -----------------------------
# Plant-specific watering rules
# -----------------------------
PLANT_RULES = {
    "Amy Dieffenbachia": {"dry": 30, "ideal_low": 35, "ideal_high": 60},
    "Peace Lily": {"dry": 35, "ideal_low": 40, "ideal_high": 65},
    "Periwinkle": {"dry": 25, "ideal_low": 30, "ideal_high": 55},
    "Rex Begonia": {"dry": 40, "ideal_low": 45, "ideal_high": 70},
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

        if not created_at or not value:
            continue

        try:
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            payload = json.loads(value)
            moisture = float(payload.get("moisture_pct"))
            temp_f = float(payload.get("temp_f"))
        except Exception:
            continue

        if ts >= cutoff:
            times.append(ts)
            moisture_vals.append(moisture)
            temp_vals.append(temp_f)

    return times, moisture_vals, temp_vals


def downsample_data(times, values, step=5):
    if len(times) <= step:
        return times, values
    return times[::step], values[::step]


def get_watering_recommendation(plant, moisture):
    if moisture is None:
        return "No data", "#666666", "#f4f4f4"

    rules = PLANT_RULES[plant]

    if moisture < rules["dry"]:
        return "Water now", "#d9534f", "#fff1f0"
    elif moisture < rules["ideal_low"]:
        return "Check soon", "#f0ad4e", "#fff8e8"
    elif moisture <= rules["ideal_high"]:
        return "Moisture looks good", "#5cb85c", "#f1fff1"
    else:
        return "Wet / hold off", "#5bc0de", "#eefbff"


def log_to_google_sheets(timestamp, plant, moisture, temp_f, raw):
    if not SHEETS_WEBHOOK_URL:
        return

    payload = {
        "timestamp": timestamp.isoformat(),
        "plant": plant,
        "moisture_pct": moisture,
        "temp_f": temp_f,
        "raw": raw,
    }

    try:
        requests.post(SHEETS_WEBHOOK_URL, json=payload, timeout=15)
    except Exception as e:
        print(f"Failed to log to Google Sheets for {plant}: {e}", flush=True)


def should_log_to_sheets(plant, moisture):
    now = datetime.now(timezone.utc)
    last_time = last_logged_time[plant]
    last_m = last_logged_moisture[plant]

    enough_time = (
        last_time is None or
        (now - last_time).total_seconds() >= SHEETS_LOG_INTERVAL
    )

    enough_change = (
        last_m is None or
        abs(moisture - last_m) >= MIN_MOISTURE_CHANGE
    )

    if enough_time and enough_change:
        last_logged_time[plant] = now
        last_logged_moisture[plant] = moisture
        return True

    return False


def send_discord_message(content):
    if not DISCORD_WEBHOOK_URL:
        return

    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": content},
            timeout=15,
        )
        if resp.status_code >= 400:
            print(f"Discord webhook failed: {resp.status_code} {resp.text}", flush=True)
    except Exception as e:
        print(f"Failed to send Discord message: {e}", flush=True)


def maybe_send_urgent_alert(plant, moisture, recommendation):
    was_alerting = alert_state[plant]
    is_alerting = (recommendation == "Water now")

    if is_alerting and not was_alerting:
        send_discord_message(
            f"🚨 **Water alert**\n"
            f"**{plant}** is dry.\n"
            f"Moisture: **{moisture:.1f}%**\n"
            f"Recommendation: **Water now**"
        )

    alert_state[plant] = is_alerting


def maybe_send_daily_summary(latest_snapshot):
    global last_daily_summary_date

    now_local = datetime.now(LOCAL_TZ)
    today = now_local.date()

    # send once per day after 6:00 PM local time
    if now_local.hour < 18:
        return

    if last_daily_summary_date == today:
        return

    lines = []
    urgent = []

    for plant, entry in latest_snapshot.items():
        moisture = entry.get("moisture")
        temp_f = entry.get("temp_f")
        rec = entry.get("recommendation")

        if moisture is None:
            line = f"- {plant}: no data"
        else:
            line = f"- {plant}: {moisture:.1f}% | {temp_f:.1f}°F | {rec}"

        lines.append(line)

        if rec == "Water now":
            urgent.append(plant)

    header = f"📅 **Daily Plant Summary** ({now_local.strftime('%Y-%m-%d %I:%M %p')})"
    if urgent:
        header += f"\nUrgent: {', '.join(urgent)}"

    message = header + "\n" + "\n".join(lines)
    send_discord_message(message)
    last_daily_summary_date = today


def add_ideal_band(fig, plant):
    rules = PLANT_RULES[plant]
    fig.add_hrect(
        y0=rules["ideal_low"],
        y1=rules["ideal_high"],
        fillcolor="rgba(92,184,92,0.10)",
        line_width=0,
    )


def make_card(plant):
    return html.Div(
        id=f"card-{plant}",
        style={
            "border": "1px solid #ddd",
            "borderRadius": "12px",
            "padding": "16px",
            "margin": "8px",
            "width": "260px",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.08)",
            "backgroundColor": "white",
        },
    )

# -----------------------------
# Figure builders
# -----------------------------
def build_live_figures(session):
    moisture_fig = go.Figure()
    temp_fig = go.Figure()

    added_band = False

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=1, limit=300)

            if times:
                moisture_fig.add_trace(
                    go.Scatter(x=times, y=moisture_vals, mode="lines", name=plant)
                )
                temp_fig.add_trace(
                    go.Scatter(x=times, y=temp_vals, mode="lines", name=plant)
                )

                if not added_band:
                    add_ideal_band(moisture_fig, plant)
                    added_band = True

        except Exception as e:
            print(f"Failed live history for {plant}: {e}", flush=True)

    moisture_fig.update_layout(
        title="Live Moisture (%)",
        xaxis_title="Time",
        yaxis_title="Moisture (%)",
        template="plotly_white",
        height=450,
    )

    temp_fig.update_layout(
        title="Live Temperature (°F)",
        xaxis_title="Time",
        yaxis_title="Temperature (°F)",
        template="plotly_white",
        height=450,
    )

    return moisture_fig, temp_fig


def build_weekly_figures(session):
    weekly_moisture_fig = go.Figure()
    weekly_temp_fig = go.Figure()

    added_band = False

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=7, limit=1000)
            times_m, moisture_vals = downsample_data(times, moisture_vals, step=2)
            times_t, temp_vals = downsample_data(times, temp_vals, step=2)

            if times_m:
                weekly_moisture_fig.add_trace(
                    go.Scatter(x=times_m, y=moisture_vals, mode="lines", name=plant)
                )
                if not added_band:
                    add_ideal_band(weekly_moisture_fig, plant)
                    added_band = True

            if times_t:
                weekly_temp_fig.add_trace(
                    go.Scatter(x=times_t, y=temp_vals, mode="lines", name=plant)
                )

        except Exception as e:
            print(f"Failed weekly history for {plant}: {e}", flush=True)

    weekly_moisture_fig.update_layout(
        title="Weekly Moisture Trend (Last 7 Days)",
        xaxis_title="Time",
        yaxis_title="Moisture (%)",
        template="plotly_white",
        height=450,
    )

    weekly_temp_fig.update_layout(
        title="Weekly Temperature Trend (Last 7 Days)",
        xaxis_title="Time",
        yaxis_title="Temperature (°F)",
        template="plotly_white",
        height=450,
    )

    return weekly_moisture_fig, weekly_temp_fig


def build_monthly_figures(session):
    monthly_moisture_fig = go.Figure()
    monthly_temp_fig = go.Figure()

    added_band = False

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=30, limit=1000)
            times_m, moisture_vals = downsample_data(times, moisture_vals, step=10)
            times_t, temp_vals = downsample_data(times, temp_vals, step=10)

            if times_m:
                monthly_moisture_fig.add_trace(
                    go.Scatter(x=times_m, y=moisture_vals, mode="lines", name=plant)
                )
                if not added_band:
                    add_ideal_band(monthly_moisture_fig, plant)
                    added_band = True

            if times_t:
                monthly_temp_fig.add_trace(
                    go.Scatter(x=times_t, y=temp_vals, mode="lines", name=plant)
                )

        except Exception as e:
            print(f"Failed monthly history for {plant}: {e}", flush=True)

    monthly_moisture_fig.update_layout(
        title="Monthly Moisture Trend (Last 30 Days)",
        xaxis_title="Time",
        yaxis_title="Moisture (%)",
        template="plotly_white",
        height=450,
    )

    monthly_temp_fig.update_layout(
        title="Monthly Temperature Trend (Last 30 Days)",
        xaxis_title="Time",
        yaxis_title="Temperature (°F)",
        template="plotly_white",
        height=450,
    )

    return monthly_moisture_fig, monthly_temp_fig

# -----------------------------
# Dash app
# -----------------------------
app = Dash(__name__)
server = app.server
app.title = "Soil Monitor Dashboard"

plant_names = list(FEEDS.keys())

app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "padding": "20px", "backgroundColor": "#f7f7f7"},
    children=[
        html.H1("Plant Soil Monitor"),
        html.Div(id="system-status"),
        html.Div(id="alert-banner"),

        dcc.Interval(id="refresh", interval=30000, n_intervals=0),

        html.Div(
            [make_card(plant) for plant in plant_names],
            style={"display": "flex", "flexWrap": "wrap", "gap": "8px"},
        ),

        dcc.Tabs(
            id="view-tabs",
            value="live",
            children=[
                dcc.Tab(label="Live", value="live"),
                dcc.Tab(label="Weekly", value="weekly"),
                dcc.Tab(label="Monthly", value="monthly"),
            ],
        ),

        html.Div(id="tab-content"),
    ],
)


@app.callback(
    [Output(f"card-{plant}", "children") for plant in plant_names]
    + [Output("system-status", "children"), Output("alert-banner", "children")],
    Input("refresh", "n_intervals"),
)
def update_cards(n):
    session = make_session()
    cards = []
    dry_alerts = []
    successful_fetches = 0
    refresh_time = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %I:%M:%S %p")
    latest_snapshot = {}

    for plant, feed_key in FEEDS.items():
        try:
            feed_data = fetch_latest_feed_value(feed_key, session)
            payload_text = feed_data["value"]
            created_at = feed_data.get("created_at")

            payload = json.loads(payload_text)
            moisture = float(payload.get("moisture_pct"))
            temp_f = float(payload.get("temp_f"))
            raw = int(payload.get("raw"))

            ts = (
                datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if created_at
                else None
            )

            recommendation, rec_color, bg_color = get_watering_recommendation(plant, moisture)

            latest_snapshot[plant] = {
                "moisture": moisture,
                "temp_f": temp_f,
                "recommendation": recommendation,
            }

            if should_log_to_sheets(plant, moisture):
                log_to_google_sheets(ts or datetime.now(timezone.utc), plant, moisture, temp_f, raw)

            maybe_send_urgent_alert(plant, moisture, recommendation)

            if recommendation == "Water now":
                dry_alerts.append(plant)

            successful_fetches += 1

            cards.append([
                html.Div(
                    [
                        html.H3(plant, style={"marginTop": "0"}),
                        html.P(f"Moisture: {moisture:.1f} %"),
                        html.P(f"Temperature: {temp_f:.2f} °F"),
                        html.P(f"Raw: {raw}"),
                        html.P(
                            f"Recommendation: {recommendation}",
                            style={"fontWeight": "bold", "color": rec_color}
                        ),
                        html.P(
                            f"Last update: {ts.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %I:%M:%S %p')}" if ts else "Last update: --",
                            style={"color": "#666", "fontSize": "0.9rem"},
                        ),
                    ],
                    style={
                        "backgroundColor": bg_color,
                        "border": f"2px solid {rec_color}",
                        "borderRadius": "12px",
                        "padding": "14px",
                        "minHeight": "210px",
                    },
                )
            ])

        except Exception as e:
            print(f"Failed latest card fetch for {plant}: {e}", flush=True)
            latest_snapshot[plant] = {
                "moisture": None,
                "temp_f": None,
                "recommendation": "No data",
            }

            cards.append([
                html.Div(
                    [
                        html.H3(plant, style={"marginTop": "0"}),
                        html.P("Moisture: --"),
                        html.P("Temperature: --"),
                        html.P("Raw: --"),
                        html.P(
                            "Recommendation: No data",
                            style={"fontWeight": "bold", "color": "#666666"}
                        ),
                        html.P(
                            "Last update: --",
                            style={"color": "#666", "fontSize": "0.9rem"},
                        ),
                    ],
                    style={
                        "backgroundColor": "#f5f5f5",
                        "border": "2px solid #cccccc",
                        "borderRadius": "12px",
                        "padding": "14px",
                        "minHeight": "210px",
                    },
                )
            ])

    maybe_send_daily_summary(latest_snapshot)

    status = html.Div(
        [
            html.P(
                f"Last dashboard refresh: {refresh_time} | Plants fetched: {successful_fetches}/{len(FEEDS)}",
                style={
                    "marginBottom": "12px",
                    "padding": "10px 14px",
                    "backgroundColor": "#ffffff",
                    "border": "1px solid #ddd",
                    "borderRadius": "10px",
                    "display": "inline-block",
                },
            )
        ]
    )

    if dry_alerts:
        alert_banner = html.Div(
            f"Water alert: {', '.join(dry_alerts)}",
            style={
                "backgroundColor": "#ffeaea",
                "color": "#a94442",
                "border": "1px solid #ebccd1",
                "padding": "12px 16px",
                "borderRadius": "10px",
                "marginBottom": "16px",
                "fontWeight": "bold",
            },
        )
    else:
        alert_banner = html.Div(
            "No urgent watering alerts.",
            style={
                "backgroundColor": "#eef9ee",
                "color": "#2f6b2f",
                "border": "1px solid #cfe9cf",
                "padding": "12px 16px",
                "borderRadius": "10px",
                "marginBottom": "16px",
                "fontWeight": "bold",
            },
        )

    return cards + [status, alert_banner]


@app.callback(
    Output("tab-content", "children"),
    [Input("view-tabs", "value"), Input("refresh", "n_intervals")],
)
def render_tab(tab, n):
    session = make_session()

    if tab == "live":
        moisture_fig, temp_fig = build_live_figures(session)
        return html.Div([dcc.Graph(figure=moisture_fig), dcc.Graph(figure=temp_fig)])

    if tab == "weekly":
        weekly_moisture_fig, weekly_temp_fig = build_weekly_figures(session)
        return html.Div([dcc.Graph(figure=weekly_moisture_fig), dcc.Graph(figure=weekly_temp_fig)])

    monthly_moisture_fig, monthly_temp_fig = build_monthly_figures(session)
    return html.Div([dcc.Graph(figure=monthly_moisture_fig), dcc.Graph(figure=monthly_temp_fig)])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
