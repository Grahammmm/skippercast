// F16-01 / SCA-205: synthetic shoreline, no place data, network, or file export.
// node --test tests/test_f16_01_audit.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import {geometryCoveredByBounds} from '../dist/geo-screen.js';
import {landWaterModel, placeOf} from '../web/land-water.ts';
import {buildProtectedRoute} from '../web/protected-route.ts';

// Invent one tile at the equator. Coordinates below are offsets in its 32×32 cell grid.
const point = (x, y) => ({
  longitude: x * 360 / (4096 * 32),
  latitude: Math.atan(Math.sinh(-2 * Math.PI * y / (4096 * 32))) * 180 / Math.PI,
});
const model = cells => {
  const data = landWaterModel({
    schema_version: 1, product: 'land-water', region_id: 'fixture', status: 'available',
    constants: {edge_m: 25, unit: 100000, tile_zoom: 12, grid: 32},
    bounds: [-1, -8790, 8790, 1], tiles: {'12/2048/2048': cells},
    derived_from: {sha256: 'synthetic'}, lines: {sha256: 'synthetic'},
  }, 'fixture');
  assert.ok(data);
  return data;
};
const start = point(10.01, 16.01), end = point(13, 16.01);
// A narrow inlet opening to the west, with a land lip to its east. The original
// stop fits inside the 25 m shoreline margins but there is no nearby grid centre
// inside the inlet. The nearest passable centre is east of the lip.
const shore = [[4, 12], [10.3, 12], [10.3, 20], [4, 20], [4, 16.1],
  [10.1, 16.1], [10.1, 15.9], [4, 15.9], [4, 12]].map(([x, y]) => {
  const p = point(x, y);
  return [p.longitude, p.latitude].map(v => Math.round(v * 100000));
});
const segments = Float64Array.from(shore.slice(1).flatMap((p, i) => [...shore[i], ...p]));
const spitLines = {edge: segments, parity: segments};
const now = new Date('2026-01-01T00:00:00Z');
const screen = {
  ready: () => true,
  exportExclusions: () => ({checked_at: now.toISOString()}),
  coversGeometry: g => geometryCoveredByBounds(g, [0, point(32, 32).latitude, point(32, 32).longitude, 0]),
  geometryAllowed: () => true, // No protected-area polygons in this synthetic tile.
};
const build = (model, lines, stops) => buildProtectedRoute({model, lines, screen, stops, title: 'Synthetic route', now});
function readGpx(gpx) {
  assert.match(gpx, /<rte>/);
  assert.match(gpx, /NOT FOR NAVIGATION/);
  const points = [...gpx.matchAll(/<rtept lat="([^"]+)" lon="([^"]+)"/g)]
    .map(m => ({latitude: Number(m[1]), longitude: Number(m[2])}));
  assert.ok(points.length >= 2, 'GPX contains route points');
  return points;
}

// At most ~9 m between samples here: enough to witness the synthetic blocks,
// not a general shoreline-intersection algorithm or navigation clearance.
function unconfirmed(model, lines, points) {
  return points.slice(1).flatMap((b, i) => {
    const a = points[i], dy = b.latitude - a.latitude, dx = b.longitude - a.longitude;
    const steps = Math.max(1, Math.ceil(Math.hypot(dx, dy) / 0.00008));
    const states = new Set();
    for (let k = 0; k <= steps; k++) {
      const p = {latitude: a.latitude + dy * k / steps, longitude: a.longitude + dx * k / steps};
      const at = placeOf(model, lines, p);
      if (at.state !== 'water') states.add(at.reason ?? at.state);
    }
    return states.size ? [{segment: i === 0 ? 'first' : i === points.length - 2 ? 'last' : `interior-${i}`, states: [...states].sort()}] : [];
  });
}

for (const [name, shoreline, lines, from] of [
  ['all-water leg', model('w1024'), null, start],
  ['confirmed passage through mixed cells', model('m1024'), spitLines, point(12.01, 16.01)],
]) {
  test(`F16-01: ${name} exports both stops and water-only connectors`, () => {
    const points = readGpx(build(shoreline, lines, [from, end]).gpx);
    assert.deepEqual([points[0], points.at(-1)], [from, end]);
    assert.deepEqual(unconfirmed(shoreline, lines, points), []);
  });
}

for (const [name, shoreline, lines, state] of [
  ['land stop beside water', model('w522l1w501'), null, 'land'],
  ['water stop across a spit', model('m1024'), spitLines, 'water'],
  ['unresolved mixed cell beside water', model('w522m1w501'), null, 'unknown'],
]) {
  for (const [side, stops] of [['departure', [start, end]], ['arrival', [end, start]]]) {
    test(`F16-01: ${name} at ${side} must not export an unconfirmed connector`, t => {
      assert.equal(placeOf(shoreline, lines, start).state, state);
      assert.equal(placeOf(shoreline, lines, end).state, 'water');
      let result;
      try {
        result = build(shoreline, lines, stops);
      } catch (err) {
        // Do not treat an exception such as a missing dependency or exhausted node budget as a pass.
        const reason = state === 'unknown' ? 'lines-needed' : side === 'departure' ? 'start-not-water' : 'end-not-water';
        assert.match(err.message, new RegExp(`^Planning route unavailable for leg 1 \\(${reason}\\)\\.`));
        t.diagnostic(`GPX refused: ${err.message}`);
        return;
      }
      const violations = unconfirmed(shoreline, lines, readGpx(result.gpx));
      t.diagnostic(JSON.stringify({stop: state, nm: Number(result.nm.toFixed(3)), violations}));
      assert.deepEqual(violations, [], 'GPX contains a segment not confirmed as water by the shoreline fixture');
    });
  }
}
