from datetime import datetime, timezone

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from flask import send_file

import data_layer
from charts import build_figures
from config import (
    CARD_REFRESH_MS,
    CSV_LOG_PATH,
    DEFAULT_PLANT_RULES,
    FEEDS,
    HISTORY_30_REFRESH_MS,
    HISTORY_7_REFRESH_MS,
    HISTORY_FAST_REFRESH_MS,
    LOCAL_TZ,
    MONTHLY_TARGET_POINTS,
    SENSOR_OFFLINE_MINUTES,
    TEMP_F_MAX,
    WEEKLY_TARGET_POINTS,
)
from data_layer import (
    compute_trend_arrow,
    ensure_csv_exists,
    ensure_watering_log_exists,
    estimate_hours_until_dry,
    fetch_history,
    fetch_latest_snapshot,
    format_last_watered,
    get_csv_last_write_time,
    get_csv_row_count,
    health_state,
    is_sensor_offline,
    load_last_watered_from_csv,
    log_to_csv,
    run_startup_checks,
    should_log_reading,
    update_last_watered_if_needed,
)
from notifications import (
    init_notification_state,
    maybe_send_daily_summary,
    maybe_send_offline_alert,
    maybe_send_urgent_alert,
    send_ntfy_alert,
)
from styles import theme_styles
from ui import (
    build_health_panel,
    build_moisture_bar,
    build_settings_panel,
    build_threshold_legend,
    make_card_shell,
    moisture_colors,
    recommendation_pill,
)

app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server
app.title = "Soil Monitor Dashboard"


@server.route("/download-csv")
def download_csv():
    ensure_csv_exists()
    return send_file(
        path_or_file=CSV_LOG_PATH,
        mimetype="text/csv",
        as_attachment=True,
        download_name="plant_readings.csv",
    )


plant_names = list(FEEDS.keys())

init_notification_state(plant_names)
run_startup_checks()


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

        local_min_idx = start + bucket_m.index(min(bucket_m))
        local_max_idx = start + bucket_m.index(max(bucket_m))
        keep_indices.add(local_min_idx)
        keep_indices.add(local_max_idx)

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
    out = {}

    for plant, row in histories.items():
        serialized_times = []
        for t in row.get("times", []):
            if isinstance(t, datetime):
                serialized_times.append(t.isoformat())
            else:
                serialized_times.append(t)

        out[plant] = {
            "times": serialized_times,
            "moisture": row.get("moisture", []),
            "temp": row.get("temp", []),
        }

    return out


def deserialize_histories(hist):
    out = {}
    hist = hist or {}

    for plant, row in hist.items():
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
        return "Reading age: unknown"

    now = datetime.now(timezone.utc)
    age_seconds = max(0, (now - ts).total_seconds())
    minutes = age_seconds / 60.0

    if minutes < 1:
        return "Reading age: just now"
    if minutes < 60:
        return f"Reading age: {minutes:.0f} min ago"

    hours = minutes / 60.0
    if hours < 24:
        return f"Reading age: {hours:.1f} hr ago"

    days = hours / 24.0
    return f"Reading age: {days:.1f} days ago"


def format_stat_value(value, suffix="", decimals=1, fallback="--"):
    if value is None:
        return fallback
    return f"{value:.{decimals}f}{suffix}"


def build_summary_cards(histories, selected_plants, title):
    styles = theme_styles(True)
    cards = []

    for plant in selected_plants:
        row = histories.get(plant, {})
        moisture = row.get("moisture", [])
        temp = row.get("temp", [])

        if not moisture:
            continue

        latest_m = moisture[-1]
        avg_m = sum(moisture) / len(moisture)
        min_m = min(moisture)
        max_m = max(moisture)

        latest_t = temp[-1] if temp else None
        avg_t = sum(temp) / len(temp) if temp else None

        cards.append(
            html.Div(
                [
                    html.Div(plant, style={"fontWeight": "700", "marginBottom": "10px"}),
                    html.Div(f"Latest moisture: {format_stat_value(latest_m, '%')}", style={"marginBottom": "6px"}),
                    html.Div(f"Avg moisture: {format_stat_value(avg_m, '%')}", style={"marginBottom": "6px"}),
                    html.Div(f"Min / Max moisture: {format_stat_value(min_m, '%')} / {format_stat_value(max_m, '%')}", style={"marginBottom": "6px"}),
                    html.Div(f"Latest temp: {format_stat_value(latest_t, '°F')}", style={"marginBottom": "6px"}),
                    html.Div(f"Avg temp: {format_stat_value(avg_t, '°F')}") if avg_t is not None else html.Div("Avg temp: --"),
                ],
                style={
                    **styles["section"],
                    "minWidth": "240px",
                    "flex": "1 1 240px",
                    "marginBottom": "12px",
                },
            )
        )

    return html.Div(
        [
            html.Div(title, style={"fontWeight": "700", "marginBottom": "10px"}),
            html.Div(cards or [html.Div("No data for selected plants.", style=styles["section"])] , style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}),
        ],
        style={**styles["section"], "marginBottom": "16px"},
    )


def build_shell(live_range=1, selected_plants=None):
    dark = True
    styles = theme_styles(True)
    selected_plants = selected_plants or plant_names

    def range_button(label, value):
        selected = live_range == value
        return html.Button(
            label,
            id={"type": "live-range-button", "value": value},
            n_clicks=0,
            style=styles["range_button_active"] if selected else styles["range_button"],
        )

    return html.Div(
        className="app-dark",
        style=styles["page"],
        children=[
            html.Div(
                style=styles["container"],
                children=[
                    html.Div(
                        style=styles["header"],
                        children=[
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.H1("Plant Soil Monitor", style={"margin": "0 0 8px 0", "fontSize": "2rem"}),
                                            html.P(
                                                "Track moisture, temperature, watering, alerts, and trends in one place.",
                                                style={"margin": "0", "opacity": "0.92"},
                                            ),
                                        ]
                                    ),
                                ],
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start", "gap": "16px"},
                            )
                        ],
                    ),
                    html.Div(id="system-status"),
                    html.Div(id="health-panel"),
                    html.Div(id="alert-banner"),
                    html.Div(
                        [make_card_shell(plant, dark=dark) for plant in plant_names],
                        style={"display": "flex", "flexWrap": "wrap", "gap": "14px", "marginBottom": "18px"},
                    ),
                    dcc.Tabs(
                        id="view-tabs",
                        value="live",
                        children=[
                            dcc.Tab(label="Live", value="live", style=styles["tab"], selected_style=styles["tab_selected"]),
                            dcc.Tab(label="Weekly", value="weekly", style=styles["tab"], selected_style=styles["tab_selected"]),
                            dcc.Tab(label="Monthly", value="monthly", style=styles["tab"], selected_style=styles["tab_selected"]),
                            dcc.Tab(label="Settings", value="settings", style=styles["tab"], selected_style=styles["tab_selected"]),
                        ],
                    ),
                    html.Div(
                        id="live-range-container",
                        style={"marginTop": "16px", "display": "block"},
                        children=[
                            html.Div("Live range", style={"marginBottom": "8px", "fontWeight": "600"}),
                            html.Div(
                                [range_button("1 hour", 1), range_button("6 hours", 6), range_button("24 hours", 24)],
                                style={"display": "flex", "gap": "10px", "flexWrap": "wrap"},
                            ),
                        ],
                    ),
                    html.Div(
                        id="plant-selector-container",
                        style={"marginTop": "16px", "display": "block"},
                        children=[
                            html.Div("Plants shown in charts", style={"marginBottom": "8px", "fontWeight": "600"}),
                            dcc.Checklist(
                                id="plant-visibility-checklist",
                                options=[{"label": plant, "value": plant} for plant in plant_names],
                                value=selected_plants,
                                inline=True,
                                inputStyle={"marginRight": "6px", "marginLeft": "10px"},
                                labelStyle={"display": "inline-flex", "alignItems": "center", "marginRight": "12px", "marginBottom": "8px"},
                            ),
                        ],
                    ),
                    html.Div(id="tab-content", style={"marginTop": "16px"}),
                ],
            )
        ],
    )


app.layout = html.Div(
    id="page-root",
    className="app-dark",
    children=[
        dcc.Store(id="plant-rules-store", storage_type="local", data=DEFAULT_PLANT_RULES),
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
        dcc.Interval(id="history-7-refresh", interval=HISTORY_7_REFRESH_MS, n_intervals=0),
        dcc.Interval(id="history-30-refresh", interval=HISTORY_30_REFRESH_MS, n_intervals=0),
        html.Div(id="app-shell", children=build_shell(1, plant_names)),
    ],
)


@app.callback(
    Output("app-shell", "children"),
    Input("live-range-store", "data"),
    Input("selected-plants-store", "data"),
)
def render_shell(live_range, selected_plants):
    return build_shell(live_range or 1, selected_plants or plant_names)


@app.callback(
    Output("selected-plants-store", "data"),
    Input("plant-visibility-checklist", "value"),
    prevent_initial_call=True,
)
def save_selected_plants(selected_plants):
    return selected_plants or plant_names


@app.callback(Output("snapshot-store", "data"), Input("card-refresh", "n_intervals"))
def refresh_snapshot(n):
    snapshot, used_fallback = fetch_latest_snapshot()
    return {"snapshot": snapshot, "used_fallback": used_fallback}


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
    return (
        serialize_histories(h1, target_points=None),
        serialize_histories(h6, target_points=None),
        serialize_histories(h24, target_points=None),
    )


@app.callback(Output("history-7-store", "data"), Input("history-7-refresh", "n_intervals"))
def refresh_7_history(n):
    h7, _ = fetch_history(hours=24 * 7, cache_name="history_7")
    return serialize_histories(h7, target_points=WEEKLY_TARGET_POINTS)


@app.callback(Output("history-30-store", "data"), Input("history-30-refresh", "n_intervals"))
def refresh_30_history(n):
    h30, _ = fetch_history(hours=24 * 30, cache_name="history_30")
    return serialize_histories(h30, target_points=MONTHLY_TARGET_POINTS)


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

    init_notification_state(plant_names)
    return new_rules, "Rules saved."


@app.callback(Output("ntfy-test-status", "children"), Input("ntfy-test-button", "n_clicks"), prevent_initial_call=True)
def send_test_notification(n_clicks):
    ok = send_ntfy_alert(
        title="Soil Monitor Test",
        message=f"Test sent at {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %I:%M:%S %p')}",
        tags=["white_check_mark", "seedling"],
    )
    return "ntfy test notification sent." if ok else "ntfy test failed."


@app.callback(
    [Output(f"card-{plant}", "children") for plant in plant_names]
    + [Output("system-status", "children"), Output("health-panel", "children"), Output("alert-banner", "children")],
    Input("snapshot-store", "data"),
    Input("history-24-store", "data"),
    Input("plant-rules-store", "data"),
)
def update_cards(snapshot_data, history24_data, rules_dict):
    dark = True
    styles = theme_styles(True)

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
            maybe_send_offline_alert(plant, offline, ts, SENSOR_OFFLINE_MINUTES)
            update_last_watered_if_needed(plant, moisture, ts, offline)

            rec, rec_color, bg_color = moisture_colors(moisture, rules_dict[plant], dark=dark, offline=offline)
            latest_snapshot[plant] = {
                "moisture": moisture,
                "temp_f": temp_f,
                "recommendation": rec,
                "offline": offline,
            }

            if not offline and should_log_reading(plant, moisture):
                log_to_csv(
                    timestamp=ts or datetime.now(timezone.utc),
                    plant=plant,
                    moisture=moisture,
                    temp_f=temp_f,
                    raw=raw,
                    recommendation=rec,
                    sensor_offline=offline,
                )

            if not offline:
                maybe_send_urgent_alert(plant, moisture, rec)

            if rec == "Water now" and not offline:
                dry_alerts.append(plant)
            if offline:
                offline_alerts.append(plant)

            hist = history24_data.get(plant, {})
            hist_times = [datetime.fromisoformat(t) for t in hist.get("times", [])]
            hist_m = hist.get("moisture", [])
            trend = compute_trend_arrow(hist_m)
            eta_hours = estimate_hours_until_dry(hist_times, hist_m, rules_dict[plant]["dry"])
            eta_text = "Dry ETA: unknown" if eta_hours is None else f"Dry ETA: ~{eta_hours:.1f} hr"

            successful_fetches += 1
            last_update = ts.astimezone(LOCAL_TZ).strftime("%m/%d %I:%M %p") if ts else "--"
            reading_age = format_reading_age(ts)

            card = html.Div(
                [
                    html.Div(
                        [
                            html.H3(f"{meta['emoji']} {plant}", style={"margin": "0", "fontSize": "1.1rem"}),
                            recommendation_pill(rec, moisture, rules_dict[plant], dark=dark, offline=offline),
                        ],
                        style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "14px"},
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(" Moisture", style={"color": styles["subtext"], "fontSize": "0.85rem"}),
                                    html.Div(f"{moisture:.1f}% {trend}", style={"fontSize": "1.25rem", "fontWeight": "700"}),
                                ],
                                style={"flex": "1"},
                            ),
                            html.Div(
                                [
                                    html.Div(" Temp", style={"color": styles["subtext"], "fontSize": "0.85rem"}),
                                    html.Div(f"{min(temp_f, TEMP_F_MAX):.1f}°F", style={"fontSize": "1.25rem", "fontWeight": "700"}),
                                ],
                                style={"flex": "1"},
                            ),
                        ],
                        style={"display": "flex", "gap": "12px", "marginBottom": "12px"},
                    ),
                    build_moisture_bar(moisture, rec_color, dark=dark),
                    html.Div(format_last_watered(plant), style={"marginBottom": "8px", "fontSize": "0.92rem", "fontWeight": "600"}),
                    html.Div(eta_text, style={"marginBottom": "8px", "fontSize": "0.92rem"}),
                    html.Div(reading_age, style={"marginBottom": "8px", "fontSize": "0.92rem", "color": styles["subtext"]}),
                    html.Div(f"Last update: {last_update}", style={"fontSize": "0.92rem", "color": styles["subtext"]}),
                ],
                style={
                    "backgroundColor": bg_color,
                    "border": f"2px solid {rec_color}",
                    "borderRadius": "18px",
                    "padding": "16px",
                    "minHeight": "285px",
                    "color": styles["text"],
                },
            )

            rank = -2 if offline else -1 if rec == "Water now" else 0
            order_rank.append((rank, moisture, plant, card))
        else:
            card = html.Div(
                [
                    html.H3(f"{meta['emoji']} {plant}", style={"marginTop": "0"}),
                    html.Div("No data", style={"fontWeight": "700", "color": styles["subtext"], "marginBottom": "10px"}),
                    html.Div(format_last_watered(plant), style={"marginBottom": "8px", "fontSize": "0.92rem", "fontWeight": "600"}),
                    html.Div("Reading age: unknown", style={"marginBottom": "8px", "fontSize": "0.92rem", "color": styles["subtext"]}),
                    html.Div("Last update: --", style={"fontSize": "0.92rem", "color": styles["subtext"]}),
                ],
                style={
                    "backgroundColor": styles["status_bg"]["nodata"],
                    "border": f"2px solid {styles['status_border']['nodata']}",
                    "borderRadius": "18px",
                    "padding": "16px",
                    "minHeight": "285px",
                    "color": styles["text"],
                },
            )
            order_rank.append((-3, 999, plant, card))
            offline_alerts.append(plant)
            latest_snapshot[plant] = {"moisture": None, "temp_f": None, "recommendation": "No data", "offline": True}

    maybe_send_daily_summary(latest_snapshot)

    order_rank.sort(key=lambda x: (x[0], x[1], x[2]))
    cards = [[item[3]] for item in order_rank]

    refresh_text = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %I:%M:%S %p")
    system_status = html.Div(
        [
            html.Div(f"Last refresh: {refresh_text}", style=styles["chip"]),
            html.Div(f"Plants fetched: {successful_fetches}/{len(FEEDS)}", style=styles["chip"]),
            html.Div(f"CSV rows: {get_csv_row_count()}", style=styles["chip"]),
            html.Div(f"CSV last write: {get_csv_last_write_time()}", style=styles["chip"]),
            html.Div(f"CSV: {data_layer.last_csv_status}", style=styles["chip"]),
        ],
        style={**styles["section"], "marginBottom": "16px"},
    )

    health_panel = build_health_panel(health_state, used_fallback, dark=dark, show_details=False)

    if offline_alerts and dry_alerts:
        text = [html.Div(f"Offline sensors: {', '.join(offline_alerts)}"), html.Div(f"Water alerts: {', '.join(dry_alerts)}", style={"marginTop": "6px"})]
        key = "check"
    elif offline_alerts:
        text = f"Offline sensors: {', '.join(offline_alerts)}"
        key = "offline"
    elif dry_alerts:
        text = f"Water alert: {', '.join(dry_alerts)}"
        key = "dry"
    else:
        text = "No urgent watering alerts or offline sensors."
        key = "good"

    alert_banner = html.Div(
        text,
        style={
            "backgroundColor": styles["status_bg"][key],
            "color": styles["status_pill_text"][key],
            "border": f"1px solid {styles['status_border'][key]}",
            "padding": "14px 18px",
            "borderRadius": "16px",
            "marginBottom": "16px",
            "fontWeight": "700",
        },
    )

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


@app.callback(
    Output("live-range-container", "style"),
    Output("plant-selector-container", "style"),
    Input("view-tabs", "value"),
)
def toggle_control_visibility(tab):
    controls_style = {"marginTop": "16px", "display": "block"}
    hidden_style = {"display": "none"}
    if tab == "settings":
        return hidden_style, hidden_style
    if tab == "live":
        return controls_style, controls_style
    return hidden_style, controls_style


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
    dark = True
    styles = theme_styles(True)
    selected_plants = selected_plants or plant_names

    if tab == "settings":
        snapshot_data = snapshot_data or {"snapshot": {}, "used_fallback": False}
        used_fallback = snapshot_data.get("used_fallback", False)
        return build_settings_panel(rules_dict, dark=dark, health_state_data=health_state, used_fallback=used_fallback)

    source_map = {
        "live": {1: deserialize_histories(h1), 6: deserialize_histories(h6), 24: deserialize_histories(h24)}.get(live_range or 1, deserialize_histories(h1)),
        "weekly": deserialize_histories(h7),
        "monthly": deserialize_histories(h30),
    }
    histories = source_map[tab]
    filtered_histories = {plant: histories.get(plant, {"times": [], "moisture": [], "temp": []}) for plant in selected_plants}

    label_suffix = "Live ({}h)".format(live_range) if tab == "live" else "Weekly" if tab == "weekly" else "Monthly"
    moisture_fig, temp_fig = build_figures(
        filtered_histories,
        rules_dict,
        label_suffix=label_suffix,
        dark=dark,
        temp_max=TEMP_F_MAX,
    )

    summary_title = "Selected plant summaries"
    return html.Div(
        [
            build_summary_cards(filtered_histories, selected_plants, summary_title),
            build_threshold_legend(selected_plants, rules_dict),
            html.Div(dcc.Graph(figure=moisture_fig), style=styles["section"]),
            html.Div(dcc.Graph(figure=temp_fig), style={**styles["section"], "marginTop": "16px"}),
        ]
    )


if __name__ == "__main__":
    ensure_csv_exists()
    ensure_watering_log_exists()
    load_last_watered_from_csv()
    run_startup_checks()
    app.run(host="0.0.0.0", port=10000, debug=False)
