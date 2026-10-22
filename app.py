from datetime import datetime, timezone

from dash import Dash, Input, Output, State, ALL, dcc, html, no_update, ctx
from dash.exceptions import PreventUpdate
from flask import send_file

from charts import build_figures
from config import (
    CARD_REFRESH_MS,
    CSV_LOG_PATH,
    DEFAULT_PLANT_RULES,
    FEEDS,
    HISTORY_FAST_REFRESH_MS,
    LOCAL_TZ,
    SENSOR_OFFLINE_MINUTES,
    TEMP_F_MAX,
)
from data_layer import (
    ensure_csv_exists,
    ensure_watering_log_exists,
    fetch_history,
    format_last_watered,
    get_csv_last_write_time,
    get_csv_row_count,
    health_state,
    is_sensor_offline,
    load_last_watered_from_csv,
    run_startup_checks,
    compute_trend_arrow,
    estimate_hours_until_dry,
    last_csv_status,
)
from notifications import (
    send_ntfy_alert,
)
from styles import theme_styles
import ui as ui_module
import monitor
import notifications
import calibration

# Weekly refresh every hour, monthly refresh every day
WEEKLY_REFRESH_MS = 60 * 60 * 1000
MONTHLY_REFRESH_MS = 24 * 60 * 60 * 1000

app = Dash(__name__, suppress_callback_exceptions=True, assets_folder="Assets",
           meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}])
server = app.server
app.title = "Soil Monitor Dashboard"

plant_names = list(FEEDS.keys())


@server.route("/download-csv")
def download_csv():
    ensure_csv_exists()
    return send_file(
        path_or_file=CSV_LOG_PATH,
        mimetype="text/csv",
        as_attachment=True,
        download_name="plant_readings.csv",
    )


run_startup_checks()


def fallback_make_card_shell(plant, dark=True):
    styles = theme_styles(dark)
    return html.Div(
        id=f"card-{plant}",
        children=html.Div([html.Div("Connecting to your plants", className="skeleton-title"),
                           html.Div("Readings will appear here automatically.", className="muted")], className="plant-card loading-card"),
        style={
            **styles.get("card_shell", {}),
            "width": "100%",
            "minWidth": "0",
            "boxSizing": "border-box",
        },
    )


def fallback_build_moisture_bar(moisture, color, dark=True):
    styles = theme_styles(dark)
    value = 0 if moisture is None else max(0, min(100, float(moisture)))
    return html.Div(
        [html.Div(style={
            "height": "10px",
            "width": f"{value}%",
            "backgroundColor": color,
            "borderRadius": "999px",
            "transition": "width 0.25s ease",
        })],
        style={
            "height": "10px",
            "width": "100%",
            "backgroundColor": styles.get("bar_track", "#24354d"),
            "borderRadius": "999px",
            "overflow": "hidden",
            "marginBottom": "12px",
        },
    )


def fallback_moisture_colors(moisture, rule, dark=True, offline=False):
    if offline or moisture is None:
        return ("Offline", "#94a3b8", "#1f2937") if dark else ("Offline", "#64748b", "#f1f5f9")

    dry = rule["dry"]
    low = rule["ideal_low"]
    high = rule["ideal_high"]

    if moisture <= dry:
        return ("Water now", "#ef4444", "#3a1318") if dark else ("Water now", "#dc2626", "#fee2e2")
    if moisture < low:
        return ("Check soon", "#f59e0b", "#3a2814") if dark else ("Check soon", "#d97706", "#fef3c7")
    if moisture <= high:
        return ("Healthy", "#22c55e", "#113222") if dark else ("Healthy", "#16a34a", "#dcfce7")
    return ("Wet", "#38bdf8", "#0f2533") if dark else ("Wet", "#0284c7", "#e0f2fe")


def fallback_recommendation_pill(rec, moisture, rule, dark=True, offline=False):
    _, color, bg = fallback_moisture_colors(moisture, rule, dark=dark, offline=offline)
    return html.Div(
        rec,
        style={
            "padding": "6px 10px",
            "borderRadius": "999px",
            "fontSize": "0.85rem",
            "fontWeight": "700",
            "border": f"1px solid {color}",
            "backgroundColor": bg,
            "color": color,
            "whiteSpace": "nowrap",
        },
    )


def fallback_build_health_panel(health_state_data, used_fallback, dark=True, show_details=False):
    styles = theme_styles(dark)

    def chip(label, ok):
        return html.Div(
            f"{label}: {'OK' if ok else 'Issue'}",
            style={
                "padding": "8px 10px",
                "borderRadius": "999px",
                "fontSize": "0.9rem",
                "fontWeight": "600",
                "backgroundColor": "#113222" if ok else "#3a1318",
                "color": "#7ff0b2" if ok else "#ff9a9a",
                "border": f"1px solid {'#2e8b57' if ok else '#a94442'}",
            },
        )

    children = [
        html.Div("System health", style={"fontWeight": "700", "marginBottom": "10px"}),
        html.Div(
            [
                chip("Adafruit IO", bool(health_state_data.get("adafruit_ok"))),
                chip("CSV logging", bool(health_state_data.get("csv_ok"))),
                chip("Watering log", bool(health_state_data.get("watering_log_ok"))),
                chip("Cache fallback", not used_fallback),
            ],
            style={"display": "flex", "gap": "10px", "flexWrap": "wrap"},
        ),
    ]

    if show_details:
        children.append(html.Div(
            f"Last successful fetch: {health_state_data.get('last_successful_fetch', 'Never')}",
            style={"marginTop": "10px", "color": styles.get("subtext", "#9ca3af")},
        ))
        if health_state_data.get("last_error"):
            children.append(html.Div(
                f"Last error: {health_state_data.get('last_error')}",
                style={"marginTop": "6px", "color": "#ff9a9a"},
            ))

    return html.Div(children, style={**styles["section"], "marginBottom": "16px"})


def learning_status(plant):
    points = calibration.references(plant)
    lines = []
    for kind, label in (("ready", "Ready to water"), ("watered", "Watered and drained")):
        point = points.get(kind)
        if point:
            raw = f" · raw {point['raw']:.0f}" if point.get("raw") is not None else ""
            lines.append(html.Div(f"{label}: {point['moisture']:.1f}%{raw} · 3-reading median"))
        else:
            lines.append(html.Div(f"{label}: not marked yet"))
    if len(points) == 2:
        try:
            rule = calibration.suggested_rules(plant)
            lines.append(html.P(f"Suggested starting points: water ≤ {rule['dry']}%, check below {rule['ideal_low']}%, upper reference {rule['ideal_high']}%. Apply when ready."))
        except ValueError as exc:
            lines.append(html.P(str(exc)))
    return html.Div(lines)


def build_learning_panel():
    styles = theme_styles(True)
    rows = []
    for plant in plant_names:
        rows.append(html.Div([
            html.H3(f"{FEEDS[plant]['emoji']} {plant}"),
            html.Div(learning_status(plant), id={"type": "learning-status", "plant": plant}, role="status", className="muted"),
            html.Div([html.Button(label, id={"type": "learning-action", "plant": plant, "action": action},
                                  n_clicks=0, style=styles["button"]) for action, label in
                      (("ready", "Mark ready to water"), ("watered", "Mark watered & drained"),
                       ("apply", "Apply suggested thresholds"), ("reset", "Clear reference points"))],
                     style={"display": "flex", "flexWrap": "wrap", "gap": "8px", "marginTop": "12px"}),
        ], className="rule-row"))
    return html.Div([
        html.H2("Teach this pot"),
        html.P("Two marks during normal care; no manual number tuning. Keep each sensor at the same depth and position. Do not let a plant wilt or dry completely for this setup.", className="muted"),
        html.Ol([
            html.Li("When you would normally water, check the soil or pot weight and mark Ready to water before watering."),
            html.Li("Water normally, let excess water drain, then wait for three steady sensor updates and mark Watered & drained."),
            html.Li("Review and apply the suggested thresholds for that pot. The lower ideal limit uses a 25% buffer between your two marks; adjust later if needed."),
        ], className="muted"),
        html.P("Uses the median of three different feed readings from the last 30 minutes (about 10–15 minutes at the default update rate). A single repeated or stale reading cannot be used. References are saved on the server; re-teach after repotting, moving a probe, or changing ESP32 calibration.", className="muted"),
        html.P("These are relative sensor percentages, not the soil's actual water content. This workflow learns watering decisions; it does not recalibrate the ESP32. If the two points are too close, the dashboard will ask you to check the sensor instead of inventing thresholds.", className="muted"),
        *rows,
    ])


def fallback_build_settings_panel(rules_dict, dark=True, health_state_data=None, used_fallback=False):
    styles = theme_styles(dark)
    rows = []
    for plant in plant_names:
        rule = rules_dict.get(plant, DEFAULT_PLANT_RULES[plant])
        fields = []
        for kind, key, label in (("dry-input", "dry", "Water at or below (%)"),
                                 ("ideal-low-input", "ideal_low", "Ideal minimum (%)"),
                                 ("ideal-high-input", "ideal_high", "Ideal maximum (%)")):
            fields.append(html.Label([html.Span(label), dcc.Input(
                id={"type": kind, "plant": plant}, type="number", value=rule[key],
                min=0, max=100, step=1, className="rule-input")], className="rule-field"))
        rows.append(html.Div([html.H3(f"{FEEDS[plant]['emoji']} {plant}"),
                              html.Div(fields, className="rule-fields")], className="rule-row"))
    return html.Div([
        html.Details([html.Summary("Teach this pot · guided setup"), build_learning_panel()], className="care-disclosure"),
        html.H2("Manual care preferences"),
        html.P("Set moisture thresholds for each plant. Values are percentages from your sensor calibration.", className="muted"),
        *rows,
        html.Button("Save care preferences", id="save-rules-button", n_clicks=0, style=styles["button_primary"]),
        html.Div(id="save-rules-status", role="status", className="save-status"),
        html.H2("Notifications & data"),
        html.P("All notifications are paused." if notifications.NOTIFICATIONS_PAUSED else "Notifications are active.", className="muted"),
        html.Button("Send test notification", id="ntfy-test-button", n_clicks=0,
                    disabled=notifications.NOTIFICATIONS_PAUSED, style=styles["button"]),
        html.Span(id="ntfy-test-status", role="status"),
        html.A("Download readings (.csv)", href="/download-csv", className="download-link"),
        html.P(f"{get_csv_row_count():,} logged readings · Last write: {get_csv_last_write_time()}", className="muted"),
        build_health_panel(health_state_data or health_state, used_fallback, dark=dark, show_details=True),
    ], style=styles["section"])


make_card_shell = getattr(ui_module, "make_card_shell", fallback_make_card_shell)
build_moisture_bar = getattr(ui_module, "build_moisture_bar", fallback_build_moisture_bar)
build_settings_panel = getattr(ui_module, "build_settings_panel", fallback_build_settings_panel)
build_health_panel = getattr(ui_module, "build_health_panel", fallback_build_health_panel)
moisture_colors = getattr(ui_module, "moisture_colors", fallback_moisture_colors)
recommendation_pill = getattr(ui_module, "recommendation_pill", fallback_recommendation_pill)


def min_max_bucket_downsample(times, moisture, temp, target_points=300):
    n = len(times)
    if n <= target_points or n == 0:
        return times, moisture, temp

    bucket_count = max(1, target_points // 2)
    bucket_size = max(1, n // bucket_count)
    keep_indices = set()

    for start in range(0, n, bucket_size):
        end = min(n, start + bucket_size)
        if start >= end:
            continue
        bucket_m = moisture[start:end]
        if not bucket_m:
            continue
        keep_indices.add(start + bucket_m.index(min(bucket_m)))
        keep_indices.add(start + bucket_m.index(max(bucket_m)))

    keep_indices.add(0)
    keep_indices.add(n - 1)
    selected = sorted(keep_indices)

    return (
        [times[i] for i in selected],
        [moisture[i] for i in selected],
        [temp[i] for i in selected],
    )


def downsample_history_dict(histories, target_points=None):
    if target_points is None:
        return histories

    out = {}
    for plant, row in (histories or {}).items():
        ds_times, ds_moisture, ds_temp = min_max_bucket_downsample(
            row.get("times", []),
            row.get("moisture", []),
            row.get("temp", []),
            target_points=target_points,
        )
        out[plant] = {"times": ds_times, "moisture": ds_moisture, "temp": ds_temp}
    return out


def serialize_histories(histories, target_points=None):
    histories = downsample_history_dict(histories, target_points=target_points)
    return {
        plant: {
            "times": row.get("times", []),
            "moisture": row.get("moisture", []),
            "temp": row.get("temp", []),
        }
        for plant, row in histories.items()
    }


def deserialize_histories(hist):
    out = {}
    for plant, row in (hist or {}).items():
        converted_times = []
        for t in row.get("times", []):
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            converted_times.append(dt.astimezone(LOCAL_TZ))
        out[plant] = {
            "times": converted_times,
            "moisture": row.get("moisture", []),
            "temp": row.get("temp", []),
        }
    return out


def format_reading_age(ts):
    if ts is None:
        return "Reading age: unavailable"
    age_seconds = max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))
    if age_seconds < 60:
        return f"Reading age: {age_seconds}s ago"
    age_minutes = age_seconds // 60
    if age_minutes < 60:
        return f"Reading age: {age_minutes} min ago"
    age_hours = age_minutes // 60
    rem_minutes = age_minutes % 60
    if age_hours < 24:
        return f"Reading age: {age_hours} hr ago" if rem_minutes == 0 else f"Reading age: {age_hours} hr {rem_minutes} min ago"
    age_days = age_hours // 24
    return f"Reading age: {age_days} day ago" if age_days == 1 else f"Reading age: {age_days} days ago"


def normalize_selected_plants(selected_plants, histories=None):
    if selected_plants is None:
        return plant_names.copy()
    return [p for p in selected_plants if p in plant_names]


def filter_histories_by_selection(histories, selected_plants):
    chosen = normalize_selected_plants(selected_plants, histories)
    return {plant: histories[plant] for plant in chosen if plant in histories}


def format_summary_timestamp(ts):
    if ts is None:
        return "—"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(LOCAL_TZ).strftime("%m/%d %I:%M %p")


def calc_summary_for_plant(row):
    times = row.get("times", [])
    moisture = row.get("moisture", [])
    temp = row.get("temp", [])
    if not moisture or not temp or not times:
        return None

    n = min(len(times), len(moisture), len(temp))
    if n == 0:
        return None

    times = times[:n]
    moisture = moisture[:n]
    temp = temp[:n]

    m_min_idx = min(range(n), key=lambda i: moisture[i])
    m_max_idx = max(range(n), key=lambda i: moisture[i])
    t_min_idx = min(range(n), key=lambda i: temp[i])
    t_max_idx = max(range(n), key=lambda i: temp[i])

    return {
        "m_avg": sum(moisture) / len(moisture),
        "m_min": min(moisture),
        "m_max": max(moisture),
        "m_min_ts": times[m_min_idx],
        "m_max_ts": times[m_max_idx],
        "t_avg": sum(temp) / len(temp),
        "t_min": min(temp),
        "t_max": max(temp),
        "t_min_ts": times[t_min_idx],
        "t_max_ts": times[t_max_idx],
    }


def build_summary_cards(histories, selected_plants, dark=True):
    styles = theme_styles(dark)
    chosen = normalize_selected_plants(selected_plants, histories)
    cards = []

    for plant in chosen:
        row = histories.get(plant, {})
        summary = calc_summary_for_plant(row)
        if summary is None:
            continue
        cards.append(
            html.Div(
                [
                    html.Div(plant, style={"fontWeight": "700", "marginBottom": "8px", "fontSize": "1rem"}),
                    html.Div(f"Moisture avg: {summary['m_avg']:.1f}%"),
                    html.Div(f"Moisture min: {summary['m_min']:.1f}%"),
                    html.Div(f"At: {format_summary_timestamp(summary['m_min_ts'])}", style={"fontSize": "0.88rem", "color": styles.get("subtext", "#9ca3af"), "marginBottom": "4px"}),
                    html.Div(f"Moisture max: {summary['m_max']:.1f}%"),
                    html.Div(f"At: {format_summary_timestamp(summary['m_max_ts'])}", style={"fontSize": "0.88rem", "color": styles.get("subtext", "#9ca3af"), "marginBottom": "6px"}),
                    html.Div(f"Temp avg: {summary['t_avg']:.1f}°F"),
                    html.Div(f"Temp min: {summary['t_min']:.1f}°F"),
                    html.Div(f"At: {format_summary_timestamp(summary['t_min_ts'])}", style={"fontSize": "0.88rem", "color": styles.get("subtext", "#9ca3af"), "marginBottom": "4px"}),
                    html.Div(f"Temp max: {summary['t_max']:.1f}°F"),
                    html.Div(f"At: {format_summary_timestamp(summary['t_max_ts'])}", style={"fontSize": "0.88rem", "color": styles.get("subtext", "#9ca3af")}),
                ],
                style={
                    "backgroundColor": styles.get("card_bg", "#111827"),
                    "border": f"1px solid {styles.get('border', '#374151')}",
                    "borderRadius": "16px",
                    "padding": "14px",
                    "minWidth": "220px",
                    "flex": "0 1 240px",
                },
            )
        )

    if not cards:
        return html.Div()

    return html.Div(
        cards,
        style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "marginBottom": "16px", "justifyContent": "center"},
    )


def build_graph_controls(selected_plants, dark=True):
    styles = theme_styles(dark)
    chosen = normalize_selected_plants(selected_plants)
    return html.Div(
        [
            html.Div("Plants shown in charts", style={"fontWeight": "700", "marginBottom": "8px"}),
            dcc.Checklist(
                id="plant-filter-checklist",
                options=[{"label": plant, "value": plant} for plant in plant_names],
                value=chosen,
                inline=True,
                className="plant-filter",
                inputStyle={"marginRight": "6px", "marginLeft": "10px"},
                labelStyle={"display": "inline-flex", "alignItems": "center", "marginRight": "14px", "marginBottom": "8px"},
            ),
            html.Div(
                "Select one plant to see its ideal moisture band. Deselect all to clear the charts.",
                style={"marginTop": "8px", "fontSize": "0.92rem", "color": styles.get("subtext", "#9ca3af")},
            ),
        ],
        style={**styles["section"], "marginBottom": "16px"},
    )


def build_shell(live_range=1):
    dark = True
    styles = theme_styles(dark)

    def range_button(label, value):
        selected = live_range == value
        return html.Button(
            label,
            id={"type": "live-range-button", "value": value},
            n_clicks=0,
            style=styles["range_button_active"] if selected else styles["range_button"],
            **{"aria-pressed": "true" if selected else "false"},
        )

    return html.Div(
        className="app-dark",
        style=styles["page"],
        children=[
            html.Div(
                style=styles["container"],
                className="dashboard-container",
                children=[
                    html.Div(
                        style=styles["header"],
                        children=[html.Div("PLANT MONITOR / OVERVIEW", className="eyebrow"),
                                  html.H1("Your plant collection"),
                                  html.P("Know what needs care. Watch the rest grow.", className="header-description")],
                    ),
                    html.Div("Notifications paused · Alerts and daily summaries are muted. Readings continue while your ESP32 is connected." if notifications.NOTIFICATIONS_PAUSED else "Notifications active · Watching for dry plants and offline sensors.", className="notification-status", role="status"),
                    html.Div(id="system-status"),
                    html.Div(id="health-panel"),
                    html.Div(id="alert-banner", role="status"),
                    html.Div([html.H2("Your plants"), html.Span("Moisture is relative to each sensor’s calibration.", className="muted")], className="section-heading"),
                    html.Div(
                        [make_card_shell(plant, dark=dark) for plant in plant_names],
                        className="plant-grid",
                    ),
                    html.Div([html.H2("Explore trends"), html.Span("Compare readings or fine-tune plant care.", className="muted")], className="section-heading"),
                    dcc.Tabs(
                        id="view-tabs",
                        value="live",
                        children=[
                            dcc.Tab(label="Recent", value="live", style=styles["tab"], selected_style=styles["tab_selected"]),
                            dcc.Tab(label="Weekly", value="weekly", style=styles["tab"], selected_style=styles["tab_selected"]),
                            dcc.Tab(label="Monthly", value="monthly", style=styles["tab"], selected_style=styles["tab_selected"]),
                            dcc.Tab(label="Plant care", value="settings", style=styles["tab"], selected_style=styles["tab_selected"]),
                        ],
                    ),
                    html.Div(
                        id="live-range-container",
                        style={"marginTop": "16px", "display": "block"},
                        children=[
                            html.Div("Time range", style={"marginBottom": "8px", "fontWeight": "600"}),
                            html.Div([range_button("1 hour", 1), range_button("6 hours", 6), range_button("24 hours", 24)], style={"display": "flex", "gap": "10px", "flexWrap": "wrap"}),
                        ],
                    ),
                    html.Div(id="tab-content", style={"marginTop": "16px"}),
                ],
            )
        ],
    )


def serve_layout():
    return html.Div(
        id="page-root",
        className="app-dark",
        children=[
            dcc.Store(id="plant-rules-store", storage_type="memory", data=monitor.load_rules()),
            dcc.Store(id="live-range-store", storage_type="memory", data=1),
            dcc.Store(id="selected-plants-store", storage_type="local", data=plant_names),
            dcc.Store(id="snapshot-store"),
            dcc.Store(id="history-1-store"),
            dcc.Store(id="history-6-store"),
            dcc.Store(id="history-24-store"),
            dcc.Store(id="history-7-store"),
            dcc.Store(id="history-30-store"),
            dcc.Interval(id="card-refresh", interval=CARD_REFRESH_MS, n_intervals=0),
            dcc.Interval(id="history-fast-refresh", interval=HISTORY_FAST_REFRESH_MS, n_intervals=0),
            dcc.Interval(id="history-7-refresh", interval=WEEKLY_REFRESH_MS, n_intervals=0, disabled=True),
            dcc.Interval(id="history-30-refresh", interval=MONTHLY_REFRESH_MS, n_intervals=0, disabled=True),
            html.Div(id="app-shell", children=build_shell(1)),
        ],
    )


app.layout = serve_layout


@app.callback(
    Output({"type": "live-range-button", "value": ALL}, "style"),
    Output({"type": "live-range-button", "value": ALL}, "aria-pressed"),
    Input("live-range-store", "data"),
)
def update_range_buttons(live_range):
    styles = theme_styles(True)
    selected = [value == (live_range or 1) for value in (1, 6, 24)]
    return ([styles["range_button_active"] if active else styles["range_button"] for active in selected],
            ["true" if active else "false" for active in selected])


@app.callback(
    Output("selected-plants-store", "data"),
    Input("plant-filter-checklist", "value"),
    State("selected-plants-store", "data"),
    prevent_initial_call=True,
)
def update_selected_plants(selected, current):
    cleaned = normalize_selected_plants(selected)
    return cleaned


@app.callback(Output("snapshot-store", "data"), Input("card-refresh", "n_intervals"))
def refresh_snapshot(n):
    return monitor.snapshot_for_browser()


@app.callback(
    Output("history-1-store", "data"),
    Output("history-6-store", "data"),
    Output("history-24-store", "data"),
    Input("history-fast-refresh", "n_intervals"),
)
def refresh_fast_history(n):
    h1, _ = fetch_history(hours=1, cache_name="history_1")
    h6, _ = fetch_history(hours=6, cache_name="history_6")
    h24, _ = fetch_history(hours=24, cache_name="history_24")
    return (serialize_histories(h1), serialize_histories(h6), serialize_histories(h24))


@app.callback(
    Output("history-7-store", "data"),
    Input("view-tabs", "value"),
    Input("history-7-refresh", "n_intervals"),
    State("history-7-store", "data"),
    prevent_initial_call=True,
)
def refresh_7_history(tab, n, current_data):
    if tab != "weekly" and n == 0:
        raise PreventUpdate
    if tab != "weekly" and n > 0:
        raise PreventUpdate
    h7, _ = fetch_history(hours=24 * 7, cache_name="history_7")
    return serialize_histories(h7)


@app.callback(
    Output("history-30-store", "data"),
    Input("view-tabs", "value"),
    Input("history-30-refresh", "n_intervals"),
    State("history-30-store", "data"),
    prevent_initial_call=True,
)
def refresh_30_history(tab, n, current_data):
    if tab != "monthly" and n == 0:
        raise PreventUpdate
    if tab != "monthly" and n > 0:
        raise PreventUpdate
    h30, _ = fetch_history(hours=24 * 30, cache_name="history_30")
    return serialize_histories(h30)


@app.callback(
    Output("history-7-refresh", "disabled"),
    Output("history-30-refresh", "disabled"),
    Input("view-tabs", "value"),
)
def control_slow_history_refresh(tab):
    if tab == "weekly":
        return False, True
    if tab == "monthly":
        return True, False
    return True, True


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
    new_rules = {}
    for i, plant in enumerate(plant_names):
        dry = dry_values[i]
        low = low_values[i]
        high = high_values[i]
        if dry is None or low is None or high is None:
            return no_update, "All values are required."
        if not (0 <= dry <= low <= high <= 100):
            return no_update, f"Invalid values for {plant}. Must satisfy dry ≤ ideal low ≤ ideal high."
        new_rules[plant] = {"dry": dry, "ideal_low": low, "ideal_high": high}
    try:
        monitor.save_rules(new_rules)
    except OSError:
        return no_update, "Could not save rules on the server. Please try again."
    return new_rules, "Rules saved on server; monitoring continues with the page closed."


@app.callback(
    Output({"type": "learning-status", "plant": ALL}, "children"),
    Output("plant-rules-store", "data", allow_duplicate=True),
    Input({"type": "learning-action", "plant": ALL, "action": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def learn_watering_points(clicks):
    trigger = ctx.triggered_id
    if not trigger or not any(clicks):
        raise PreventUpdate
    plant, action = trigger["plant"], trigger["action"]
    message = ""
    updated_rules = no_update
    try:
        if action == "apply":
            rule = calibration.suggested_rules(plant)
            rules = monitor.load_rules()
            rules[plant] = rule
            monitor.save_rules(rules)
            updated_rules = rules
            message = "Suggested thresholds saved. Manual values will update when Settings is reopened."
        elif action == "reset":
            calibration.reset(plant)
            message = "Reference points cleared. Current thresholds are unchanged."
        else:
            calibration.capture(plant, action)
            message = "Reference point saved. Thresholds change only when you Apply."
    except (ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "Could not save reference points; please try again."
    statuses = [html.Div([learning_status(p), html.P(message) if p == plant else None]) for p in plant_names]
    return statuses, updated_rules


@app.callback(Output("ntfy-test-status", "children"), Input("ntfy-test-button", "n_clicks"), prevent_initial_call=True)
def send_test_notification(n_clicks):
    ok = send_ntfy_alert(
        title="Soil Monitor Test",
        message=f"Test sent at {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %I:%M:%S %p')}",
        tags=["white_check_mark", "seedling"],
    )
    return "ntfy test notification sent." if ok else "ntfy test failed."


@app.callback(
    [Output(f"card-{plant}", "children") for plant in plant_names] + [Output("system-status", "children"), Output("health-panel", "children"), Output("alert-banner", "children")],
    Input("snapshot-store", "data"),
    Input("history-24-store", "data"),
    Input("plant-rules-store", "data"),
)
def update_cards(snapshot_data, history24_data, rules_dict):
    dark = True
    styles = theme_styles(dark)
    rules_dict = monitor.load_rules()

    snapshot_data = snapshot_data or {"snapshot": {}, "used_fallback": False}
    snapshot = snapshot_data.get("snapshot", {})
    used_fallback = snapshot_data.get("used_fallback", False)
    history24_data = history24_data or {}

    dry_alerts = []
    offline_alerts = []
    successful_fetches = 0
    latest_snapshot = {}
    order_rank = []

    for plant in plant_names:
        meta = FEEDS[plant]
        row = snapshot.get(plant)

        if row:
            moisture = row.get("moisture")
            temp_f = row.get("temp_f")
            raw = row.get("raw")
            ts = datetime.fromisoformat(row["timestamp"]) if row.get("timestamp") else None

            offline = is_sensor_offline(ts)

            rec, rec_color, bg_color = moisture_colors(moisture, rules_dict[plant], dark=dark)
            if offline:
                rec, rec_color, bg_color = moisture_colors(None, rules_dict[plant], dark=dark, offline=True)

            latest_snapshot[plant] = {"moisture": moisture, "temp_f": temp_f, "recommendation": rec, "offline": offline}

            if rec == "Water now" and not offline:
                dry_alerts.append(plant)
            if offline:
                offline_alerts.append(plant)

            hist = history24_data.get(plant, {})
            hist_times = []
            for t in hist.get("times", []):
                dt = datetime.fromisoformat(t)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                hist_times.append(dt)
            hist_m = hist.get("moisture", [])

            trend = compute_trend_arrow(hist_m)
            eta_hours = estimate_hours_until_dry(hist_times, hist_m, rules_dict[plant]["dry"])
            eta_text = "Dry estimate unavailable for an offline sensor" if offline else ("Dry estimate: gathering trend data" if eta_hours is None else f"Estimated dry in ~{eta_hours:.1f} hr")

            successful_fetches += 1
            last_update = ts.astimezone(LOCAL_TZ).strftime("%m/%d %I:%M %p") if ts else "--"
            reading_age = format_reading_age(ts)

            display_moisture = f"{moisture:.1f}" if moisture is not None else "—"
            display_temp = f"{min(temp_f, TEMP_F_MAX):.1f}°F" if temp_f is not None else "—"
            trend_label = {"↑": "Rising", "↓": "Falling", "→": "Steady"}.get(trend, "Steady")
            rule = rules_dict[plant]
            value = max(0, min(100, moisture)) if moisture is not None else 0
            card = html.Div([
                html.Div([
                    html.H3(f"{meta['emoji']} {plant}"),
                    recommendation_pill(rec, moisture, rule, dark=dark, offline=offline),
                ], className="plant-card-header"),
                html.Div("Last known moisture" if offline else "Soil moisture", className="metric-label"),
                html.Div([html.Strong(display_moisture), html.Span("%", className="reading-unit"),
                          html.Span("Stale reading" if offline else (f"{trend} {trend_label}" if len(hist_m) >= 3 else "Gathering data"), className="trend-label")], className="primary-reading"),
                html.Div([
                    html.Div(style={"left": f"{rule['ideal_low']}%", "width": f"{rule['ideal_high'] - rule['ideal_low']}%"}, className="ideal-zone"),
                    html.Div(style={"width": f"{value}%", "backgroundColor": rec_color}, className="moisture-fill"),
                    html.Div(style={"left": f"{rule['dry']}%"}, className="dry-marker"),
                ], className="moisture-track", role="img", **{"aria-label": f"Moisture {display_moisture} percent. Ideal {rule['ideal_low']} to {rule['ideal_high']} percent. Water at or below {rule['dry']} percent."}),
                html.Div(f"Ideal {rule['ideal_low']}–{rule['ideal_high']}% · water ≤ {rule['dry']}%", className="target-caption"),
                html.Div([
                    html.Div([html.Span("Last temperature" if offline else "Temperature", className="metric-label"), html.Strong(display_temp)]),
                    html.Div([html.Span("Watering", className="metric-label"), html.Span(format_last_watered(plant))]),
                ], className="card-secondary"),
                html.Div(reading_age, className="reading-age"),
                html.Details([html.Summary("Sensor details"), html.Div([
                    html.Div(eta_text), html.Div(f"Last update: {last_update}"),
                    html.Div(f"Raw sensor value: {raw if raw is not None else 'Unavailable'}"),
                ], className="sensor-details")]),
            ], className="plant-card is-offline" if offline else "plant-card",
                style={"--status-color": rec_color})

            rank = -2 if offline else (-1 if rec == "Water now" else 0)
            sort_moisture = moisture if moisture is not None else 999
            order_rank.append((rank, sort_moisture, plant, card))
        else:
            card = html.Div([
                html.Div([html.H3(f"{meta['emoji']} {plant}"), html.Span("No data", className="waiting-badge")], className="plant-card-header"),
                html.Div("Soil moisture", className="metric-label"),
                html.Div("—", className="primary-reading"),
                html.Div("Waiting for sensor", className="empty-title"),
                html.P("Connect your ESP32 to power and Wi-Fi. Readings will appear automatically.", className="muted"),
                html.Div(format_last_watered(plant), className="reading-age"),
            ], className="plant-card is-offline", style={"--status-color": "#80928e"})

            order_rank.append((-3, 999, plant, card))
            offline_alerts.append(plant)
            latest_snapshot[plant] = {"moisture": None, "temp_f": None, "recommendation": "No data", "offline": True}


    # Keep each callback output aligned with its named plant card.
    cards = [item[3] for item in order_rank]

    refresh_text = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %I:%M:%S %p")
    system_status = html.Div(
        [
            html.Div([html.Span("Connected sensors", className="metric-label"), html.Strong(f"{len(FEEDS) - len(offline_alerts)} / {len(FEEDS)}", className="metric-value")]),
            html.Div([html.Span("Need water", className="metric-label"), html.Strong(str(len(dry_alerts)), className="metric-value")]),
            html.Div([html.Span("Data source", className="metric-label"), html.Strong("Cached readings" if used_fallback else ("Adafruit IO" if snapshot else "Waiting for readings"), className="metric-value")]),
            html.Div([html.Span("Dashboard updated", className="metric-label"), html.Strong(datetime.now(LOCAL_TZ).strftime("%I:%M %p"), className="metric-value")]),
        ], className="overview-grid", role="status", style={**styles["section"], "marginBottom": "16px"},
    )

    health_panel = html.Div()

    alert_styles = {
        "mixed": {"backgroundColor": "#3a2814", "color": "#ffd089", "border": "1px solid #7a5b22"},
        "offline": {"backgroundColor": "#1d2633", "color": "#c2ccd8", "border": "1px solid #5f738a"},
        "dry": {"backgroundColor": "#3a1318", "color": "#ff9a9a", "border": "1px solid #a94442"},
        "ok": {"backgroundColor": "#113222", "color": "#7ff0b2", "border": "1px solid #2e8b57"},
    }

    if notifications.NOTIFICATIONS_PAUSED and len(offline_alerts) == len(FEEDS):
        alert_banner = html.Div("Waiting for your ESP32. Historical readings remain available; notifications are paused.", role="status", style={**alert_styles["offline"], "padding": "14px 18px", "borderRadius": "16px", "marginBottom": "16px"})
    elif offline_alerts and dry_alerts:
        alert_banner = html.Div([html.Div(f"Offline sensors: {', '.join(offline_alerts)}"), html.Div(f"Water alerts: {', '.join(dry_alerts)}", style={"marginTop": "6px"})], style={**alert_styles["mixed"], "padding": "14px 18px", "borderRadius": "16px", "marginBottom": "16px", "fontWeight": "700"})
    elif offline_alerts:
        alert_banner = html.Div(f"Offline sensors: {', '.join(offline_alerts)}", style={**alert_styles["offline"], "padding": "14px 18px", "borderRadius": "16px", "marginBottom": "16px", "fontWeight": "700"})
    elif dry_alerts:
        alert_banner = html.Div(f"Water alert: {', '.join(dry_alerts)}", style={**alert_styles["dry"], "padding": "14px 18px", "borderRadius": "16px", "marginBottom": "16px", "fontWeight": "700"})
    else:
        alert_banner = html.Div("No urgent watering alerts or offline sensors.", style={**alert_styles["ok"], "padding": "14px 18px", "borderRadius": "16px", "marginBottom": "16px", "fontWeight": "700"})

    return cards + [system_status, health_panel, alert_banner]


@app.callback(
    Output("live-range-store", "data"),
    Input({"type": "live-range-button", "value": ALL}, "n_clicks"),
    State("live-range-store", "data"),
    prevent_initial_call=True,
)
def set_live_range(_, current_value):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "live-range-button":
        return triggered.get("value", current_value or 1)
    return current_value or 1


@app.callback(Output("live-range-container", "style"), Input("view-tabs", "value"))
def toggle_live_range_visibility(tab):
    return {"marginTop": "16px", "display": "block"} if tab == "live" else {"display": "none"}


@app.callback(
    Output("tab-content", "children"),
    Input("view-tabs", "value"),
    Input("live-range-store", "data"),
    Input("selected-plants-store", "data"),
    Input("history-1-store", "data"),
    Input("history-6-store", "data"),
    Input("history-24-store", "data"),
    Input("history-7-store", "data"),
    Input("history-30-store", "data"),
    Input("snapshot-store", "data"),
    Input("plant-rules-store", "data"),
)
def render_tab(tab, live_range, selected_plants, h1, h6, h24, h7, h30, snapshot_data, rules_dict):
    rules_dict = monitor.load_rules()
    dark = True
    styles = theme_styles(dark)

    if tab == "settings":
        # Keep in-progress form edits and feedback when background data refreshes.
        if ctx.triggered_id not in (None, "view-tabs"):
            return no_update
        snapshot_data = snapshot_data or {"snapshot": {}, "used_fallback": False}
        return build_settings_panel(rules_dict, dark=dark, health_state_data=health_state, used_fallback=snapshot_data.get("used_fallback", False))

    if tab == "live":
        live_hist = {1: deserialize_histories(h1), 6: deserialize_histories(h6), 24: deserialize_histories(h24)}.get(live_range, deserialize_histories(h1))
        filtered_hist = filter_histories_by_selection(live_hist, selected_plants)
        moisture_fig, temp_fig = build_figures(filtered_hist, rules_dict, label_suffix=f"Live ({live_range}h)", dark=dark, temp_max=TEMP_F_MAX)
        return html.Div([build_graph_controls(selected_plants, dark=dark), html.Div(dcc.Graph(figure=moisture_fig, config={"displaylogo": False, "scrollZoom": False, "responsive": True}), style=styles["section"]), html.Div(dcc.Graph(figure=temp_fig, config={"displaylogo": False, "scrollZoom": False, "responsive": True}), style={**styles["section"], "marginTop": "16px"})])

    if tab == "weekly":
        weekly_hist = deserialize_histories(h7)
        filtered_hist = filter_histories_by_selection(weekly_hist, selected_plants)
        moisture_fig, temp_fig = build_figures(filtered_hist, rules_dict, label_suffix="Weekly (days)", dark=dark, temp_max=TEMP_F_MAX)
        return html.Div([build_graph_controls(selected_plants, dark=dark), build_summary_cards(filtered_hist, selected_plants, dark=dark), html.Div(dcc.Graph(figure=moisture_fig, config={"displaylogo": False, "scrollZoom": False, "responsive": True}), style=styles["section"]), html.Div(dcc.Graph(figure=temp_fig, config={"displaylogo": False, "scrollZoom": False, "responsive": True}), style={**styles["section"], "marginTop": "16px"})])

    monthly_hist = deserialize_histories(h30)
    filtered_hist = filter_histories_by_selection(monthly_hist, selected_plants)
    moisture_fig, temp_fig = build_figures(filtered_hist, rules_dict, label_suffix="Monthly (days)", dark=dark, temp_max=TEMP_F_MAX)
    return html.Div([build_graph_controls(selected_plants, dark=dark), build_summary_cards(filtered_hist, selected_plants, dark=dark), html.Div(dcc.Graph(figure=moisture_fig, config={"displaylogo": False, "scrollZoom": False, "responsive": True}), style=styles["section"]), html.Div(dcc.Graph(figure=temp_fig, config={"displaylogo": False, "scrollZoom": False, "responsive": True}), style={**styles["section"], "marginTop": "16px"})])


if __name__ == "__main__":
    ensure_csv_exists()
    ensure_watering_log_exists()
    load_last_watered_from_csv()
    run_startup_checks()
    monitor.start()
    app.run(host="0.0.0.0", port=10000, debug=False)
