"""Read-only contour endpoint proximity observations, NOT FOR NAVIGATION."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _read(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _crs(data):
    crs = data.get('crs')
    if crs is not None and crs.get('properties', {}).get('name') not in (
            'EPSG:4326', 'urn:ogc:def:crs:OGC:1.3:CRS84', 'urn:ogc:def:crs:EPSG::4326'):
        raise ValueError('crs_not_4326')


def _line(data, code):
    from shapely.geometry import shape
    from shapely.errors import GEOSException
    try:
        coords = data['coordinates']
        if data['type'] != 'LineString' or not 2 <= len(coords) <= (1000 if code == 'boundary_invalid' else math.inf):
            raise ValueError(code)
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p)
               or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in coords):
            raise ValueError(code)
        line = shape(data)
        if not line.is_valid or not line.is_simple or line.length == 0:
            raise ValueError(code)
        return line
    except (KeyError, TypeError, ValueError, GEOSException) as exc:
        raise ValueError(code) from exc


def shared_edge(bbox_a, bbox_b, *, match_m=0):
    """Return the common edge; optional metre tolerance admits only shallow overlap.

    With no source resolution available here, the default requires exact touching.
    Callers may pass their observation's match_m for the overlap tolerance.
    """
    from pyproj import Geod
    geod = Geod(ellps='WGS84')
    try:
        a, b = [list(map(float, box)) for box in (bbox_a, bbox_b)]
        if any(len(v) != 4 or not all(math.isfinite(x) for x in v)
               or not -180 <= v[0] < v[2] <= 180 or not -90 <= v[1] < v[3] <= 90 for v in (a, b)):
            raise ValueError
        if not math.isfinite(match_m) or match_m < 0:
            raise ValueError
        candidates = []
        for axis in (0, 1):
            low, high = sorted((a, b), key=lambda v: v[axis])
            other = 1 - axis
            start, end = max(a[other], b[other]), min(a[other+2], b[other+2])
            overlap = low[axis+2] - high[axis]
            if end <= start or overlap < 0 or low[axis] == high[axis]:
                continue
            mid = (start + end) / 2
            p, q = ([low[2], mid], [high[0], mid]) if axis == 0 else ([mid, low[3]], [mid, high[1]])
            distance = geod.inv(*p, *q)[2]
            if overlap == 0 or distance < match_m:
                centre = (low[axis+2] + high[axis]) / 2
                coords = [[centre, start], [centre, end]] if axis == 0 else [[start, centre], [end, centre]]
                candidates.append(dict(type='LineString', coordinates=coords))
        if len(candidates) == 1:
            return candidates[0]
    except (TypeError, ValueError, IndexError):
        pass
    raise ValueError('segments_not_adjacent')


def observe(a_dir, b_dir, boundary, *, band_m=None, match_m=None) -> dict:
    """Read two C2 outputs and a boundary GeoJSON path; never write or stitch."""
    from pyproj import Transformer
    from shapely.geometry import Point
    from shapely import transform

    try:
        edge_data, edge_hash = _read(boundary)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError('boundary_invalid') from exc
    if not isinstance(edge_data, dict):
        raise ValueError('boundary_invalid')
    _crs(edge_data)
    geometry = edge_data.get('geometry') if edge_data.get('type') == 'Feature' else edge_data
    edge = _line(geometry, 'boundary_invalid')
    midpoint = edge.interpolate(0.5, normalized=True)
    project = Transformer.from_crs('EPSG:4326',
        f'+proj=aeqd +lat_0={midpoint.y} +lon_0={midpoint.x} +datum=WGS84 +units=m',
        always_xy=True).transform
    edge = transform(edge, project, interleaved=False)
    inputs, collections, manifests = [], [], []
    for directory in (a_dir, b_dir):
        directory = Path(directory)
        try:
            manifest, manifest_hash = _read(directory / 'manifest.json')
        except FileNotFoundError as exc:
            raise ValueError('manifest_missing') from exc
        try:
            contours, contour_hash = _read(directory / 'contours.geojson')
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError('empty_contours') from exc
        if contours.get('type') != 'FeatureCollection' or not contours.get('features'):
            raise ValueError('empty_contours')
        _crs(contours)
        inputs.append(dict(label=str(directory), manifest_sha256=manifest_hash,
                           contours_sha256=contour_hash))
        collections.append(contours['features'])
        manifests.append(manifest)
    if (any(m.get('status') != 'review_required' for m in manifests)
            or any(manifests[0].get(k) != manifests[1].get(k) or k not in manifests[0]
                   for k in ('value_convention', 'contour_crs'))):
        raise ValueError('convention_mismatch')
    if manifests[0]['contour_crs'] != 'EPSG:4326':
        raise ValueError('crs_not_4326')
    resolution = max(f['properties']['source_resolution_m'] for rows in collections for f in rows)
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError('source_resolution_invalid')
    band_m = 2 * resolution if band_m is None else band_m
    match_m = 3 * resolution if match_m is None else match_m
    if any(not math.isfinite(v) or v < 0 for v in (band_m, match_m)):
        raise ValueError('distance_invalid')
    sides = []
    for features in collections:
        endpoints = {}
        for feature in features:
            line = _line(feature['geometry'], 'empty_contours')
            depth = feature['properties']['depth_ft']
            if not math.isfinite(depth):
                raise ValueError('empty_contours')
            points = endpoints.setdefault(depth, [])
            if not line.is_closed:
                for xy in (line.coords[0], line.coords[-1]):
                    point = transform(Point(xy), project, interleaved=False)
                    if point.distance(edge) <= band_m:
                        points.append((tuple(xy), point))
        sides.append(endpoints)
    levels = []
    keys = ('a_endpoints', 'b_endpoints', 'matched', 'unmatched_a', 'unmatched_b')
    for depth in sorted(sides[0].keys() | sides[1].keys()):
        a, b = (sorted(side.get(depth, []), key=lambda p: p[0]) for side in sides)
        candidates = sorted((pa.distance(pb), xa, xb, i, j)
                            for i, (xa, pa) in enumerate(a) for j, (xb, pb) in enumerate(b)
                            if pa.distance(pb) <= match_m)
        used_a, used_b, gaps = set(), set(), []
        for distance, _, _, i, j in candidates:
            if i not in used_a and j not in used_b:
                used_a.add(i)
                used_b.add(j)
                gaps.append(distance)
        levels.append(dict(depth_ft=depth, a_endpoints=len(a), b_endpoints=len(b), matched=len(gaps),
                           unmatched_a=len(a)-len(gaps), unmatched_b=len(b)-len(gaps),
                           gap_m=dict(min=min(gaps), median=median(gaps), max=max(gaps)) if gaps else None))
    return dict(schema='coast-seam-observation-v1', inputs=inputs, boundary_sha256=edge_hash,
                band_m=band_m, match_m=match_m, levels=levels,
                levels_one_side_only=sorted(sides[0].keys() ^ sides[1].keys()),
                totals={key: sum(row[key] for row in levels) for key in keys},
                stitched=False, inputs_modified=False, review_required=True,
                navigation='NOT FOR NAVIGATION', vertical_datum='undeclared',
                limitations=['Endpoint proximity only; no seam acceptance.',
                             'No horizontal or vertical datum transform or reconciliation.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('a', 'b', 'boundary', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('band-m', 'match-m'):
        parser.add_argument('--' + name, type=float)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError('Use a fresh output path')
    report = observe(args.a, args.b, args.boundary, band_m=args.band_m, match_m=args.match_m)
    payload = _json_bytes(report)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as target:
        os.fchmod(target.fileno(), 0o600)
        target.write(payload)


if __name__ == '__main__':
    main()
