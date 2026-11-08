#!/usr/bin/env python3
"""PERF-BASELINE-1: a synthetic wind preview for load-cost measurement only (never real data, never published).

Writes var/maplayer-wind-1/wind-preview.json with the same 17 x 13, 0.25-degree grid as the 2026-11-07 GFS crop
(-123..-119, 34..37), a smooth 6-12 m/s north-westerly field and a data time of the current UTC hour, so
wind-test.html draws its particles. Grid size and the base archive decide the load cost, not the values.
Usage (from the repo root): python3 reports/perf/wind_fixture.py
"""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
W, H = 17, 13
u, v = [], []
for j in range(H):
    ur, vr = [], []
    for i in range(W):
        speed = 9 + 3 * math.sin(i / 3) * math.cos(j / 4)
        ang = math.radians(315 + 15 * math.sin((i + j) / 5))   # wind from the NW blows toward the SE
        ur.append(round(speed * math.sin(ang + math.pi), 3))
        vr.append(round(speed * math.cos(ang + math.pi), 3))
    u.append(ur)
    v.append(vr)
doc = {'schema_version': 1, 'source_id': 'noaa-gfs', 'run_time': (now - timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%SZ'),
       'data_time': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'source_url': 'https://example.invalid/perf-baseline-fixture',
       'max_age_hours': 18, 'width': W, 'height': H, 'west': -123.0, 'north': 37.0, 'resolution_degrees': .25,
       'units': 'm/s', 'u': u, 'v': v}
out = ROOT / 'var/maplayer-wind-1/wind-preview.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc) + '\n')
print(out, out.stat().st_size, 'bytes')
