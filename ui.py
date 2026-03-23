import plotly.graph_objects as go

from styles import theme_styles


MOISTURE_SMOOTHING = 0.45
TEMP_SMOOTHING = 1.0


def get_axis_range(values, pad=5, min_floor=0, max_cap=None):
    if not values:
        return None

    vmin = min(values)
    vmax = max(values)
    low = max(min_floor, vmin - pad)
    high = vmax + pad

    if max_cap is not None:
        high = min(max_cap, high)

    if high <= low:
        high = low + 1

    return [low, high]


def style_figure(fig, title, yaxis_title, yaxis_range=None):
    styles = theme_styles(True)
    fig.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        xaxis_title="Time",
        yaxis_title=yaxis_title,
        template="plotly_dark",
        height=460,
        paper_bgcolor=styles["plot_bg"],
        plot_bgcolor=styles["plot_bg"],
        font={"color": styles["text"]},
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")

    if yaxis_range is not None:
        fig.update_yaxes(range=yaxis_range)

    return fig


def add_moisture_guides(fig, plant, rules, color):
    guide_specs = [
        (rules["dry"], "dot", f"{plant} dry"),
        (rules["ideal_low"], "dash", f"{plant} ideal low"),
        (rules["ideal_high"], "dash", f"{plant} ideal high"),
    ]

    for y_value, dash, name in guide_specs:
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                name=name,
                line={"dash": dash, "width": 2, "color": color},
                hoverinfo="skip",
                visible="legendonly",
                legendgroup=plant,
            )
        )
        fig.add_hline(
            y=y_value,
            line_width=1,
            line_dash=dash,
            line_color=color,
            opacity=0.22,
        )


def build_figures(histories, rules_dict, label_suffix="", dark=True, temp_max=120.0):
    moisture_fig = go.Figure()
    temp_fig = go.Figure()
    all_moisture = []
    all_temp = []

    for plant, hist in histories.items():
        times = hist.get("times", [])
        moisture = hist.get("moisture", [])
        temp = hist.get("temp", [])

        if not times:
            continue

        rules = rules_dict.get(plant, {"dry": 20, "ideal_low": 35, "ideal_high": 80})

        moisture_fig.add_trace(
            go.Scatter(
                x=times,
                y=moisture,
                mode="lines",
                name=plant,
                line={"shape": "spline", "smoothing": MOISTURE_SMOOTHING},
                connectgaps=True,
                legendgroup=plant,
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Time: %{x}<br>"
                    "Moisture: %{y:.1f}%<br>"
                    f"Dry below: {rules['dry']:.0f}%<br>"
                    f"Ideal: {rules['ideal_low']:.0f}%–{rules['ideal_high']:.0f}%"
                    "<extra></extra>"
                ),
            )
        )
        color = moisture_fig.data[-1].line.color
        add_moisture_guides(moisture_fig, plant, rules, color)

        temp_fig.add_trace(
            go.Scatter(
                x=times,
                y=temp,
                mode="lines",
                name=plant,
                line={"shape": "spline", "smoothing": TEMP_SMOOTHING},
                connectgaps=True,
                legendgroup=plant,
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Time: %{x}<br>"
                    "Temperature: %{y:.1f}°F"
                    "<extra></extra>"
                ),
            )
        )

        all_moisture.extend(moisture)
        all_temp.extend(temp)

    moisture_range = get_axis_range(all_moisture, pad=5, min_floor=0, max_cap=100)
    temp_range = get_axis_range(all_temp, pad=4, min_floor=0, max_cap=temp_max)

    moisture_fig = style_figure(
        moisture_fig,
        f"{label_suffix} Moisture".strip(),
        "Moisture (%)",
        yaxis_range=moisture_range,
    )
    temp_fig = style_figure(
        temp_fig,
        f"{label_suffix} Temperature".strip(),
        "Temperature (°F)",
        yaxis_range=temp_range,
    )

    return moisture_fig, temp_fig
