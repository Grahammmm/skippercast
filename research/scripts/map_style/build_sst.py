#!/usr/bin/env python3
"""Offline SST-2 preview from existing sst-analysis tiles; never fetches or publishes.

python research/scripts/map_style/build_sst.py --input var/maplayer-sst-1/morro-bay
Writes only beneath this checkout's ignored var/. No region config is read.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
# layers.py sst(2): turbo(linspace(.04,.96,14)), 15 boundaries at 52..66 F.
COLOURS = ['#3b2f80', '#4661d6', '#448ffe', '#28bceb', '#18e0bd',
           '#3ff68a', '#84ff51', '#bcf534', '#e5d938', '#fcb336',
           '#fb8122', '#ea4e0d', '#ca2a04', '#9b0f01']
BREAK_F_PER_KM = 1.2


def number(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'invalid numeric value: {value!r}')
    return float(value)


def stamp(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('data time must include timezone')
    return t.astimezone(timezone.utc)


def feature(geometry, properties):
    return {'type': 'Feature', 'geometry': geometry, 'properties': properties}


def collection(features):
    return {'type': 'FeatureCollection', 'features': features}


def build(folder, now):
    raw = (folder / 'habitat-dynamics.json').read_bytes()
    meta = json.loads(raw)
    layer = meta['layers']['sst-analysis']
    when = stamp(layer['sample_at'])
    if when > now:
        raise ValueError('future data time')
    resolution = layer['resolution_degrees']
    if len(resolution) != 2:
        raise ValueError('invalid resolution')
    dy, dx = [number(r, .0001, .25) for r in resolution]
    west, south, east, north = meta['bounds']
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError('invalid bounds')
    limit = number(layer['max_age_hours'], .01, 720)
    cells, grid, receipts = {}, {}, []
    tiles = layer['tiles']
    if not 0 < len(tiles) <= 256:
        raise ValueError('unbounded tile list')
    for entry in tiles:
        name = entry['path']
        if not re.fullmatch(r'habitat-tiles/sst-analysis--?\d+--?\d+-[a-f0-9]{16}\.json', name):
            raise ValueError('invalid tile path')
        path = folder / name
        if not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError('tile escaped input directory')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry['sha256']:
            raise ValueError('tile checksum mismatch')
        tile = json.loads(payload)
        if tile['region_id'] != meta['region_id'] or tile['layer_id'] != 'sst-analysis' or tile['resolution_degrees'] != resolution:
            raise ValueError('tile identity/resolution mismatch')
        fields = tile['fields']
        indices = [fields.index(n) for n in ('latitude', 'longitude', 'temperature_c', 'temperature_gradient_c_per_km')]
        frames = [f for f in tile['frames'] if f['time'] == when.timestamp()]
        if len(frames) != 1:
            raise ValueError('tile missing unique matching data time')
        for row in frames[0]['cells']:
            lat, lon, temp, gradient = [row[i] for i in indices]
            lat, lon = number(lat, -90, 90), number(lon, -180, 180)
            if temp is None or not (west <= lon <= east and south <= lat <= north):
                continue
            temp = number(temp, -2, 40)
            gradient = None if gradient is None else number(gradient, 0, 100) * 1.8
            key = (math.floor(lat / dy + 1e-7), math.floor(lon / dx + 1e-7))
            value = (lat, lon, temp, gradient)
            if key in cells and cells[key] != value:
                raise ValueError('conflicting tile overlap')
            cells[key] = value
        receipts.append({'path': name, 'sha256': entry['sha256']})
    if not cells:
        raise ValueError('no valid SST cells')
    polygons = []
    for key, (lat, lon, temp, gradient) in sorted(cells.items()):
        f = temp * 1.8 + 32
        band = max(0, min(13, math.floor(f - 52)))
        w, s, e, n = max(west, lon - dx / 2), max(south, lat - dy / 2), min(east, lon + dx / 2), min(north, lat + dy / 2)
        polygons.append(feature({'type': 'Polygon', 'coordinates': [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
                                {'temperature_f': round(f, 3), 'colour': COLOURS[band]}))
        if gradient is not None:
            grid[key] = (lon, lat, gradient)
    # March the native provider gradient, not an upsampled 10 m illustrative field.
    # Require all four adjacent sea cells: never bridge a missing-data hole.
    segments = []
    for y, x in sorted(grid):
        keys = [(y, x), (y, x + 1), (y + 1, x + 1), (y + 1, x)]
        if not all(k in grid for k in keys):
            continue
        points = [grid[k] for k in keys]
        crossings = []
        for a, b in zip(points, points[1:] + points[:1]):
            if (a[2] < BREAK_F_PER_KM) != (b[2] < BREAK_F_PER_KM):
                t = (BREAK_F_PER_KM - a[2]) / (b[2] - a[2])
                crossings.append([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])])
        if len(crossings) == 2:  # ambiguous saddles are omitted, never invented
            segments.append(feature({'type': 'LineString', 'coordinates': crossings}, {}))
    age = (now - when).total_seconds() / 3600
    return {'schema_version': 1, 'region_id': meta['region_id'], 'data_time': layer['sample_at'],
            'generated_at': now.isoformat(), 'max_age_hours': limit, 'stale': age > limit,
            'resolution_degrees': resolution, 'bounds': meta['bounds'], 'colours': COLOURS,
            'source_id': layer['source_id'], 'source_url': layer['source_url'], 'dataset': layer['dataset'],
            'license': layer['license'], 'limitations': layer['limitations'],
            'valid_cells': len(cells), 'source_valid_cells': layer.get('valid_cells'), 'total_cells': layer['total_cells'],
            'break_threshold_f_per_km': BREAK_F_PER_KM,
            'metadata_sha256': hashlib.sha256(raw).hexdigest(), 'inputs': receipts,
            'cells': collection(polygons), 'breaks': collection(segments)}


def private_output(path):
    if not path.resolve().is_relative_to((ROOT / 'var').resolve()):
        raise ValueError('preview output must stay under checkout var/')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'var/maplayer-sst-1/sst-preview.json')
    args = parser.parse_args()
    target = private_output(args.output)
    result = build(args.input, datetime.now(timezone.utc))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False) + '\n')
    print(f"{target}: {result['valid_cells']} cells, {len(result['breaks']['features'])} break segments; data {result['data_time']}; stale={result['stale']}")


if __name__ == '__main__':
    main()
