# soil-dashboard-big

A Dash-based plant soil monitoring dashboard for ESP32 sensor feeds stored in Adafruit IO.

## What it does

This dashboard shows:
- live, weekly, and monthly moisture and temperature trends
- per-plant status cards with watering guidance
- watering event detection based on moisture jumps
- offline sensor detection
- CSV logging and CSV download
- ntfy alerts for dry plants, offline sensors, and a daily summary
- browser-saved moisture thresholds for each plant

## Current dashboard structure

The app is centered around:
- `app.py` for layout, callbacks, stores, and tab rendering
- `data_layer.py` for Adafruit IO fetches, caching, CSV logging, and watering detection
- `charts.py` for Plotly graph creation
- `ui.py` for reusable UI blocks and settings layout
- `config.py` for environment variables and refresh intervals

## Features in this version

This version includes:
- 5-minute live refresh for cards and fast history
- local-time chart rendering
- paginated history fetching for weekly and monthly tabs
- per-card reading age
- plant visibility toggles for charts
- per-tab summary cards with latest / average / min / max values
- plant-aware moisture threshold guidance in chart hover and legend content
- cleaner settings sections for rules, system status, and data/logging

## Environment variables

Important settings are read from environment variables in `config.py`.

Typical ones are:
- `AIO_USERNAME`
- `AIO_KEY`
- `NTFY_TOPIC`
- `NTFY_BASE_URL`
- `LOCAL_TIMEZONE`
- `CARD_REFRESH_MS`
- `HISTORY_FAST_REFRESH_MS_V2`
- `HISTORY_7_REFRESH_MS`
- `HISTORY_30_REFRESH_MS`
- `CSV_LOG_PATH`
- `WATERING_LOG_PATH`
- `CACHE_DIR`
- `TEMP_F_MAX`
- `SENSOR_OFFLINE_MINUTES`

## Local run

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the dashboard:

```bash
python app.py
```

## Deploy notes

This repo is set up for Render using `render.yaml`.

Recommended checks after deploy:
1. confirm the cards update every 5 minutes
2. confirm chart timestamps match your local timezone
3. confirm weekly and monthly tabs show more than the most recent day
4. confirm the chart plant toggle persists in browser storage
5. confirm ntfy test notifications send successfully

## Suggested future improvements

Good next additions would be:
- exporting chart images
- a dedicated watering history tab
- per-plant notification cooldowns
- calibration tools for each sensor
- a compact mobile-first card layout
