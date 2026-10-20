#!/usr/bin/env python3
"""Land/water feasibility probe on a published CUSP shoreline (CI6-01B step 0, 2026-10-20, round 2).

    PYTHONPATH=src:. python research/scripts/assess_land_water_feasibility.py \\
        [--region morro-bay] [--habitat path/to/skippercast-habitat.geojson]
    PYTHONPATH=src:. python research/scripts/assess_land_water_feasibility.py --self-test

Read-only. It measures whether the published shoreline lines
(dist/regions/<id>/shoreline.geojson, platform/shoreline.py) can be built into
a land/water topology by the rule docs/land-water-method.md proposes, and how
today's ranked waypoints would classify under it. It is evidence for the method
note, not the classifier: the product builder and its tests come after review.
--self-test runs the same rules on small injected geometries (the review's
50 m headland gap, a bowtie, crossing rings, a spike, a curl, a touch).

Written against origin/main ad1118ef7 (shoreline unchanged since b2474f6d) and
the reviewed terrain habitat release 4c24f963f09b… (detail sha256 cb4d9cbb…,
fetched through skippercast.com/coast-data/; pass it with --habitat, it is not
committed). Every topology test is exact: coordinates are compared as integers
on the published 5-decimal grid (1e-5 degree units), so no tolerance decides a
crossing, a touch or a shared endpoint. Steps, as the note numbers them:

1. Lines: at least two positions, finite numbers; repeated consecutive
   positions are dropped. Closed (first == last) or open.
2. Open lines chain at exactly equal endpoints; a node of degree 3+ fails.
3. Each dangling endpoint pairs with its mutual-nearest dangling endpoint. Two
   chains are joined only at a tile seam: both ends on one zoom-12 tile edge,
   the two lines from the two served tiles either side of it, the gap at most
   twice the larger HOR_ACC. A chain whose own ends pair is kept only when its
   closure is degenerate (step 5). There are no bridges: any other gap makes
   the product unavailable.
4. The one path that runs bounds to bounds is the mainland, closed along the
   region bounds through the declared land corners (east for Morro Bay).
5. Degenerate closed curves (all positions collinear, or at most EDGE_M
   across) are edge-only: they change the parity of no point outside the band.
6. Defects: every proper crossing, touch, overlap and retrace within or between
   the remaining closed curves, joins and bounds closure included. A retrace,
   or a sub-loop at a self-defect that is collinear or at most EDGE_M across,
   is removed and the census re-run until nothing removable is left. Touches
   that do not cross may stay. Anything else makes the product unavailable.
7. Even-odd parity; coverage from the served zoom-12 tiles; the EDGE_M band.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDGE_M = 25
UNIT = 10 ** 5  # published coordinates have 5 decimals
CELL = 200  # grid units (0.002 degrees) per segment-index cell
Z = 12


def tile_of(lon, lat, z=Z):
    x = int((lon + 180) / 360 * 2 ** z)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z)
    return f'{z}/{x}/{y}'


def tile_lon(x, z=Z):
    return round((x / 2 ** z * 360 - 180) * UNIT)


def tile_lat(y, z=Z):
    return round(math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z)))) * UNIT)


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


def box(ring):
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def across(k, points):
    bb = box(points)
    return distance(k, bb[:2], bb[2:])


def degenerate(k, curve):
    """'collinear' or 'small' (at most EDGE_M across) when no point outside the edge band can change parity, else None.

    A closed curve's parity contribution is zero off its own line when it is
    collinear, and zero outside its bounding box otherwise; every point of a box
    at most EDGE_M across lies within EDGE_M of the curve's own vertices.
    """
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
        row = {'kind': kind, 'scope': 'self' if ci == cj else 'between', 'curves': (curves[ci][0], curves[cj][0]), 'ids': (ci, cj), 'at': x,
               'witness': None, 'remove': None}
        if kind == 'retrace':
            row['witness'] = 'retrace'
            row['remove'] = ('vertex', ci, (si + 1) if sj - si == 1 else 0)
        elif kind == 'touch' and transversal(s, t, x) is False:
            row['witness'] = 'touch without crossing'
        elif ci == cj:
            c = curves[ci][1][:-1]
            inner, outer = [x] + c[si + 1:sj + 1] + [x], [x] + c[sj + 1:] + c[:si + 1] + [x]
            row['loops_m'] = (round(across(k, inner), 1), round(across(k, outer), 1))
            for name, loop in (('inner', inner), ('outer', outer)):
                if collinear(loop) or across(k, loop) <= EDGE_M:
                    row['witness'] = f'{name} sub-loop {"collinear" if collinear(loop) else f"{across(k, loop):.1f} m across"}'
                    row['remove'] = ('loop', ci, si, sj, x, name)
                    break
        if row['witness'] is None and kind != 'proper':
            row['contact'] = {True: 'crosses', None: 'runs together'}.get(transversal(s, t, x))
        out.append(row)
    return out


def witness_kind(row):
    w = row['witness']
    return 'NO WITNESS' if w is None else w.split(' sub-loop')[0] + ' sub-loop' if 'sub-loop' in w else w


def resolve(k, curves, limit=10_000):
    """Remove retraces and witnessed sub-loops one at a time, re-running the census, until none is left.

    Returns (curves, first census, removals, defects left). No removal changes
    the parity of a point farther than EDGE_M from the lines (see degenerate()).
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
    raise RuntimeError('defect removal did not converge')


def seam_problem(k, a, b, line_a, line_b, served):
    """Why the gap a-b between two chains is not a zoom-12 tile seam, or None when it is one."""
    if not (line_a.get('tile') and line_b.get('tile')):
        return 'no source tile'
    (_, xa, ya), (_, xb, yb) = (map(int, line['tile'].split('/')) for line in (line_a, line_b))
    if abs(xa - xb) + abs(ya - yb) != 1:
        return f'tiles {line_a["tile"]} and {line_b["tile"]} are not edge neighbours'
    if not {line_a['tile'], line_b['tile']} <= served:
        return 'a tile was not served'
    axis, edge = (0, tile_lon(max(xa, xb))) if xa != xb else (1, tile_lat(max(ya, yb)))
    if not a[axis] == b[axis] == edge:
        return 'ends not on the shared tile edge'
    limit = 2 * max(line_a['acc'], line_b['acc'])
    if distance(k, a, b) > limit:
        return f'gap {distance(k, a, b):.1f} m over 2 x HOR_ACC {limit:.2f} m'
    return None


def inside(pt, ring, bb):
    x, y = pt
    if not (bb[1] <= y <= bb[3]) or x > bb[2]:
        return False
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def report(rows, label):
    summary = Counter((r['scope'], r['kind'], '/'.join(sorted(set(r['curves']))), witness_kind(r)) for r in rows)
    print(f'{label}: {len(rows)}')
    for key, v in sorted(summary.items()):
        print(f'   {v:4d} {key}')


def self_test():
    """The rules on injected geometry (metres near 35.4 N), each with the result it must give."""
    k = metres_per_unit(35.4)
    m = lambda pts: [(round(x / k[0]), round(y / k[1])) for x, y in pts]
    ring = lambda pts: m(pts + pts[:1])
    checks, detail = [], []

    def case(label, got, want):
        checks.append(got == want)
        print(f'   {"ok  " if got == want else "FAIL"} {label}: {got}')
        while detail:
            print(detail.pop())

    def outcome(curves):
        curves = [(n, c) for n, c in curves if not degenerate(k, c)]
        _, first, removals, left = resolve(k, curves)
        bad = [r for r in left if r['witness'] is None]
        detail.append(f'        census {dict(Counter(witness_kind(r) for r in first))}; removed {dict(removals)}; '
                      f'left {dict(Counter(witness_kind(r) for r in left))}')
        return 'unavailable' if bad else 'available'
    t = {'tile': '12/671/1616', 'acc': 4.31}
    case('50 m mid-tile coast gap, the review counterexample: joined?', seam_problem(k, m([(0, 0)])[0], m([(0, 50)])[0], t, t, {t['tile']}) is None, False)
    case('6 m mid-tile coast gap: joined?', seam_problem(k, m([(0, 0)])[0], m([(0, 6)])[0], t, t, {t['tile']}) is None, False)
    edge = tile_lat(1616)
    a, b = (-12_100_000, edge), (-12_099_993, edge)  # 7 units of longitude, about 6.4 m, on a row edge
    north, south = {'tile': '12/671/1615', 'acc': 4.31}, {'tile': '12/671/1616', 'acc': 4.31}
    case('6.4 m gap on the shared tile edge, both tiles served: problem', seam_problem(k, a, b, north, south, {'12/671/1615', '12/671/1616'}), None)
    case('the same gap with one tile not served: joined?', seam_problem(k, a, b, north, south, {'12/671/1616'}) is None, False)
    case('the same tiles, gap 20 m: joined?', seam_problem(k, a, (a[0] + 22, edge), north, south, {'12/671/1615', '12/671/1616'}) is None, False)
    case('2-position line closed on itself (56 m)', degenerate(k, m([(0, 0), (56, 0), (0, 0)])), 'collinear')
    case('10 m bowtie ring', degenerate(k, ring([(0, 0), (10, 10), (0, 10), (10, 0)])), 'small')
    case('200 m bowtie ring (even-odd would call its side triangles water)', outcome([('ring', ring([(0, 0), (200, 200), (0, 200), (200, 0)]))]), 'unavailable')
    case('500 m ring with a 10 m curl crossing itself', outcome([('ring', ring([(0, 0), (500, 0), (500, 500), (240, 500), (240, 510), (250, 510), (250, 495), (0, 495)]))]),
         'available')
    case('500 m ring with a 100 m spike (retrace)', outcome([('ring', ring([(0, 0), (500, 0), (500, 250), (600, 250), (500, 250), (500, 500), (0, 500)]))]), 'available')
    case('500 m ring with a 100 m loop crossing itself', outcome([('ring', ring([(0, 0), (500, 0), (500, 500), (200, 500), (200, 600), (300, 600), (300, 450), (0, 450)]))]),
         'unavailable')
    case('two 300 m rings crossing', outcome([('ring', ring([(0, 0), (300, 0), (300, 300), (0, 300)])), ('ring', ring([(150, 150), (450, 150), (450, 450), (150, 450)]))]),
         'unavailable')
    case('island touching the mainland at one vertex, not crossing',
         outcome([('ring', ring([(0, 0), (300, 0), (300, 300), (0, 300)])), ('ring', ring([(300, 100), (500, 0), (500, 200)]))]), 'available')
    case('island crossing the mainland',
         outcome([('ring', ring([(0, 0), (300, 0), (300, 300), (0, 300)])), ('ring', ring([(300, 100), (500, 0), (100, 50)]))]), 'unavailable')
    print(f'self-test {"passed" if all(checks) else "FAILED"}: {sum(checks)} of {len(checks)}')
    return all(checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--region', default='morro-bay')
    parser.add_argument('--land-corners', default='SE,NE', help='bounds corners on the land side, in order from the mainland path end back to its start')
    parser.add_argument('--habitat', type=Path, help='reviewed terrain habitat GeoJSON (not committed)')
    parser.add_argument('--self-test', action='store_true', help='run the rules on injected geometry only')
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(0 if self_test() else 1)
    shore = json.loads((ROOT / 'dist/regions' / args.region / 'shoreline.geojson').read_text())
    prov = shore['provenance']
    W, S, E, N = (round(v * UNIT) for v in prov['bounds'])
    k = metres_per_unit((S + N) / 2 / UNIT)
    dist = lambda a, b: distance(k, a, b)
    on_bounds = lambda p: p[0] in (W, E) or p[1] in (S, N)
    served = {r['tile'] for r in prov['tile_receipts']}
    unavailable = []

    # 1. lines
    lines, malformed, repeats = [], [], 0
    for f in shore['features']:
        for raw in f['geometry']['coordinates']:
            if len(raw) < 2 or any(len(q) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in q) for q in raw):
                malformed.append(f.get('id'))
                continue
            c = [(round(x * UNIT), round(y * UNIT)) for x, y in raw]
            kept = [c[0]] + [q for p, q in zip(c, c[1:]) if q != p]
            repeats += len(c) - len(kept)
            lines.append({'c': kept, 'attr': f['properties'].get('ATTRIBUTE'), 'acc': float(f['properties']['HOR_ACC']),
                          'tile': f['properties'].get('source_tile')})
    if malformed:
        unavailable.append(f'malformed lines {len(malformed)}')
    closed = [l for l in lines if l['c'][0] == l['c'][-1]]
    opened = [l for l in lines if l['c'][0] != l['c'][-1]]
    print(f'1. features {len(shore["features"])}, lines {len(lines)}, vertices {sum(len(l["c"]) for l in lines)} '
          f'(repeated consecutive positions dropped {repeats}); closed {len(closed)}, open {len(opened)}; malformed {len(malformed)}')
    print(f'   HOR_ACC per line {dict(Counter(l["acc"] for l in lines))}; display quantisation {prov["display_quantisation_m"]} m')

    # 2. chain at shared endpoints
    ends = defaultdict(list)
    for i, l in enumerate(opened):
        ends[l['c'][0]].append(i)
        ends[l['c'][-1]].append(i)
    if any(len(v) > 2 for v in ends.values()):
        unavailable.append('node of degree 3+')
    bounds_ends = [p for p, v in ends.items() if len(v) == 1 and on_bounds(p)]
    print(f'2. open-line endpoints {2 * len(opened)}: shared {sum(len(v) for v in ends.values() if len(v) > 1)} '
          f'(node degrees {dict(Counter(len(v) for v in ends.values()))}), on bounds {len(bounds_ends)}, '
          f'dangling {sum(1 for v in ends.values() if len(v) == 1) - len(bounds_ends)}')
    used, chains = set(), []

    def walk(i, reverse):
        coords, cur, members = (list(reversed(opened[i]['c'])) if reverse else list(opened[i]['c'])), i, [i]
        used.add(i)
        while True:
            nxt = [j for j in ends[coords[-1]] if j != cur and j not in used]
            if not nxt:
                return {'c': coords, 'lines': members}
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
    print(f'   chains {len(chains)}: closed {len(closed_chains)}, open {len(open_chains)}')

    # 3. pair dangling endpoints: seam joins only, no bridges
    end_line = lambda e: opened[open_chains[e[0]]['lines'][0 if e[1] == 0 else -1]]
    at = lambda e: open_chains[e[0]]['c'][e[1]]
    dangling = [(ci, j) for ci, c in enumerate(open_chains) for j in (0, -1) if not on_bounds(c['c'][j])]
    nearest = {e: min((f for f in dangling if f != e), key=lambda f: dist(at(e), at(f))) for e in dangling} if len(dangling) > 1 else {}
    pairs = sorted({tuple(sorted((e, nearest[e]))) for e in dangling if nearest.get(nearest.get(e)) == e})
    joins, edge_only_chains, link = [], [], {}
    for e, f in pairs:
        gap = dist(at(e), at(f))
        if e[0] == f[0]:
            loop = open_chains[e[0]]['c'] + [at(e)]
            kind = degenerate(k, loop)
            if kind:
                edge_only_chains.append(e[0])
            else:
                unavailable.append(f'non-degenerate unclosed loop, gap {gap:.1f} m')
            print(f'3. own-chain pair: gap {gap:.1f} m, {len(loop) - 1} positions, tile {end_line(e)["tile"]}, '
                  f'closure {kind or "NOT degenerate"} -> {"edge-only" if kind else "unavailable"}')
            continue
        why = seam_problem(k, at(e), at(f), end_line(e), end_line(f), served)
        print(f'3. inter-chain pair: gap {gap:.1f} m (2 x HOR_ACC {2 * max(end_line(e)["acc"], end_line(f)["acc"]):.2f} m), '
              f'tiles {end_line(e)["tile"]} | {end_line(f)["tile"]}, ends ({at(e)[0] / UNIT}, {at(e)[1] / UNIT}) and '
              f'({at(f)[0] / UNIT}, {at(f)[1] / UNIT}): {"seam join" if why is None else "REJECTED, " + why}')
        if why is None:
            joins.append((at(e), at(f)))
            link[e], link[f] = f, e
        else:
            unavailable.append(f'gap not a tile seam ({why})')
    unpaired = set(dangling) - {x for p in pairs for x in p}
    if unpaired:
        unavailable.append(f'unpaired endpoints {len(unpaired)}')
    print(f'   joins {len(joins)}, edge-only chains {len(edge_only_chains)}, unpaired {len(unpaired)}, bridges 0 (none allowed)')

    # 4. assemble paths and the mainland
    paths, seen = [], set(edge_only_chains)
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
    mainland = [p for p in paths if on_bounds(p[0]) and on_bounds(p[-1])]
    loops = [p for p in paths if p not in mainland]
    if len(mainland) != 1:
        unavailable.append(f'bounds-to-bounds paths {len(mainland)}')
    print(f'4. bounds-to-bounds paths {len(mainland)} ({[len(p) for p in mainland]} positions); closed loops from seam joins {len(loops)}')
    corners = {'NE': (E, N), 'SE': (E, S), 'SW': (W, S), 'NW': (W, N)}

    def close(path, names):
        a, b = path[0], path[-1]
        assert a[1] == N and b[1] == S, 'probe handles a north-to-south mainland only'
        return path + [corners[n] for n in names] + [a]

    # 5. curves for parity; degenerate ones are edge-only
    curves = [('mainland', close(mainland[0], args.land_corners.split(',')))] if len(mainland) == 1 else []
    curves += [('ring', l['c']) for l in closed] + [('chain', c['c']) for c in closed_chains] + [('seam loop', p + [p[0]]) for p in loops]
    kinds = Counter((name, degenerate(k, c)) for name, c in curves)
    parity_curves = [(name, c) for name, c in curves if not degenerate(k, c)]
    print(f'5. closed curves {len(curves)}: {dict(kinds)} (None = enters parity)')
    everything = census(k, curves)
    between = [r for r in everything if r['scope'] == 'between']
    sizes = [min(across(k, curves[i][1]) for i in r['ids']) for r in between]
    print(f'   census over all {len(curves)} closed curves, edge-only ones included: {len(everything)} defects; between two curves '
          f'{dict(Counter(r["kind"] for r in between))}, each involving an edge-only curve: '
          f'{all(any(degenerate(k, curves[i][1]) for i in r["ids"]) for r in between)}, smaller curve at most {max(sizes, default=0):.1f} m across')

    # 6. defect census, removal of witnessed defects, census again
    resolved, first, removals, left = resolve(k, parity_curves)
    report(first, f'6. defects among {len(parity_curves)} parity curves ({sum(len(c) - 1 for _, c in parity_curves)} segments)')
    for r in first:
        if r['kind'] != 'retrace':
            print(f'      {r["scope"]} {r["kind"]} {"/".join(r["curves"])} at ({r["at"][0] / UNIT:.5f}, {r["at"][1] / UNIT:.5f}): '
                  f'{r["witness"] or "NO WITNESS"}{", sub-loops " + str(r["loops_m"]) + " m across" if "loops_m" in r else ""}'
                  f'{", " + r["contact"] if r.get("contact") else ""}')
    print(f'   removed {dict(removals)}; parity curves after removal {len(resolved)}')
    report(left, '   defects left')
    gross = [r for r in left if r['witness'] is None]
    if gross:
        unavailable.append(f'defects without a local witness {len(gross)}')

    # 7. parity, coverage, waypoints
    def classifier(names, source):
        polys = [close(mainland[0], names)] + [c for name, c in source if name != 'mainland']
        polys = [[(x / UNIT, y / UNIT) for x, y in r] for r in polys]
        polys = [(r, box(r)) for r in polys]
        return polys, lambda pt, skip=None: sum(1 for i, (r, bb) in enumerate(polys) if i != skip and inside(pt, r, bb)) % 2
    other = 'SW,NW' if args.land_corners == 'SE,NE' else 'SE,NE'
    polys, parity = classifier(args.land_corners.split(','), parity_curves)
    _, parity_after = classifier(args.land_corners.split(','), resolved)
    in_land = [r for i, (r, bb) in enumerate(polys[1:], start=1) if parity(r[0], skip=i)]
    print(f'7. parity curves besides the mainland {len(polys) - 1}: lying in water (bound land) {len(polys) - 1 - len(in_land)}, '
          f'lying in land (bound water) {len(in_land)} {[(len(r), box(r)) for r in in_land]}')
    print(f'   tiles served {len(served)} of {prov["requested_tiles"]} requested ({len(prov["unavailable_tiles"])} unavailable)')

    band = [(a, b) for l in lines for a, b in zip(l['c'], l['c'][1:])] + joins
    fgrid = defaultdict(list)
    for n, (a, b) in enumerate(band):
        for gx in range(min(a[0], b[0]) // CELL, max(a[0], b[0]) // CELL + 1):
            for gy in range(min(a[1], b[1]) // CELL, max(a[1], b[1]) // CELL + 1):
                fgrid[(gx, gy)].append(n)

    def seg_dist(p, a, b):
        ax, ay, bx, by, px, py = a[0] * k[0], a[1] * k[1], b[0] * k[0], b[1] * k[1], p[0] * k[0], p[1] * k[1]
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0 if length == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / length))
        return math.hypot(px - ax - t * dx, py - ay - t * dy)

    def shore_m(p, reach=3):
        gx, gy = int(p[0] // CELL), int(p[1] // CELL)
        return min((seg_dist(p, *band[s]) for i in range(gx - reach, gx + reach + 1) for j in range(gy - reach, gy + reach + 1)
                    for s in fgrid.get((i, j), ())), default=math.inf)  # inf: farther than ~3 cells (~ 540 m)

    waypoints = [('atlas', t['id'], t['longitude'], t['latitude']) for t in json.loads((ROOT / 'dist/data/atlas.json').read_text())['targets']]
    if args.habitat:
        waypoints += [('terrain', f.get('id') or f['properties'].get('id'), f['properties']['waypoint_longitude'], f['properties']['waypoint_latitude'])
                      for f in json.loads(args.habitat.read_text())['features']
                      if f['properties'].get('region') == args.region and isinstance(f['properties'].get('waypoint_latitude'), (int, float))]
    _, wrong = classifier(other.split(','), parity_curves)
    out, near, differ = Counter(), [], 0
    for source, pid, x, y in waypoints:
        if not (W <= x * UNIT <= E and S <= y * UNIT <= N):
            state = 'unknown:outside-bounds'
        elif unavailable:
            state = 'unknown:unavailable'
        elif tile_of(x, y) not in served:
            state = 'unknown:unserved-tile'
        else:
            m = shore_m((x * UNIT, y * UNIT))
            near.append(m)
            state = 'unknown:edge' if m <= EDGE_M else 'land' if parity((x, y)) else 'water'
            differ += parity((x, y)) != parity_after((x, y))
        out[(source, state)] += 1
        if state != 'water':
            print(f'   exception {source} {pid} ({x}, {y}) tile {tile_of(x, y)}: {state}')
    print(f'   waypoints {dict(Counter(s for s, *_ in waypoints))}: {dict(out)}')
    if near:
        print(f'   nearest shoreline line from a classified waypoint: {min(near):.1f} m; within 50 m: {sum(1 for m in near if m <= 50)}; '
              f'parity changed by defect removal: {differ}')
    print(f'   with the opposite closure ({other}): on land {sum(wrong((x, y)) for _, _, x, y in waypoints)} of {len(waypoints)}')
    print(f'PRODUCT {"UNAVAILABLE: " + "; ".join(unavailable) if unavailable else "AVAILABLE"}')


if __name__ == '__main__':
    main()
