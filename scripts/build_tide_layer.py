#!/usr/bin/env python3
"""MAPLAYER-TIDE-1: build the private tide-prediction layer file for the map test page.

Reads NOAA CO-OPS tide predictions (high/low tables, MLLW, feet) for the CO-OPS prediction stations
inside the chosen coastal sectors and writes one JSON file under var/ (git-ignored, never published):

    var/tide/tide-layer-<name>.json

The map style test page (bathy-deep-test.html?tide=1, with tide-layer.js) draws it.

Sectors come from catalog/coastal-sectors.json (latitude bands), so another sector plugs in with
`--sectors <id>[,<id>...] --name <name>` and no code change.

What the file is, and is not (these words are copied to the page and the README):
  * PREDICTIONS from harmonic constants (or offsets from a reference station), not observations;
  * water-level high/low TABLES at points. CO-OPS publishes no tidal-current predictions for this
    coast, so the layer shows rising or falling water, not current direction or speed;
  * NOT FOR NAVIGATION.

Usage:
    python3 scripts/build_tide_layer.py --name central-coast \
        --sectors pigeon-monterey,monterey-sur,big-sur,sur-san-simeon,cambria-morro,morro-conception
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
STATIONS_URL = 'https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions'
DATA_URL = 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'
CENTRAL_COAST = 'pigeon-monterey,monterey-sur,big-sur,sur-san-simeon,cambria-morro,morro-conception'
DEFAULT_LON = (-123.0, -119.4)      # central coast (the default sectors)
CALIFORNIA_LON = (-125.0, -117.0)   # any sector outside the central coast: whole California outer coast
NAME_RE = re.compile(r'^[a-z0-9-]+$')   # same shape scripts/client-build.mjs keeps unpublished
APPLICATION = 'skippercast-maplayer-tide-1'
SCHEMA = 'skippercast.tide-layer.v1'
LABELS = {
    'kind': 'PREDICTION (not an observation)',
    'shows': 'rising or falling water level at tide stations; not current direction or speed',
    'navigation': 'NOT FOR NAVIGATION',
}


def sector_bounds(sectors_file, ids):
    """Latitude bands of the named sectors, from catalog/coastal-sectors.json."""
    data = json.loads(Path(sectors_file).read_text())
    by_id = {s['id']: s for s in data['sectors']}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit('unknown sector id(s): ' + ', '.join(missing))
    return [(i, by_id[i]['latitude'][0], by_id[i]['latitude'][1]) for i in ids]


def default_lon(ids):
    """Longitude window for the chosen sectors: central-coast bounds only when every sector is central."""
    return DEFAULT_LON if set(ids) <= set(CENTRAL_COAST.split(',')) else CALIFORNIA_LON


def layer_name(value):
    if not NAME_RE.match(value):
        raise argparse.ArgumentTypeError('--name must be lowercase letters, digits and hyphens only')
    return value


def select_stations(stations, bands, lon_range=DEFAULT_LON):
    """CO-OPS prediction stations whose point falls in a sector band (south edge inclusive)."""
    out = []
    for s in stations:
        lat, lon = s.get('lat'), s.get('lng')
        if lat is None or lon is None or not lon_range[0] <= lon <= lon_range[1]:
            continue
        for sector, lo, hi in bands:
            if lo <= lat < hi:
                out.append({'id': str(s['id']), 'name': s['name'], 'lat': lat, 'lon': lon,
                            'kind': 'harmonic' if s.get('type') == 'R' else 'subordinate',
                            'sector': sector})
                break
    return sorted(out, key=lambda s: -s['lat'])


def parse_extremes(payload):
    """CO-OPS `predictions` (interval=hilo, time_zone=gmt) -> [{'t': ISO UTC, 'type': 'H'|'L', 'v': ft}]."""
    if 'error' in payload:
        raise ValueError(payload['error'].get('message', 'CO-OPS error'))
    out = []
    for row in payload.get('predictions', []):
        when = dt.datetime.strptime(row['t'], '%Y-%m-%d %H:%M').replace(tzinfo=dt.timezone.utc)
        if row['type'] not in ('H', 'L'):
            raise ValueError('unexpected extreme type ' + repr(row['type']))
        out.append({'t': when.strftime('%Y-%m-%dT%H:%MZ'), 'type': row['type'], 'v': round(float(row['v']), 3)})
    out.sort(key=lambda r: r['t'])
    for a, b in zip(out, out[1:]):
        if a['type'] == b['type']:   # a tide table alternates; two highs in a row means a missing row
            raise ValueError('extremes do not alternate at ' + b['t'])
    return out


def http_json(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': APPLICATION})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as exc:   # network flake: retry, then fail loudly
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f'fetch failed: {url}: {last}')


def predictions_url(station_id, begin, end):
    q = {'product': 'predictions', 'station': station_id, 'begin_date': begin.strftime('%Y%m%d'),
         'end_date': end.strftime('%Y%m%d'), 'interval': 'hilo', 'datum': 'MLLW', 'units': 'english',
         'time_zone': 'gmt', 'format': 'json', 'application': APPLICATION}
    return DATA_URL + '?' + urllib.parse.urlencode(q)


def build(sectors_file, ids, name, now, days, fetch=http_json, lon_range=None, pause=0.2):
    lon_range = lon_range or default_lon(ids)
    bands = sector_bounds(sectors_file, ids)
    listing = fetch(STATIONS_URL)
    chosen = select_stations(listing['stations'], bands, lon_range)
    begin = (now - dt.timedelta(days=1)).date()
    end = (now + dt.timedelta(days=days)).date()
    stations, failed = [], []
    for st in chosen:
        try:
            extremes = parse_extremes(fetch(predictions_url(st['id'], begin, end)))
            if len(extremes) < 4:
                raise ValueError('fewer than 4 extremes returned')
        except (ValueError, RuntimeError, KeyError) as exc:
            failed.append({'id': st['id'], 'name': st['name'], 'reason': str(exc)})
            continue
        stations.append(dict(st, extremes=extremes))
        time.sleep(pause)
    if not stations:
        raise SystemExit('no station returned predictions; nothing written')
    return {
        'schema': SCHEMA, 'name': name, 'sectors': list(ids), 'labels': LABELS,
        'fetched_at': now.strftime('%Y-%m-%dT%H:%MZ'),
        'window': {'begin': begin.isoformat(), 'end': end.isoformat(), 'time_zone': 'UTC'},
        'datum': 'MLLW', 'units': 'ft',
        'source': {'name': 'NOAA CO-OPS tide predictions (hilo)', 'station_list': STATIONS_URL,
                   'data': DATA_URL + '?product=predictions&interval=hilo&datum=MLLW'},
        'stations': stations, 'failed': failed,
    }


def write_private(doc, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix('.part')
    tmp.write_text(json.dumps(doc, indent=1) + '\n')
    os.replace(tmp, out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--name', default='central-coast', type=layer_name, help='lowercase letters, digits, hyphens')
    ap.add_argument('--sectors', default=CENTRAL_COAST, help='ids from catalog/coastal-sectors.json')
    ap.add_argument('--lon-min', type=float, help='override the longitude window (west edge)')
    ap.add_argument('--lon-max', type=float, help='override the longitude window (east edge)')
    ap.add_argument('--days', type=int, default=8, help='days ahead (the app fetches 8)')
    ap.add_argument('--output', help='default var/tide/tide-layer-<name>.json')
    args = ap.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    ids = args.sectors.split(',')
    lon = default_lon(ids)
    lon = (lon[0] if args.lon_min is None else args.lon_min, lon[1] if args.lon_max is None else args.lon_max)
    doc = build(ROOT / 'catalog' / 'coastal-sectors.json', ids, args.name, now, args.days, lon_range=lon)
    out = args.output or ROOT / 'var' / 'tide' / f'tide-layer-{args.name}.json'
    write_private(doc, out)
    print(f'{len(doc["stations"])} stations, {len(doc["failed"])} failed -> {out}')
    for f in doc['failed']:
        print('  failed', f['id'], f['name'], f['reason'], file=sys.stderr)


if __name__ == '__main__':
    main()
