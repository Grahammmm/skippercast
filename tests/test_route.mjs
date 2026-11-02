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
const mid = (a, b) => ({latitude: (a.latitude + b.latitude) / 2, longitude: (a.longitude + b.longitude) / 2});

/** Every returned point and every segment midpoint classifies water. */
function allWater(model, lines, points) {
  for (const [i, p] of points.entries()) {
    assert.equal(placeOf(model, lines, p).state, 'water', `point ${i}`);
    if (i) assert.equal(placeOf(model, lines, mid(points[i - 1], p)).state, 'water', `midpoint ${i}`);
  }
}

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
  assert.ok(r.points.some(p => placeOf(model, null, p).state === 'unknown'), 'passes the mixed cells');
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
  assert.ok(r.points.some(p => p.latitude < 35.3667), 'leaves by the entrance south of Morro Rock');
  const again = waterRoute(model, lines, harbor, to);
  assert.equal(again.nm, r.nm);
  assert.equal(JSON.stringify(again.points), JSON.stringify(r.points));
  assert.equal(why(waterRoute(model, null, harbor, to)), 'lines-needed');
});
