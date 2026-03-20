def theme_styles(dark: bool):
    if dark:
        page_bg = "#0f1720"
        panel_bg = "rgba(20,28,38,0.92)"
        text = "#e6edf3"
        subtext = "#a7b4bf"
        border = "rgba(255,255,255,0.08)"
        chip_bg = "#18222d"
        plot_bg = "#111923"
        header_grad = "linear-gradient(135deg, #1f7a5d 0%, #265f84 100%)"
        input_bg = "#111923"
        input_text = "#e6edf3"
    else:
        page_bg = "linear-gradient(180deg, #f5fbf7 0%, #eef4f8 100%)"
        panel_bg = "rgba(255,255,255,0.80)"
        text = "#1f2b24"
        subtext = "#5b6b63"
        border = "rgba(0,0,0,0.06)"
        chip_bg = "#ffffff"
        plot_bg = "#ffffff"
        header_grad = "linear-gradient(135deg, #2e7d5a 0%, #4e9c78 100%)"
        input_bg = "#ffffff"
        input_text = "#1f2b24"

    return {
        "page": {
            "fontFamily": "Arial, sans-serif",
            "background": page_bg,
            "minHeight": "100vh",
            "padding": "24px",
            "color": text,
        },
        "container": {
            "maxWidth": "1280px",
            "margin": "0 auto",
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
            "backdropFilter": "blur(4px)",
            "border": f"1px solid {border}",
            "borderRadius": "18px",
            "padding": "16px",
            "boxShadow": "0 6px 20px rgba(0,0,0,0.05)",
        },
        "card_shell": {
            "width": "272px",
            "borderRadius": "18px",
            "backgroundColor": chip_bg,
            "boxShadow": "0 10px 24px rgba(0,0,0,0.06)",
            "border": f"1px solid {border}",
            "overflow": "hidden",
        },
        "button": {
            "padding": "10px 16px",
            "borderRadius": "10px",
            "border": f"1px solid {border}",
            "cursor": "pointer",
            "backgroundColor": chip_bg,
            "color": text,
            "fontWeight": "600",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.04)",
        },
        "chip": {
            "display": "inline-block",
            "padding": "10px 14px",
            "borderRadius": "999px",
            "backgroundColor": chip_bg,
            "border": f"1px solid {border}",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.04)",
            "fontSize": "0.95rem",
            "marginRight": "10px",
            "marginBottom": "10px",
            "color": text,
        },
        "subtext": subtext,
        "text": text,
        "plot_bg": plot_bg,
        "input_bg": input_bg,
        "input_text": input_text,
        "border": border,
    }