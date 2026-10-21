"""Learn watering reference points from normal care, not volumetric moisture."""
import json
import math
import os
import threading
from datetime import datetime, timezone, timedelta
from statistics import median

from config import CACHE_DIR, CARD_REFRESH_MS, FEEDS

_lock = threading.RLock()


def _read():
    try:
        with open(os.path.join(CACHE_DIR, 'watering_reference.json'), encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _write(state):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, 'watering_reference.json')
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(state, f, allow_nan=False)
    os.replace(path + '.tmp', path)


def _timestamp(text):
    ts = datetime.fromisoformat(text)
    if ts.tzinfo is None:
        raise ValueError('Reading must have a timezone.')
    return ts


def record_snapshot(snapshot, fallback=False, now=None):
    if fallback:
        return
    now = now or datetime.now(timezone.utc)
    with _lock:
        state = _read()
        for plant in FEEDS:
            row = snapshot.get(plant) or {}
            try:
                ts = _timestamp(row['timestamp'])
                value = float(row['moisture'])
                if not math.isfinite(value) or not 0 <= value <= 100:
                    continue
                if not timedelta(0) <= now - ts <= timedelta(minutes=30):
                    continue
                raw = row.get('raw')
                raw = float(raw) if raw is not None else None
                if raw is not None and not math.isfinite(raw):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            entry = state.setdefault(plant, {})
            samples = [s for s in entry.get('samples', [])
                       if now - _timestamp(s['timestamp']) <= timedelta(minutes=30)]
            if not any(s['timestamp'] == row['timestamp'] for s in samples):
                samples.append({'timestamp': row['timestamp'], 'moisture': value, 'raw': raw})
            entry['samples'] = sorted(samples, key=lambda s: _timestamp(s['timestamp']))[-12:]
        _write(state)


def references(plant):
    with _lock:
        entry = _read().get(plant, {})
        return {k: entry[k] for k in ('ready', 'watered') if k in entry}


def capture(plant, kind, now=None):
    if plant not in FEEDS or kind not in ('ready', 'watered'):
        raise ValueError('Choose a plant and a reference point.')
    now = now or datetime.now(timezone.utc)
    with _lock:
        state = _read()
        entry = state.setdefault(plant, {})
        other = entry.get('watered' if kind == 'ready' else 'ready')
        samples = [s for s in entry.get('samples', [])
                   if timedelta(0) <= now - _timestamp(s['timestamp']) <= timedelta(minutes=30)
                   and (not other or _timestamp(s['timestamp']) > _timestamp(other['captured_at']))]
        if len(samples) < 3:
            raise ValueError('Waiting for 3 distinct recent readings. Leave the sensor in place; retry after a few updates.')
        samples = samples[-3:]
        max_age = timedelta(seconds=max(600, 2 * CARD_REFRESH_MS / 1000))
        if now - _timestamp(samples[-1]['timestamp']) > max_age:
            raise ValueError('Latest reading is stale. Reconnect the ESP32 before capturing.')
        values = [s['moisture'] for s in samples]
        if max(values) - min(values) > 5:
            raise ValueError('Readings are still changing. Wait for 3 steady updates and try again.')
        raw_values = [s['raw'] for s in samples if s.get('raw') is not None]
        point = {'moisture': median(values), 'raw': median(raw_values) if len(raw_values) == 3 else None,
                 'captured_at': now.isoformat(), 'sample_count': 3,
                 'spread': max(values) - min(values)}
        entry[kind] = point
        _write(state)
        return point


def suggested_rules(plant):
    points = references(plant)
    if not all(k in points for k in ('ready', 'watered')):
        raise ValueError('Mark both reference points before applying suggestions.')
    dry, wet = (points[k]['moisture'] for k in ('ready', 'watered'))
    if wet - dry < 5:
        raise ValueError('Watered and ready-to-water readings are too close or reversed. Check sensor placement or ESP32 calibration; thresholds were not changed.')
    # This buffer is a starting suggestion, not a botanical ideal moisture range.
    return {'dry': round(dry, 1), 'ideal_low': round(dry + .25 * (wet - dry), 1),
            'ideal_high': round(wet, 1)}


def reset(plant):
    if plant not in FEEDS:
        raise ValueError('Choose a plant.')
    with _lock:
        state = _read()
        entry = state.setdefault(plant, {})
        entry.pop('ready', None)
        entry.pop('watered', None)
        entry['samples'] = []
        _write(state)
