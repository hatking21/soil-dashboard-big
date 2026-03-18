import os
import json
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


def build_live_figures(session):
    moisture_fig = go.Figure()
    temp_fig = go.Figure()

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=1, limit=300)

            if times:
                moisture_fig.add_trace(
                    go.Scatter(
                        x=times,
                        y=moisture_vals,
                        mode="lines",
                        name=plant,
                    )
                )

                temp_fig.add_trace(
                    go.Scatter(
                        x=times,
                        y=temp_vals,
                        mode="lines",
                        name=plant,
                    )
                )
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

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=7, limit=1000)

            times_m, moisture_vals = downsample_data(times, moisture_vals, step=2)
            times_t, temp_vals = downsample_data(times, temp_vals, step=2)

            if times_m:
                weekly_moisture_fig.add_trace(
                    go.Scatter(
                        x=times_m,
                        y=moisture_vals,
                        mode="lines",
                        name=plant,
                    )
                )

            if times_t:
                weekly_temp_fig.add_trace(
                    go.Scatter(
                        x=times_t,
                        y=temp_vals,
                        mode="lines",
                        name=plant,
                    )
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

    for plant, feed_key in FEEDS.items():
        try:
            times, moisture_vals, temp_vals = get_history_for_days(feed_key, session, days=30, limit=1000)

            times_m, moisture_vals = downsample_data(times, moisture_vals, step=10)
            times_t, temp_vals = downsample_data(times, temp_vals, step=10)

            if times_m:
                monthly_moisture_fig.add_trace(
                    go.Scatter(
                        x=times_m,
                        y=moisture_vals,
                        mode="lines",
                        name=plant,
                    )
                )

            if times_t:
                monthly_temp_fig.add_trace(
                    go.Scatter(
                        x=times_t,
                        y=temp_vals,
                        mode="lines",
                        name=plant,
                    )
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
        html.P("Live readings from Adafruit IO"),

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
    [Output(f"card-{plant}", "children") for plant in plant_names],
    Input("refresh", "n_intervals"),
)
def update_cards(n):
    session = make_session()
    cards = []

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

            recommendation, rec_color = get_watering_recommendation(plant, moisture)

            cards.append([
                html.H3(plant, style={"marginTop": "0"}),
                html.P(f"Moisture: {moisture:.1f} %"),
                html.P(f"Temperature: {temp_f:.2f} °F"),
                html.P(f"Raw: {raw}"),
                html.P(
                    f"Recommendation: {recommendation}",
                    style={"fontWeight": "bold", "color": rec_color}
                ),
                html.P(
                    f"Last update: {ts.astimezone().strftime('%Y-%m-%d %I:%M:%S %p')}" if ts else "Last update: --",
                    style={"color": "#666", "fontSize": "0.9rem"},
                ),
            ])

        except Exception as e:
            print(f"Failed latest card fetch for {plant}: {e}", flush=True)
            cards.append([
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
            ])

    return cards


@app.callback(
    Output("tab-content", "children"),
    [
        Input("view-tabs", "value"),
        Input("refresh", "n_intervals"),
    ],
)
def render_tab(tab, n):
    session = make_session()

    if tab == "live":
        moisture_fig, temp_fig = build_live_figures(session)
        return html.Div([
            dcc.Graph(figure=moisture_fig),
            dcc.Graph(figure=temp_fig),
        ])

    if tab == "weekly":
        weekly_moisture_fig, weekly_temp_fig = build_weekly_figures(session)
        return html.Div([
            dcc.Graph(figure=weekly_moisture_fig),
            dcc.Graph(figure=weekly_temp_fig),
        ])

    monthly_moisture_fig, monthly_temp_fig = build_monthly_figures(session)
    return html.Div([
        dcc.Graph(figure=monthly_moisture_fig),
        dcc.Graph(figure=monthly_temp_fig),
    ])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
