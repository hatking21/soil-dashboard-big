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
- server-saved moisture thresholds for each plant

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

## Monitoring with the browser closed

`monitor.py` polls Adafruit IO every `CARD_REFRESH_MS` (default five minutes).
It owns CSV logging, watering detection, offline/dry alerts, and the daily
summary. Dash callbacks only display the results. The ESP32 must remain powered
and connected to Wi-Fi; your computer and browser can be off.

Gunicorn starts the monitor with `gunicorn.conf.py`. Use exactly one worker and
one service instance, without preload, to avoid duplicate collectors. Local
`python app.py` also starts it, but stops when that computer/process stops.

### Runtime requirements and verification

This change leaves `render.yaml` and hosting settings unchanged. Continuous
monitoring requires the application process to remain running; it cannot run
while its host is sleeping or powered off. Saved data survives restarts only
when the configured CSV and cache paths use persistent storage.

1. After starting the app, open Settings and save your preferred plant rules
   once. Old browser-only rules are not automatically migrated. All browsers
   now share these rules, and a new page load reads the server copy.
2. Close every dashboard tab for at least two polling intervals. Reopen it and
   verify recent CSV timestamps; use a safe temporary dry threshold to test an
   ntfy alert while the page is closed, then restore it.

Notification transition flags and the daily-summary date are saved on disk so
normal restarts do not repeat already delivered alerts. Failed/rate-limited
alerts are retried next cycle. A crash between sending and saving can still
repeat an alert. Startup begins with current feed values, not a backfill of
readings missed during downtime; watering detection needs consecutive samples.
History charts still load on demand from Adafruit IO.

If you prefer no cloud hosting charge, run this process as a boot-time service
on an existing always-on Raspberry Pi instead; it still needs power, Internet,
and persistent paths configured via the environment variables above.

Validation: `python -m unittest -v test_monitor`. Tests mock external services;
real Adafruit/ntfy credentials are not needed.

## Learn watering thresholds during normal care

In Settings, use **Teach this pot** for each plant:

1. Leave the probe at a consistent depth and position. When the pot reaches
   the point where you normally water (check the soil or pot weight), select
   **Mark ready to water** before watering. Do not deliberately stress the plant.
2. Water normally and let excess water drain. After three steady feed updates,
   select **Mark watered & drained**. With five-minute updates, sampling takes
   about 10–15 minutes without any further interaction.
3. Review the suggested values, then select **Apply suggested thresholds**.
   This affects only that plant. Manual thresholds remain available.

Each mark uses the median of three distinct samples from the preceding
30 minutes. Samples for the second mark must be newer than the first mark.
Cached API fallbacks, missing/invalid values and duplicate timestamps do not
add samples. Stale samples and spreads above five percentage points block
capture. A wet/dry span below five points, including a reversed span, blocks
application and suggests checking placement or ESP32 calibration.

The ready-to-water value becomes the dry threshold; the watered-and-drained
value becomes the upper reference. The lower ideal threshold uses a suggested
25% buffer across that span. This is an adjustable starting rule, not a
species-specific ideal range. The reference display includes raw sensor values
when available to help troubleshoot compressed or saturated percentages.

STEMMA readings are capacitive measurements, not measured volumetric water
content. The dashboard currently receives `moisture_pct` from the ESP32; this
workflow learns watering reference points on that existing scale and does not
recalibrate firmware or rewrite historic readings. Adafruit explains the
measurement limitation at
https://learn.adafruit.com/adafruit-stemma-soil-sensor-i2c-capacitive-moisture-sensor/faq.

Use **Clear reference points** and repeat after repotting, moving a probe or
changing firmware calibration. Clearing references also discards the sampling
buffer but leaves applied thresholds unchanged. Samples and reference points
are saved under `CACHE_DIR`; they require persistent storage to survive host
replacement. Notifications stay paused independently of this feature.

Validation: `python -m unittest -v test_dashboard test_monitor test_calibration`.
