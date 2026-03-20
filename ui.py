from dash import dcc, html

from config import (
    CARD_REFRESH_MS,
    CSV_RETENTION_DAYS,
    FEEDS,
    HISTORY_REFRESH_MS,
    SENSOR_OFFLINE_MINUTES,
    TEMP_F_MAX,
    WATERING_JUMP_THRESHOLD,
)
from data_layer import get_csv_last_write_time, get_csv_row_count, last_csv_status
from styles import theme_styles


def moisture_colors(moisture, rules):
    if moisture is None:
        return "No data", "#6b7280", "#f3f4f6"
    if moisture < rules["dry"]:
        return "Water now", "#c0392b", "#fff1ef"
    if moisture < rules["ideal_low"]:
        return "Check soon", "#d9822b", "#fff7eb"
    if moisture <= rules["ideal_high"]:
        return "Moisture looks good", "#2e8b57", "#f2fff7"
    return "Wet / hold off", "#2f7ea1", "#eef9ff"


def make_card_shell(plant, dark=False):
    styles = theme_styles(dark)
    return html.Div(id=f"card-{plant}", style=styles["card_shell"])


def build_moisture_bar(moisture, color):
    safe = max(0, min(100, moisture))
    return html.Div(
        [
            html.Div("Moisture level", style={"fontSize": "0.85rem", "marginBottom": "6px"}),
            html.Div(
                [html.Div(style={"width": f"{safe}%", "height": "100%", "background": color, "borderRadius": "999px"})],
                style={
                    "height": "12px",
                    "backgroundColor": "#e9efeb",
                    "borderRadius": "999px",
                    "overflow": "hidden",
                },
            ),
        ],
        style={"marginBottom": "14px"},
    )


def build_health_panel(health_state, used_fallback, dark=False):
    styles = theme_styles(dark)

    def pill(label, ok):
        return html.Span(
            f"{label}: {'OK' if ok else 'Issue'}",
            style={**styles["chip"], "color": "#2e8b57" if ok else "#c0392b"},
        )

    items = [
        pill("Adafruit", health_state["adafruit_ok"]),
        pill("CSV", health_state["csv_ok"]),
        pill("Water log", health_state["watering_log_ok"]),
    ]
    if used_fallback:
        items.append(html.Span("Using last good data", style={**styles["chip"], "color": "#d9822b"}))

    if health_state.get("last_error"):
        items.append(html.Div(f"Last error: {health_state['last_error']}", style={"fontSize": "0.9rem"}))

    return html.Div(items, style={**styles["section"], "marginBottom": "16px"})


def build_settings_panel(rules_dict, dark=False):
    styles = theme_styles(dark)
    children = [
        html.H3("Settings", style={"marginTop": "0"}),
        html.P("Rules are stored in this browser.", style={"color": styles["subtext"]}),
        html.Div(
            [
                html.Span(f"Offline threshold: {SENSOR_OFFLINE_MINUTES} min", style=styles["chip"]),
                html.Span(f"Watering jump: {WATERING_JUMP_THRESHOLD:.1f}%", style=styles["chip"]),
                html.Span(f"CSV retention: {CSV_RETENTION_DAYS} days", style=styles["chip"]),
                html.Span(f"CSV rows: {get_csv_row_count()}", style=styles["chip"]),
                html.Span(f"Temp cap: {TEMP_F_MAX:.0f}°F", style=styles["chip"]),
                html.Span(f"Card refresh: {CARD_REFRESH_MS // 1000}s", style=styles["chip"]),
                html.Span(f"Chart refresh: {HISTORY_REFRESH_MS // 1000}s", style=styles["chip"]),
            ]
        ),
        html.P(f"CSV last write: {get_csv_last_write_time()}", style={"color": styles["subtext"]}),
        html.P(f"CSV status: {last_csv_status}", style={"fontWeight": "600"}),
    ]

    for plant in FEEDS:
        pr = rules_dict[plant]
        children.append(
            html.Div(
                [
                    html.H4(plant, style={"marginTop": "0"}),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Dry threshold"),
                                    dcc.Input(
                                        id={"type": "dry-input", "plant": plant},
                                        type="number",
                                        value=pr["dry"],
                                        min=0,
                                        max=100,
                                        step=1,
                                        style={
                                            "width": "100%",
                                            "padding": "10px",
                                            "borderRadius": "10px",
                                            "border": f"1px solid {styles['border']}",
                                            "backgroundColor": styles["input_bg"],
                                            "color": styles["input_text"],
                                        },
                                    ),
                                ],
                                style={"flex": "1"},
                            ),
                            html.Div(
                                [
                                    html.Label("Ideal low"),
                                    dcc.Input(
                                        id={"type": "ideal-low-input", "plant": plant},
                                        type="number",
                                        value=pr["ideal_low"],
                                        min=0,
                                        max=100,
                                        step=1,
                                        style={
                                            "width": "100%",
                                            "padding": "10px",
                                            "borderRadius": "10px",
                                            "border": f"1px solid {styles['border']}",
                                            "backgroundColor": styles["input_bg"],
                                            "color": styles["input_text"],
                                        },
                                    ),
                                ],
                                style={"flex": "1"},
                            ),
                            html.Div(
                                [
                                    html.Label("Ideal high"),
                                    dcc.Input(
                                        id={"type": "ideal-high-input", "plant": plant},
                                        type="number",
                                        value=pr["ideal_high"],
                                        min=0,
                                        max=100,
                                        step=1,
                                        style={
                                            "width": "100%",
                                            "padding": "10px",
                                            "borderRadius": "10px",
                                            "border": f"1px solid {styles['border']}",
                                            "backgroundColor": styles["input_bg"],
                                            "color": styles["input_text"],
                                        },
                                    ),
                                ],
                                style={"flex": "1"},
                            ),
                        ],
                        style={"display": "flex", "gap": "12px"},
                    ),
                ],
                style={**styles["section"], "marginBottom": "14px"},
            )
        )

    children.append(
        html.Div(
            [
                html.Button("Save Rules", id="save-rules-button", n_clicks=0, style={**styles["button"], "marginRight": "12px"}),
                html.Button("Send ntfy Test", id="ntfy-test-button", n_clicks=0, style={**styles["button"], "marginRight": "12px"}),
                html.A(
                    "Download CSV",
                    href="/download-csv",
                    target="_blank",
                    style={**styles["button"], "display": "inline-block", "textDecoration": "none"},
                ),
                html.Button(
                    "Toggle Dark Mode",
                    id="toggle-dark-button",
                    n_clicks=0,
                    style={**styles["button"], "marginLeft": "12px"},
                ),
            ]
        )
    )
    children.append(html.Div(id="save-rules-status", style={"marginTop": "10px", "fontWeight": "600"}))
    children.append(html.Div(id="ntfy-test-status", style={"marginTop": "10px", "fontWeight": "600"}))

    return html.Div(children, style=styles["section"])