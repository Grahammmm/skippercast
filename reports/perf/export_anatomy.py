#!/usr/bin/env python3
"""PERF-BASELINE-1: what the 15 MB reef export (habitat-export.geojson.gz) is made of, and what slimmer forms would weigh.

Usage: python3 reports/perf/export_anatomy.py <habitat-export.geojson.gz> > reports/perf/raw/export-anatomy.json
Measures (gzip level 9 and the raw JSON bytes): the whole file; properties only; geometry only; coordinates rounded
to 6 and 5 decimals (0.11 m and 1.1 m); the fields loadReefTrip keeps per target (no geometry); and a ring-thinned
copy (every vertex closer than 5 m to the last kept one dropped, a crude stand-in for proper simplification).
"""
import gzip
import json
import math
import sys

raw_gz = open(sys.argv[1], 'rb').read()
raw = gzip.decompress(raw_gz)
doc = json.loads(raw)
feats = doc['features']


def size(obj):
    b = json.dumps(obj, separators=(',', ':')).encode()
    return {'json_bytes': len(b), 'gzip9_bytes': len(gzip.compress(b, 9))}


def walk(c, fn):
    if isinstance(c[0], (int, float)):
        return fn(c)
    return [walk(x, fn) for x in c]


def count(c):
    if isinstance(c[0], (int, float)):
        return 1
    return sum(count(x) for x in c)


def rounded(n):
    return lambda p: [round(p[0], n), round(p[1], n)] + list(p[2:])


def thin(ring, tol_m=5.0):
    if not ring or not isinstance(ring[0][0], (int, float)):
        return [thin(r, tol_m) for r in ring]
    lat = ring[0][1]
    kx, ky = 111320 * math.cos(math.radians(lat)), 110540
    out = [ring[0]]
    for p in ring[1:-1]:
        q = out[-1]
        if math.hypot((p[0] - q[0]) * kx, (p[1] - q[1]) * ky) >= tol_m:
            out.append(p)
    out.append(ring[-1])
    return out if len(out) >= 4 else ring


types = {}
for f in feats:
    types[f['geometry']['type']] = types.get(f['geometry']['type'], 0) + 1
vertices = sum(count(f['geometry']['coordinates']) for f in feats)
sample = feats[0]['geometry']['coordinates']
while isinstance(sample[0], list):
    sample = sample[0]
report = {
    'file_gzip_bytes': len(raw_gz), 'decoded_bytes': len(raw), 'features': len(feats), 'geometry_types': types, 'vertices': vertices,
    'sample_coordinate': sample, 'top_level_keys': sorted(k for k in doc if k != 'features'),
    'property_keys': sorted(feats[0]['properties'].keys()),
    'whole': size(doc),
    'properties_only': size([f['properties'] for f in feats]),
    'geometry_only': size([f['geometry'] for f in feats]),
    'coords_6dp': size({**doc, 'features': [{**f, 'geometry': {**f['geometry'], 'coordinates': walk(f['geometry']['coordinates'], rounded(6))}} for f in feats]}),
    'coords_5dp': size({**doc, 'features': [{**f, 'geometry': {**f['geometry'], 'coordinates': walk(f['geometry']['coordinates'], rounded(5))}} for f in feats]}),
    'thinned_5m_6dp': size({**doc, 'features': [{**f, 'geometry': {**f['geometry'], 'coordinates': walk(thin(f['geometry']['coordinates']), rounded(6))}} for f in feats]}),
}
keep = ['id', 'waypoint', 'depth_min_ft', 'depth_max_ft', 'vertical_datum', 'terrain', 'fit', 'resolution_m', 'source_urls', 'source_year', 'area_ha', 'source_rights', 'tier', 'status', 'exportable', 'screen', 'region']
report['targets_only_no_geometry'] = size([{k: f['properties'].get(k) for k in keep} for f in feats])
report['thinned_vertices'] = sum(count(thin(f['geometry']['coordinates'])) for f in feats)
print(json.dumps(report, indent=1))
