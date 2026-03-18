import threading
import json
from collections import defaultdict, deque
from datetime import datetime, timezone

import pandas as pd
import paho.mqtt.client as mqtt
from dash import Dash, html, dcc, Input, Output
import plotly.graph_objects as go

import os

# -----------------------------
# Adafruit IO / MQTT settings
# -----------------------------
AIO_USERNAME = os.getenv("AIO_USERNAME")
AIO_KEY = os.getenv("AIO_KEY")
if not AIO_USERNAME or not AIO_KEY:
    raise ValueError("Missing AIO_USERNAME or AIO_KEY environment variables")
BROKER = "io.adafruit.com"
PORT = 1883

TOPIC_TO_PLANT = {
    f"{AIO_USERNAME}/feeds/amy-dieffenbachia": "Amy Dieffenbachia",
    f"{AIO_USERNAME}/feeds/peace-lily": "Peace Lily",
    f"{AIO_USERNAME}/feeds/periwinkle": "Periwinkle",
    f"{AIO_USERNAME}/feeds/rex-begonia": "Rex Begonia",
}

# Keep recent points in memory for the live dashboard
MAX_POINTS = 500

plant_history = defaultdict(lambda: {
    "time": deque(maxlen=MAX_POINTS),
    "moisture_pct": deque(maxlen=MAX_POINTS),
    "temp_f": deque(maxlen=MAX_POINTS),
    "raw": deque(maxlen=MAX_POINTS),
})

latest_data = {
    plant: {"moisture_pct": None, "temp_f": None, "raw": None, "timestamp": None}
    for plant in TOPIC_TO_PLANT.values()
}

data_lock = threading.Lock()


# -----------------------------
# MQTT callbacks
# -----------------------------
def on_connect(client, userdata, flags, reason_code, properties=None):
    print("Connected with code:", reason_code)
    for topic in TOPIC_TO_PLANT:
        client.subscribe(topic)
        print("Subscribed to:", topic)


def on_message(client, userdata, msg):
    topic = msg.topic
    plant = TOPIC_TO_PLANT.get(topic)
    if plant is None:
        return

    payload_text = msg.payload.decode("utf-8")

    try:
        data = json.loads(payload_text)
        moisture = float(data.get("moisture_pct"))
        temp_f = float(data.get("temp_f"))
        raw = int(data.get("raw"))
    except Exception as e:
        print("Bad payload:", payload_text, "| Error:", e)
        return

    timestamp = datetime.now(timezone.utc)

    with data_lock:
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

    print(f"{timestamp.isoformat()} | {plant} | {moisture:.1f}% | {temp_f:.2f} F | raw={raw}")


def mqtt_thread():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(AIO_USERNAME, AIO_KEY)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.loop_forever()


# -----------------------------
# Dash app
# -----------------------------
app = Dash(__name__)
app.title = "Soil Monitor Dashboard"

plant_names = list(TOPIC_TO_PLANT.values())

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
        dcc.Interval(id="refresh", interval=3000, n_intervals=0),

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
    with data_lock:
        latest_copy = {k: v.copy() for k, v in latest_data.items()}
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
        hist = history_copy.get(plant)
        if not hist or len(hist["time"]) == 0:
            continue

        moisture_fig.add_trace(
            go.Scatter(
                x=hist["time"],
                y=hist["moisture_pct"],
                mode="lines+markers",
                name=plant,
            )
        )

        temp_fig.add_trace(
            go.Scatter(
                x=hist["time"],
                y=hist["temp_f"],
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


# Start MQTT thread immediately (IMPORTANT for Render)
threading.Thread(target=mqtt_thread, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050)
