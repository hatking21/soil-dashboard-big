def theme_styles(_dark: bool = True):
    page_bg = "#071224"
    panel_bg = "rgba(10, 20, 38, 0.94)"
    text = "#eef4fb"
    subtext = "#a7b4c6"
    border = "rgba(148, 163, 184, 0.18)"

    card_shell_bg = "#0b1628"
    chip_bg = "#162235"
    plot_bg = "#0b1628"
    input_bg = "#0f1c31"
    input_text = "#eef4fb"

    header_grad = "linear-gradient(135deg, #16645a 0%, #235c8a 100%)"

    tab_bg = "#12233b"
    tab_selected = "#27486d"

    button_bg = "#162235"
    button_text = "#eef4fb"
    button_primary_bg = "#1d3557"
    button_primary_text = "#f8fbff"
    button_primary_border = "#4ea3ff"

    range_button_bg = "#12233b"
    range_button_text = "#dce9f6"
    range_button_border = "#355b87"
    range_button_active_bg = "#1d3557"
    range_button_active_text = "#ffffff"
    range_button_active_border = "#4ea3ff"

    status_bg = {
        "dry": "#3a1318",
        "check": "#3a2710",
        "good": "#113222",
        "wet": "#112d3b",
        "offline": "#1d2633",
        "nodata": "#182231",
    }
    status_border = {
        "dry": "#ff6b6b",
        "check": "#ffb347",
        "good": "#33d17a",
        "wet": "#4db8ff",
        "offline": "#93a4b8",
        "nodata": "#66788f",
    }

    status_pill_bg = {
        "dry": "#5a1d24",
        "check": "#5a3b12",
        "good": "#17492f",
        "wet": "#163f55",
        "offline": "#2a3442",
        "nodata": "#243041",
    }
    status_pill_text = {
        "dry": "#ff9a9a",
        "check": "#ffd089",
        "good": "#7ff0b2",
        "wet": "#8fd8ff",
        "offline": "#c2ccd8",
        "nodata": "#c2ccd8",
    }

    bar_track = "#24354d"

    return {
        "page": {
            "fontFamily": "Arial, sans-serif",
            "background": page_bg,
            "minHeight": "100vh",
            "padding": "0",
            "color": text,
        },
        "container": {
            "maxWidth": "1280px",
            "margin": "0 auto",
            "padding": "24px",
            "boxSizing": "border-box",
        },
        "header": {
            "background": header_grad,
            "color": "white",
            "borderRadius": "20px",
            "padding": "24px 26px",
            "boxShadow": "0 10px 28px rgba(0,0,0,0.18)",
            "marginBottom": "18px",
        },
        "section": {
            "backgroundColor": panel_bg,
            "backdropFilter": "blur(6px)",
            "border": f"1px solid {border}",
            "borderRadius": "18px",
            "padding": "16px",
            "boxShadow": "0 6px 20px rgba(0,0,0,0.08)",
        },
        "card_shell": {
            "width": "272px",
            "borderRadius": "18px",
            "backgroundColor": card_shell_bg,
            "boxShadow": "0 10px 24px rgba(0,0,0,0.12)",
            "border": f"1px solid {border}",
            "overflow": "hidden",
        },
        "button": {
            "padding": "10px 16px",
            "borderRadius": "12px",
            "border": f"1px solid {border}",
            "cursor": "pointer",
            "backgroundColor": button_bg,
            "color": button_text,
            "fontWeight": "600",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.08)",
        },
        "button_primary": {
            "padding": "10px 16px",
            "borderRadius": "12px",
            "border": f"1px solid {button_primary_border}",
            "cursor": "pointer",
            "backgroundColor": button_primary_bg,
            "color": button_primary_text,
            "fontWeight": "700",
            "boxShadow": "0 6px 18px rgba(0,0,0,0.18)",
        },
        "range_button": {
            "padding": "10px 16px",
            "borderRadius": "12px",
            "border": f"1px solid {range_button_border}",
            "cursor": "pointer",
            "backgroundColor": range_button_bg,
            "color": range_button_text,
            "fontWeight": "700",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.08)",
        },
        "range_button_active": {
            "padding": "10px 16px",
            "borderRadius": "12px",
            "border": f"1px solid {range_button_active_border}",
            "cursor": "pointer",
            "backgroundColor": range_button_active_bg,
            "color": range_button_active_text,
            "fontWeight": "700",
            "boxShadow": "0 6px 18px rgba(0,0,0,0.18)",
        },
        "chip": {
            "display": "inline-block",
            "padding": "10px 14px",
            "borderRadius": "999px",
            "backgroundColor": chip_bg,
            "border": f"1px solid {border}",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.06)",
            "fontSize": "0.95rem",
            "marginRight": "10px",
            "marginBottom": "10px",
            "color": text,
        },
        "tab": {
            "padding": "12px 16px",
            "fontWeight": "600",
            "backgroundColor": tab_bg,
            "color": text,
            "border": f"1px solid {border}",
        },
        "tab_selected": {
            "padding": "12px 16px",
            "fontWeight": "700",
            "backgroundColor": tab_selected,
            "color": text,
            "border": f"1px solid {border}",
        },
        "subtext": subtext,
        "text": text,
        "plot_bg": plot_bg,
        "input_bg": input_bg,
        "input_text": input_text,
        "border": border,
        "status_bg": status_bg,
        "status_border": status_border,
        "status_pill_bg": status_pill_bg,
        "status_pill_text": status_pill_text,
        "bar_track": bar_track,
    }
