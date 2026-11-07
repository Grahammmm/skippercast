#!/usr/bin/env python3
"""Fetch the newest HF-radar (IOOS HFRNet) surface-current grid for one sector into var/.

    python research/scripts/map_style/fetch_hfr_currents.py --sector central-coast            # 6 km, newest populated hour
    python research/scripts/map_style/fetch_hfr_currents.py --sector central-coast --resolution 1

MAPLAYER-CURRENT-1. Writes `var/currents/hfr-<sector>-<res>km.json`: a private research output for the
map-style test page (research/scripts/map_style/currents-test.html). Nothing here is published and the
live app does not read it. A sector is a lon/lat box in `research/scripts/map_style/current_sectors.json`;
another coast plugs in by adding a box there.

Source: NOAA/IOOS HFRNet US West Coast, hourly total vectors, via the NDBC THREDDS/OPeNDAP server the app's
own pipeline already reads (src/skippercast/pipeline/ocean.py). The same quality rules apply: no fill
value, HDOP <= 2, between 2 and 20 contributing radars, speed <= 5 m/s. Gaps stay gaps: nothing is
interpolated or extrapolated across a missing cell. Standard library only.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
SECTORS = Path(__file__).with_name('current_sectors.json')
OUT_DIR = ROOT / 'var/currents'
HOST = 'https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_{res}km'
FILL = -32767
SCALE = 0.01
MAX_SPEED = 5.0       # m/s, a larger vector is a processing error
MAX_HDOP = 2.0
LOOKBACK = 6          # hours examined, newest first
RULE = '---------------------------------------------'
SCHEMA = 'skippercast.hfr-currents.v1'


def get(url, timeout=120):
    request = Request(url, headers={'User-Agent': 'skippercast-research/1 (map style test)'})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode('utf-8', 'replace')


def dap_arrays(text):
    """Numeric part of a DAP2 ASCII response as {name: [floats]}; fill values are kept."""
    if RULE not in text:
        raise ValueError('Expected DAP ASCII response')
    arrays, key = {}, None
    for line in text.split(RULE, 1)[1].splitlines():
        line = line.strip()
        header = re.fullmatch(r'([\w.]+)((?:\[\d+\])+)', line)
        if header:
            key = header[1]
            arrays[key] = []
            continue
        if not line or key is None:
            continue
        line = re.sub(r'^(?:\[\d+\])+\s*,?\s*', '', line)
        arrays[key].extend(float(x) for x in re.split(r'\s*,\s*', line) if x)
    return arrays


def span(values, low, high):
    """First and last index of the sorted axis `values` inside [low, high]."""
    inside = [i for i, v in enumerate(values) if low <= v <= high]
    if not inside:
        raise ValueError('Dataset has no coordinate coverage in the sector box')
    return inside[0], inside[-1]


def keep_cell(u, v, hdop, sites):
    """The pipeline's quality rule for one cell (raw integers as stored)."""
    if FILL in (u, v) or not math.isfinite(hdop) or hdop < 0 or hdop * SCALE > MAX_HDOP:
        return False
    if not 2 <= sites <= 20:
        return False
    return math.hypot(u * SCALE, v * SCALE) <= MAX_SPEED


def frame_grid(arrays, step, rows, cols):
    """One time step as u/v grids in m/s (None where the cell fails the rule) and a count."""
    n = rows * cols
    u = [[None] * cols for _ in range(rows)]
    v = [[None] * cols for _ in range(rows)]
    sites = [[0] * cols for _ in range(rows)]
    valid = 0
    for y in range(rows):
        for x in range(cols):
            i = step * n + y * cols + x
            ru, rv = arrays['u'][i], arrays['v'][i]
            if keep_cell(ru, rv, arrays['hdop'][i], arrays['number_of_sites'][i]):
                u[y][x] = round(ru * SCALE, 2)
                v[y][x] = round(rv * SCALE, 2)
                sites[y][x] = int(arrays['number_of_sites'][i])
                valid += 1
    return u, v, sites, valid


def pick_frame(arrays, times, rows, cols, minimum):
    """Newest hour with at least `minimum` usable cells. Returns (index, u, v, sites, valid) or None."""
    for step in range(len(times) - 1, -1, -1):
        u, v, sites, valid = frame_grid(arrays, step, rows, cols)
        if valid >= minimum:
            return step, u, v, sites, valid
    return None


def iso(epoch):
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def build(sector_id, sector, resolution, fetch=get, now=None, minimum=None):
    base = HOST.format(res=resolution)
    dds, das = fetch(base + '.dds'), fetch(base + '.das')
    sizes = {k: int(v) for k, v in re.findall(r'\[(time|lat|lon) = (\d+)\]', dds)}
    if not all(k in sizes for k in ('time', 'lat', 'lon')):
        raise ValueError('Unknown HFR axes')
    if '1970-01-01' not in das or 'scale_factor 0.01' not in das or '_FillValue -32767' not in das:
        raise ValueError('HFR units/packing contract changed')
    first = max(0, sizes['time'] - LOOKBACK)
    last = sizes['time'] - 1

    def query(q):
        return dap_arrays(fetch(base + '.ascii?' + quote(q, safe=',._:[]')))

    axes = query(f'time[{first}:1:{last}],lat,lon')
    west, south, east, north = sector['bounds']
    y0, y1 = span(axes['lat'], south, north)
    x0, x1 = span(axes['lon'], west, east)
    sel = f'[{first}:1:{last}][{y0}:1:{y1}][{x0}:1:{x1}]'
    data = query(','.join(k + sel for k in ('u', 'v', 'hdop', 'number_of_sites')))
    arrays = {k: data.get(k + '.' + k, data.get(k)) for k in ('u', 'v', 'hdop', 'number_of_sites')}
    lats, lons = axes['lat'][y0:y1 + 1], axes['lon'][x0:x1 + 1]
    rows, cols = len(lats), len(lons)
    times = axes['time']
    if any(a is None or len(a) != rows * cols * len(times) for a in arrays.values()):
        raise ValueError('Incomplete HFR vectors')
    picked = pick_frame(arrays, times, rows, cols, minimum=minimum or max(10, rows * cols // 50))
    if picked is None:
        raise ValueError('No hour in the lookback window has usable cells in this sector')
    step, u, v, sites, valid = picked
    now = now or datetime.now(timezone.utc)
    return {
        'schema': SCHEMA, 'sector': sector_id, 'name': sector.get('name', sector_id),
        'bounds': sector['bounds'], 'resolution_km': resolution,
        'provider': 'NOAA / IOOS HFRNet (hourly total vectors, US West Coast)',
        'source_url': base + '.html', 'retrieved_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'sample_at': iso(times[step]), 'latest_grid_time': iso(times[-1]), 'hours_behind_latest': len(times) - 1 - step,
        'lats': [round(x, 5) for x in lats], 'lons': [round(x, 5) for x in lons],
        'u': u, 'v': v, 'sites': sites, 'unit': 'm s-1', 'u_positive': 'east', 'v_positive': 'north',
        'valid_cells': valid, 'total_cells': rows * cols,
        'quality': f'no fill value; HDOP <= {MAX_HDOP:g}; 2 to 20 radars; speed <= {MAX_SPEED:g} m/s',
        'limitations': 'Observed near-surface flow (top ~2.4 m, hourly mean), radar footprint only; gaps are kept, '
                       'nothing is filled. Not boat drift, not a bottom current, not tide predictions. '
                       'NOT FOR NAVIGATION.',
    }


def write(doc, out_dir=OUT_DIR):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"hfr-{doc['sector']}-{doc['resolution_km']}km.json"
    path.write_text(json.dumps(doc, separators=(',', ':')) + '\n')
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or '').split('\n')[0])
    ap.add_argument('--sector', default='central-coast')
    ap.add_argument('--resolution', type=int, choices=(1, 6), default=6)
    ap.add_argument('--out-dir', type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    sectors = json.loads(SECTORS.read_text())
    if args.sector not in sectors:
        sys.exit(f'unknown sector {args.sector!r}; known: {", ".join(sorted(sectors))}')
    doc = build(args.sector, sectors[args.sector], args.resolution)
    path = write(doc, args.out_dir)
    print(f"{path}  sample_at={doc['sample_at']}  valid={doc['valid_cells']}/{doc['total_cells']}  "
          f"grid {len(doc['lats'])}x{len(doc['lons'])}")


if __name__ == '__main__':
    main()
