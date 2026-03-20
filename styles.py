def theme_styles(dark: bool):
    if dark:
        page_bg = "#0b1220"
        panel_bg = "rgba(17, 24, 39, 0.96)"
        text = "#e5edf5"
        subtext = "#9fb0c3"
        border = "rgba(148, 163, 184, 0.22)"

        card_shell_bg = "#111827"
        chip_bg = "#182334"
        plot_bg = "#0f172a"
        input_bg = "#0f172a"
        input_text = "#e5edf5"

        header_grad = "linear-gradient(135deg, #185c47 0%, #1e4f7a 100%)"

        tab_bg = "#132033"
        tab_selected = "#1f3c5c"

        button_bg = "#182334"
        button_hover_bg = "#1d2a3d"
        button_primary_bg = "#dbe7f3"
        button_primary_text = "#0f172a"

        status_bg = {
            "dry": "#311414",
            "check": "#35240f",
            "good": "#10281d",
            "wet": "#0f2431",
            "offline": "#1c2430",
            "nodata": "#161f2b",
        }
        status_border = {
            "dry": "#f87171",
            "check": "#f59e0b",
            "good": "#34d399",
            "wet": "#38bdf8",
            "offline": "#94a3b8",
            "nodata": "#64748b",
        }
        bar_track = "#223044"

    else:
        page_bg = "linear-gradient(180deg, #f5fbf7 0%, #eef4f8 100%)"
        panel_bg = "rgba(255,255,255,0.86)"
        text = "#1f2b24"
        subtext = "#5b6b63"
        border = "rgba(0,0,0,0.06)"

        card_shell_bg = "#ffffff"
        chip_bg = "#ffffff"
        plot_bg = "#ffffff"
        input_bg = "#ffffff"
        input_text = "#1f2b24"

        header_grad = "linear-gradient(135deg, #2e7d5a 0%, #4e9c78 100%)"

        tab_bg = "#f7faf8"
        tab_selected = "#dcefe4"

        button_bg = "#ffffff"
        button_hover_bg = "#f7faf8"
        button_primary_bg = "rgba(255,255,255,0.96)"
        button_primary_text = "#1f2b24"

        status_bg = {
            "dry": "#fff1ef",
            "check": "#fff7eb",
            "good": "#f2fff7",
            "wet": "#eef9ff",
            "offline": "#f1f5f9",
            "nodata": "#f5f5f5",
        }
        status_border = {
            "dry": "#c0392b",
            "check": "#d9822b",
            "good": "#2e8b57",
            "wet": "#2f7ea1",
            "offline": "#6b7280",
            "nodata": "#cccccc",
        }
        bar_track = "#e9efeb"

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
            "borderRadius": "10px",
            "border": f"1px solid {border}",
            "cursor": "pointer",
            "backgroundColor": button_bg,
            "color": text,
            "fontWeight": "600",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.08)",
        },
        "button_primary": {
            "padding": "10px 16px",
            "borderRadius": "10px",
            "border": "none",
            "cursor": "pointer",
            "backgroundColor": button_primary_bg,
            "color": button_primary_text,
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
        "bar_track": bar_track,
        "button_hover_bg": button_hover_bg,
    }
