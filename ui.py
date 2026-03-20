from dash import dcc, html

from config import (
    CSV_RETENTION_DAYS,
    FEEDS,
    SENSOR_OFFLINE_MINUTES,
    TEMP_F_MAX,
    WATERING_JUMP_THRESHOLD,
)
from data_layer import get_csv_last_write_time, get_csv_row_count, last_csv_status
from styles import theme_styles


DARK = True


def moisture_status_key(moisture, rules, offline=False):
    if offline:
        return "offline"
    if moisture is None:
        return "nodata"
    if moisture < rules["dry"]:
        return "dry"
    if moisture < rules["ideal_low"]:
        return "check"
    if moisture <= rules["ideal_high"]:
        return "good"
    return "wet"


def moisture_colors(moisture, rules, dark=True, offline=False):
    styles = theme_styles(True)
    key = moisture_status_key(moisture, rules, offline=offline)

    label_map = {
        "offline": "Sensor offline",
        "nodata": "No data",
        "dry": "Water now",
        "check": "Check soon",
        "good": "Moisture looks good",
        "wet": "Wet / hold off",
    }

    return (
        label_map[key],
        styles["status_border"][key],
        styles["status_bg"][key],
    )


def recommendation_pill(label, moisture, rules, dark=True, offline=False):
    styles = theme_styles(True)
    key = moisture_status_key(moisture, rules, offline=offline)

    return html.Div(
        label,
        style={
            "display": "inline-block",
            "padding": "10px 14px",
            "borderRadius": "999px",
            "backgroundColor": styles["status_pill_bg"][key],
            "color": styles["status_pill_text"][key],
            "fontWeight": "700",
            "fontSize": "0.95rem",
            "lineHeight": "1.1",
            "border": f"1px solid {styles['status_border'][key]}",
            "boxShadow": "0 2px 10px rgba(0,0,0,0.12)",
        },
    )


def make_card_shell(plant, dark=True):
    styles = theme_styles(True)
    return html.Div(id=f"card-{plant}", style=styles["card_shell"])


def build_moisture_bar(moisture, color, dark=True):
    styles = theme_styles(True)
    safe = max(0, min(100, moisture))

    return html.Div(
        [
            html.Div("Moisture level", style={"fontSize": "0.85rem", "marginBottom": "6px"}),
            html.Div(
                [
                    html.Div(
                        style={
                            "width": f"{safe}%",
                            "height": "100%",
                            "background": color,
                            "borderRadius": "999px",
                        }
                    )
                ],
                style={
                    "height": "12px",
                    "backgroundColor": styles["bar_track"],
                    "borderRadius": "999px",
                    "overflow": "hidden",
                },
            ),
        ],
        style={"marginBottom": "14px"},
    )


def build_health_panel(health_state, used_fallback, dark=True, show_details=False):
    styles = theme_styles(True)

    def pill(label, ok):
        return html.Span(
            f"{label}: {'OK' if ok else 'Issue'}",
            style={
                **styles["chip"],
                "color": styles["status_border"]["good"] if ok else styles["status_border"]["dry"],
            },
        )

    items = [
        pill("Adafruit", health_state["adafruit_ok"]),
        pill("CSV", health_state["csv_ok"]),
        pill("Water log", health_state["watering_log_ok"]),
        html.Span(
            f"Last successful fetch: {health_state.get('last_successful_fetch', 'Never')}",
            style=styles["chip"],
        ),
    ]

    if show_details:
        for label, ok in health_state.get("startup_checks", []):
            items.append(
                html.Span(
                    f"{label}: {'OK' if ok else 'Missing'}",
                    style={
                        **styles["chip"],
                        "color": styles["status_border"]["good"] if ok else styles["status_border"]["dry"],
                    },
                )
            )

    if used_fallback:
        items.append(
            html.Span(
                "Using last good data",
                style={**styles["chip"], "color": styles["status_border"]["check"]},
            )
        )

    if health_state.get("last_error"):
        items.append(
            html.Div(
                f"Last error: {health_state['last_error']}",
                style={"fontSize": "0.9rem", "color": styles["subtext"]},
            )
        )

    return html.Div(items, style={**styles["section"], "marginBottom": "16px"})


def build_settings_panel(rules_dict, dark=True, health_state_data=None, used_fallback=False):
    styles = theme_styles(True)

    input_style = {
        "width": "100%",
        "padding": "10px",
        "borderRadius": "10px",
        "border": f"1px solid {styles['border']}",
        "backgroundColor": styles["input_bg"],
        "color": styles["input_text"],
    }

    health_state_data = health_state_data or {}

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
            ]
        ),
        html.P(f"CSV last write: {get_csv_last_write_time()}", style={"color": styles["subtext"]}),
        html.P(f"CSV status: {last_csv_status}", style={"fontWeight": "600"}),
        html.Div(
            [
                html.H4("Startup / service status", style={"marginTop": "6px", "marginBottom": "10px"}),
                build_health_panel(health_state_data, used_fallback, dark=True, show_details=True),
            ],
            style={"marginBottom": "14px"},
        ),
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
                                        style=input_style,
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
                                        style=input_style,
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
                                        style=input_style,
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
                html.Button(
                    "Save Rules",
                    id="save-rules-button",
                    n_clicks=0,
                    style={**styles["button"], "marginRight": "12px"},
                ),
                html.Button(
                    "Send ntfy Test",
                    id="ntfy-test-button",
                    n_clicks=0,
                    style={**styles["button"], "marginRight": "12px"},
                ),
                html.A(
                    "Download CSV",
                    href="/download-csv",
                    target="_blank",
                    style={
                        **styles["button"],
                        "display": "inline-block",
                        "textDecoration": "none",
                    },
                ),
            ]
        )
    )

    children.append(html.Div(id="save-rules-status", style={"marginTop": "10px", "fontWeight": "600"}))
    children.append(html.Div(id="ntfy-test-status", style={"marginTop": "10px", "fontWeight": "600"}))

    return html.Div(children, style=styles["section"])
