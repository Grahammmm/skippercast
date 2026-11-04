// SC1322-11: trip plan legs (harbor, stops, harbor) take the water route where one is computed (web/route.ts,
// FSC-04) and label the rest as straight line; the planner's "Straight-line legs between stops" clause shows only
// while a leg is straight. Synthetic land-water products reuse tests/test_route.mjs's fixture, so every case is offline.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {tripLegs} from '../web/trip-legs.ts';
import {runMinutes} from '../web/brief/run.ts';
import {distanceNm} from '../dist/spot-ranking.js';
import {decodeCells, landWaterModel} from '../web/land-water.ts';

const port = {name: 'Home', lat: 35, lon: -121};
const stops = [1, 2, 3].map(n => ({id: String(n), name: `Stop ${n}`, lat: 35 + n * 0.01, lon: -121}));
const straight = (a, b) => distanceNm({latitude: a.lat, longitude: a.lon}, {latitude: b.lat, longitude: b.lon});
/** A fake route: `nm` per call in order (or a failure reason), counting calls. */
const fake = answers => { const f = () => { const x = answers[f.calls++ % answers.length]; return typeof x === 'number' ? {ok: true, nm: x, points: []} : {ok: false, reason: x}; }; f.calls = 0; return f; };

test('every leg routed: water legs, nm and totals from the route, run minutes from the route nm', () => {
  const route = fake([5, 6, 7, 8]), r = tripLegs(port, stops, 20, route);
  assert.equal(route.calls, 4);
  assert.deepEqual(r.legs.map(l => [l.from, l.to, l.nm, l.basis, 'why' in l]), [['Home', 'Stop 1', 5, 'water', false], ['Stop 1', 'Stop 2', 6, 'water', false],
    ['Stop 2', 'Stop 3', 7, 'water', false], ['Stop 3', 'Home', 8, 'water', false]]);
  assert.deepEqual(r.legs.map(l => l.runMin), [5, 6, 7, 8].map(nm => runMinutes(nm, 20)));
  assert.equal(r.totalNm, 26);
  assert.equal(r.totalRunMin, [5, 6, 7, 8].reduce((n, nm) => n + runMinutes(nm, 20), 0));
});

test('one leg without a route keeps the straight line, labelled with why; the others stay water', () => {
  const r = tripLegs(port, stops, 20, fake([5, 'no-route', 7, 8])), points = [port, ...stops, port];
  assert.deepEqual(r.legs.map(l => l.basis), ['water', 'straight', 'water', 'water']);
  assert.equal(r.legs[1].why, 'no-route');
  assert.equal(r.legs[1].nm, straight(points[1], points[2]));
  assert.equal(r.legs[1].runMin, runMinutes(r.legs[1].nm, 20));
  assert.equal(r.totalNm, 5 + r.legs[1].nm + 7 + 8);
  const none = tripLegs(port, stops, 20, () => null);
  assert.ok(none.legs.every(l => l.basis === 'straight' && !('why' in l)), 'a null route is a straight leg with no reason');
});

test('no route argument: the legs and totals of before, each marked straight', () => {
  const r = tripLegs(port, stops, 20), points = [port, ...stops, port];
  assert.deepEqual(r.legs, points.slice(1).map((b, i) => {
    const nm = straight(points[i], b);
    return {from: points[i].name, to: b.name, nm, runMin: runMinutes(nm, 20), basis: 'straight', screen: {inside: false, name: null, distanceM: null, screened: false}};
  }));
  assert.equal(r.totalNm, r.legs.reduce((n, l) => n + l.nm, 0));
  assert.equal(r.totalRunMin, r.legs.reduce((n, l) => n + l.runMin, 0));
});

test('no usable speed gives no run minutes, whatever the route', () => {
  for (const speed of [null, 0, NaN]) {
    const r = tripLegs(port, stops, speed, fake([5, 'no-route']));
    assert.ok(r.legs.every(l => l.runMin === null), String(speed)); assert.equal(r.totalRunMin, null);
    assert.equal(r.legs[0].basis, 'water');
  }
});

test('duplicates and bad coordinates are skipped before any route call; fewer than two stops never routes', () => {
  const route = fake([3]);
  const r = tripLegs(port, [stops[0], {id: 'bad', name: 'Bad', lat: NaN, lon: 0}, stops[1], {...stops[0], name: 'Again'}], 10, route);
  assert.deepEqual(r.skipped, ['Bad']);
  assert.deepEqual(r.legs.map(l => l.to), ['Stop 1', 'Stop 2', 'Home']);
  assert.equal(route.calls, r.legs.length);
  const once = fake([3]);
  assert.equal(tripLegs(port, [stops[0], stops[0]], 10, once).legs.length, 0); assert.equal(once.calls, 0);
});

// The planner over a real land-water product (tile 12/671/1616, 32×32 cells).
const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/land-water/${name}`, import.meta.url), 'utf8'));
const coast = fixture('coast.json'), COAST = '12/671/1616', N = 4096, G = 32;
const cell = (col, row) => ({lat: Math.atan(Math.sinh(Math.PI * (1 - 2 * (1616 + (row + 0.5) / G) / N))) * 180 / Math.PI, lon: (671 + (col + 0.5) / G) / N * 360 - 180});
const paint = (rects, base = 'w'.repeat(G * G)) => {
  const a = [...base];
  for (const [c, c0, r0, c1, r1] of rects) for (let r = r0; r <= r1; r++) for (let k = c0; k <= c1; k++) a[r * G + k] = c;
  return a.join('').replace(/(.)\1*/g, m => m[0] + m.length);
};
const product = (rects, base, bounds = [-12110000, 3530000, -12075000, 3555000]) => landWaterModel({...coast, bounds, tiles: {[COAST]: paint(rects, base)}}, 'fixture');
const ready = (model, lines = null) => ({region: 'fixture', state: 'ready', model, lines, linesLoading: false});
const CLAUSE = /Straight-line legs between stops; the real route is longer\./, SEA = /Sea state, the bar, fuel and conditions at each stop are not included\./;

test('planner: routed legs drop the straight-line clause; a straight leg is labelled and brings it back; lines are asked once', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'trip-legs-route-')), out = join(dir, 'ui.mjs');
  try {
    await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {Planner} from './web/app/Planner.tsx';
      export {createPlanner} from './web/planner.ts';
      export {cruiseSpeed} from './web/limits.ts';
      export {landWater, loadLandWaterLines, resetLandWater} from './web/land-water.ts';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const m = await import(pathToFileURL(out).href);
    const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true};
    const home = cell(4, 8), spots = [cell(10, 8), cell(16, 8)];
    const targets = spots.map((p, i) => ({id: `s${i}`, label: `Spot ${i}`, latitude: p.lat, longitude: p.lon, neighborhood_depth_ft: [90, 110]}));
    const model = m.createPlanner({atlas: {targets, areas: []}, screen,
      region: {id: 'fixture', timezone: 'UTC', mpa: {bounds: [-180, -90, 180, 90]}}, storage: null, emit() {},
      map: {getSize: () => ({x: 1}), getBounds: () => ({getWest: () => -180, getSouth: () => -90, getEast: () => 180, getNorth: () => 90})},
      getVisible: () => [], nav: {open() {}, showMap() {}, conditions() {}}, loadPorts: async () => ({ports: []})});
    try {
      await new Promise(resolve => setTimeout(resolve, 0));
      model.setResearch(true); model.toggleSpot('s0', true); model.toggleSpot('s1', true);
      model.ports.value = [{id: 'home', name: 'Home', match: [home.lat, home.lon]}]; model.setFilter('port', 'home');
      m.cruiseSpeed.value = 20;
      const html = () => m.render(m.h(m.Planner, {model, open: false}));
      const legs = markup => [...markup.matchAll(/<li>([^<]*)<\/li>/g)].map(x => x[1]).filter(t => t.includes('→'));

      m.landWater.value = ready(product([]));
      let markup = html();
      assert.deepEqual(legs(markup).map(t => t.split(' · ')[0]), ['Home → Spot 0', 'Spot 0 → Spot 1', 'Spot 1 → Home']);
      assert.ok(legs(markup).every(t => /\d nm · at least \d+ min$/.test(t)), legs(markup).join(' | '));
      assert.doesNotMatch(markup, CLAUSE); assert.match(markup, SEA);

      m.landWater.value = ready(product([['l', 15, 7, 17, 9]]));
      markup = html();
      assert.deepEqual(legs(markup).map(t => / nm straight line/.test(t)), [false, true, true], legs(markup).join(' | '));
      assert.match(markup, CLAUSE); assert.match(markup, SEA);

      m.landWater.value = {region: 'other', state: 'ready', model: product([]), lines: null, linesLoading: false};
      assert.ok(legs(html()).every(t => / nm straight line/.test(t)), 'another region\'s product never routes these legs');
      assert.match(html(), CLAUSE);

      // A wall with a gap only the lines file can open: lines-needed, so straight, until the shared lines request lands.
      const walled = product([['l', 0, 22, 31, 22], ['m', 17, 22, 18, 22]], decodeCells(coast.tiles[COAST], G * G), coast.bounds);
      const north = cell(14, 12), south = [cell(14, 25), cell(15, 26)];
      model.ports.value = [{id: 'home', name: 'Home', match: [north.lat, north.lon]}];
      model.tripAtlas.value = {...model.tripAtlas.value, targets: targets.map((t, i) => ({...t, latitude: south[i].lat, longitude: south[i].lon}))};
      m.landWater.value = ready(walled);
      for (let i = 0; i < 2; i++) {
        markup = html();
        assert.deepEqual(legs(markup).map(t => / nm straight line/.test(t)), [true, false, true], legs(markup).join(' | '));
        assert.match(markup, CLAUSE);
      }
      const text = await readFile(new URL('./fixtures/land-water/coast.lines.json', import.meta.url), 'utf8');
      let asked = 0;
      const fetchFn = async () => { asked++; return {ok: true, text: async () => text}; };
      await Promise.all([m.loadLandWaterLines('fixture', fetchFn), m.loadLandWaterLines('fixture', fetchFn)]);
      await m.loadLandWaterLines('fixture', fetchFn);
      assert.equal(asked, 1, 'one lines request across re-renders and callers');
      markup = html();
      assert.deepEqual(legs(markup).map(t => / nm straight line/.test(t)), [false, false, false], legs(markup).join(' | '));
      assert.doesNotMatch(markup, CLAUSE); assert.match(markup, SEA);
    } finally { model.dispose(); m.resetLandWater(); }
  } finally { await rm(dir, {recursive: true, force: true}); }
});
