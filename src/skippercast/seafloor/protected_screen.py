"""Publish-time protected-area verdict for each reef of the habitat export (SC-PERF-PROTCHECK-1).

The browser shows every ranked reef with the verdict of the shared closure screen
(dist/geo-screen.js `screenPlace`: inside / nearest closure name / distance in metres). Computing it
there froze the page for about 11 s (distance to every boundary vertex, per picked reef) and the answer
is the same for every visitor, so it is computed here, once, with an exact port of that code
(`screenPlace`, `distanceM`, `geometryIntersects`, `pointInGeometry`, `geometryCoveredByBounds`).
The same IEEE-754 double operations run in the same order, vectorised with numpy (every ufunc rounds
on its own, so results equal the scalar JS ones).

The browser uses the stored verdict only when its own boundary data hash to `fingerprint` (the same hash,
`boundaryFingerprint` in dist/geo-screen.js); otherwise it runs the old check. Keep this file and
dist/geo-screen.js in step: tests/unit/test_protected_screen_verdicts.py runs both side by side, and
scripts/protected_screen_parity.py does it for a whole real export.
"""
import json
import math
import os
import struct
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

PLANNING_MARGIN_M = 70
VERSION = 2
FAR_M = 20000
GEOMETRY_DEPTH = {'Point': 0, 'MultiPoint': 1, 'LineString': 1, 'MultiLineString': 2, 'Polygon': 2, 'MultiPolygon': 3}
CELLS = 2_000_000          # pairwise cells per numpy block


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def positions(g):
    out = []

    def walk(c):
        if c and _is_num(c[0]):
            out.append(c)
        else:
            for child in c or []:
                walk(child)
    if g:
        walk(g.get('coordinates'))
    return out


class Shape:
    """A geometry with the caches the JS side keeps (bbox, positions, edges), as numpy arrays."""

    def __init__(self, g):
        self.g = g
        self.pos = positions(g)
        self.P = np.array([[p[0], p[1]] for p in self.pos], dtype=np.float64).reshape(-1, 2)
        self.box = ([float(self.P[:, 0].min()), float(self.P[:, 1].min()), float(self.P[:, 0].max()), float(self.P[:, 1].max())]
                    if len(self.P) else [math.inf, math.inf, -math.inf, -math.inf])
        t, c = g.get('type'), g.get('coordinates')
        lines = (c if t == 'Polygon' else [r for poly in c for r in poly] if t == 'MultiPolygon'
                 else [c] if t == 'LineString' else c if t == 'MultiLineString' else [])
        rows = [(line[i][0], line[i][1], line[i + 1][0], line[i + 1][1]) for line in lines for i in range(len(line) - 1)]
        self.E = np.array(rows, dtype=np.float64).reshape(-1, 4)


def _on_segment(p0, p1, a0, a1, b0, b1):
    cross = (p1 - a1) * (b0 - a0) - (p0 - a0) * (b1 - a1)
    return ((np.abs(cross) < 1e-12) & (p0 >= np.minimum(a0, b0) - 1e-10) & (p0 <= np.maximum(a0, b0) + 1e-10)
            & (p1 >= np.minimum(a1, b1) - 1e-10) & (p1 <= np.maximum(a1, b1) + 1e-10))


def _in_ring(P, ring):
    """JS `inRing` for each row of P: 2 on the ring, 1 inside, 0 outside."""
    r = np.array([[v[0], v[1]] for v in ring], dtype=np.float64).reshape(-1, 2)
    a, b = np.roll(r, 1, axis=0), r              # edge i joins ring[i-1] to ring[i], as `j=i++` does
    out = np.zeros(len(P), dtype=np.int8)
    step = max(1, CELLS // max(1, len(r)))
    for s in range(0, len(P), step):
        p0, p1 = P[s:s + step, 0:1], P[s:s + step, 1:2]
        a0, a1, b0, b1 = a[:, 0][None], a[:, 1][None], b[:, 0][None], b[:, 1][None]
        on = _on_segment(p0, p1, a0, a1, b0, b1).any(axis=1)
        cond = (a1 > p1) != (b1 > p1)
        den = np.where(cond, b1 - a1, 1.0)
        cross = cond & (p0 < (b0 - a0) * (p1 - a1) / den + a0)
        out[s:s + step] = np.where(on, 2, cross.sum(axis=1) % 2)
    return out


def points_in_geometry(P, s):
    """JS `pointInGeometry` for each row of P against shape `s`."""
    b = s.box
    ok = ~((P[:, 0] < b[0] - 1e-10) | (P[:, 0] > b[2] + 1e-10) | (P[:, 1] < b[1] - 1e-10) | (P[:, 1] > b[3] + 1e-10))
    result = np.zeros(len(P), dtype=bool)
    idx = np.nonzero(ok)[0]
    if not len(idx):
        return result
    Q = P[idx]
    t, c = s.g.get('type'), s.g.get('coordinates')
    polygons = [c] if t == 'Polygon' else c if t == 'MultiPolygon' else []
    inside = np.zeros(len(Q), dtype=bool)
    for rings in polygons:
        outer = _in_ring(Q, rings[0])
        holes = [_in_ring(Q, r) for r in rings[1:]]
        any2 = np.any([h == 2 for h in holes], axis=0) if holes else np.zeros(len(Q), dtype=bool)
        any1 = np.any([h == 1 for h in holes], axis=0) if holes else np.zeros(len(Q), dtype=bool)
        inside |= (outer == 2) | ((outer == 1) & (any2 | ~any1))
    result[idx] = inside
    return result


def _cr(x0, x1, y0, y1, z0, z1):
    return (y0 - x0) * (z1 - x1) - (y1 - x1) * (z0 - x0)


def _edges_intersect(A, B):
    """Any edge of A (rows x0,y0,x1,y1) meets any edge of B, by JS `intersects`."""
    if not len(A) or not len(B):
        return False
    c0, c1, d0, d1 = (B[:, i][None] for i in range(4))
    step = max(1, CELLS // len(B))
    for s in range(0, len(A), step):
        a0, a1, b0, b1 = (A[s:s + step, i][:, None] for i in range(4))
        hit = (_on_segment(a0, a1, c0, c1, d0, d1) | _on_segment(b0, b1, c0, c1, d0, d1)
               | _on_segment(c0, c1, a0, a1, b0, b1) | _on_segment(d0, d1, a0, a1, b0, b1))
        hit |= ((_cr(a0, a1, b0, b1, c0, c1) * _cr(a0, a1, b0, b1, d0, d1) < 0)
                & (_cr(c0, c1, d0, d1, a0, a1) * _cr(c0, c1, d0, d1, b0, b1) < 0))
        if hit.any():
            return True
    return False


def geometry_intersects(a, b):
    x, y = a.box, b.box
    if x[2] < y[0] or y[2] < x[0] or x[3] < y[1] or y[3] < x[1]:
        return False
    if len(a.P) and points_in_geometry(a.P, b).any():
        return True
    if len(b.P) and points_in_geometry(b.P, a).any():
        return True
    return _edges_intersect(a.E, b.E)


def m_per_deg(lat):
    r = lat * math.pi / 180
    return (111412.84 * math.cos(r) - 93.5 * math.cos(3 * r),
            111132.92 - 559.82 * math.cos(2 * r) + 1.175 * math.cos(4 * r))


def _best_dist2(pts, segs):
    """min over pts of min over segs of JS `segDist2` (pts (N,2), segs (S,4), all projected)."""
    a0, a1, b0, b1 = (segs[:, i][None] for i in range(4))
    dx, dy = b0 - a0, b1 - a1
    l = dx * dx + dy * dy
    safe = np.where(l > 0, l, 1.0)
    best = math.inf
    step = max(1, CELLS // len(segs))
    for s in range(0, len(pts), step):
        p0, p1 = pts[s:s + step, 0:1], pts[s:s + step, 1:2]
        t = np.where(l > 0, np.maximum(0, np.minimum(1, ((p0 - a0) * dx + (p1 - a1) * dy) / safe)), 0.0)
        x, y = a0 + t * dx - p0, a1 + t * dy - p1
        best = min(best, float((x * x + y * y).min()))
    return best


def distance_m(a, b):
    """JS `distanceM`: metres between two geometries, 0 when they touch, overlap or one holds the other; None without coordinates."""
    if not len(a.P) or not len(b.P):
        return None
    if geometry_intersects(a, b):
        return 0.0
    kx, ky = m_per_deg((a.pos[0][1] + b.pos[0][1]) / 2)
    k = np.array([kx, ky])

    def lines(s):
        if len(s.E):
            return np.concatenate([s.E[:, 0:2] * k, s.E[:, 2:4] * k], axis=1)
        p = s.P * k
        return np.concatenate([p, p], axis=1)
    return math.sqrt(min(_best_dist2(a.P * k, lines(b)), _best_dist2(b.P * k, lines(a))))


def far_apart(a, b):
    x, y = a.box, b.box
    if not all(math.isfinite(v) for v in x + y):
        return True
    kx, ky = m_per_deg((x[1] + x[3]) / 2)
    return max(x[0] - y[2], y[0] - x[2], 0) * kx > FAR_M or max(x[1] - y[3], y[1] - x[3], 0) * ky > FAR_M


def _checked_positions(g):
    depth = GEOMETRY_DEPTH.get(str(g.get('type'))) if isinstance(g, dict) else None
    if depth is None:
        return None
    out = []

    def walk(c, d):
        if d == 0:
            if (not isinstance(c, list) or len(c) < 2 or not _is_num(c[0]) or not _is_num(c[1])
                    or not math.isfinite(c[0]) or not math.isfinite(c[1]) or abs(c[0]) > 180 or abs(c[1]) > 90):
                return False
            out.append(c)
            return True
        return isinstance(c, list) and len(c) > 0 and all(walk(child, d - 1) for child in c)
    return out if walk(g.get('coordinates'), depth) else None


def covered_by_bounds(g, bounds, margin_m=PLANNING_MARGIN_M):
    """JS `geometryCoveredByBounds`."""
    if (not isinstance(bounds, list) or len(bounds) != 4
            or not all(_is_num(v) and math.isfinite(v) for v in bounds)):
        return False
    west, south, east, north = bounds
    if not (west < east and south < north) or west < -180 or east > 180 or south < -90 or north > 90:
        return False
    ps = _checked_positions(g)
    if not ps:
        return False
    lats = [south, north] + ([0] if south < 0 < north else [])
    kx = min(m_per_deg(l)[0] for l in lats)
    ky = min(m_per_deg(l)[1] for l in lats)
    if not (kx > 1) or not (ky > 1):
        return False
    dx, dy = margin_m / kx, margin_m / ky
    return all(west + dx <= p[0] <= east - dx and south + dy <= p[1] <= north - dy for p in ps)


def screen_place(closures, bounds, geometries, longitude, latitude):
    """JS `screenPlace` over a screen holding `closures` ([(name, Shape)]) and covering `bounds`, for a place with
    `geometries` (reef outlines) and a point. Returns {inside, name, distanceM, screened}."""
    none = {'inside': False, 'name': None, 'distanceM': None, 'screened': False}
    shapes = [Shape(g) for g in geometries] + [Shape({'type': 'Point', 'coordinates': [longitude, latitude]})]
    if not all(covered_by_bounds(s.g, bounds) for s in shapes):
        return none
    near = None
    for name, c in closures:
        for g in shapes:
            if far_apart(g, c):
                continue
            d = distance_m(g, c)
            if d is not None and (near is None or d < near[0]):
                near = (d, name)
    return {'inside': near is not None and near[0] == 0, 'name': near[1] if near else None,
            'distanceM': math.floor(near[0] * 10 + 0.5) / 10 if near else None, 'screened': True}


# ---- the boundary fingerprint (same words, same hash as dist/geo-screen.js `boundaryFingerprint`) ----

def _words(geometries, bounds, names=()):
    out = [float(VERSION), float(PLANNING_MARGIN_M), *[float(v) for v in bounds], float(len(geometries))]

    def walk(c):
        if c and _is_num(c[0]):
            out.extend((1.0, float(c[0]), float(c[1])))
        else:
            out.extend((0.0, float(len(c or []))))
            for child in c or []:
                walk(child)
    for i, g in enumerate(geometries):
        name = names[i] if i < len(names) else None
        if name is None:
            out.append(-1.0)
        else:
            units = struct.unpack('<%dH' % (len(name.encode('utf-16-le')) // 2), name.encode('utf-16-le'))   # UTF-16 code units, as JS charCodeAt
            out.append(float(len(units)))
            out.extend(float(u) for u in units)
        out.append(float(sum(map(ord, g.get('type') or ''))))
        walk(g.get('coordinates'))
    return out


def fingerprint(geometries, bounds, names=()):
    doubles = _words(geometries, bounds, names)
    data = struct.pack('<%dd' % len(doubles), *doubles)
    n = len(data) // 4
    h1, h2 = 0x811c9dc5, 0x01000193
    for w in struct.unpack('<%dI' % n, data):
        h1 = ((h1 ^ w) * 16777619) & 0xffffffff
        h2 = ((h2 ^ w) * 2246822519) & 0xffffffff
        h2 ^= h2 >> 15
    return 'ps%d-%08x%08x-%d' % (VERSION, h1, h2, n)


def load_screen(root, region):
    """The boundary data the browser loads for `region` (dist/regions/<id>/region.json assets), or None without a screen."""
    root = Path(root)
    config = root/'dist/regions'/region/'region.json'
    if not config.is_file():
        return None
    cfg = json.loads(config.read_text())
    bounds = (cfg.get('mpa') or {}).get('bounds')
    assets = cfg.get('assets') or {}
    if not assets.get('protected_areas') or not bounds:
        return None
    features, files = [], []
    for key in ('protected_areas', 'closures'):
        if assets.get(key):
            features.extend(json.loads((root/'dist'/assets[key]).read_text())['features'])
            files.append(assets[key])
    return bounds, features, files


def feature_name(f):
    """The closure name a verdict is shown under (the browser's FULLNAME || NAME || null)."""
    p = f.get('properties') or {}
    return p.get('FULLNAME') or p.get('NAME') or None


def verdicts(boundary, bounds, reefs):
    """{reef id: verdict} for `reefs` ([(id, outline geometry, longitude, latitude)]) against `boundary` (GeoJSON features)."""
    closures = [(feature_name(f), Shape(f['geometry'])) for f in boundary]
    return {rid: screen_place(closures, bounds, [geometry], lon, lat) for rid, geometry, lon, lat in reefs}


def _verdicts_part(args):
    return verdicts(*args)


def stamp(root, region, export_features):
    """Add `protected_place` to each of `export_features` (in place); return the export's top-level `protected_screen`, or None."""
    loaded = load_screen(root, region)
    if loaded is None:
        return None
    bounds, boundary, files = loaded
    reefs = [(f['properties']['id'], f['geometry'], f['properties']['waypoint']['longitude'], f['properties']['waypoint']['latitude'])
             for f in export_features]
    workers = min(4, os.cpu_count() or 1) if len(reefs) > 200 else 1     # about 70 s per 3000 reefs on four cores
    if workers == 1:
        by_id = verdicts(boundary, bounds, reefs)
    else:
        size = -(-len(reefs)//(workers*4))
        by_id = {}
        with ProcessPoolExecutor(workers) as pool:
            for part in pool.map(_verdicts_part, [(boundary, bounds, reefs[i:i + size]) for i in range(0, len(reefs), size)]):
                by_id.update(part)
    for f in export_features:
        f['properties']['protected_place'] = by_id[f['properties']['id']]
    return {'version': VERSION, 'fingerprint': fingerprint([f['geometry'] for f in boundary], bounds, [feature_name(f) for f in boundary]),
            'margin_m': PLANNING_MARGIN_M, 'bounds': bounds, 'boundary_features': len(boundary), 'boundary_files': files}
