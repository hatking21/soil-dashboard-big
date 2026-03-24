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


def add_ideal_band(fig, ideal_low, ideal_high):
    fig.add_hrect(
        y0=ideal_low,
        y1=ideal_high,
        fillcolor="rgba(46,139,87,0.10)",
        line_width=0,
    )


def style_figure(fig, title, yaxis_title, yaxis_range=None, label_suffix=""):
    styles = theme_styles(True)

    weekly_or_monthly = "Weekly" in label_suffix or "Monthly" in label_suffix

    fig.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        xaxis_title="Time (local)",
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

    if weekly_or_monthly:
        fig.update_xaxes(
            showgrid=False,
            tickformat="%b %d\n%I:%M %p",
            hoverformat="%Y-%m-%d %I:%M:%S %p",
        )
    else:
        fig.update_xaxes(
            showgrid=False,
            tickformat="%I:%M %p",
            hoverformat="%Y-%m-%d %I:%M:%S %p",
        )

    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")

    if yaxis_range is not None:
        fig.update_yaxes(range=yaxis_range)

    return fig


def add_no_data_annotation(fig, message="No data available for the selected plants."):
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"size": 16},
        align="center",
    )


def build_figures(histories, rules_dict, label_suffix="", dark=True, temp_max=120.0):
    moisture_fig = go.Figure()
    temp_fig = go.Figure()

    all_moisture = []
    all_temp = []
    band_added = False
    trace_count = 0

    for plant, hist in (histories or {}).items():
        times = hist.get("times", []) or []
        moisture = hist.get("moisture", []) or []
        temp = hist.get("temp", []) or []

        n = min(len(times), len(moisture), len(temp))
        if n <= 0:
            continue

        times = times[:n]
        moisture = moisture[:n]
        temp = temp[:n]

        moisture_fig.add_trace(
            go.Scatter(
                x=times,
                y=moisture,
                mode="lines",
                name=plant,
                line={"shape": "spline", "smoothing": MOISTURE_SMOOTHING},
                connectgaps=True,
            )
        )

        temp_fig.add_trace(
            go.Scatter(
                x=times,
                y=temp,
                mode="lines",
                name=plant,
                line={"shape": "spline", "smoothing": TEMP_SMOOTHING},
                connectgaps=True,
            )
        )

        trace_count += 1
        all_moisture.extend(moisture)
        all_temp.extend(temp)

        if not band_added and plant in rules_dict:
            add_ideal_band(
                moisture_fig,
                rules_dict[plant]["ideal_low"],
                rules_dict[plant]["ideal_high"],
            )
            band_added = True

    moisture_range = get_axis_range(all_moisture, pad=5, min_floor=0, max_cap=100)
    temp_range = get_axis_range(all_temp, pad=4, min_floor=0, max_cap=temp_max)

    moisture_fig = style_figure(
        moisture_fig,
        f"{label_suffix} Moisture".strip(),
        "Moisture (%)",
        yaxis_range=moisture_range,
        label_suffix=label_suffix,
    )
    temp_fig = style_figure(
        temp_fig,
        f"{label_suffix} Temperature".strip(),
        "Temperature (°F)",
        yaxis_range=temp_range,
        label_suffix=label_suffix,
    )

    if trace_count == 0:
        add_no_data_annotation(moisture_fig)
        add_no_data_annotation(temp_fig)

    return moisture_fig, temp_fig
