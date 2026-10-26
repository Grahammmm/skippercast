// SP1401 (SP-14-v1): illustrative current streamlines stop at screen-resolved land
// gaps between integration probes. The complete web/map/flow.ts module is imported
// through its public pure API (flowPaths, screenVector, seedSpacing and constants)
// after offline sentinels are installed; inputs are the card-owned synthetic screen
// samplers in tests/fixtures/sp1401_flow_gaps/cases.json, shaped like the samplers in
// tests/test_flow.mjs. No map service, raster, field packet or geographic source.
//
// A one-pixel screen-resolution contract only: no navigation, terrain, safe-water or
// fish-presence conclusion follows from these tests.
//
// SP1401_SUITE=baseline registers only the A4 pair ("primary regression" and
// "healthy control"); every other value registers A1-A4.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import net from 'node:net';
import test, {afterEach, beforeEach} from 'node:test';

// Offline sentinels before any product import (including bound defaults).
const denied = name => function () { throw new Error(`SP1401: ${name} is disabled in this offline test`); };
const ORIGINAL = {fetch: globalThis.fetch, WebSocket: globalThis.WebSocket, XMLHttpRequest: globalThis.XMLHttpRequest,
  connect: net.connect, createConnection: net.createConnection, socketConnect: net.Socket.prototype.connect};
function seal() {
  globalThis.fetch = denied('fetch');
  globalThis.WebSocket = denied('WebSocket');
  globalThis.XMLHttpRequest = denied('XMLHttpRequest');
  net.connect = denied('net.connect');
  net.createConnection = denied('net.createConnection');
  net.Socket.prototype.connect = denied('net.Socket.connect');
}
function unseal() {
  for (const key of ['fetch', 'WebSocket', 'XMLHttpRequest']) {
    if (ORIGINAL[key] === undefined) delete globalThis[key]; else globalThis[key] = ORIGINAL[key];
  }
  net.connect = ORIGINAL.connect; net.createConnection = ORIGINAL.createConnection; net.Socket.prototype.connect = ORIGINAL.socketConnect;
}
seal();
const flow = await import('../web/map/flow.ts');
unseal();
beforeEach(seal);
afterEach(unseal);

const {flowPaths, screenVector, seedSpacing, MAX_PATHS, MAX_STEPS, STEP_PX} = flow;
const F = JSON.parse(readFileSync(new URL('./fixtures/sp1401_flow_gaps/cases.json', import.meta.url), 'utf8'));
const BASELINE = process.env.SP1401_SUITE === 'baseline';
const C = F.constants, SCREEN = F.screen, SPEED = F.speed_knots;

// ---- synthetic samplers and independent oracles ---------------------------------
const unit = ([x, y]) => { const m = Math.hypot(x, y); return {x: x / m, y: y / m}; };
const inRect = (r, x, y) => x >= r.x0 && x <= r.x1 && y >= r.y0 && y <= r.y1;
/** A constant unit vector everywhere except a closed blocked rectangle (null there), as tests/test_flow.mjs samplers. */
function sampler(direction, blocked = null) {
  const d = unit(direction);
  return (x, y) => (blocked && inRect(blocked, x, y) ? null : {x: d.x, y: d.y, speed: SPEED});
}
/** Counts and records every call a sampler receives. */
function counted(vector) {
  const calls = [];
  const wrapped = (x, y) => { calls.push({x, y}); return vector(x, y); };
  return {wrapped, calls};
}
/**
 * The unchanged integration (fish's midpoint rule) for a CONSTANT unit field written
 * independently of flow.ts: vertex and midpoint probes only. On fully supported or
 * broad-gap inputs it is the baseline the product must keep.
 */
function oracle(direction, width, height, seeds, supported = () => true) {
  const d = unit(direction), out = [];
  const inside = p => p.x >= 0 && p.y >= 0 && p.x <= width && p.y <= height;
  for (const [x, y] of seeds) {
    if (!supported(x, y)) continue;
    const halves = [];
    for (const sign of [-1, 1]) {
      const pts = [];
      let p = {x, y};
      for (let i = 0; i < C.max_steps; i++) {
        if (!supported(p.x, p.y)) break;
        if (!supported(p.x + sign * d.x * C.step_px / 2, p.y + sign * d.y * C.step_px / 2)) break;
        const next = {x: p.x + sign * d.x * C.step_px, y: p.y + sign * d.y * C.step_px};
        if (!inside(next) || !supported(next.x, next.y)) break;
        pts.push(next); p = next;
      }
      halves.push(pts);
    }
    const points = [...halves[0].reverse(), {x, y}, ...halves[1]];
    if (points.length > C.min_points_exclusive) out.push(points);
  }
  return out;
}
/** Closed segment against closed axis-aligned rectangle (Liang-Barsky): the whole segment, not just its vertices. */
function segmentHits(p, q, r) {
  let t0 = 0, t1 = 1;
  const dx = q.x - p.x, dy = q.y - p.y;
  for (const [den, num] of [[-dx, p.x - r.x0], [dx, r.x1 - p.x], [-dy, p.y - r.y0], [dy, r.y1 - p.y]]) {
    if (den === 0) { if (num < 0) return false; continue; }
    const t = num / den;
    if (den < 0) { if (t > t1) return false; if (t > t0) t0 = t; } else { if (t < t0) return false; if (t < t1) t1 = t; }
  }
  return t0 <= t1;
}
const segments = paths => paths.flatMap(path => path.points.slice(1).map((q, i) => [path.points[i], q]));
const crossings = (paths, r) => segments(paths).filter(([p, q]) => segmentHits(p, q, r))
  .map(([p, q]) => `(${p.x.toFixed(2)},${p.y.toFixed(2)})->(${q.x.toFixed(2)},${q.y.toFixed(2)})`);
/** Runs flowPaths, capturing a product exception as observed data before any semantic assertion. */
function observe(vector, width, height, fast = Infinity) {
  try { return {paths: flowPaths(vector, width, height, fast), exception: null}; }
  catch (error) { return {paths: [], exception: `${error?.name}: ${error?.message}`}; }
}
const pointsOf = paths => paths.map(p => p.points.map(({x, y}) => ({x, y})));

// ---- A4: the baseline pair (registered in every mode) ---------------------------
test('primary regression', () => {
  const {direction, blocked} = F.primary;
  const seen = observe(sampler(direction, blocked), SCREEN.width, SCREEN.height);
  assert.equal(seen.exception, null, `product exception observed: ${seen.exception}`);
  assert.deepEqual(crossings(seen.paths, blocked), [], 'no emitted segment crosses the one-pixel null strip');
});

test('healthy control', () => {
  const direction = F.primary.direction;
  const seen = observe(sampler(direction), SCREEN.width, SCREEN.height);
  assert.equal(seen.exception, null, `product exception observed: ${seen.exception}`);
  assert.deepEqual(pointsOf(seen.paths), oracle(direction, SCREEN.width, SCREEN.height, SCREEN.seeds), 'the original supported line');
  for (const path of seen.paths) {
    assert.equal(path.speed, SPEED);
    for (let k = 1; k < path.points.length; k++) {
      assert.ok(path.points[k].x > path.points[k - 1].x, 'eastward');
      assert.equal(path.points[k].y, path.points[k - 1].y, 'no drift off the line');
    }
  }
});

if (!BASELINE) {
  // ---- A1 ---------------------------------------------------------------------
  test('A1: no emitted segment crosses a one-pixel gap: east/west, north/south and diagonal cells', () => {
    assert.equal(F.one_pixel_gaps.length, 12);
    for (const {name, direction, blocked} of F.one_pixel_gaps) {
      const vector = sampler(direction, blocked);
      const seen = observe(vector, SCREEN.width, SCREEN.height);
      assert.equal(seen.exception, null, name);
      assert.deepEqual(crossings(seen.paths, blocked), [], name);
      for (const path of seen.paths) for (const p of path.points) assert.ok(vector(p.x, p.y), `${name}: vertex on support`);
      // The unchanged probes alone would have let at least one segment through: the case is a real sub-step gap.
      const old = oracle(direction, SCREEN.width, SCREEN.height, SCREEN.seeds, (x, y) => !inRect(blocked, x, y));
      assert.ok(crossings(old.map(points => ({points})), blocked).length > 0, `${name}: the gap lies between the vertex and midpoint probes`);
    }
  });

  test('A1: the gap ends the path at its last supported vertex and leaves the other seed untouched', () => {
    const {direction, blocked} = F.primary;
    const {paths} = observe(sampler(direction, blocked), SCREEN.width, SCREEN.height);
    // Seed (24, 24) stops before the strip: 4 points west plus the seed is a short path and is dropped.
    // Seed (88, 24) still runs west to x = 28, the last vertex before the strip (x = 23 would cross it).
    assert.equal(paths.length, 1);
    const xs = paths[0].points.map(p => p.x);
    assert.deepEqual(xs, [28, 33, 38, 43, 48, 53, 58, 63, 68, 73, 78, 83, 88, 93, 98, 103, 108, 113, 118, 123, 128]);
  });

  // ---- A2 ---------------------------------------------------------------------
  test('A2: a fully supported constant vector keeps the baseline points, speed, fast flag and direction', () => {
    for (const direction of F.supported_directions) {
      const {paths} = observe(sampler(direction), SCREEN.width, SCREEN.height, 0.5);
      const expected = oracle(direction, SCREEN.width, SCREEN.height, SCREEN.seeds);
      assert.ok(expected.length > 0, `${direction}`);
      assert.deepEqual(pointsOf(paths), expected, `${direction}: identical points`);
      assert.ok(paths.every(p => p.speed === SPEED && p.fast === true), `${direction}: speed and fast above 0.5 kt`);
      const d = unit(direction);
      for (const {points} of paths) for (let k = 1; k < points.length; k++) {
        const dx = points[k].x - points[k - 1].x, dy = points[k].y - points[k - 1].y;
        assert.ok(Math.abs(dx - d.x * STEP_PX) < 1e-9 && Math.abs(dy - d.y * STEP_PX) < 1e-9, `${direction}: one ${STEP_PX} px step along the flow`);
      }
    }
    // The fast flag is strictly above the threshold.
    assert.ok(observe(sampler([1, 0]), SCREEN.width, SCREEN.height, SPEED).paths.every(p => p.fast === false));
  });

  test('A2: the seed grid and MAX_PATHS cap are unchanged on a large screen', () => {
    const {width, height} = F.large_screen;
    const spacing = seedSpacing(width, height), offset = spacing * 24 / 64, seeds = [];
    for (let y = offset; y < height; y += spacing) for (let x = offset; x < width; x += spacing) seeds.push([x, y]);
    const {paths} = observe(sampler([1, 0]), width, height);
    assert.ok(paths.length <= MAX_PATHS);
    assert.deepEqual(pointsOf(paths), oracle([1, 0], width, height, seeds).slice(0, MAX_PATHS));
    assert.equal(MAX_STEPS, C.max_steps);
    assert.equal(STEP_PX, C.step_px);
  });

  test('A2: still water and a broad gap the probes already caught keep their baseline results', () => {
    const field = Object.freeze({sample: () => F.still_sample_ms.slice()});
    assert.deepEqual(flowPaths(screenVector(field, (x, y) => ({lon: x, lat: y})), SCREEN.width, SCREEN.height, Infinity), []);
    const {direction, blocked} = F.broad_gap;
    const {paths} = observe(sampler(direction, blocked), SCREEN.width, SCREEN.height);
    assert.deepEqual(pointsOf(paths), oracle(direction, SCREEN.width, SCREEN.height, SCREEN.seeds, (x, y) => !inRect(blocked, x, y)));
    assert.deepEqual(crossings(paths, blocked), []);
  });

  // ---- A3 ---------------------------------------------------------------------
  test('A3: each five-pixel segment is sampled a constant bounded number of times at most one pixel apart', () => {
    const {height, widths} = F.edge_screen, totals = [];
    for (const width of widths) {
      const {wrapped, calls} = counted(sampler([1, 0]));
      const {paths} = observe(wrapped, width, height);
      assert.equal(paths.length, 1, `${width}: one seed`);
      const steps = paths[0].points.length - 1;
      totals.push({steps, calls: calls.length});
      for (const [p, q] of segments(paths)) {
        const len = Math.hypot(q.x - p.x, q.y - p.y);
        const ts = [...new Set(calls.filter(c => Math.abs((c.x - p.x) * (q.y - p.y) - (c.y - p.y) * (q.x - p.x)) < 1e-9)
          .map(c => ((c.x - p.x) * (q.x - p.x) + (c.y - p.y) * (q.y - p.y)) / (len * len)).filter(t => t >= -1e-12 && t <= 1 + 1e-12))].sort((a, b) => a - b);
        assert.ok(Math.abs(ts[0]) < 1e-12 && Math.abs(ts.at(-1) - 1) < 1e-12, `${width}: both endpoints sampled`);
        for (let k = 1; k < ts.length; k++) assert.ok((ts[k] - ts[k - 1]) * len <= C.sample_px + 1e-9, `${width}: samples at most ${C.sample_px} px apart`);
      }
    }
    // Calls grow linearly in accepted segments: one constant per segment, the same on every screen.
    const [a, b, c] = totals, perSegment = (b.calls - a.calls) / (b.steps - a.steps);
    assert.ok(Number.isInteger(perSegment), `${perSegment} calls per segment`);
    assert.equal((c.calls - b.calls) / (c.steps - b.steps), perSegment);
    assert.ok(perSegment <= 2 + STEP_PX / C.sample_px + 1, `${perSegment} calls per segment is bounded`);
    // Diagonal five-pixel segments are sampled at the same spacing.
    const {wrapped, calls} = counted(sampler([3, -4]));
    const {paths} = observe(wrapped, SCREEN.width, SCREEN.height);
    for (const [p, q] of segments(paths)) {
      const on = calls.filter(k => Math.abs((k.x - p.x) * (q.y - p.y) - (k.y - p.y) * (q.x - p.x)) < 1e-9
        && Math.min(p.x, q.x) - 1e-9 <= k.x && k.x <= Math.max(p.x, q.x) + 1e-9 && Math.min(p.y, q.y) - 1e-9 <= k.y && k.y <= Math.max(p.y, q.y) + 1e-9);
      const ts = [...new Set(on.map(k => Math.hypot(k.x - p.x, k.y - p.y)))].sort((m, n) => m - n);
      for (let k = 1; k < ts.length; k++) assert.ok(ts[k] - ts[k - 1] <= C.sample_px + 1e-9, 'diagonal spacing');
      assert.ok(ts.length >= STEP_PX / C.sample_px + 1, 'diagonal segment covered end to end');
    }
  });

  test('A3: zero support, short paths and the viewport edge keep their existing results', () => {
    const {wrapped, calls} = counted(() => null);
    assert.deepEqual(flowPaths(wrapped, SCREEN.width, SCREEN.height, Infinity), []);
    assert.equal(calls.length, SCREEN.seeds.length, 'only the seeds are asked');
    for (const [what, {direction, supported_x: [lo, hi]}] of Object.entries(F.short_path)) {
      const ok = (x) => x >= lo && x <= hi;
      const vector = (x, y) => (ok(x) ? {...unit(direction), speed: SPEED} : null);
      const expected = oracle(direction, SCREEN.width, SCREEN.height, SCREEN.seeds, x => ok(x));
      assert.deepEqual(pointsOf(flowPaths(vector, SCREEN.width, SCREEN.height, Infinity)), expected, what);
      assert.equal(expected.length, what === 'kept' ? 1 : 0, what);
    }
    for (const width of F.edge_screen.widths) {
      const {paths} = observe(sampler([1, 0]), width, F.edge_screen.height);
      assert.deepEqual(pointsOf(paths), oracle([1, 0], width, F.edge_screen.height, [[24, 24]]), `edge ${width}`);
      assert.ok(paths[0].points.at(-1).x <= width && paths[0].points[0].x >= 0);
    }
  });

  test('A3: the vector function, its field and masks are not mutated', () => {
    const mask = Object.freeze({...F.primary.blocked});
    const before = JSON.stringify(mask);
    const field = Object.freeze({direction: Object.freeze([1, 0])});
    const vector = (x, y) => (inRect(mask, x, y) ? null : {...unit(field.direction), speed: SPEED});
    const keys = Reflect.ownKeys(vector).sort().join();
    const {wrapped, calls} = counted(vector);
    const seen = observe(wrapped, SCREEN.width, SCREEN.height);
    assert.equal(seen.exception, null);
    assert.equal(JSON.stringify(mask), before);
    assert.deepEqual(field.direction, [1, 0]);
    assert.equal(Reflect.ownKeys(vector).sort().join(), keys);
    assert.ok(calls.every(c => Number.isFinite(c.x) && Number.isFinite(c.y)), 'only finite screen points are asked');
  });
}
