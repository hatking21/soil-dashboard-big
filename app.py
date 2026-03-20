from datetime import datetime, timezone

from dash import Dash, Input, Output, State, ALL, dcc, html, no_update
from flask import send_file

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
    ensure_csv_exists,
    ensure_watering_log_exists,
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
    compute_trend_arrow,
    estimate_hours_until_dry,
    last_csv_status,
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
        times = row.get("times", [])
        moisture = row.get("moisture", [])
        temp = row.get("temp", [])

        ds_times, ds_moisture, ds_temp = min_max_bucket_downsample(
            times, moisture, temp, target_points=target_points
        )

        out[plant] = {
            "times": ds_times,
            "moisture": ds_moisture,
            "temp": ds_temp,
        }
    return out


def serialize_histories(histories, target_points=None):
    histories = downsample_history_dict(histories, target_points=target_points)
    out = {}

    for plant, row in histories.items():
        out[plant] = {
            "times": row.get("times", []),
            "moisture": row.get("moisture", []),
            "temp": row.get("temp", []),
        }

    return out


def deserialize_histories(hist):
    out = {}
    hist = hist or {}

    for plant, row in hist.items():
        out[plant] = {
            "times": [datetime.fromisoformat(t) for t in row.get("times", [])],
            "moisture": row.get("moisture", []),
            "temp": row.get("temp", []),
        }

    return out


app.layout = html.Div(
    id="page-root",
    children=[
        dcc.Store(id="plant-rules-store", storage_type="local", data=DEFAULT_PLANT_RULES),
        dcc.Store(id="theme-store", storage_type="local", data={"dark": False}),
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
        html.Div(id="app-shell"),
    ],
)


@app.callback(
    Output("theme-store", "data"),
    Input("toggle-dark-button", "n_clicks"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def toggle_theme(n_clicks, theme_data):
    dark = bool((theme_data or {}).get("dark", False))
    return {"dark": not dark}


@app.callback(
    Output("app-shell", "children"),
    Input("theme-store", "data"),
)
def render_shell(theme_data):
    dark = bool((theme_data or {}).get("dark", False))
    styles = theme_styles(dark)

    return html.Div(
        className="app-dark" if dark else "app-light",
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
                                    html.Button(
                                        "Light Mode" if dark else "Dark Mode",
                                        id="toggle-dark-button",
                                        n_clicks=0,
                                        style=styles["button_primary"],
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
                        children=[
                            dcc.Tab(label="Live", value="live", style=styles["tab"], selected_style=styles["tab_selected"]),
                            dcc.Tab(label="Weekly", value="weekly", style=styles["tab"], selected_style=styles["tab_selected"]),
                            dcc.Tab(label="Monthly", value="monthly", style=styles["tab"], selected_style=styles["tab_selected"]),
                            dcc.Tab(label="Settings", value="settings", style=styles["tab"], selected_style=styles["tab_selected"]),
                        ],
                    ),
                    html.Div(
                        id="live-range-container",
                        style={"marginTop": "16px"},
                        children=[
                            html.Label("Live range", style={"marginRight": "10px"}),
                            dcc.Dropdown(
                                id="live-range",
                                options=[
                                    {"label": "1 hour", "value": 1},
                                    {"label": "6 hours", "value": 6},
                                    {"label": "24 hours", "value": 24},
                                ],
                                value=1,
                                clearable=False,
                                className="live-range-dropdown",
                                style={"width": "220px", "display": "inline-block", "verticalAlign": "middle"},
                            ),
                        ]
                    ),
                    html.Div(id="tab-content", style={"marginTop": "16px"}),
                ],
            )
        ],
    )


@app.callback(
    Output("snapshot-store", "data"),
    Input("card-refresh", "n_intervals"),
)
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


@app.callback(
    Output("history-7-store", "data"),
    Input("history-7-refresh", "n_intervals"),
)
def refresh_7_history(n):
    h7, _ = fetch_history(hours=24 * 7, cache_name="history_7")
    return serialize_histories(h7, target_points=WEEKLY_TARGET_POINTS)


@app.callback(
    Output("history-30-store", "data"),
    Input("history-30-refresh", "n_intervals"),
)
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

        new_rules[plant] = {
            "dry": dry,
            "ideal_low": low,
            "ideal_high": high,
        }

    init_notification_state(plant_names)
    return new_rules, "Rules saved."


@app.callback(
    Output("ntfy-test-status", "children"),
    Input("ntfy-test-button", "n_clicks"),
    prevent_initial_call=True,
)
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
    Input("theme-store", "data"),
)
def update_cards(snapshot_data, history24_data, rules_dict, theme_data):
    dark = bool((theme_data or {}).get("dark", False))
    styles = theme_styles(dark)

    snapshot_data = snapshot_data or {"snapshot": {}, "used_fallback": False}
    snapshot = snapshot_data.get("snapshot", {})
    used_fallback = snapshot_data.get("used_fallback", False)
    history24_data = history24_data or {}

    cards = []
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

            rec, rec_color, bg_color = moisture_colors(moisture, rules_dict[plant], dark=dark)
            if offline:
                rec, rec_color, bg_color = moisture_colors(None, rules_dict[plant], dark=dark, offline=True)

            latest_snapshot[plant] = {
                "moisture": moisture,
                "temp_f": temp_f,
                "recommendation": rec,
                "offline": offline,
            }

            if should_log_reading(plant, moisture):
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
            title = f"{meta['emoji']} {plant}"

            card = html.Div(
                [
                    html.Div(
                        [
                            html.H3(title, style={"margin": "0", "fontSize": "1.1rem"}),
                            recommendation_pill(rec, moisture, rules_dict[plant], dark=dark, offline=offline),
                        ],
                        style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "14px"},
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div("💧 Moisture", style={"color": styles["subtext"], "fontSize": "0.85rem"}),
                                    html.Div(f"{moisture:.1f}% {trend}", style={"fontSize": "1.25rem", "fontWeight": "700"}),
                                ],
                                style={"flex": "1"},
                            ),
                            html.Div(
                                [
                                    html.Div("🌡 Temp", style={"color": styles["subtext"], "fontSize": "0.85rem"}),
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
                    html.Div(f"Last update: {last_update}", style={"fontSize": "0.92rem", "color": styles["subtext"]}),
                ],
                style={
                    "backgroundColor": bg_color,
                    "border": f"2px solid {rec_color}",
                    "borderRadius": "18px",
                    "padding": "16px",
                    "minHeight": "255px",
                    "color": styles["text"],
                },
            )

            rank = 0
            if offline:
                rank = -2
            elif rec == "Water now":
                rank = -1
            order_rank.append((rank, moisture, plant, card))

        else:
            card = html.Div(
                [
                    html.H3(f"{meta['emoji']} {plant}", style={"marginTop": "0"}),
                    html.Div(
                        "No data",
                        style={
                            "fontWeight": "700",
                            "color": styles["subtext"],
                            "marginBottom": "10px",
                        },
                    ),
                    html.Div(format_last_watered(plant), style={"marginBottom": "8px", "fontSize": "0.92rem", "fontWeight": "600"}),
                    html.Div("Last update: --", style={"fontSize": "0.92rem", "color": styles["subtext"]}),
                ],
                style={
                    "backgroundColor": styles["status_bg"]["nodata"],
                    "border": f"2px solid {styles['status_border']['nodata']}",
                    "borderRadius": "18px",
                    "padding": "16px",
                    "minHeight": "255px",
                    "color": styles["text"],
                },
            )
            order_rank.append((-3, 999, plant, card))
            offline_alerts.append(plant)
            latest_snapshot[plant] = {
                "moisture": None,
                "temp_f": None,
                "recommendation": "No data",
                "offline": True,
            }

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
            html.Div(f"CSV: {last_csv_status}", style=styles["chip"]),
        ],
        style={**styles["section"], "marginBottom": "16px"},
    )

    health_panel = build_health_panel(health_state, used_fallback, dark=dark)

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
            },
        )

    return cards + [system_status, health_panel, alert_banner]


@app.callback(
    Output("live-range-container", "style"),
    Input("view-tabs", "value"),
)
def toggle_live_range_visibility(tab):
    if tab == "live":
        return {"marginTop": "16px", "display": "block"}
    return {"display": "none"}


@app.callback(
    Output("tab-content", "children"),
    Input("view-tabs", "value"),
    Input("live-range", "value"),
    Input("history-1-store", "data"),
    Input("history-6-store", "data"),
    Input("history-24-store", "data"),
    Input("history-7-store", "data"),
    Input("history-30-store", "data"),
    Input("plant-rules-store", "data"),
    Input("theme-store", "data"),
)
def render_tab(tab, live_range, h1, h6, h24, h7, h30, rules_dict, theme_data):
    dark = bool((theme_data or {}).get("dark", False))
    styles = theme_styles(dark)

    if tab == "settings":
        return build_settings_panel(rules_dict, dark=dark)

    if tab == "live":
        live_hist = {
            1: deserialize_histories(h1),
            6: deserialize_histories(h6),
            24: deserialize_histories(h24),
        }.get(live_range, deserialize_histories(h1))

        moisture_fig, temp_fig = build_figures(
            live_hist,
            rules_dict,
            label_suffix=f"Live ({live_range}h)",
            dark=dark,
            temp_max=TEMP_F_MAX,
        )
        return html.Div(
            [
                html.Div(dcc.Graph(figure=moisture_fig), style=styles["section"]),
                html.Div(dcc.Graph(figure=temp_fig), style={**styles["section"], "marginTop": "16px"}),
            ]
        )

    if tab == "weekly":
        weekly_hist = deserialize_histories(h7)
        moisture_fig, temp_fig = build_figures(
            weekly_hist,
            rules_dict,
            label_suffix="Weekly",
            dark=dark,
            temp_max=TEMP_F_MAX,
        )
        return html.Div(
            [
                html.Div(dcc.Graph(figure=moisture_fig), style=styles["section"]),
                html.Div(dcc.Graph(figure=temp_fig), style={**styles["section"], "marginTop": "16px"}),
            ]
        )

    monthly_hist = deserialize_histories(h30)
    moisture_fig, temp_fig = build_figures(
        monthly_hist,
        rules_dict,
        label_suffix="Monthly",
        dark=dark,
        temp_max=TEMP_F_MAX,
    )
    return html.Div(
        [
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
