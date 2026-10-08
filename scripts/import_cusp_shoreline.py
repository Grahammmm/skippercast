#!/usr/bin/env python3
"""Import the NOAA CUSP shoreline for a region (FE-10, docs/plans/front-end/design.md § 11).

    python scripts/import_cusp_shoreline.py morro-bay [more region ids]   # writes catalog/shoreline/<id>.geojson

Reads NOAA's published CUSP vector tiles (zoom 12, the tiles fish's SLO
extract used) over the region's `bounds` from regions/<id>/region.json, clips
each line to its own tile (dropping the tile buffer, so no line is doubled)
and to the region, and keeps the source fields per feature: SRC_DATE as
`source_date` (ISO), HOR_ACC (source accuracy, metres), creator and citation.

- Display quantisation: a zoom-12 tile has 4096 units a side, about 2 m at
  35° N; it is recorded per file and is separate from the source accuracy.
- Rights: CUSP mixes NOAA and outside contributors. Only features whose
  creator (DAT_SET_CR) is NOAA are kept, as NOAA public domain; the others are
  counted under `provenance.held_creators` for the region's review.
- A tile NOAA answers 403 or 404 is recorded as unavailable, never as
  certified empty. Any other failure stops the import and writes nothing.
The platform build copies the file to dist/regions/<id>/shoreline.geojson.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TILES = 'https://nsde.ngs.noaa.gov/cusp/tiles/{z}/{x}/{y}.pbf'
ZOOM = 12
KEEP = ('SOURCE_ID', 'SRC_DATE', 'HOR_ACC', 'ATTRIBUTE', 'DATA_SOURC', 'EXT_METH', 'DAT_SET_CR', 'SRC_CITA')
AGENT = {'User-Agent': 'SkipperCast shoreline import (https://skippercast.com)'}
LIMITATIONS = [
    'Historical mean-high-water and alongshore features from the dates in source_date; not a live or tidal shoreline, '
    'a legal boundary, a land polygon or a nautical chart.',
    'Lines come from NOAA\'s zoom-12 display tiles, which can be generalised from the source vectors; display '
    'quantisation (display_quantisation_m) is separate from source accuracy (HOR_ACC, metres).',
    'Tiles NOAA did not serve are listed as unavailable; their absence is not proof of no shoreline.',
]


def varint(buf, i):
    """(value, next offset) of the protobuf varint at buf[i]."""
    result = shift = 0
    while True:
        byte = buf[i]
        result, i, shift = result | (byte & 0x7F) << shift, i + 1, shift + 7
        if byte < 0x80:
            return result, i


def fields(buf):
    """(field number, value) for each field of one protobuf message; bytes for length-delimited fields."""
    i = 0
    while i < len(buf):
        key, i = varint(buf, i)
        wire = key & 7
        if wire == 0:
            value, i = varint(buf, i)
        elif wire == 2:
            size, i = varint(buf, i)
            value, i = buf[i:i + size], i + size
        elif wire in (1, 5):
            value, i = buf[i:i + (8 if wire == 1 else 4)], i + (8 if wire == 1 else 4)
        else:
            raise ValueError(f'Unsupported protobuf wire type {wire}')
        yield key >> 3, value


def packed(buf):
    values, i = [], 0
    while i < len(buf):
        value, i = varint(buf, i)
        values.append(value)
    return values


VALUES = {1: lambda b: bytes(b).decode('utf-8'), 2: lambda b: struct.unpack('<f', b)[0],
          3: lambda b: struct.unpack('<d', b)[0], 4: lambda v: v - (1 << 64) if v >= 1 << 63 else v,
          5: lambda v: v, 6: lambda v: (v >> 1) ^ -(v & 1), 7: bool}


def decode_tile(data):
    """[{name, extent, features: [{type, properties, geometry}]}] of a Mapbox Vector Tile (gzip or plain)."""
    if data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    layers = []
    for number, raw in fields(data):
        if number != 3:
            continue
        parts = {n: [] for n in (1, 2, 3, 4, 5)}
        for n, item in fields(raw):
            parts.setdefault(n, []).append(item)
        keys = [bytes(k).decode('utf-8') for k in parts[3]]
        values = [next((VALUES[n](v) for n, v in fields(item) if n in VALUES), None) for item in parts[4]]
        features = []
        for item in parts[2]:
            feature = dict(fields(item))
            tags = packed(feature.get(2, b''))
            features.append({'type': feature.get(3, 0), 'geometry': packed(feature.get(4, b'')),
                             'properties': {keys[k]: values[v] for k, v in zip(tags[::2], tags[1::2])}})
        layers.append({'name': bytes(parts[1][0]).decode('utf-8') if parts[1] else '',
                       'extent': parts[5][0] if parts[5] else 4096, 'features': features})
    return layers


def lines(commands):
    """Tile-unit lines from MVT geometry commands (MoveTo, LineTo; ClosePath ignored)."""
    out, x, y, i = [], 0, 0, 0
    while i < len(commands):
        command, count = commands[i] & 7, commands[i] >> 3
        i += 1
        if command == 7:
            continue
        for _ in range(count):
            dx, dy = commands[i], commands[i + 1]
            i += 2
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            if command == 1:
                out.append([])
            out[-1].append((x, y))
    return [line for line in out if len(line) > 1]


def tile_lon(x, z):
    return x / 2 ** z * 360 - 180


def tile_lat(y, z):
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z))))


def tiles_for(box, z=ZOOM):
    west, south, east, north = box
    col = lambda lon: int((lon + 180) / 360 * 2 ** z)
    row = lambda lat: int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z)
    return [(z, x, y) for x in range(col(west), col(east) + 1) for y in range(row(north), row(south) + 1)]


def clip_segment(a, b, box):
    """Liang-Barsky: the part of segment a-b inside box, or None."""
    (x0, y0), (x1, y1) = a, b
    dx, dy, t0, t1 = x1 - x0, y1 - y0, 0.0, 1.0
    for p, q in ((-dx, x0 - box[0]), (dx, box[2] - x0), (-dy, y0 - box[1]), (dy, box[3] - y0)):
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            t0 = max(t0, q / p)
        else:
            t1 = min(t1, q / p)
    if t0 > t1:
        return None
    return (a if t0 == 0 else (x0 + t0 * dx, y0 + t0 * dy)), (b if t1 == 1 else (x0 + t1 * dx, y0 + t1 * dy))


def clip(points, box):
    """The runs of a line inside box."""
    pieces, run = [], []
    for a, b in zip(points, points[1:]):
        segment = clip_segment(a, b, box)
        if segment is None or (run and run[-1] != segment[0]):
            pieces.append(run)
            run = []
        if segment is not None:
            run = run + [segment[1]] if run else list(segment)
            if segment[1] != b:
                pieces.append(run)
                run = []
    pieces.append(run)
    rounded = [[(round(x, 6), round(y, 6)) for x, y in piece] for piece in pieces]
    rounded = [[p for i, p in enumerate(piece) if i == 0 or p != piece[i - 1]] for piece in rounded]
    return [[list(p) for p in piece] for piece in rounded if len(piece) > 1]


def source_date(raw):
    match = re.fullmatch(r'(\d{4})(\d{2})(\d{2})', str(raw or ''))
    if not match:
        return None
    try:
        return datetime(*map(int, match.groups())).date().isoformat()
    except ValueError:
        return None


def fetch(tile):
    z, x, y = tile
    try:
        with urlopen(Request(TILES.format(z=z, x=x, y=y), headers=AGENT), timeout=60) as response:
            return response.read()
    except HTTPError as error:
        if error.code in (403, 404):
            return None
        raise


def region_bounds(region_id, root=ROOT):
    region = json.loads((root / 'regions' / region_id / 'region.json').read_text())
    return [float(v) for v in region['bounds']]


def extract(region_id, box, get=fetch, now=None):
    """The region's shoreline as a GeoJSON FeatureCollection with provenance."""
    tiles = tiles_for(box)
    with ThreadPoolExecutor(max_workers=8) as pool:
        bodies = dict(zip(tiles, pool.map(get, tiles)))
    features, receipts, held, undated, quantisation = [], [], {}, 0, 0.0
    for (z, x, y), body in sorted(bodies.items()):
        if body is None:
            continue
        receipts.append({'tile': f'{z}/{x}/{y}', 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
        cell = [tile_lon(x, z), tile_lat(y + 1, z), tile_lon(x + 1, z), tile_lat(y, z)]
        inside = [max(cell[0], box[0]), max(cell[1], box[1]), min(cell[2], box[2]), min(cell[3], box[3])]
        for layer in decode_tile(body):
            size = layer['extent']
            quantisation = max(quantisation, 40075016.686 * math.cos(math.radians(cell[1])) / (2 ** z * size))
            for index, feature in enumerate(layer['features']):
                props = feature['properties']
                if props.get('DAT_SET_CR') != 'NOAA':
                    held[str(props.get('DAT_SET_CR'))] = held.get(str(props.get('DAT_SET_CR')), 0) + 1
                    continue
                if not source_date(props.get('SRC_DATE')):
                    undated += 1
                    continue
                pieces = []
                for line in lines(feature['geometry']) if feature['type'] == 2 else []:
                    lonlat = [(tile_lon(x + px / size, z), tile_lat(y + py / size, z)) for px, py in line]
                    pieces += clip(lonlat, inside)
                if not pieces:
                    continue
                geometry = ({'type': 'LineString', 'coordinates': pieces[0]} if len(pieces) == 1
                            else {'type': 'MultiLineString', 'coordinates': pieces})
                properties = {k: props[k] for k in KEEP if k in props}
                properties.update(source_date=source_date(props['SRC_DATE']), source_tile=f'{z}/{x}/{y}')
                features.append({'type': 'Feature', 'id': f'cusp-{z}-{x}-{y}-{index}', 'geometry': geometry,
                                 'properties': properties})
    dates = sorted(f['properties']['source_date'] for f in features)
    return {'type': 'FeatureCollection', 'provenance': {
        'source': 'NOAA National Geodetic Survey, Continually Updated Shoreline Product (CUSP)',
        'source_url': 'https://nsde.ngs.noaa.gov/', 'tile_template': TILES, 'source_id': 'noaa-cusp-shoreline',
        'license': 'public-domain', 'attribution': 'NOAA National Geodetic Survey · CUSP shoreline',
        'region_id': region_id, 'bounds': box, 'source_zoom': ZOOM,
        'retrieved_at': (now or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'display_quantisation_m': round(quantisation, 2), 'coordinate_decimals': 6,
        'source_dates': [dates[0], dates[-1]] if dates else [], 'features': len(features),
        'requested_tiles': len(tiles), 'unavailable_tiles': [f'{z}/{x}/{y}' for (z, x, y), b in sorted(bodies.items()) if b is None],
        'held_creators': dict(sorted(held.items())), 'undated_features_dropped': undated,
        'tile_receipts': receipts, 'limitations': LIMITATIONS}, 'features': features}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('regions', nargs='+')
    parser.add_argument('--out', type=Path, default=ROOT / 'catalog/shoreline')
    args = parser.parse_args(argv)
    for region_id in args.regions:
        collection = extract(region_id, region_bounds(region_id))
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f'{region_id}.geojson'
        path.write_text(json.dumps(collection, separators=(',', ':'), ensure_ascii=False) + '\n')
        p = collection['provenance']
        print(f"{path}: {p['features']} features, {len(p['tile_receipts'])}/{p['requested_tiles']} tiles served, "
              f"source dates {p['source_dates']}, held {p['held_creators']}, {path.stat().st_size:,} bytes")


if __name__ == '__main__':
    main()
