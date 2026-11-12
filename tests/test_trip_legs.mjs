import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {tripLegs} from '../web/trip-legs.ts';
import {runMinutes} from '../web/brief/run.ts';
import {distanceNm} from '../dist/spot-ranking.js';

const port = {name: 'Home', lat: 35, lon: -121};
const stops = [1, 2, 3].map(n => ({id: String(n), name: `Stop ${n}`, lat: 35 + n * 0.01, lon: -121}));
const dist = (a, b) => distanceNm({latitude: a.lat, longitude: a.lon}, {latitude: b.lat, longitude: b.lon});
test('port and three stops keep every pair and sum separately rounded run minutes', () => {
  const route = tripLegs(port, stops, 20), points = [port, ...stops, port];
  assert.equal(route.legs.length, 4);
  for (const [i, leg] of route.legs.entries()) {
    assert.equal(leg.from, points[i].name); assert.equal(leg.to, points[i + 1].name);
    assert.equal(leg.nm, dist(points[i], points[i + 1]));
    assert.equal(leg.runMin, runMinutes(leg.nm, 20));
  }
  assert.equal(route.totalNm.toFixed(1), route.legs.reduce((n, l) => n + l.nm, 0).toFixed(1));
  assert.equal(route.totalRunMin, route.legs.reduce((n, l) => n + l.runMin, 0));
  assert.notEqual(route.totalRunMin, runMinutes(route.totalNm, 20));
});
test('missing or unusable speeds never supply run times', () => {
  for (const speed of [null, 0, -1, NaN, Infinity]) {
    const route = tripLegs(port, stops, speed);
    assert.ok(route.legs.every(l => l.runMin === null)); assert.equal(route.totalRunMin, null);
  }
});
test('no origin omits both port legs; fewer than two distinct valid stops has no legs', () => {
  assert.deepEqual(tripLegs(null, stops, null).legs.map(l => [l.from, l.to]), [['Stop 1', 'Stop 2'], ['Stop 2', 'Stop 3']]);
  for (const origin of [null, port]) for (const choices of [[], stops.slice(0, 1), [stops[0], stops[0]]]) {
    assert.equal(tripLegs(origin, choices, null).legs.length, 0);
  }
});
test('bad coordinates are named and skipped without breaking the chain; duplicate ids keep first position', () => {
  const invalid = [{id: 'nan', name: 'NaN', lat: NaN, lon: 0}, {id: 'lon', name: 'Bad longitude', lat: 0, lon: 200},
    {id: 'lat', name: 'Bad latitude', lat: -91, lon: 0}, {id: 'inf', name: 'Infinite', lat: 0, lon: Infinity}];
  const route = tripLegs(null, [stops[0], ...invalid, stops[1], {...stops[0], name: 'Duplicate'}, stops[2]], null);
  assert.deepEqual(route.skipped, invalid.map(p => p.name));
  assert.deepEqual(route.legs.map(l => l.to), ['Stop 2', 'Stop 3']);
  assert.equal(tripLegs(null, [{...stops[0], lat: 90, lon: 180}, {...stops[1], lat: -90, lon: -180}], 10).legs.length, 1);
});

test('planner rendering follows selection and stored waypoint order, without changing GPX or gates', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'trip-legs-')), out = join(dir, 'ui.mjs');
  try {
    await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {Planner} from './web/app/Planner.tsx';
      export {createPlanner} from './web/planner.ts';
      export {cruiseSpeed} from './web/limits.ts';
      export {buildExport} from './dist/trip-export.js';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const m = await import(pathToFileURL(out).href);
    let fresh = true;
    const screen = {ready: () => fresh, pointAllowed: () => true, geometryAllowed: () => true};
    const targets = stops.map(p => ({id: p.id, label: p.name, latitude: p.lat, longitude: p.lon, neighborhood_depth_ft: [90, 110]}));
    const model = m.createPlanner({atlas: {targets, areas: []}, screen,
      region: {id: 'test', timezone: 'UTC', mpa: {bounds: [-180, -90, 180, 90]}}, storage: null, emit() {},
      map: {getSize: () => ({x: 1}), getBounds: () => ({getWest: () => -180, getSouth: () => -90, getEast: () => 180, getNorth: () => 90})},
      getVisible: () => [], nav: {open() {}, showMap() {}, conditions() {}}, loadPorts: async () => ({ports: []})});
    try {
      await new Promise(resolve => setTimeout(resolve, 0));
      model.setResearch(true); model.toggleSpot('1', true);
      const html = () => m.render(m.h(m.Planner, {model, open: false}));
      assert.doesNotMatch(html(), /aria-label="Stops in order"/);
      model.toggleSpot('2', true); model.toggleSpot('3', true);
      const request = {atlas: model.tripAtlas.value, screen, ids: model.draft.value.ids, allowResearch: true,
        region: model.region, now: new Date('2026-11-01T00:00:00Z')};
      const before = m.buildExport(request).gpx;
      let markup = html();
      assert.match(markup, /<ol aria-label="Stops in order">/);
      assert.match(markup, /No home port chosen, so the run from port is not counted\./);
      assert.match(markup, /Sea state, the bar, fuel and conditions at each stop are not included\./);
      assert.doesNotMatch(markup, /at least \d+ min/);
      assert.ok(before === m.buildExport(request).gpx, 'rendering leaves GPX bytes unchanged');
      model.toggleSpot('2', false); model.toggleSpot('2', true);
      assert.match(html(), /Stop 1 → Stop 3/); assert.match(html(), /Stop 3 → Stop 2/);
      model.draft.value = {...model.draft.value, ids: ['user:b', ...model.draft.value.ids, 'user:a'], userWaypoints: [
        {id: 'user:a', name: 'Waypoint A', latitude: 35.4, longitude: -121, category: 'other'},
        {id: 'user:b', name: 'Waypoint B', latitude: 35.5, longitude: -121, category: 'other'}]};
      assert.match(html(), /Stop 2 → Waypoint A/); assert.match(html(), /Waypoint A → Waypoint B/);
      model.ports.value = [{id: 'home', name: 'Home', match: [port.lat, port.lon]}]; model.setFilter('port', 'home');
      m.cruiseSpeed.value = 20; markup = html();
      assert.match(markup, /Home → Stop 1/); assert.match(markup, /Waypoint B → Home/); assert.match(markup, /at least \d+ min/);
      model.portsFailed.value = true;
      assert.match(html(), /No home port chosen/); assert.doesNotMatch(html(), /Home → Stop 1/);
      model.search.value = 'no matching spots';
      assert.match(html(), /Stop 1 → Stop 3/, 'search cannot hide selected stops');
      model.tripAtlas.value = {...model.tripAtlas.value, targets: targets.map(t => t.id === '3' ? {...t, latitude: NaN} : t)};
      assert.match(html(), /Stops skipped because coordinates are unavailable: Stop 3/);
      fresh = false;
      assert.throws(() => m.buildExport(request), /Protected-area checks/);
      assert.doesNotMatch(html(), /id="export-download"(?![^>]*disabled)[^>]*>/);
      model.preset('none'); assert.doesNotMatch(html(), /aria-label="Stops in order"/);
    } finally { model.dispose(); }
  } finally { await rm(dir, {recursive: true, force: true}); }
});
