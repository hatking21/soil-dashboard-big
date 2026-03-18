import os
import json
from collections import defaultdict, deque
from datetime import datetime

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
            ]
        ),
    ],
)


@app.callback(
    [Output(f"card-{plant}", "children") for plant in plant_names]
    + [Output("moisture-graph", "figure"), Output("temperature-graph", "figure")],
    Input("refresh", "n_intervals"),
)
def update_dashboard(n):
    for plant, feed_key in FEEDS.items():
        try:
            feed_data = fetch_latest_feed_value(feed_key)
            payload_text = feed_data["value"]
            created_at = feed_data.get("created_at")

            payload = json.loads(payload_text)
            moisture = float(payload.get("moisture_pct"))
            temp_f = float(payload.get("temp_f"))
            raw = int(payload.get("raw"))

            timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else datetime.utcnow()

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

        except Exception as e:
            print(f"Failed to fetch {plant}: {e}")

    cards = []
    for plant in plant_names:
        entry = latest_data.get(plant, {})
        moisture = entry.get("moisture_pct")
        temp_f = entry.get("temp_f")
        raw = entry.get("raw")
        ts = entry.get("timestamp")

        cards.append([
            html.H3(plant, style={"marginTop": "0"}),
            html.P(f"Moisture: {moisture:.1f} %" if moisture is not None else "Moisture: --"),
            html.P(f"Temperature: {temp_f:.2f} °F" if temp_f is not None else "Temperature: --"),
            html.P(f"Raw: {raw}" if raw is not None else "Raw: --"),
            html.P(
                f"Last update: {ts.astimezone().strftime('%Y-%m-%d %I:%M:%S %p')}" if ts else "Last update: --",
                style={"color": "#666", "fontSize": "0.9rem"},
            ),
        ])

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

    return cards + [moisture_fig, temp_fig]


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
