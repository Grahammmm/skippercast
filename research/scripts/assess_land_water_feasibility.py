#!/usr/bin/env python3
"""Land/water feasibility probe on a published CUSP shoreline (CI6-01B step 0, 2026-10-20).

    PYTHONPATH=src:. python research/scripts/assess_land_water_feasibility.py \
        [--region morro-bay] [--habitat path/to/skippercast-habitat.geojson]

Read-only. It measures whether the published shoreline lines
(dist/regions/<id>/shoreline.geojson, platform/shoreline.py) can be built into
a land/water topology by the rule docs/land-water-method.md proposes, and how
today's ranked waypoints would classify under it. It is evidence for the method
note, not the classifier: the product builder and its tests come after review.

Written against origin/main ad1118ef7 (shoreline unchanged since b2474f6d) and
the reviewed terrain habitat release 4c24f963f09b… (detail sha256 cb4d9cbb…,
fetched through skippercast.com/coast-data/; pass it with --habitat, it is not
committed). Steps, as the note numbers them:

1. Lines: closed (first == last) with at least four positions are rings; closed
   with fewer are zero-area lines (edge only); the rest are open.
2. Open lines chain at exactly equal endpoints (after the 5-decimal rounding).
3. Each remaining dangling endpoint pairs with its mutual-nearest dangling
   endpoint: a join when the gap is at most twice the larger HOR_ACC of the two
   lines, a bridge (straight, with an unknown zone) up to MAX_BRIDGE_M, else
   the region is unavailable.
4. The one path that runs bounds to bounds is the mainland, closed along the
   region bounds through the declared land corners (east for Morro Bay).
5. Even-odd: a point is land when an odd number of closed rings contain it.
6. Coverage: only zoom-12 tiles NOAA served; elsewhere unknown.
7. Edge: within EDGE_M of any line, join or bridge, unknown.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDGE_M = 25
MAX_BRIDGE_M = 100
CELL = 0.002  # degrees, segment index cell


def tile_of(lon, lat, z=12):
    x = int((lon + 180) / 360 * 2 ** z)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z)
    return f'{z}/{x}/{y}'


def box(ring):
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def inside(pt, ring, bb):
    x, y = pt
    if not (bb[1] <= y <= bb[3]) or x > bb[2]:
        return False
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def crosses(p1, p2, p3, p4):
    o = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = o(p3, p4, p1), o(p3, p4, p2), o(p1, p2, p3), o(p1, p2, p4)
    return d1 * d2 < 0 and d3 * d4 < 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--region', default='morro-bay')
    parser.add_argument('--land-corners', default='SE,NE', help='bounds corners on the land side, in order from the mainland path end back to its start')
    parser.add_argument('--habitat', type=Path, help='reviewed terrain habitat GeoJSON (not committed)')
    args = parser.parse_args()
    shore = json.loads((ROOT / 'dist/regions' / args.region / 'shoreline.geojson').read_text())
    prov = shore['provenance']
    W, S, E, N = prov['bounds']
    kx, ky = 111_320 * math.cos(math.radians((S + N) / 2)), 110_540
    dist = lambda a, b: math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * ky)
    on_bounds = lambda p: p[0] in (W, E) or p[1] in (S, N)

    # 1. lines
    lines = [{'c': [tuple(q) for q in line], 'attr': f['properties'].get('ATTRIBUTE'), 'acc': float(f['properties']['HOR_ACC'])}
             for f in shore['features'] for line in f['geometry']['coordinates']]
    closed = [l for l in lines if l['c'][0] == l['c'][-1]]
    rings = [l for l in closed if len(l['c']) >= 4]
    opened = [l for l in lines if l['c'][0] != l['c'][-1]]
    print(f'1. features {len(shore["features"])}, lines {len(lines)}, vertices {sum(len(l["c"]) for l in lines)}: '
          f'closed {len(closed)} (rings with >= 4 positions {len(rings)}, zero-area {len(closed) - len(rings)}), open {len(opened)}')
    print(f'   HOR_ACC per line {dict(Counter(l["acc"] for l in lines))}; display quantisation {prov["display_quantisation_m"]} m')

    # 2. chain at shared endpoints
    ends = defaultdict(list)
    for i, l in enumerate(opened):
        ends[l['c'][0]].append(i)
        ends[l['c'][-1]].append(i)
    degree = Counter(len(v) for v in ends.values())
    shared = sum(len(v) for v in ends.values() if len(v) > 1)
    bounds_ends = [p for p, v in ends.items() if len(v) == 1 and on_bounds(p)]
    print(f'2. open-line endpoints {2 * len(opened)}: shared {shared} (node degrees {dict(degree)}), '
          f'on bounds {len(bounds_ends)}, dangling {sum(1 for p, v in ends.items() if len(v) == 1) - len(bounds_ends)}')
    used, chains = set(), []

    def walk(i, reverse):
        coords, cur = (list(reversed(opened[i]['c'])) if reverse else list(opened[i]['c'])), i
        used.add(i)
        while True:
            nxt = [j for j in ends[coords[-1]] if j != cur and j not in used]
            if not nxt:
                return coords
            j = nxt[0]
            used.add(j)
            coords += (opened[j]['c'] if opened[j]['c'][0] == coords[-1] else list(reversed(opened[j]['c'])))[1:]
            cur = j
    for i, l in enumerate(opened):
        if i not in used and (len(ends[l['c'][0]]) == 1 or len(ends[l['c'][-1]]) == 1):
            chains.append(walk(i, len(ends[l['c'][0]]) != 1))
    for i in range(len(opened)):
        if i not in used:
            chains.append(walk(i, False))
    closed_chains = [c for c in chains if c[0] == c[-1]]
    open_chains = [c for c in chains if c[0] != c[-1]]
    print(f'   chains {len(chains)}: closed {len(closed_chains)}, open {len(open_chains)}')

    # 3. pair dangling endpoints
    acc_at = {p: opened[v[0]]['acc'] for p, v in ends.items() if len(v) == 1}
    dangling = [(ci, k) for ci, c in enumerate(open_chains) for k in (0, -1) if not on_bounds(c[k])]
    at = lambda e: open_chains[e[0]][e[1]]
    nearest = {e: min((f for f in dangling if f != e), key=lambda f: dist(at(e), at(f))) for e in dangling} if len(dangling) > 1 else {}
    pairs = sorted({tuple(sorted((e, nearest[e]))) for e in dangling if nearest.get(nearest.get(e)) == e})
    joins, bridges, unavailable = [], [], []
    for e, f in pairs:
        gap, tol = dist(at(e), at(f)), 2 * max(acc_at[at(e)], acc_at[at(f)])
        row = {'a': at(e), 'b': at(f), 'gap_m': round(gap, 1), 'join_tolerance_m': round(tol, 2), 'closes_own_chain': e[0] == f[0],
               'on_tile_edge': at(e)[0] == at(f)[0] or at(e)[1] == at(f)[1]}
        (joins if gap <= tol else bridges if gap <= MAX_BRIDGE_M else unavailable).append(row)
    unpaired = set(dangling) - {e for p in pairs for e in p}
    print(f'3. joins {[(j["gap_m"], j["join_tolerance_m"], j["closes_own_chain"], j["on_tile_edge"]) for j in joins]} (gap m, tolerance m, closes its own chain, on a tile edge)')
    print(f'   bridges {[(b["gap_m"], b["closes_own_chain"], b["a"], b["b"]) for b in bridges]}; over {MAX_BRIDGE_M} m {len(unavailable)}; unpaired {len(unpaired)}')

    link = {}
    for e, f in pairs:
        link[e], link[f] = f, e
    paths, seen = [], set()
    starts = [(ci, k) for ci, c in enumerate(open_chains) for k in (0, -1) if on_bounds(c[k])] + [(ci, 0) for ci in range(len(open_chains))]
    for ci, k in starts:
        if ci in seen:
            continue
        path = []
        while True:
            seen.add(ci)
            path += open_chains[ci] if k == 0 else list(reversed(open_chains[ci]))
            other = (ci, -1 if k == 0 else 0)
            if other not in link:
                break
            ci, k = link[other]
            if ci in seen:
                path.append(open_chains[ci][k])
                break
        paths.append(path)
    mainland = [p for p in paths if on_bounds(p[0]) and on_bounds(p[-1])]
    loops = [p for p in paths if p not in mainland]
    print(f'4. bounds-to-bounds paths {len(mainland)} (ends {[(p[0], p[-1]) for p in mainland]}, {[len(p) for p in mainland]} vertices); '
          f'closed loops from joins/bridges {len(loops)} ({[len(p) for p in loops]} positions)')
    corners = {'NE': (E, N), 'SE': (E, S), 'SW': (W, S), 'NW': (W, N)}

    def close(path, names):
        a, b = path[0], path[-1]
        assert a[1] == N and b[1] == S, 'probe handles a north-to-south mainland only'
        return path + [corners[n] for n in names] + [a]
    other = 'SW,NW' if args.land_corners == 'SE,NE' else 'SE,NE'
    others = [l['c'] for l in rings] + closed_chains + [p + [p[0]] for p in loops]

    def classifier(names):
        polys = [(close(mainland[0], names), None)] + [(r, None) for r in others]
        polys = [(r, box(r)) for r, _ in polys]
        return polys, lambda pt, skip=None: sum(1 for i, (r, bb) in enumerate(polys) if i != skip and inside(pt, r, bb)) % 2

    # segment index for edges and crossings
    segs, owner = [], []
    for li, l in enumerate(lines):
        for a, b in zip(l['c'], l['c'][1:]):
            segs.append((a, b))
            owner.append(li)
    for j in joins + bridges:
        segs.append((j['a'], j['b']))
        owner.append(-1)
    grid = defaultdict(list)
    for si, (a, b) in enumerate(segs):
        for gx in range(int(min(a[0], b[0]) // CELL), int(max(a[0], b[0]) // CELL) + 1):
            for gy in range(int(min(a[1], b[1]) // CELL), int(max(a[1], b[1]) // CELL) + 1):
                grid[(gx, gy)].append(si)

    def seg_dist(p, a, b):
        ax, ay, bx, by, px, py = a[0] * kx, a[1] * ky, b[0] * kx, b[1] * ky, p[0] * kx, p[1] * ky
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0 if length == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / length))
        return math.hypot(px - ax - t * dx, py - ay - t * dy)

    def shore_m(p, reach=3):
        gx, gy = int(p[0] // CELL), int(p[1] // CELL)
        return min((seg_dist(p, *segs[s]) for i in range(gx - reach, gx + reach + 1) for j in range(gy - reach, gy + reach + 1)
                    for s in grid.get((i, j), ())), default=math.inf)  # inf: farther than ~3 cells (~ 540 m)

    polys, parity = classifier(args.land_corners.split(','))
    in_land = [(i, r) for i, (r, bb) in enumerate(polys[1:], start=1) if parity(r[0], skip=i)]
    print(f'5. closed rings and loops: {len(polys) - 1}; lying in water (bound land) {len(polys) - 1 - len(in_land)}, '
          f'lying in land (bound water) {len(in_land)}: {[(len(r), round(max(dist(r[0], q) for q in r), 1), box(r) if len(r) > 10 else "") for i, r in in_land]}')

    crossings = set()
    for ids in grid.values():
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                i, j = ids[x], ids[y]
                if owner[i] != owner[j] and -1 not in (owner[i], owner[j]) and crosses(*segs[i], *segs[j]):
                    crossings.add((min(i, j), max(i, j)))
    kind = lambda l: 'ring' if l in rings else 'zero-area' if l['c'][0] == l['c'][-1] else 'open'
    print(f'   proper crossings between different lines: {len(crossings)}; kinds {dict(Counter(tuple(sorted((kind(lines[owner[i]]), kind(lines[owner[j]])))) for i, j in crossings))}; '
          f'longest crossing segment {max((max(dist(*segs[i]), dist(*segs[j])) for i, j in crossings), default=0):.1f} m')

    served = {r['tile'] for r in prov['tile_receipts']}
    print(f'6. tiles served {len(served)} of {prov["requested_tiles"]} requested ({len(prov["unavailable_tiles"])} unavailable)')

    waypoints = [('atlas', t['id'], t['longitude'], t['latitude']) for t in json.loads((ROOT / 'dist/data/atlas.json').read_text())['targets']]
    if args.habitat:
        waypoints += [('terrain', f.get('id') or f['properties'].get('id'), f['properties']['waypoint_longitude'], f['properties']['waypoint_latitude'])
                      for f in json.loads(args.habitat.read_text())['features']
                      if f['properties'].get('region') == args.region and isinstance(f['properties'].get('waypoint_latitude'), (int, float))]
    _, wrong = classifier(other.split(','))
    out, near = Counter(), []
    for source, pid, x, y in waypoints:
        p = (x, y)
        if not (W <= x <= E and S <= y <= N):
            state = 'unknown:outside-bounds'
        elif tile_of(x, y) not in served:
            state = 'unknown:unserved-tile'
        else:
            m = shore_m(p)
            near.append(m)
            state = 'unknown:edge' if m <= EDGE_M else 'land' if parity(p) else 'water'
        out[(source, state)] += 1
        if state != 'water':
            print(f'   exception {source} {pid} ({x}, {y}) tile {tile_of(x, y)}: {state}')
    print(f'7. waypoints {dict(Counter(s for s, *_ in waypoints))}: {dict(out)}')
    print(f'   nearest shoreline line from a classified waypoint: {min(near):.1f} m; within 50 m: {sum(1 for m in near if m <= 50)}')
    print(f'   with the opposite closure ({other}): on land {sum(wrong((x, y)) for _, _, x, y in waypoints)} of {len(waypoints)}')


if __name__ == '__main__':
    main()
