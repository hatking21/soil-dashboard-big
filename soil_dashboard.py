import os
import json
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
# You can replace this later with:
# SHEETS_WEBHOOK_URL = os.getenv("SHEETS_WEBHOOK_URL")
SHEETS_WEBHOOK_URL = os.getenv("SHEETS_WEBHOOK_URL")

if not SHEETS_WEBHOOK_URL:
    print("Warning: SHEETS_WEBHOOK_URL not set — Google Sheets backup disabled")
    
# Prevent duplicate sheet writes for the same reading
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


def fetch_latest_feed_value(feed_key):
    url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data/last"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_feed_history(feed_key, limit=1000):
    url = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/feeds/{feed_key}/data"
    resp = requests.get(url, headers=HEADERS, params={"limit": limit}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_history_for_days(feed_key, days, limit=1000):
    entries = fetch_feed_history(feed_key, limit=limit)
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
        print(f"Sheets log status for {plant}: {resp.status_code}")
        print(f"Sheets response: {resp.text}")
    except Exception as e:
        print(f"Failed to log to Google Sheets for {plant}: {e}")


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
        dcc.Interval(id="refresh", interval=10000, n_intervals=0),

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
        Output("weekly-moisture-graph", "figure"),
        Output("weekly-temperature-graph", "figure"),
        Output("monthly-moisture-graph", "figure"),
        Output("monthly-temperature-graph", "figure"),
    ],
    Input("refresh", "n_intervals"),
)
def update_dashboard(n):
    # -----------------------------
    # Fetch latest values for cards + live graphs
    # -----------------------------
    for plant, feed_key in FEEDS.items():
        try:
            feed_data = fetch_latest_feed_value(feed_key)
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

                # Backup to Google Sheets once per new reading
                if logged_timestamps[plant] != timestamp:
                    log_to_google_sheets(timestamp, plant, moisture, temp_f, raw)
                    logged_timestamps[plant] = timestamp

        except Exception as e:
            print(f"Failed to fetch latest value for {plant}: {e}")

    # -----------------------------
    # Build cards
    # -----------------------------
    cards = []
    for plant in plant_names:
        entry = latest_data.get(plant, {})
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

    # -----------------------------
    # Live graphs
    # -----------------------------
    moisture_fig = go.Figure()
    temp_fig = go.Figure()

    for plant in plant_names:
        hist = plant_history.get(plant)
        if not hist or len(hist["time"]) == 0:
            continue

        moisture_fig.add_trace(
            go.Scatter(
                x=list(hist["time"]),
                y=list(hist["moisture_pct"]),
                mode="lines+markers",
                name=plant,
            )
        )

        temp_fig.add_trace(
            go.Scatter(
                x=list(hist["time"]),
                y=list(hist["temp_f"]),
                mode="lines+markers",
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

    # -----------------------------
    # Weekly graphs
    # -----------------------------
    weekly_moisture_fig = go.Figure()
    weekly_temp_fig = go.Figure()

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, days=7, limit=1000)

            if times:
                weekly_moisture_fig.add_trace(
                    go.Scatter(
                        x=times,
                        y=moisture_vals,
                        mode="lines+markers",
                        name=plant,
                    )
                )

                weekly_temp_fig.add_trace(
                    go.Scatter(
                        x=times,
                        y=temp_vals,
                        mode="lines+markers",
                        name=plant,
                    )
                )

        except Exception as e:
            print(f"Failed weekly history for {plant}: {e}")

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

    # -----------------------------
    # Monthly graphs
    # -----------------------------
    monthly_moisture_fig = go.Figure()
    monthly_temp_fig = go.Figure()

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, days=30, limit=1000)

            if times:
                monthly_moisture_fig.add_trace(
                    go.Scatter(
                        x=times,
                        y=moisture_vals,
                        mode="lines+markers",
                        name=plant,
                    )
                )

                monthly_temp_fig.add_trace(
                    go.Scatter(
                        x=times,
                        y=temp_vals,
                        mode="lines+markers",
                        name=plant,
                    )
                )

        except Exception as e:
            print(f"Failed monthly history for {plant}: {e}")

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

    return cards + [
        moisture_fig,
        temp_fig,
        weekly_moisture_fig,
        weekly_temp_fig,
        monthly_moisture_fig,
        monthly_temp_fig,
    ]


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
