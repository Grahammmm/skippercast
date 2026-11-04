// Charted routes (FSC-04, web/route.ts): a water-only route from the harbor to a chosen place on the region's
// land-water product. Synthetic products reuse the land-water fixture's constants (tests/fixtures/land-water/
// coast.json) with painted zoom-12 grids, so every case is offline; then the committed Morro Bay product.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {distanceNm} from '../dist/spot-ranking.js';
import {decodeCells, landWaterLines, landWaterModel, placeOf} from '../web/land-water.ts';
import {MAX_NODES, SNAP_M, waterRoute} from '../web/route.ts';

const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/land-water/${name}`, import.meta.url), 'utf8'));
const dist = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const coast = fixture('coast.json'), COAST = '12/671/1616';
const coastLines = landWaterLines(fixture('coast.lines.json'), landWaterModel(coast, 'fixture'));

// Zoom-12 tile 671/1616 holds the fixture; cell (col, row) of tile (tx, ty) and its centre.
const N = 4096, G = 32;
const lonOf = fx => fx / N * 360 - 180;
const latOf = fy => Math.atan(Math.sinh(Math.PI * (1 - 2 * fy / N))) * 180 / Math.PI;
const cell = (col, row, tx = 671, ty = 1616) => ({latitude: latOf(ty + (row + 0.5) / G), longitude: lonOf(tx + (col + 0.5) / G)});
// A 32×32 grid from `base` (all water, or decoded cells) with [char, col0, row0, col1, row1] rectangles painted in.
const paint = (rects, base = 'w'.repeat(G * G)) => {
  const a = [...base];
  for (const [c, c0, r0, c1, r1] of rects) for (let r = r0; r <= r1; r++) for (let k = c0; k <= c1; k++) a[r * G + k] = c;
  return a.join('').replace(/(.)\1*/g, m => m[0] + m.length);
};
const WIDE = [-12110000, 3530000, -12075000, 3555000];
const product = (tiles, bounds = WIDE) => landWaterModel({...coast, bounds, tiles}, 'fixture');
const coastGrid = rects => product({[COAST]: paint(rects, decodeCells(coast.tiles[COAST], G * G))}, coast.bounds);
const why = r => r.ok ? `ok ${r.nm} nm` : r.reason;

/** Sample points along a polyline at 1/8 sub-cell (twice as dense as the route's own 1/4 checks), interpolated in the grid's own (Mercator) space. */
function* along(points) {
  const fx = p => (p.longitude + 180) / 360 * N, fy = p => (1 - Math.asinh(Math.tan(p.latitude * Math.PI / 180)) / Math.PI) / 2 * N;
  for (const [i, p] of points.entries()) {
    yield [`point ${i}`, p];
    if (!i) continue;
    const q = points[i - 1], steps = Math.ceil(Math.max(Math.abs(fx(p) - fx(q)), Math.abs(fy(p) - fy(q))) * G * 32);
    for (let k = 1; k < steps; k++) yield [`segment ${i} sample ${k}/${steps}`, {latitude: latOf(fy(q) + (fy(p) - fy(q)) * k / steps), longitude: lonOf(fx(q) + (fx(p) - fx(q)) * k / steps)}];
  }
}

/** Every returned point and every sample along each segment classifies water. */
function allWater(model, lines, points) {
  for (const [what, p] of along(points)) assert.equal(placeOf(model, lines, p).state, 'water', what);
}

/** The polyline passes through a cell of `state` (checked on the segments, not only the vertices). */
const passes = (model, points, state) => [...along(points)].some(([, p]) => placeOf(model, null, p).state === state);

test('open water across a tile seam: within 8 % of the straight line and never below it', () => {
  const model = product({'12/671/1616': paint([]), '12/672/1616': paint([])});
  const from = cell(4, 12), to = cell(28, 20, 672), r = waterRoute(model, null, from, to), straight = distanceNm(from, to);
  assert.ok(r.ok, JSON.stringify(r));
  assert.ok(r.nm >= straight && r.nm <= straight * 1.08, `${r.nm} vs ${straight}`);
  assert.ok(r.points.some(p => p.longitude < lonOf(672)) && r.points.some(p => p.longitude > lonOf(672)), 'crosses the seam');
  allWater(model, null, r.points);
  assert.equal(MAX_NODES, 400_000);
  assert.equal(SNAP_M, 300);
});

test('a headland between the ends: the route goes around it, every point and midpoint water', () => {
  const model = product({[COAST]: paint([['l', 10, 0, 21, 23]])});
  const from = cell(4, 8), to = cell(28, 8), r = waterRoute(model, null, from, to);
  assert.ok(r.ok, JSON.stringify(r));
  allWater(model, null, r.points);
  assert.ok(r.points.some(p => p.latitude < latOf(1616 + 24 / G)), 'passes south of the headland');
  assert.ok(r.nm > distanceNm(from, to) * 1.5, `${r.nm}`);
});

test('two land cells touching at a corner: no path through the corner', () => {
  const from = cell(16, 4), to = cell(16, 28);
  const corner = product({[COAST]: paint([['l', 0, 16, 15, 16], ['l', 16, 17, 31, 17]])});
  assert.equal(why(waterRoute(corner, null, from, to)), 'no-route');
  const gap = product({[COAST]: paint([['l', 0, 16, 15, 16], ['l', 17, 17, 31, 17]])});
  const r = waterRoute(gap, null, from, to);
  assert.ok(r.ok, 'a one-cell gap is a passage');
  allWater(gap, null, r.points);
});

test('land separating the ends is no-route; a node budget too small is too-far', () => {
  const wall = product({[COAST]: paint([['l', 0, 16, 31, 16]])});
  assert.equal(why(waterRoute(wall, null, cell(16, 4), cell(16, 28))), 'no-route');
  const open = product({[COAST]: paint([])});
  assert.equal(why(waterRoute(open, null, cell(2, 2), cell(29, 29), 10)), 'too-far');
  assert.ok(waterRoute(open, null, cell(2, 2), cell(29, 29)).ok);
});

test('ends that are not water: land beyond SNAP_M, an unserved tile, outside bounds, no position, no product', () => {
  const model = product({[COAST]: paint([['l', 0, 0, 15, 31]])}), water = cell(24, 16);
  assert.equal(why(waterRoute(model, null, cell(4, 16), water)), 'start-not-water');
  assert.equal(why(waterRoute(model, null, water, cell(16, 16, 672))), 'end-not-water');
  assert.equal(why(waterRoute(model, null, water, {latitude: 35.6, longitude: -120.95})), 'end-not-water');
  assert.equal(why(waterRoute(model, null, {latitude: NaN, longitude: -120.95}, water)), 'start-not-water');
  assert.equal(why(waterRoute(model, null, water, null)), 'end-not-water');
  assert.equal(why(waterRoute(null, null, water, water)), 'no-product');
  // A berth on the shore (land within SNAP_M of water) snaps to the nearest water centre.
  const berth = cell(15, 16), r = waterRoute(model, null, berth, water);
  assert.ok(r.ok, JSON.stringify(r));
  assert.ok(distanceNm(berth, r.points[0]) * 1852 <= SNAP_M && r.nm >= distanceNm(berth, water));
  allWater(model, null, r.points);
});

test('mixed cells as the only passage: lines-needed without lines, a route with them, never one when they failed', () => {
  // The fixture coast with a land wall across row 22, open only through two mixed cells in open water.
  const model = coastGrid([['l', 0, 22, 31, 22], ['m', 17, 22, 18, 22]]);
  const from = cell(14, 12), to = cell(14, 25);
  assert.equal(why(waterRoute(model, null, from, to)), 'lines-needed');
  assert.equal(why(waterRoute(model, false, from, to)), 'no-route');
  const r = waterRoute(model, coastLines, from, to);
  assert.ok(r.ok, JSON.stringify(r));
  allWater(model, coastLines, r.points);
  assert.ok(passes(model, r.points, 'unknown'), 'the route passes the mixed cells');
  assert.ok(r.nm > distanceNm(from, to));
});

test('a start or end only mixed cells reach needs the lines', () => {
  const model = coastGrid([['m', 14, 11, 18, 17]]), inMixed = cell(16, 14), open = cell(14, 25);
  assert.equal(why(waterRoute(model, null, inMixed, open)), 'lines-needed');
  assert.equal(why(waterRoute(model, null, open, inMixed)), 'lines-needed');
  assert.equal(why(waterRoute(model, false, inMixed, open)), 'start-not-water');
  assert.equal(why(waterRoute(model, false, open, inMixed)), 'end-not-water');
  const r = waterRoute(model, coastLines, inMixed, open);
  assert.ok(r.ok, JSON.stringify(r));
  allWater(model, coastLines, r.points);
});

test('a mixed cell the start snap already looked at still makes a blocked search lines-needed', () => {
  // A one-cell water berth under a row of mixed cells, then open water: the snap caches the mixed cells first.
  const model = product({[COAST]: paint([['w', 13, 0, 15, 14], ['m', 13, 15, 15, 15], ['w', 14, 16, 14, 16]], 'l'.repeat(G * G))});
  const from = cell(14, 16), to = cell(14, 4);
  assert.equal(why(waterRoute(model, null, from, to)), 'lines-needed');
  assert.equal(why(waterRoute(model, false, from, to)), 'no-route');
  const r = waterRoute(model, coastLines, from, to);
  assert.ok(r.ok, JSON.stringify(r));
  allWater(model, coastLines, r.points);
});

test('a breakwater line between two water sub-cell centres is never crossed', () => {
  const model = coastGrid([['l', 0, 22, 31, 22], ['m', 17, 22, 18, 22]]);
  // An edge-only line across the gap, half way between two sub-cell centre rows (~31 m from each, outside the
  // 25 m edge band), from inside the wall west of the gap to inside it east; a small far parity ring.
  const y = Math.round(latOf(1616 + (22 * 4 + 2) / (G * 4)) * 1e5), x0 = Math.round(lonOf(671 + 16.5 / G) * 1e5);
  const x1 = Math.round(lonOf(671 + 19.5 / G) * 1e5), ring = [-12100000, 3545500, 100, 0, 0, 100, -100, 0, 0, -100];
  const data = {...fixture('coast.lines.json'), edge: [[x0, y, x1 - x0, 0], ring], parity: [ring]};
  const breakwater = landWaterLines(data, model);
  assert.ok(breakwater, 'the lines load');
  const from = cell(14, 12), to = cell(14, 25), sub = row => ({latitude: latOf(1616 + row / (G * 4)), longitude: lonOf(671 + 69.5 / (G * 4))});
  for (const row of [89.5, 90.5]) assert.equal(placeOf(model, breakwater, sub(row)).state, 'water', 'both centres beside the line are water');
  assert.equal(why(waterRoute(model, breakwater, from, to)), 'no-route');
  assert.ok(waterRoute(model, coastLines, from, to).ok, 'the same gap without the line is a passage');
});

test('Morro Bay: the harbor to 3 nm WNW past Morro Rock, all water, longer than the line, fast and deterministic', () => {
  const region = dist('regions/morro-bay/region.json');
  const model = landWaterModel(dist('regions/morro-bay/land-water.json'), 'morro-bay');
  const lines = landWaterLines(dist('regions/morro-bay/land-water-lines.json'), model);
  assert.ok(model && lines, 'the committed product loads');
  const harbor = {latitude: region.harbor.latitude, longitude: region.harbor.longitude}, b = 292.5 * Math.PI / 180;
  const to = {latitude: harbor.latitude + 3 * Math.cos(b) / 60, longitude: harbor.longitude + 3 * Math.sin(b) / 60 / Math.cos(harbor.latitude * Math.PI / 180)};
  const t0 = performance.now(), r = waterRoute(model, lines, harbor, to), ms = performance.now() - t0;
  assert.ok(r.ok, JSON.stringify(r));
  assert.ok(ms < 2000, `${ms} ms`);
  allWater(model, lines, r.points);
  assert.ok(r.nm > distanceNm(harbor, to), `${r.nm}`);
  assert.ok(r.nm <= 3.650936378508364, `smoothing never lengthens the unsmoothed route (3.6509 nm on main): ${r.nm}`);
  assert.ok(r.points.length < 90, `the stair steps are gone: ${r.points.length} points`);
  assert.ok(r.points.some(p => p.latitude < 35.3667), 'leaves by the entrance south of Morro Rock');
  const again = waterRoute(model, lines, harbor, to);
  assert.equal(again.nm, r.nm);
  assert.equal(JSON.stringify(again.points), JSON.stringify(r.points));
  assert.equal(why(waterRoute(model, null, harbor, to)), 'lines-needed');
});

// Smoothing (line-of-sight shortcuts over water sub-cells).
const cheb = (a, b) => Math.max(Math.abs(a.longitude - b.longitude) / 360 * N * G * 4, Math.abs(Math.asinh(Math.tan(a.latitude * Math.PI / 180)) - Math.asinh(Math.tan(b.latitude * Math.PI / 180))) / (2 * Math.PI) * N * G * 4);

test('smoothing: open water at a 22.5° course is within 0.5 % of the straight line, never below it', () => {
  const model = product({[COAST]: paint([])});
  // Between sub-cell centres (96 across, 40 down: 22.6°), so the snap adds no leg.
  const sub = (col, row) => ({latitude: latOf(1616 + (row + 0.5) / (G * 4)), longitude: lonOf(671 + (col + 0.5) / (G * 4))});
  const from = sub(16, 40), to = sub(112, 80), r = waterRoute(model, null, from, to), straight = distanceNm(from, to);
  assert.ok(r.ok, JSON.stringify(r));
  assert.ok(r.nm >= straight && r.nm <= straight * 1.005, `${r.nm} vs ${straight}`);
  assert.ok(r.points.length <= 3, `${r.points.length} points`);
  allWater(model, null, r.points);
});

test('smoothing: a land cell in the way is rounded, never clipped at its corner, at every approach', () => {
  const model = product({[COAST]: paint([['l', 16, 16, 16, 16]])});
  let bent = 0;
  for (const [a, b] of [[[12, 20], [20, 12]], [[12, 12], [20, 20]], [[13, 20], [19, 12]], [[12, 19], [20, 13]], [[12, 16], [20, 16]], [[16, 12], [16, 20]], [[11, 21], [22, 12]], [[21, 11], [12, 21]]]) {
    const from = cell(...a), to = cell(...b), r = waterRoute(model, null, from, to);
    assert.ok(r.ok, JSON.stringify(r));
    allWater(model, null, r.points);
    assert.ok(r.nm >= distanceNm(from, to), `${a} → ${b}: ${r.nm}`);
    if (r.points.length > 2) bent++;
  }
  assert.ok(bent >= 4, `${bent} routes keep a bend where land is in the way`);
});

test('smoothing: a headland keeps its detour and the smoothed route is shorter than the stair steps', () => {
  const model = product({[COAST]: paint([['l', 10, 0, 21, 23]])});
  const from = cell(4, 8), to = cell(28, 8), r = waterRoute(model, null, from, to);
  assert.ok(r.ok, JSON.stringify(r));
  allWater(model, null, r.points);
  assert.ok(r.points.some(p => p.latitude < latOf(1616 + 24 / G)), 'passes south of the headland');
  assert.ok(r.points.length <= 6, `${r.points.length} points`);
});

test('smoothing: no shortcut through mixed cells without lines, and none across an edge line with them', () => {
  const block = product({[COAST]: paint([['m', 12, 12, 20, 20]])}), from = cell(16, 6), to = cell(16, 26);
  for (const lines of [null, false]) {
    const r = waterRoute(block, lines, from, to);
    assert.ok(r.ok, `${lines}: ${JSON.stringify(r)}`);
    assert.ok(!passes(block, r.points, 'unknown'), `${lines}: the route stays out of the mixed block`);
    assert.ok(r.nm > distanceNm(from, to));
  }
  // A breakwater across the middle of a row of mixed cells: an edge line half way between two sub-cell centre rows.
  const row = product({[COAST]: paint([['m', 8, 16, 24, 16]])});
  const y = Math.round(latOf(1616 + (16 * 4 + 2) / (G * 4)) * 1e5), x0 = Math.round(lonOf(671 + 8.5 / G) * 1e5), x1 = Math.round(lonOf(671 + 24.5 / G) * 1e5);
  const ring = [-12100000, 3545500, 100, 0, 0, 100, -100, 0, 0, -100];
  const wall = landWaterLines({...fixture('coast.lines.json'), edge: [[x0, y, x1 - x0, 0], ring], parity: [ring]}, row);
  assert.ok(wall, 'the lines load');
  const r = waterRoute(row, wall, cell(16, 8), cell(16, 24));
  assert.ok(r.ok, JSON.stringify(r));
  allWater(row, wall, r.points);
  assert.ok(r.points.some(p => p.longitude < x0 / 1e5 || p.longitude > x1 / 1e5), 'goes round an end of the line');
  assert.ok(r.nm > distanceNm(cell(16, 8), cell(16, 24)) * 1.1, `${r.nm}`);
});

test('smoothing: a berth on the shore keeps its snapped first and last vertex, whichever way it is routed', () => {
  const model = product({[COAST]: paint([['l', 0, 0, 15, 31]])}), berth = cell(15, 16), water = cell(24, 16);
  const there = waterRoute(model, null, berth, water), back = waterRoute(model, null, water, berth);
  assert.ok(there.ok && back.ok);
  assert.equal(JSON.stringify(there.points[0]), JSON.stringify(back.points[back.points.length - 1]));
  assert.equal(JSON.stringify(there.points[there.points.length - 1]), JSON.stringify(back.points[0]));
  assert.ok(distanceNm(berth, there.points[0]) * 1852 <= SNAP_M);
});

test('smoothing: segments over 400 sub-cells are not tried; a long open route is still short and deterministic', () => {
  const tiles = {};
  for (let tx = 671; tx <= 684; tx++) tiles[`12/${tx}/1616`] = paint([]);
  const model = product(tiles, [-12110000, 3530000, -11980000, 3555000]), from = cell(2, 12), to = cell(28, 20, 684);
  const r = waterRoute(model, null, from, to), straight = distanceNm(from, to);
  assert.ok(r.ok, JSON.stringify(r));
  assert.ok(r.points.length > 2, 'one segment cannot span the whole route');
  assert.ok(r.points.slice(1).every((p, i) => cheb(r.points[i], p) <= 401), 'no segment over 400 sub-cells');
  assert.ok(r.nm >= straight && r.nm <= straight * 1.005, `${r.nm} vs ${straight}`);
  assert.equal(JSON.stringify(waterRoute(model, null, from, to)), JSON.stringify(r));
});
