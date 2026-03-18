import os
import json
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import requests
from dash import Dash, html, dcc, Input, Output
import plotly.graph_objects as go

# -----------------------------
# Adafruit IO settings
# -----------------------------
AIO_USERNAME = os.getenv("AIO_USERNAME")
AIO_KEY = os.getenv("AIO_KEY")

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

# -----------------------------
# Google Sheets backup
# -----------------------------
SHEETS_WEBHOOK_URL = os.getenv("SHEETS_WEBHOOK_URL")

if not SHEETS_WEBHOOK_URL:
    print("Warning: SHEETS_WEBHOOK_URL not set — Google Sheets backup disabled", flush=True)

logged_timestamps = {plant: None for plant in FEEDS}

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
# In-memory data stores
# -----------------------------
MAX_POINTS = 500

plant_history = defaultdict(lambda: {
    "time": deque(maxlen=MAX_POINTS),
    "moisture_pct": deque(maxlen=MAX_POINTS),
    "temp_f": deque(maxlen=MAX_POINTS),
    "raw": deque(maxlen=MAX_POINTS),
})

latest_data = {
    plant: {"moisture_pct": None, "temp_f": None, "raw": None, "timestamp": None}
    for plant in FEEDS
}

weekly_cache = {
    plant: {"time_moisture": [], "moisture": [], "time_temp": [], "temp": []}
    for plant in FEEDS
}

monthly_cache = {
    plant: {"time_moisture": [], "moisture": [], "time_temp": [], "temp": []}
    for plant in FEEDS
}

data_lock = threading.Lock()
threads_started = False


def make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s

# -----------------------------
# Adafruit IO fetch helpers
# -----------------------------
def fetch_latest_feed_value(feed_key, session):
    url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data/last"
    resp = session.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_feed_history(feed_key, session, limit=1000):
    url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data"
    resp = session.get(url, params={"limit": limit}, timeout=20)
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
        resp = requests.post(SHEETS_WEBHOOK_URL, json=payload, timeout=15)
        print(f"Sheets log status for {plant}: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"Failed to log to Google Sheets for {plant}: {e}", flush=True)


def get_watering_recommendation(plant, moisture):
    if moisture is None:
        return "No data", "#666666"

    rules = PLANT_RULES[plant]

    if moisture < rules["dry"]:
        return "Water now", "#d9534f"
    elif moisture < rules["ideal_low"]:
        return "Check soon", "#f0ad4e"
    elif moisture <= rules["ideal_high"]:
        return "Moisture looks good", "#5cb85c"
    else:
        return "Wet / hold off", "#5bc0de"

# -----------------------------
# Background refresh workers
# -----------------------------
def refresh_latest_data():
    print("Starting latest-data thread", flush=True)
    session = make_session()

    while True:
        for plant, feed_key in FEEDS.items():
            try:
                feed_data = fetch_latest_feed_value(feed_key, session)
                payload_text = feed_data["value"]
                created_at = feed_data.get("created_at")

                payload = json.loads(payload_text)
                moisture = float(payload.get("moisture_pct"))
                temp_f = float(payload.get("temp_f"))
                raw = int(payload.get("raw"))

                timestamp = (
                    datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if created_at
                    else datetime.now(timezone.utc)
                )

                should_log = False

                with data_lock:
                    previous_ts = latest_data[plant]["timestamp"]
                    if previous_ts != timestamp:
                        latest_data[plant] = {
                            "moisture_pct": moisture,
                            "temp_f": temp_f,
                            "raw": raw,
                            "timestamp": timestamp,
                        }

                        plant_history[plant]["time"].append(timestamp)
                        plant_history[plant]["moisture_pct"].append(moisture)
                        plant_history[plant]["temp_f"].append(temp_f)
                        plant_history[plant]["raw"].append(raw)

                        if logged_timestamps[plant] != timestamp:
                            logged_timestamps[plant] = timestamp
                            should_log = True

                if should_log:
                    print(f"New live reading for {plant}: {moisture:.1f}% {temp_f:.2f}F", flush=True)
                    log_to_google_sheets(timestamp, plant, moisture, temp_f, raw)

            except Exception as e:
                print(f"Failed latest refresh for {plant}: {e}", flush=True)

        time.sleep(10)


def refresh_history_data():
    print("Starting history-data thread", flush=True)
    session = make_session()

    while True:
        for plant, feed_key in FEEDS.items():
            try:
                times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=7, limit=1000)
                ds_times_week_m, ds_moisture_week = downsample_data(times, moisture_vals, step=2)
                ds_times_week_t, ds_temp_week = downsample_data(times, temp_vals, step=2)

                with data_lock:
                    weekly_cache[plant] = {
                        "time_moisture": ds_times_week_m,
                        "moisture": ds_moisture_week,
                        "time_temp": ds_times_week_t,
                        "temp": ds_temp_week,
                    }
            except Exception as e:
                print(f"Failed weekly refresh for {plant}: {e}", flush=True)

            try:
                times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=30, limit=1000)
                ds_times_month_m, ds_moisture_month = downsample_data(times, moisture_vals, step=10)
                ds_times_month_t, ds_temp_month = downsample_data(times, temp_vals, step=10)

                with data_lock:
                    monthly_cache[plant] = {
                        "time_moisture": ds_times_month_m,
                        "moisture": ds_moisture_month,
                        "time_temp": ds_times_month_t,
                        "temp": ds_temp_month,
                    }
            except Exception as e:
                print(f"Failed monthly refresh for {plant}: {e}", flush=True)

        print("History cache refreshed", flush=True)
        time.sleep(600)


def start_background_threads():
    global threads_started
    if threads_started:
        return

    threads_started = True
    threading.Thread(target=refresh_latest_data, daemon=True).start()
    threading.Thread(target=refresh_history_data, daemon=True).start()

# -----------------------------
# Dash app
# -----------------------------
app = Dash(__name__)
server = app.server
app.title = "Soil Monitor Dashboard"

plant_names = list(FEEDS.keys())


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


app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "padding": "20px", "backgroundColor": "#f7f7f7"},
    children=[
        html.H1("Plant Soil Monitor"),
        html.P("Live readings from Adafruit IO"),

        dcc.Interval(id="live-refresh", interval=10000, n_intervals=0),
        dcc.Interval(id="history-refresh", interval=300000, n_intervals=0),

        html.Div(
            [make_card(plant) for plant in plant_names],
            style={"display": "flex", "flexWrap": "wrap", "gap": "8px"},
        ),

        html.Div(
            [
                dcc.Graph(id="moisture-graph"),
                dcc.Graph(id="temperature-graph"),
                dcc.Graph(id="weekly-moisture-graph"),
                dcc.Graph(id="weekly-temperature-graph"),
                dcc.Graph(id="monthly-moisture-graph"),
                dcc.Graph(id="monthly-temperature-graph"),
            ]
        ),
    ],
)


@app.callback(
    [Output(f"card-{plant}", "children") for plant in plant_names]
    + [
        Output("moisture-graph", "figure"),
        Output("temperature-graph", "figure"),
    ],
    Input("live-refresh", "n_intervals"),
)
def update_live_dashboard(n):
    with data_lock:
        latest_copy = {plant: data.copy() for plant, data in latest_data.items()}
        history_copy = {
            plant: {
                "time": list(vals["time"]),
                "moisture_pct": list(vals["moisture_pct"]),
                "temp_f": list(vals["temp_f"]),
                "raw": list(vals["raw"]),
            }
            for plant, vals in plant_history.items()
        }

    cards = []
    for plant in plant_names:
        entry = latest_copy.get(plant, {})
        moisture = entry.get("moisture_pct")
        temp_f = entry.get("temp_f")
        raw = entry.get("raw")
        ts = entry.get("timestamp")

        recommendation, rec_color = get_watering_recommendation(plant, moisture)

        cards.append([
            html.H3(plant, style={"marginTop": "0"}),
            html.P(f"Moisture: {moisture:.1f} %" if moisture is not None else "Moisture: --"),
            html.P(f"Temperature: {temp_f:.2f} °F" if temp_f is not None else "Temperature: --"),
            html.P(f"Raw: {raw}" if raw is not None else "Raw: --"),
            html.P(
                f"Recommendation: {recommendation}",
                style={"fontWeight": "bold", "color": rec_color}
            ),
            html.P(
                f"Last update: {ts.astimezone().strftime('%Y-%m-%d %I:%M:%S %p')}" if ts else "Last update: --",
                style={"color": "#666", "fontSize": "0.9rem"},
            ),
        ])

    moisture_fig = go.Figure()
    temp_fig = go.Figure()

    for plant in plant_names:
        hist = history_copy.get(plant)
        if not hist or len(hist["time"]) == 0:
            continue

        moisture_fig.add_trace(
            go.Scatter(
                x=hist["time"],
                y=hist["moisture_pct"],
                mode="lines",
                name=plant,
            )
        )

        temp_fig.add_trace(
            go.Scatter(
                x=hist["time"],
                y=hist["temp_f"],
                mode="lines",
                name=plant,
            )
        )

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

    return cards + [moisture_fig, temp_fig]


@app.callback(
    [
        Output("weekly-moisture-graph", "figure"),
        Output("weekly-temperature-graph", "figure"),
        Output("monthly-moisture-graph", "figure"),
        Output("monthly-temperature-graph", "figure"),
    ],
    Input("history-refresh", "n_intervals"),
)
def update_history_graphs(n):
    with data_lock:
        weekly_copy = {plant: vals.copy() for plant, vals in weekly_cache.items()}
        monthly_copy = {plant: vals.copy() for plant, vals in monthly_cache.items()}

    weekly_moisture_fig = go.Figure()
    weekly_temp_fig = go.Figure()
    monthly_moisture_fig = go.Figure()
    monthly_temp_fig = go.Figure()

    for plant in plant_names:
        w = weekly_copy[plant]
        m = monthly_copy[plant]

        if w.get("time_moisture"):
            weekly_moisture_fig.add_trace(
                go.Scatter(
                    x=w["time_moisture"],
                    y=w["moisture"],
                    mode="lines",
                    name=plant,
                )
            )

        if w.get("time_temp"):
            weekly_temp_fig.add_trace(
                go.Scatter(
                    x=w["time_temp"],
                    y=w["temp"],
                    mode="lines",
                    name=plant,
                )
            )

        if m.get("time_moisture"):
            monthly_moisture_fig.add_trace(
                go.Scatter(
                    x=m["time_moisture"],
                    y=m["moisture"],
                    mode="lines",
                    name=plant,
                )
            )

        if m.get("time_temp"):
            monthly_temp_fig.add_trace(
                go.Scatter(
                    x=m["time_temp"],
                    y=m["temp"],
                    mode="lines",
                    name=plant,
                )
            )

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

    return [
        weekly_moisture_fig,
        weekly_temp_fig,
        monthly_moisture_fig,
        monthly_temp_fig,
    ]


# Start background refresh workers once
start_background_threads()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
