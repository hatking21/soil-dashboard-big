import plotly.graph_objects as go

from styles import theme_styles


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


def style_figure(fig, title, yaxis_title, dark=False, yaxis_range=None):
    styles = theme_styles(dark)
    fig.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        xaxis_title="Time",
        yaxis_title=yaxis_title,
        template="plotly_white",
        height=460,
        paper_bgcolor=styles["plot_bg"],
        plot_bgcolor=styles["plot_bg"],
        font={"color": styles["text"]},
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
    if yaxis_range is not None:
        fig.update_yaxes(range=yaxis_range)
    return fig


def build_figures(histories, rules_dict, label_suffix="", dark=False, temp_max=120.0):
    moisture_fig = go.Figure()
    temp_fig = go.Figure()

    all_moisture = []
    all_temp = []
    band_added = False

    for plant, hist in histories.items():
        times = hist.get("times", [])
        moisture = hist.get("moisture", [])
        temp = hist.get("temp", [])

        if times:
            moisture_fig.add_trace(go.Scatter(x=times, y=moisture, mode="lines", name=plant))
            temp_fig.add_trace(go.Scatter(x=times, y=temp, mode="lines", name=plant))
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
    temp_range = get_axis_range(all_temp, pad=5, min_floor=0, max_cap=temp_max)

    moisture_fig = style_figure(
        moisture_fig,
        f"{label_suffix} Moisture".strip(),
        "Moisture (%)",
        dark=dark,
        yaxis_range=moisture_range,
    )
    temp_fig = style_figure(
        temp_fig,
        f"{label_suffix} Temperature".strip(),
        "Temperature (°F)",
        dark=dark,
        yaxis_range=temp_range,
    )
    return moisture_fig, temp_fig