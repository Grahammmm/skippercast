// SC1407-01 (#1762 R1): dist/geo-screen.js distanceM projects each position and edge once per pair, scans with plain loops (no
// spread into Math.min) and skips a segment whose projected box is already farther than the best so far. Every answer must be
// the one the old code gave: the old distanceM is kept below as a test-only oracle (checked main f5e3be15 / 5c6e906c), and raw
// distances are compared with strict equality, verdicts in full. Committed Morro Bay data and synthetic fixtures; no network.
import assert from 'node:assert/strict';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {distanceM, geometryIntersects, placeRefused, pointGeometry, positions, screenPlace} from '../dist/geo-screen.js';

const data = name => JSON.parse(readFileSync(new URL(`../dist/data/${name}`, import.meta.url), 'utf8'));
const ATLAS = data('atlas.json'), BOUNDARY = data('protected-areas.geojson').features, PORTS = data('home-ports.json').ports.filter(p => p.region === 'morro-bay');
const nameOf = f => f.properties?.FULLNAME || f.properties?.NAME || null;
const CLOSURES = BOUNDARY.map(f => ({name: nameOf(f), geometry: f.geometry}));
const screenOf = closures => ({status: 'ready', boundaries: closures});

// ---- Test-only legacy oracle: the checked-main distanceM and screenPlace distance rules, unchanged. Never used by the app. ----
const legacyBoxes = new WeakMap();
function legacyBbox(g) {
  if (!legacyBoxes.has(g)) legacyBoxes.set(g, positions(g).reduce((b, p) => [Math.min(b[0], p[0]), Math.min(b[1], p[1]), Math.max(b[2], p[0]), Math.max(b[3], p[1])], [Infinity, Infinity, -Infinity, -Infinity]));
  return legacyBoxes.get(g);
}
const mPerDeg = lat => {
  const r = lat * Math.PI / 180;
  return [111412.84 * Math.cos(r) - 93.5 * Math.cos(3 * r), 111132.92 - 559.82 * Math.cos(2 * r) + 1.175 * Math.cos(4 * r)];
};
function legacyEdges(g) {
  const lines = g.type === 'Polygon' ? g.coordinates : g.type === 'MultiPolygon' ? g.coordinates.flat() : g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates : [];
  return lines.flatMap(line => line.slice(1).map((p, i) => [line[i], p]));
}
let legacySegCalls = 0;
function legacySegDist2(p, a, b) {
  legacySegCalls++;
  const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy;
  const t = l ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l)) : 0;
  const x = a[0] + t * dx - p[0], y = a[1] + t * dy - p[1];
  return x * x + y * y;
}
function legacyDistanceM(a, b) {
  const pa = positions(a), pb = positions(b);
  if (!pa.length || !pb.length) return null;
  if (geometryIntersects(a, b)) return 0;
  const lat = (pa[0][1] + pb[0][1]) / 2, [kx, ky] = mPerDeg(lat), proj = p => [p[0] * kx, p[1] * ky];
  const lines = g => { const e = legacyEdges(g); return e.length ? e.map(([p, q]) => [proj(p), proj(q)]) : positions(g).map(p => [proj(p), proj(p)]); };
  const best = (pts, segs) => Math.min(...pts.map(p => Math.min(...segs.map(([s, t]) => legacySegDist2(proj(p), s, t)))));
  return Math.sqrt(Math.min(best(pa, lines(b)), best(pb, lines(a))));
}
const legacyMemo = new WeakMap();
function legacyDistanceMemo(a, b) {
  if (!a || !b) return legacyDistanceM(a, b);
  if (!legacyMemo.has(a)) legacyMemo.set(a, new WeakMap());
  const m = legacyMemo.get(a);
  if (!m.has(b)) m.set(b, legacyDistanceM(a, b));
  return m.get(b);
}
const FAR_M = 20000;
function legacyFarApart(a, b) {
  const x = legacyBbox(a), y = legacyBbox(b);
  if (![...x, ...y].every(Number.isFinite)) return true;
  const [kx, ky] = mPerDeg((x[1] + x[3]) / 2);
  return Math.max(x[0] - y[2], y[0] - x[2], 0) * kx > FAR_M || Math.max(x[1] - y[3], y[1] - x[3], 0) * ky > FAR_M;
}
/** The checked-main screenPlace for a ready boundary screen (the closures path), with the legacy distanceM. */
function legacyScreenPlace(closures, place) {
  const shapes = [...(place?.geometry ? [place.geometry] : []), ...(place?.geometries ?? [])];
  if (Number.isFinite(place?.longitude) && Number.isFinite(place?.latitude)) shapes.push(pointGeometry(place.longitude, place.latitude));
  if (!shapes.length) return {inside: false, name: null, distanceM: null, screened: false};
  let near = null;
  for (const c of closures) for (const g of shapes) { if (legacyFarApart(g, c.geometry)) continue; const d = legacyDistanceMemo(g, c.geometry); if (d !== null && (!near || d < near.d)) near = {d, name: c.name}; }
  return {inside: near?.d === 0, name: near?.name ?? null, distanceM: near ? Math.round(near.d * 10) / 10 : null, screened: true};
}
// ---- end of the legacy oracle ----

/** Strict raw parity in both argument directions (Object.is: 0, NaN and null all distinct). */
function sameDistance(a, b, label) {
  const want = legacyDistanceMemo(a, b);
  for (const [got, dir] of [[distanceM(a, b), 'a,b'], [distanceM(b, a), 'b,a']]) assert.ok(Object.is(got, want), `${label} (${dir}): ${got} !== legacy ${want}`);
  return want;
}
function sameVerdict(closures, place, label) {
  const got = screenPlace(screenOf(closures), place), want = legacyScreenPlace(closures, place);
  assert.deepStrictEqual(got, want, label);
  assert.equal(placeRefused(got), placeRefused(want), label);
  return got;
}
const areasOf = t => ATLAS.areas.filter(a => (a.target_ids ?? []).includes(t.id) || (t.area_ids ?? []).includes(a.id)).map(a => a.geometry);
function mulberry32(seed) {
  return () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const ring = (w, s, e, n) => [[w, s], [e, s], [e, n], [w, n], [w, s]];
const poly = (...rings) => ({type: 'Polygon', coordinates: rings});
const line = (...c) => ({type: 'LineString', coordinates: c});

test('distance_m_committed_atlas_and_run_lines_exact_parity', () => {
  assert.equal(ATLAS.targets.length, 132);
  assert.equal(BOUNDARY.length, 8);
  assert.ok(PORTS.length >= 2, 'the Morro Bay harbors');
  let measured = 0, nonzero = 0;
  for (const t of ATLAS.targets) {
    const areas = areasOf(t), point = pointGeometry(t.longitude, t.latitude);
    sameVerdict(CLOSURES, {latitude: t.latitude, longitude: t.longitude, geometries: areas}, t.id);
    for (const g of [point, ...areas]) for (const c of CLOSURES) {
      if (legacyFarApart(g, c.geometry)) continue;
      const d = sameDistance(g, c.geometry, `${t.id} / ${c.name}`); measured++; if (d > 0) nonzero++;
    }
    for (const port of PORTS) {
      const [lat, lon] = port.match, run = line([lon, lat], [t.longitude, t.latitude]);
      const bent = line([lon, lat], [lon - 0.03, lat - 0.01], [(lon + t.longitude) / 2 - 0.02, (lat + t.latitude) / 2], [t.longitude, t.latitude]);
      for (const g of [run, bent]) {
        sameVerdict(CLOSURES, {geometry: g}, `${port.id} -> ${t.id}`);
        for (const c of CLOSURES) sameDistance(g, c.geometry, `${port.id} -> ${t.id} / ${c.name}`);
      }
    }
  }
  assert.ok(measured > 200 && nonzero > 100, `measured ${measured}, nonzero ${nonzero}`);
});

test('distance_m_seeded_random_point_and_line_parity', () => {
  const rand = mulberry32(1407), r = (lo, hi) => lo + (hi - lo) * rand(), SEED_NOTE = 'mulberry32(1407)';
  const near = BOUNDARY.filter(f => ['Point Buchon State Marine Conservation Area', 'Morro Bay State Marine Reserve', 'White Rock State Marine Conservation Area'].includes(nameOf(f)));
  const synthetic = [poly(ring(-120.9, 35.2, -120.85, 35.25)), line([-120.95, 35.3], [-120.7, 35.3]), line([-120.8, 35.1], [-120.8, 35.45]),
    poly(ring(-120.9, 35.3, -120.8, 35.4), ring(-120.87, 35.33, -120.83, 35.37))];
  const targets = [...near.map(f => f.geometry), ...synthetic];
  for (let i = 0; i < 120; i++) {
    const x = r(-121.0, -120.7), y = r(35.1, 35.5), kind = i % 6;
    const g = kind === 0 ? pointGeometry(x, y)
      : kind === 1 ? line([x, y], [x + r(-0.02, 0.02), y]) // horizontal
      : kind === 2 ? line([x, y], [x, y + r(-0.02, 0.02)]) // vertical
      : kind === 3 ? line([x, y], [x + r(-0.05, 0.05), y + r(-0.05, 0.05)], [x + r(-0.05, 0.05), y + r(-0.05, 0.05)]) // diagonal
      : kind === 4 ? line([x, y], [x, y]) // zero-length
      : line([x - 0.2, y], [x + 0.2, y + 1e-4]); // long thin: nearest point in a segment interior
    for (const t of targets) sameDistance(g, t, `${SEED_NOTE} #${i} kind ${kind}`);
    sameVerdict(targets.map((geometry, k) => ({name: `T${k}`, geometry})), {geometry: g}, `${SEED_NOTE} verdict #${i}`);
  }
  // Large-coordinate cancellation: far from the origin, a few metres apart.
  const far = poly(ring(179.99990, 89.4, 179.99995, 89.40001));
  for (let i = 0; i < 20; i++) sameDistance(pointGeometry(179.99996 + i * 1e-7, 89.400005 + r(-1e-6, 1e-6)), far, `far #${i}`);
  // Very close box-bound ties: many horizontal segments at one height, where each box gap equals the true distance.
  const comb = {type: 'MultiLineString', coordinates: Array.from({length: 40}, (_, k) => [[-120.9 + k * 1e-3, 35.3], [-120.9 + k * 1e-3 + 9e-4, 35.3]])};
  for (let i = 0; i < 40; i++) sameDistance(pointGeometry(-120.9 + i * 1e-3 + r(0, 9e-4), 35.3 - r(1e-6, 1e-3)), comb, `comb #${i}`);
  sameDistance(pointGeometry(-120.9 + 9.5e-4, 35.2995), comb, 'between two teeth');
});

test('distance_m_contact_holes_and_multipart', () => {
  const holed = poly(ring(-120.9, 35.3, -120.8, 35.4), ring(-120.87, 35.33, -120.83, 35.37));
  const cases = [
    ['touching vertex', pointGeometry(-120.9, 35.3), holed, 0],
    ['touching edge', line([-120.95, 35.35], [-120.9, 35.35]), holed, 0],
    ['crossing, both ends outside', line([-120.95, 35.31], [-120.75, 35.31]), holed, 0],
    ['wholly inside', poly(ring(-120.89, 35.31, -120.88, 35.32)), holed, 0],
    ['surrounding closure', poly(ring(-121, 35.2, -120.7, 35.5)), holed, 0],
    ['inside the hole', pointGeometry(-120.85, 35.35), holed, '>0'],
    ['on the hole edge', pointGeometry(-120.87, 35.35), holed, 0],
    ['MultiPolygon', {type: 'MultiPolygon', coordinates: [[ring(-120.99, 35.2, -120.98, 35.21)], [ring(-120.95, 35.2, -120.94, 35.21)]]}, holed, '>0'],
    ['MultiLineString', {type: 'MultiLineString', coordinates: [[[-121, 35.2], [-120.99, 35.25]], [[-120.95, 35.45], [-120.92, 35.42]]]}, holed, '>0'],
    ['MultiPoint', {type: 'MultiPoint', coordinates: [[-120.95, 35.45], [-120.91, 35.35], [-120.7, 35.2]]}, holed, '>0'],
    ['single-position line', line([-120.91, 35.35]), holed, '>0'],
    ['empty geometry', poly(), holed, null],
    ['null geometry', null, holed, null],
  ];
  for (const [label, g, c, expect] of cases) {
    const d = sameDistance(g, c, label);
    if (expect === 0) assert.ok(Object.is(d, 0), `${label}: ${d}`);
    else if (expect === '>0') assert.ok(d > 0 && Number.isFinite(d), `${label}: ${d}`);
    else assert.equal(d, null, label);
  }
  const hole = sameDistance(pointGeometry(-120.85, 35.35), holed, 'hole');
  assert.ok(hole > 1000 && hole < 3000, `${hole} m to the hole's edge`);
  for (const [label, g] of cases) if (g) sameVerdict([{name: 'Holed', geometry: holed}], {geometry: g}, label);
});

test('distance_m_margin_rounding_and_far_cutoff', () => {
  const wall = poly(ring(-120.9, 35.3, -120.8, 35.4)), lat = 35.35, kx = mPerDeg((lat + 35.3) / 2)[0]; // the pair's frame: first positions' mean latitude
  // Points east of the wall's east edge at metres around the 70 m refusal and the 0.1 m rounding steps.
  for (const m of [0.04, 0.05, 0.06, 69.94, 69.95, 69.96, 69.99, 70, 70.01, 70.04, 70.05, 70.06, 70.1, 1234.55, 19999.9]) {
    const v = sameVerdict([{name: 'Wall', geometry: wall}], {latitude: lat, longitude: -120.8 + m / kx}, `${m} m`);
    assert.ok(Math.abs(v.distanceM - m) < 0.11, `${m} m -> ${v.distanceM}`);
  }
  // The 20 km shortcut: past FAR_M nothing is measured (distanceM null), just inside it is.
  const beyond = sameVerdict([{name: 'Wall', geometry: wall}], {latitude: lat, longitude: -120.8 + 20100 / kx}, 'beyond FAR_M');
  assert.deepStrictEqual(beyond, {inside: false, name: null, distanceM: null, screened: true});
  assert.ok(sameVerdict([{name: 'Wall', geometry: wall}], {latitude: lat, longitude: -120.8 + 19900 / kx}, 'inside FAR_M').distanceM > 19800);
  // Equal distance to two closures (the same outline under two names): the first listed keeps the name (strict <), in either order.
  const twin = poly(ring(-121.0, 35.3, -120.95, 35.4)), mid = {latitude: 35.35, longitude: -120.9};
  assert.equal(sameVerdict([{name: 'West', geometry: twin}, {name: 'Twin', geometry: structuredClone(twin)}], mid, 'tie W,T').name, 'West');
  assert.equal(sameVerdict([{name: 'Twin', geometry: structuredClone(twin)}, {name: 'West', geometry: twin}], mid, 'tie T,W').name, 'Twin');
});

test('distance_m_large_positions_do_not_spread', () => {
  const lon = -120.85, lat = 35.3, up = 35.31, N = 150_000, [, ky] = mPerDeg((lat + up) / 2);
  const many = {type: 'MultiPoint', coordinates: Array.from({length: N}, () => [lon, up])};
  const want = Math.abs(up * ky - lat * ky);
  for (const d of [distanceM(pointGeometry(lon, lat), many), distanceM(many, pointGeometry(lon, lat))]) assert.ok(Number.isFinite(d) && Math.abs(d - want) < 1e-6, `${d} vs ${want}`);
  const long = {type: 'LineString', coordinates: Array.from({length: N + 2}, (_, i) => [-121 + i * 2e-6, up])};
  assert.ok(long.coordinates.length - 1 > N);
  for (const d of [distanceM(pointGeometry(lon, lat), long), distanceM(long, pointGeometry(lon, lat))]) assert.ok(Number.isFinite(d) && Math.abs(d - want) < 1e-6, `${d} vs ${want}`);
  const v = screenPlace(screenOf([{name: 'Many', geometry: many}]), {latitude: lat, longitude: lon});
  assert.equal(v.distanceM, Math.round(want * 10) / 10);
});

test('distance_m_projects_linear_work_and_prunes_exactly', async () => {
  // A temporary instrumented copy of the module (the app's copy has no counters): count projections and segment distances.
  const src = await readFile(new URL('../dist/geo-screen.js', import.meta.url), 'utf8');
  const hooks = [['function projectTo(p, kx, ky, out, i) {', 'globalThis.__sc1407.proj++;'], ['function segD2(px, py, ax, ay, bx, by) {', 'globalThis.__sc1407.seg++;']];
  let copy = src;
  for (const [head, count] of hooks) { assert.equal(src.split(head).length, 2, `${head} once`); copy = copy.replace(head, `${head} ${count}`); }
  const file = join(await mkdtemp(join(tmpdir(), 'sc1407-')), 'geo-screen-counted.mjs');
  await writeFile(file, copy);
  const counted = await import(pathToFileURL(file).href);
  const run = (a, b) => { globalThis.__sc1407 = {proj: 0, seg: 0}; const d = counted.distanceM(a, b); return {d, ...globalThis.__sc1407}; };
  const shore = n => line(...Array.from({length: n}, (_, i) => [-121.2 + i * 1e-4, 35.0 + (i % 7) * 1e-5]));
  const box = poly(ring(-120.9, 35.3, -120.8, 35.4));
  for (const n of [100, 200, 400]) {
    const a = shore(n), r = run(a, box);
    assert.equal(r.proj, 2 * n + 2 * 5, `${n} positions: projections ${r.proj}`); // each position once as a point, once as a shared edge end
    legacySegCalls = 0;
    assert.ok(Object.is(r.d, legacyDistanceM(a, box)));
    assert.equal(legacySegCalls, n * 4 + 5 * (n - 1));
    assert.ok(r.seg <= legacySegCalls, `${r.seg} <= ${legacySegCalls}`);
  }
  // A distant-box fixture: the real Morro Bay SMRMA outline against a point kilometres off; most segments are pruned, same answer.
  const smrma = BOUNDARY.find(f => /Recreational Management/.test(nameOf(f))).geometry, off = pointGeometry(-120.95, 35.25);
  const r = run(off, smrma);
  legacySegCalls = 0;
  assert.ok(Object.is(r.d, legacyDistanceM(off, smrma)) && r.d > 1000, `${r.d}`);
  assert.ok(r.seg * 4 < legacySegCalls, `pruned: ${r.seg} of ${legacySegCalls} segment distances`);
  assert.equal(r.proj, 1 + 2 * positions(smrma).length, `projections ${r.proj}`); // the point once; each outline position as a point and as an edge end
});
