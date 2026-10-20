"""Land or water for ranked places (CI6-01B; method: docs/land-water-method.md, approved at step 0).

The platform build derives this product from the region's published CUSP
shoreline (dist/regions/<id>/shoreline.geojson, platform/shoreline.py) and the
land corners the region declares (regions/<id>/region.json `land_water`). It
adds no source and does not change the import. Two files are written:

- land-water.json, the index the client loads with a ranked list: the status
  (available, or unavailable with its causes), the constants, the census
  counts and provenance, and for every zoom-12 tile NOAA served a GRID x GRID
  grid of cells, each one `w` (water), `l` (land) or `m` (mixed). A `w` or `l`
  cell is clean: every point of it lies more than EDGE_M + MARGIN_M from every
  published line and seam join, and no parity curve touches it, so every
  point of it has the parity of its centre. Cells are uniform in Web Mercator
  inside their tile, the way the client finds them (web/land-water.ts).
- land-water-lines.json, loaded only when a candidate falls in an `m` cell:
  every published line and seam join (the edge band is measured from them) and
  the parity curves after the defect removals (step 6). Coordinates are
  integers on the published 5-decimal grid, delta-encoded.

Every topology test is exact on that integer grid. The steps follow the note:

1. Lines: at least two positions of finite numbers; repeated consecutive
   positions are dropped. Closed (first == last) or open.
2. Open lines chain at exactly equal endpoints; a node of degree 3+ fails.
3. Each dangling endpoint pairs with its mutual-nearest dangling endpoint. Two
   chains join only at a zoom-12 tile seam (both ends on the shared edge of
   the two served tiles the end lines came from, the gap at most 2 x the larger
   HOR_ACC). A chain whose own ends pair is kept, as an edge line, only when
   its closure is degenerate. There are no bridges.
4. Exactly one path runs bounds to bounds: the mainland, closed along the
   region bounds through the declared land corners.
5. Degenerate closed curves (collinear, or at most EDGE_M across) are
   edge-only.
6. Census of crossings, touches, overlaps and retraces over the parity curves;
   retraces and witnessed sub-loops are removed one at a time and the census
   re-run; touches without crossing stay; anything else fails.
7. Even-odd parity over the parity curves after removal.
8. EDGE_M from any published line or seam join is edge (unknown).
9. Only served tiles count; 10. any failure makes the whole product
   unavailable, and then every point is unknown.
"""
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from .contracts import read_json

SCHEMA_VERSION = 1
EDGE_M = 25
# Clean grid cells keep this much more than EDGE_M from every line, so the client's
# per-point metre scale and the build's per-tile one cannot disagree about a band edge.
MARGIN_M = 1
UNIT = 10 ** 5  # published coordinates have 5 decimals
CELL = 200  # grid units (0.002 degrees) per segment-index cell
Z = 12
GRID = 32  # cells per tile side in the index
ROUNDING_M = 0.55  # half a 5-decimal unit of latitude, rounded up
CORNERS = ('NE', 'SE', 'SW', 'NW')
CORNER_EDGES = {'NE': {'N', 'E'}, 'SE': {'S', 'E'}, 'SW': {'S', 'W'}, 'NW': {'N', 'W'}}
INDEX = 'land-water.json'
LINES = 'land-water-lines.json'


class Unavailable(ValueError):
    """The shoreline cannot be built into a land/water topology under the method."""


# ---- geometry on the integer grid (docs/land-water-method.md steps 1-6) ----

def tile_of(lon, lat, z=Z):
    x = (lon + 180) / 360 * 2 ** z
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z
    return int(math.floor(x)), int(math.floor(y)), x, y


def tile_lon(x, z=Z):
    return round((x / 2 ** z * 360 - 180) * UNIT)


def tile_lat(y, z=Z):
    return round(_lat(y, z) * UNIT)


def _lat(y, z=Z):
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z))))


def metres_per_unit(lat):
    return 111_320 * math.cos(math.radians(lat)) / UNIT, 110_540 / UNIT


def distance(k, a, b):
    return math.hypot((a[0] - b[0]) * k[0], (a[1] - b[1]) * k[1])


def orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(p, a, b):
    return orient(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def meet(a, b, c, d):
    """Exact relation of segments ab and cd: None, ('proper', point), ('touch', point) or ('overlap', point)."""
    d1, d2, d3, d4 = orient(c, d, a), orient(c, d, b), orient(a, b, c), orient(a, b, d)
    if d1 * d2 < 0 and d3 * d4 < 0:
        t = d1 / (d1 - d2)
        return 'proper', (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    if d1 == d2 == d3 == d4 == 0:
        shared = [p for p in (a, b) if on_segment(p, c, d)] + [p for p in (c, d) if on_segment(p, a, b)]
        if not shared:
            return None
        return ('overlap' if len(set(shared)) > 1 else 'touch'), shared[0]
    for p, (s, e) in ((a, (c, d)), (b, (c, d)), (c, (a, b)), (d, (a, b))):
        if on_segment(p, s, e):
            return 'touch', p
    return None


def collinear(points):
    """True when every position lies on one straight line (a closed curve there encloses no area)."""
    base = next((p for p in points if p != points[0]), None)
    return base is None or all(orient(points[0], base, p) == 0 for p in points)


def box(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def across(k, points):
    bb = box(points)
    return distance(k, bb[:2], bb[2:])


def degenerate(k, curve):
    """'collinear' or 'small' (at most EDGE_M across) when no point outside the edge band can change parity, else None."""
    return 'collinear' if collinear(curve) else 'small' if across(k, curve) <= EDGE_M else None


def tidy(curve):
    """A closed curve without repeated consecutive positions (first == last kept)."""
    c = curve[:-1]
    out = [p for i, p in enumerate(c) if p != c[i - 1]] if len(c) > 1 else c
    return out + out[:1]


def census(k, curves):
    """Exact defects among closed curves [(name, closed coords)]: dicts with a witness and a removal, when there is one."""
    segs = [(ci, si, a, b) for ci, (_, c) in enumerate(curves) for si, (a, b) in enumerate(zip(c, c[1:]))]
    grid = defaultdict(list)
    for n, (_, _, a, b) in enumerate(segs):
        for gx in range(min(a[0], b[0]) // CELL, max(a[0], b[0]) // CELL + 1):
            for gy in range(min(a[1], b[1]) // CELL, max(a[1], b[1]) // CELL + 1):
                grid[(gx, gy)].append(n)
    found = {}
    for ids in grid.values():
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                s, t = sorted((ids[x], ids[y]))
                if (s, t) in found:
                    continue
                (ci, si, a, b), (cj, sj, c, d) = segs[s], segs[t]
                n = len(curves[ci][1]) - 1
                if ci == cj and (sj - si == 1 or (si == 0 and sj == n - 1)):  # adjacent: only a reversal is a defect
                    shared, p, q = (b, a, d) if sj - si == 1 else (a, b, c)
                    if orient(p, shared, q) == 0 and (shared[0] - p[0]) * (q[0] - shared[0]) + (shared[1] - p[1]) * (q[1] - shared[1]) < 0:
                        found[(s, t)] = ('retrace', shared)
                    continue
                hit = meet(a, b, c, d)
                if hit:
                    found[(s, t)] = hit

    def strand(ci, si, x):
        c = curves[ci][1][:-1]
        n = len(c)
        a, b = c[si % n], c[(si + 1) % n]
        before, after = (c[(si - 1) % n], b) if x == a else (a, c[(si + 2) % n]) if x == b else (a, b)
        return (before[0] - x[0], before[1] - x[1]), (after[0] - x[0], after[1] - x[1])

    def transversal(s, t, x):
        """True when the two strands cross at x, False when they only touch, None when they run together."""
        (ci, si, *_), (cj, sj, *_) = segs[s], segs[t]
        (a1, a2), (b1, b2) = strand(ci, si, x), strand(cj, sj, x)
        cross = lambda u, v: u[0] * v[1] - u[1] * v[0]
        dot = lambda u, v: u[0] * v[0] + u[1] * v[1]
        if any(cross(u, v) == 0 and dot(u, v) > 0 for u in (a1, a2) for v in (b1, b2)):
            return None
        half = lambda v: 0 if cross(a1, v) > 0 or (cross(a1, v) == 0 and dot(a1, v) > 0) else 1
        before = lambda u, v: half(u) < half(v) or (half(u) == half(v) and cross(u, v) > 0)  # counter-clockwise from a1
        return before(b1, a2) != before(b2, a2)

    out = []
    for (s, t), (kind, point) in sorted(found.items()):
        (ci, si, *_), (cj, sj, *_) = segs[s], segs[t]
        x = (round(point[0]), round(point[1]))
        row = {'kind': kind, 'scope': 'self' if ci == cj else 'between', 'curves': (curves[ci][0], curves[cj][0]), 'at': x,
               'witness': None, 'remove': None}
        if kind == 'retrace':
            row['witness'] = 'retrace'
            row['remove'] = ('vertex', ci, (si + 1) if sj - si == 1 else 0)
        elif kind == 'touch' and transversal(s, t, x) is False:
            row['witness'] = 'touch without crossing'
        elif ci == cj:
            c = curves[ci][1][:-1]
            inner, outer = [x] + c[si + 1:sj + 1] + [x], [x] + c[sj + 1:] + c[:si + 1] + [x]
            for name, loop in (('inner', inner), ('outer', outer)):
                if collinear(loop) or across(k, loop) <= EDGE_M:
                    row['witness'] = f'{name} sub-loop'
                    row['remove'] = ('loop', ci, si, sj, x, name)
                    break
        out.append(row)
    return out


def witness_kind(row):
    return row['witness'] or 'no witness'


def resolve(k, curves, limit=10_000):
    """Remove retraces and witnessed sub-loops one at a time, re-running the census, until none is left.

    Returns (curves, first census, removals, defects left). No removal changes the
    parity of a point farther than EDGE_M from the lines (the note's edge-band lemma).
    """
    curves, first, removals = list(curves), None, Counter()
    for _ in range(limit):
        rows = census(k, curves)
        first = rows if first is None else first
        step = next((r for r in rows if r['remove']), None)
        if step is None:
            return curves, first, removals, rows
        removals[witness_kind(step)] += 1
        kind, ci, *rest = step['remove']
        name, curve = curves[ci]
        c = curve[:-1]
        if kind == 'vertex':
            c = c[:rest[0]] + c[rest[0] + 1:]
        else:
            si, sj, x, which = rest
            c = c[:si + 1] + [x] + c[sj + 1:] if which == 'inner' else [x] + c[si + 1:sj + 1]
        curve = tidy(c + c[:1])
        if len(curve) < 4 or degenerate(k, curve):
            del curves[ci]
        else:
            curves[ci] = (name, curve)
    raise Unavailable('defect removal did not converge')


def seam_problem(k, a, b, line_a, line_b, served):
    """Why the gap a-b between two chains is not a zoom-12 tile seam, or None when it is one."""
    try:
        (za, xa, ya), (zb, xb, yb) = (map(int, str(line['tile']).split('/')) for line in (line_a, line_b))
    except (TypeError, ValueError):
        return 'no source tile'
    if za != Z or zb != Z or abs(xa - xb) + abs(ya - yb) != 1:
        return f'tiles {line_a["tile"]} and {line_b["tile"]} are not edge neighbours'
    if not {line_a['tile'], line_b['tile']} <= served:
        return 'a tile was not served'
    axis, edge = (0, tile_lon(max(xa, xb))) if xa != xb else (1, tile_lat(max(ya, yb)))
    if not a[axis] == b[axis] == edge:
        return 'ends not on the shared tile edge'
    if line_a['acc'] is None or line_b['acc'] is None:
        return 'no HOR_ACC'
    limit = 2 * max(line_a['acc'], line_b['acc'])
    if distance(k, a, b) > limit:
        return f'gap {distance(k, a, b):.1f} m over 2 x HOR_ACC {limit:.2f} m'
    return None


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _acc(value):
    try:
        acc = float(value)
    except (TypeError, ValueError):
        return None
    return acc if math.isfinite(acc) and acc >= 0 else None


# ---- the build ----

def assemble(shore, region):
    """Steps 1-7 on a published shoreline: a dict with the edge lines, joins, parity curves and counts.

    Raises Unavailable with every cause found when the product cannot be built.
    """
    causes = []
    if not isinstance(shore, dict) or shore.get('type') != 'FeatureCollection' or not isinstance(shore.get('features'), list):
        raise Unavailable('shoreline file is not a FeatureCollection')
    prov = shore.get('provenance') or {}
    bounds = region.get('bounds')
    if not (isinstance(bounds, list) and len(bounds) == 4 and all(map(_number, bounds))):
        raise Unavailable('region bounds missing')
    W, S, E, N = (round(v * UNIT) for v in bounds)
    if prov.get('bounds') is not None and [round(v * UNIT) for v in prov['bounds']] != [W, S, E, N]:
        raise Unavailable('shoreline bounds differ from the region bounds')
    k = metres_per_unit((S + N) / 2 / UNIT)
    on_bounds = lambda p: p[0] in (W, E) or p[1] in (S, N)
    served = {r.get('tile') for r in prov.get('tile_receipts') or [] if isinstance(r, dict)} - {None}
    if not served:
        causes.append('no served tiles recorded')
    quantum = prov.get('display_quantisation_m')

    # 1. lines
    lines, malformed = [], 0
    for f in shore['features']:
        geometry, props = (f or {}).get('geometry') or {}, (f or {}).get('properties') or {}
        coords = geometry.get('coordinates')
        group = [coords] if geometry.get('type') == 'LineString' else coords if geometry.get('type') == 'MultiLineString' else None
        if not isinstance(group, list):
            malformed += 1
            continue
        for raw in group:
            if not isinstance(raw, list) or any(not isinstance(q, list) or len(q) != 2 or not all(map(_number, q)) for q in raw):
                malformed += 1
                continue
            c = [(round(x * UNIT), round(y * UNIT)) for x, y in raw]
            kept = c[:1] + [q for p, q in zip(c, c[1:]) if q != p]
            if len(kept) < 2:
                malformed += 1
                continue
            if any(not (W <= x <= E and S <= y <= N) for x, y in kept):
                causes.append('a line lies outside the region bounds')
            lines.append({'c': kept, 'acc': _acc(props.get('HOR_ACC')), 'tile': props.get('source_tile')})
    if malformed:
        causes.append(f'malformed lines {malformed}')
    accs = [l['acc'] for l in lines]
    if not lines:
        causes.append('no shoreline lines')
    elif None in accs or not _number(quantum):
        causes.append('HOR_ACC or display quantisation missing')
    elif 2 * (max(accs) + quantum + ROUNDING_M) > EDGE_M:
        causes.append(f'stated error 2 x ({max(accs)} + {quantum} + {ROUNDING_M}) m exceeds EDGE_M {EDGE_M} m')
    if causes:
        raise Unavailable('; '.join(causes))
    closed = [l for l in lines if l['c'][0] == l['c'][-1]]
    opened = [l for l in lines if l['c'][0] != l['c'][-1]]

    # 2. chain at shared endpoints
    ends = defaultdict(list)
    for i, l in enumerate(opened):
        ends[l['c'][0]].append(i)
        ends[l['c'][-1]].append(i)
    if any(len(v) > 2 for v in ends.values()):
        raise Unavailable('a node joins three or more lines')
    used, chains = set(), []

    def walk(i, reverse):
        coords, cur, members = (list(reversed(opened[i]['c'])) if reverse else list(opened[i]['c'])), i, [i]
        used.add(i)
        while True:
            nxt = [j for j in ends[coords[-1]] if j != cur and j not in used]
            if not nxt:
                return {'c': coords, 'first': members[0], 'last': members[-1]}
            j = nxt[0]
            used.add(j)
            members.append(j)
            coords += (opened[j]['c'] if opened[j]['c'][0] == coords[-1] else list(reversed(opened[j]['c'])))[1:]
            cur = j
    for i, l in enumerate(opened):
        if i not in used and (len(ends[l['c'][0]]) == 1 or len(ends[l['c'][-1]]) == 1):
            chains.append(walk(i, len(ends[l['c'][0]]) != 1))
    for i in range(len(opened)):
        if i not in used:
            chains.append(walk(i, False))
    closed_chains = [c for c in chains if c['c'][0] == c['c'][-1]]
    open_chains = [c for c in chains if c['c'][0] != c['c'][-1]]

    # 3. pair dangling endpoints: seam joins only, no bridges
    end_line = lambda e: opened[open_chains[e[0]]['first' if e[1] == 0 else 'last']]
    at = lambda e: open_chains[e[0]]['c'][e[1]]
    dangling = [(ci, j) for ci, c in enumerate(open_chains) for j in (0, -1) if not on_bounds(c['c'][j])]
    nearest = {e: min((f for f in dangling if f != e), key=lambda f: (distance(k, at(e), at(f)), f)) for e in dangling} if len(dangling) > 1 else {}
    pairs = sorted({tuple(sorted((e, nearest[e]))) for e in dangling if nearest.get(nearest.get(e)) == e})
    joins, edge_only, link = [], set(), {}
    for e, f in pairs:
        if e[0] == f[0]:
            if degenerate(k, open_chains[e[0]]['c'] + [at(e)]):
                edge_only.add(e[0])
            else:
                causes.append(f'an unclosed curve whose ends are {distance(k, at(e), at(f)):.1f} m apart is not degenerate')
            continue
        why = seam_problem(k, at(e), at(f), end_line(e), end_line(f), served)
        if why is None:
            joins.append((at(e), at(f)))
            link[e], link[f] = f, e
        else:
            causes.append(f'gap not a tile seam ({why})')
    unpaired = set(dangling) - {x for p in pairs for x in p}
    if unpaired:
        causes.append(f'unpaired endpoints {len(unpaired)}')
    if causes:
        raise Unavailable('; '.join(causes))

    # 4. paths and the mainland
    paths, seen = [], set(edge_only)
    starts = [(ci, j) for ci, c in enumerate(open_chains) for j in (0, -1) if on_bounds(c['c'][j])] + [(ci, 0) for ci in range(len(open_chains))]
    for ci, j in starts:
        if ci in seen:
            continue
        path = []
        while True:
            seen.add(ci)
            path += open_chains[ci]['c'] if j == 0 else list(reversed(open_chains[ci]['c']))
            other = (ci, -1 if j == 0 else 0)
            if other not in link:
                break
            ci, j = link[other]
            if ci in seen:
                path.append(open_chains[ci]['c'][j])
                break
        paths.append(path)
    mainland = [p for p in paths if on_bounds(p[0]) and on_bounds(p[-1]) and p[0] != p[-1]]
    loops = [p for p in paths if p not in mainland]
    if len(mainland) != 1:
        raise Unavailable(f'bounds-to-bounds paths {len(mainland)}, not one')
    closure = close_mainland(mainland[0], region, (W, S, E, N))

    # 5. curves for parity; degenerate ones are edge-only
    curves = [('mainland', closure)] + [('ring', l['c']) for l in closed] + [('chain', c['c']) for c in closed_chains]
    curves += [('seam loop', p + [p[0]]) for p in loops]
    for name, c in curves:
        if len(c) < 4 and not collinear(c):
            raise Unavailable(f'a {name} has under four positions')
    parity = [(name, c) for name, c in curves if not degenerate(k, c)]
    kinds = Counter(degenerate(k, c) or 'parity' for _, c in curves)

    # 6. census, removal of witnessed defects, census again
    resolved, first, removals, left = resolve(k, parity)
    gross = [r for r in left if r['witness'] is None]
    if gross:
        raise Unavailable(f'defects without a witness {len(gross)} (first at {gross[0]["at"][0] / UNIT:.5f}, {gross[0]["at"][1] / UNIT:.5f})')
    edge = [l['c'] for l in lines] + [[a, b] for a, b in joins]
    return {
        'units': (W, S, E, N), 'k': k, 'served': sorted(served), 'edge': edge, 'parity': [c for _, c in resolved],
        'counts': {'lines': len(lines), 'closed_lines': len(closed), 'open_lines': len(opened), 'chains': len(chains),
                   'seam_joins': len(joins), 'edge_only_chains': len(edge_only),
                   'closed_curves': dict(sorted(kinds.items())), 'parity_curves': len(parity),
                   'parity_segments': sum(len(c) - 1 for _, c in parity),
                   'defects': dict(sorted(Counter(witness_kind(r) for r in first).items())),
                   'removed': dict(sorted(removals.items())),
                   'left': dict(sorted(Counter(witness_kind(r) for r in left).items())),
                   'parity_curves_after_removal': len(resolved)},
    }


def close_mainland(path, region, units):
    """The mainland path closed along the bounds through the region's declared land corners (step 4)."""
    W, S, E, N = units
    names = (region.get('land_water') or {}).get('land_corners')
    if not (isinstance(names, list) and names and all(n in CORNERS for n in names) and len(set(names)) == len(names)):
        raise Unavailable('the region declares no land corners')
    if any(not CORNER_EDGES[a] & CORNER_EDGES[b] for a, b in zip(names, names[1:])):
        raise Unavailable('consecutive land corners do not share a bounds edge')
    xy = {'NE': (E, N), 'SE': (E, S), 'SW': (W, S), 'NW': (W, N)}
    sides = lambda p: {s for s, hit in (('W', p[0] == W), ('E', p[0] == E), ('S', p[1] == S), ('N', p[1] == N)) if hit}
    options = []
    for cand in (path, path[::-1]):
        if sides(cand[-1]) & CORNER_EDGES[names[0]] and sides(cand[0]) & CORNER_EDGES[names[-1]]:
            curve = cand + [xy[n] for n in names] + [cand[0]]
            if curve not in options and curve[::-1] not in options:
                options.append(curve)
    if len(options) != 1:
        raise Unavailable('the mainland ends do not fit the declared land corners' if not options else 'the land side is ambiguous')
    return options[0]


# ---- the index grid ----

def _segment_box_m(k, a, b, box_):
    """Metres from segment ab to the closed box (x0, y0, x1, y1), all in grid units scaled by k."""
    x0, y0, x1, y1 = box_
    if _hits_box(a, b, box_):
        return 0.0
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    best = min(_point_box_m(k, p, box_) for p in (a, b))
    for c in corners:
        best = min(best, _point_segment_m(k, c, a, b))
    return best


def _point_box_m(k, p, box_):
    x0, y0, x1, y1 = box_
    dx = max(x0 - p[0], 0, p[0] - x1) * k[0]
    dy = max(y0 - p[1], 0, p[1] - y1) * k[1]
    return math.hypot(dx, dy)


def _point_segment_m(k, p, a, b):
    ax, ay, bx, by, px, py = a[0] * k[0], a[1] * k[1], b[0] * k[0], b[1] * k[1], p[0] * k[0], p[1] * k[1]
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0 if length == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _hits_box(a, b, box_):
    """True when segment ab meets the closed box (Liang-Barsky clipping)."""
    x0, y0, x1, y1 = box_
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if p == 0:
            if q < 0:
                return False
        else:
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 > t1:
                return False
    return True


def _index(segments):
    grid = defaultdict(list)
    for n, (a, b) in enumerate(segments):
        for gx in range(min(a[0], b[0]) // CELL, max(a[0], b[0]) // CELL + 1):
            for gy in range(min(a[1], b[1]) // CELL, max(a[1], b[1]) // CELL + 1):
                grid[(gx, gy)].append(n)
    return grid


def _near(grid, box_):
    x0, y0, x1, y1 = box_
    out = set()
    for gx in range(math.floor(x0) // CELL, math.floor(x1) // CELL + 1):
        for gy in range(math.floor(y0) // CELL, math.floor(y1) // CELL + 1):
            out.update(grid.get((gx, gy), ()))
    return out


def parity_at(rows, point):
    """Even-odd parity of `point` (grid units) under the parity segments, by a ray east (half-open in y)."""
    x, y = point
    hit = False
    for a, b in rows.get(math.floor(y) // CELL, ()):
        (x1, y1), (x2, y2) = a, b
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def _rows(segments):
    rows = defaultdict(list)
    for a, b in segments:
        for gy in range(min(a[1], b[1]) // CELL, max(a[1], b[1]) // CELL + 1):
            rows[gy].append((a, b))
    return rows


def cell_box(tile, row, col):
    """Cell (row from the north, col from the west) of zoom-12 tile 'z/x/y', in grid units (x0, y0, x1, y1)."""
    _, x, y = map(int, tile.split('/'))
    lon = lambda f: ((x + f) / 2 ** Z * 360 - 180) * UNIT
    lat = lambda f: _lat(y + f) * UNIT
    return lon(col / GRID), lat((row + 1) / GRID), lon((col + 1) / GRID), lat(row / GRID)


def grid_for(tile, edge_index, edge_segments, parity_index, parity_segments, rows, k):
    """The tile's GRID x GRID cells, north row first, as a run-length string of w/l/m."""
    reach_x, reach_y = (EDGE_M + MARGIN_M) / k[0], (EDGE_M + MARGIN_M) / k[1]
    cells = []
    for r in range(GRID):
        for c in range(GRID):
            b = cell_box(tile, r, c)
            wide = (b[0] - reach_x, b[1] - reach_y, b[2] + reach_x, b[3] + reach_y)
            mixed = any(_segment_box_m(k, *edge_segments[n], b) <= EDGE_M + MARGIN_M for n in _near(edge_index, wide))
            mixed = mixed or any(_hits_box(*parity_segments[n], b) for n in _near(parity_index, b))
            cells.append('m' if mixed else 'l' if parity_at(rows, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)) else 'w')
    out, run = [], 1
    for i in range(1, len(cells) + 1):
        if i < len(cells) and cells[i] == cells[i - 1]:
            run += 1
            continue
        out.append(f'{cells[i - 1]}{run}')
        run = 1
    return ''.join(out)


def delta(line):
    out = [line[0][0], line[0][1]]
    for (a, b), (c, d) in zip(line, line[1:]):
        out += [c - a, d - b]
    return out


def build_product(shore, region, source=None):
    """(index, lines) for a published shoreline; lines is None when the product is unavailable."""
    index = {'schema_version': SCHEMA_VERSION, 'product': 'land-water', 'region_id': region['id'],
             'method': 'docs/land-water-method.md',
             'note': 'A planning screen for ranked places, built from the published NOAA CUSP shoreline. It is not a navigation '
                     'boundary, a legal shoreline or a tidal line.',
             'derived_from': source,
             'constants': {'edge_m': EDGE_M, 'margin_m': MARGIN_M, 'unit': UNIT, 'tile_zoom': Z, 'grid': GRID,
                           'join_limit': '2 x HOR_ACC, at a validated zoom-12 tile seam only'},
             'land_corners': (region.get('land_water') or {}).get('land_corners')}
    try:
        built = assemble(shore, region)
    except Unavailable as error:
        return {**index, 'status': 'unavailable', 'causes': [str(error)]}, None
    k = built['k']
    edge_segments = [(a, b) for line in built['edge'] for a, b in zip(line, line[1:])]
    parity_segments = [(a, b) for c in built['parity'] for a, b in zip(c, c[1:])]
    edge_index, parity_index, rows = _index(edge_segments), _index(parity_segments), _rows(parity_segments)
    tiles = {t: grid_for(t, edge_index, edge_segments, parity_index, parity_segments, rows, k) for t in built['served']}
    lines = {'schema_version': SCHEMA_VERSION, 'product': 'land-water-lines', 'region_id': region['id'], 'derived_from': source,
             'unit': UNIT, 'edge': [delta(l) for l in built['edge']], 'parity': [delta(c) for c in built['parity']]}
    return {**index, 'status': 'available', 'causes': [], 'bounds': list(built['units']), 'census': built['counts'],
            'lines': {'sha256': hashlib.sha256(_dump(lines)).hexdigest()}, 'tiles': tiles}, lines


def _dump(data):
    return (json.dumps(data, separators=(',', ':'), ensure_ascii=False) + '\n').encode()


def publish_land_water(root, region, output):
    """Write the product beside the published shoreline; without one, remove stale copies and write nothing.

    The client reads a missing index as unavailable (every place unknown, withheld).
    """
    output = Path(output)
    shoreline, index_path, lines_path = output / 'shoreline.geojson', output / INDEX, output / LINES
    if not shoreline.is_file():
        index_path.unlink(missing_ok=True)
        lines_path.unlink(missing_ok=True)
        return None
    raw = shoreline.read_bytes()
    source = {'path': f"regions/{region['id']}/shoreline.geojson", 'sha256': hashlib.sha256(raw).hexdigest()}
    index, lines = build_product(json.loads(raw), region, source)
    if lines is None:
        lines_path.unlink(missing_ok=True)
    else:
        lines_path.write_bytes(_dump(lines))
    index_path.write_bytes(_dump(index))
    return index


if __name__ == '__main__':
    import sys
    from .contracts import REPO, load_region
    region = load_region(sys.argv[1] if len(sys.argv) > 1 else 'morro-bay')
    index, _ = build_product(read_json(REPO / 'dist/regions' / region['id'] / 'shoreline.geojson'), region)
    print(json.dumps({key: index.get(key) for key in ('status', 'causes', 'census')}, indent=1))
