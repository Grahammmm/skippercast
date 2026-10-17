// Map startup (P4-05): deferred loading helpers, the daily-feed parts the map
// reads at startup, the on-map legend's rows, and the startup JSON budget file.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {whenView, mapReady} from '../dist/startup.js';
import {validDailyPart, loadDailyPart, dailyPartURL} from '../dist/daily-feed.js';
import {legendEntries} from '../web/legend.ts';
import {isJSON, isLive, summarise, stubForecast} from '../scripts/measure_startup.mjs';
import {POINT_SIGNATURE} from '../dist/marine-data.js';

function fakeDocument(view) {
  const observers = [];
  const body = {dataset: {view}};
  globalThis.MutationObserver = class { constructor(fn) { this.fn = fn; observers.push(this); } observe() {} disconnect() { this.off = true; } };
  return {body, set(next) { body.dataset.view = next; for (const o of observers) if (!o.off) o.fn([]); }};
}

test('whenView runs the work once, when the view first shows', t => {
  t.after(() => { delete globalThis.MutationObserver; });
  const doc = fakeDocument('map');
  let runs = 0;
  whenView('forecast', () => runs++, doc);
  assert.equal(runs, 0, 'not while the map shows');
  doc.set('guide');
  assert.equal(runs, 0);
  doc.set('forecast');
  doc.set('map');
  doc.set('forecast');
  assert.equal(runs, 1, 'once only');
  let now = 0;
  whenView('forecast', () => now++, doc);
  assert.equal(now, 1, 'at once when the view is already showing');
  let early = 0;
  const run = whenView('export', () => early++, fakeDocument('map'));
  run(); run();
  assert.equal(early, 1, 'the returned function runs it once, sooner');
});

test('mapReady hides the skeleton and clears aria-busy', () => {
  const skeleton = {hidden: false}, wrap = {removed: null, removeAttribute(name) { this.removed = name; }};
  mapReady({getElementById: id => id === 'map-loading' ? skeleton : null, querySelector: sel => sel === '.map-wrap' ? wrap : null});
  assert.equal(skeleton.hidden, true);
  assert.equal(wrap.removed, 'aria-busy');
  mapReady({getElementById: () => null, querySelector: () => null});   // absent elements are fine
});

const region = {id: 'morro-bay'};
const part = extra => ({schema_version: 1, region_id: 'morro-bay', generated_at: '2026-09-29T11:00:00Z', catch_probability: null, bite_score: null, ...extra});

test('daily feed parts are checked like the full feed', () => {
  assert.ok(validDailyPart(part({part: 'regulations', regulations: {}}), 'regulations', region));
  assert.ok(validDailyPart(part({part: 'mpa-boundaries', sources: {}}), 'mpa-boundaries', region));
  assert.ok(!validDailyPart(part({part: 'mpa-boundaries', sources: {}}), 'regulations', region), 'the part asked for');
  assert.ok(!validDailyPart(part({part: 'regulations', regulations: {}, region_id: 'bodega-bay'}), 'regulations', region), 'region');
  assert.ok(!validDailyPart(part({part: 'regulations', regulations: {}, catch_probability: 0.3}), 'regulations', region), 'no catch probability');
  assert.ok(!validDailyPart(part({part: 'regulations', regulations: {}, generated_at: 'soon'}), 'regulations', region), 'timestamp');
  assert.ok(!validDailyPart(part({part: 'regulations', regulations: null}), 'regulations', region));
  assert.ok(!validDailyPart(part({part: 'mpa-boundaries', sources: []}), 'mpa-boundaries', region));
  assert.equal(dailyPartURL('mpa-boundaries', region), '/api/daily?region=morro-bay&part=mpa-boundaries');
});

test('loadDailyPart returns a valid part and throws otherwise, so callers fall back to the full feed', async () => {
  const answer = body => async url => { assert.match(url, /^\/api\/daily\?region=morro-bay&part=regulations$/); return Response.json(body); };
  const data = await loadDailyPart('regulations', {region, fetch: answer(part({part: 'regulations', regulations: {reviewed_at: 'r'}}))});
  assert.deepEqual(data.regulations, {reviewed_at: 'r'});
  await assert.rejects(loadDailyPart('regulations', {region, fetch: answer(part({part: 'regulations', regulations: {}, bite_score: 7}))}));
  await assert.rejects(loadDailyPart('regulations', {region, fetch: async () => new Response('down', {status: 503})}));
  await assert.rejects(loadDailyPart('reports', {region, fetch: answer({})}), /Unknown/);
});

const state = (checked, assets = ['atlas', 'charters', 'commercial_ais'], extra = {}) => ({
  checked: id => checked.includes(id), hasAsset: key => assets.includes(key), weatherLayer: null, seafloorView: null, searchAreasLoaded: false, ...extra,
});

test('the legend lists what the map shows by default, MPAs first', () => {
  const rows = legendEntries(state(['layer-charters', 'layer-targets', 'layer-areas', 'layer-forecast']));
  assert.deepEqual(rows.map(r => r.id), ['mpa', 'grades', 'cluster', 'habitat', 'charter']);
  assert.match(rows[0].text, /always shown/);
  assert.equal(rows[1].link.href, '#grade-guide');
  assert.match(rows[1].text, /not catch odds/, 'the caveat survives');
});

test('the legend follows layer choices and what the region publishes', () => {
  assert.deepEqual(legendEntries(state([])).map(r => r.id), ['mpa'], 'MPAs are always on');
  assert.deepEqual(legendEntries(state(['layer-targets', 'layer-charters', 'layer-commercial'], [])).map(r => r.id), ['mpa'], 'no dataset, no row');
  const all = legendEntries(state(['layer-targets', 'layer-areas', 'layer-drifts', 'layer-charters', 'layer-commercial', 'layer-forecast', 'layer-central-coverage', 'layer-seafloor'],
    undefined, {weatherLayer: 'Waves · feet', seafloorView: 'Substrate', searchAreasLoaded: true}));
  assert.deepEqual(all.map(r => r.id), ['mpa', 'grades', 'cluster', 'habitat', 'search', 'drift', 'charter', 'commercial', 'weather', 'coverage', 'seafloor']);
  assert.equal(all.find(r => r.id === 'weather').label, 'Weather layer · Waves · feet');
  assert.equal(all.find(r => r.id === 'seafloor').text, 'Colored by Substrate.');
  assert.match(all.find(r => r.id === 'drift').text, /not navigation routes/);
});

test('the startup measurement counts JSON bodies and the budget allows 10% over the measured value', () => {
  assert.ok(isJSON('https://s/data/atlas.json'));
  assert.ok(isJSON('https://s/data/x.geojson'));
  assert.ok(isJSON('https://s/api/forecast?region=x', 'application/json; charset=utf-8'));
  assert.ok(!isJSON('https://s/assets/app.1234567890.js', 'text/javascript'));
  const summary = summarise([{path: '/a.json', bytes: 10, beforeInteractive: true}, {path: '/a.json', bytes: 5, beforeInteractive: false},
    {path: '/b.json', bytes: 20, beforeInteractive: false}, {path: '/api/forecast?region=x', bytes: 50, beforeInteractive: true, live: true}]);
  assert.deepEqual(summary.rows.map(r => [r.path, r.bytes, r.requests]), [['/b.json', 20, 1], ['/a.json', 15, 2], ['/api/forecast?region=x', 50, 1]], 'static first');
  assert.equal(summary.interactive, 60);
  assert.equal(summary.startup, 85);
  assert.equal(summary.static, 35, 'only committed files are budgeted');
  assert.equal(summary.live, 50);
  assert.ok(isLive('/api/daily') && isLive('/feeds/data/x.json') && !isLive('/data/atlas.json') && !isLive('/regions/x/region.json'));
  const budget = JSON.parse(readFileSync(new URL('../scripts/startup-budget.json', import.meta.url), 'utf8'))['morro-bay'];
  assert.equal(budget.max_bytes, Math.ceil(budget.static_bytes * 1.1));
  assert.ok(budget.target_bytes <= 400 * 1024, 'the guide target (P4-05) is 400 KB');
});

test('the stand-in forecast passes the checks loadMarine applies to the shared forecast', () => {
  const region = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8'));
  const now = Date.parse('2026-09-29T12:34:00Z'), f = stubForecast(region, now);
  assert.equal(f.region_id, 'morro-bay');
  assert.equal(JSON.stringify(f.requested_points), POINT_SIGNATURE);
  assert.ok(Date.now() - f.retrieved < 3 * 3600000 || f.retrieved === now);
  for (const model of Object.values(f.models)) {
    assert.equal(model.data.length, region.forecast_points.length);
    assert.ok(model.meta);
    assert.equal(model.data[0].hourly.time.length, 192);
  }
});

// v2 entry scheduling: exercise real signals and Brief loader with controlled frames/fetches.
let v2;
async function v2Startup() {
  if (v2) return v2;
  const [{build}, {mkdtemp}, {tmpdir}, {join}, {pathToFileURL}, {rendererPlugins}] = await Promise.all([
    import('esbuild'), import('node:fs/promises'), import('node:os'), import('node:path'), import('node:url'), import('./helpers/esbuild-url.mjs'),
  ]);
  const out = join(await mkdtemp(join(tmpdir(), 'p02-startup-')), 'startup.mjs');
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {deferDailyFeed} from './web/app/main.tsx';
    export {dailyFeed, feedGaps, loadDailyFeed, regionalForecast} from './web/brief/Brief.tsx';
    export {signal} from '@preact/signals';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  v2 = await import(pathToFileURL(out).href);
  return v2;
}
function controlledPaint() {
  let id = 0;
  const callbacks = new Map();
  return {frame: fn => {callbacks.set(++id, fn); return id;}, cancel: id => callbacks.delete(id),
    paint() {const pending = [...callbacks.values()]; callbacks.clear(); for (const fn of pending) fn(0);},
    get pending() {return callbacks.size;}};
}
const v2Feed = id => ({schema_version: 1, region_id: id, generated_at: '2026-10-08T20:00:00Z', sources: {
  buoy: {id: 'buoy', kind: 'observation', checked_at: '2026-10-08T19:00:00Z', status: 'ok', data: {observations: [{time: '2026-10-08T18:00:00Z'}]}},
}});

test('v2 daily feed waits for a paint opportunity, then requests the latest region once', async () => {
  const m = await v2Startup(), paint = controlledPaint(), selected = m.signal('old'), calls = [];
  const forecast = {region: 'latest', retrieved: 42}; m.regionalForecast.value = forecast;
  const stop = m.deferDailyFeed({current: () => selected.value, loaded: () => undefined,
    load: async id => {calls.push(id);}, frame: paint.frame, cancel: paint.cancel});
  assert.deepEqual(calls, [], 'no daily fetch in the startup task');
  paint.paint(); assert.deepEqual(calls, [], 'first animation frame is still before paint');
  selected.value = 'latest'; assert.deepEqual(calls, []);
  paint.paint(); assert.deepEqual(calls, ['latest']);
  paint.paint(); assert.deepEqual(calls, ['latest'], 'no repeated frame request');
  assert.equal(m.regionalForecast.peek(), forecast, 'critical forecast data and retrieval clock are untouched');
  selected.value = 'third'; assert.deepEqual(calls, ['latest', 'third']);
  stop(); selected.value = 'fourth'; assert.deepEqual(calls, ['latest', 'third']);
});

test('v2 deferred real loader rejects stale completion and preserves source clocks', async () => {
  const m = await v2Startup(), paint = controlledPaint(), selected = m.signal('alpha'), pending = [];
  m.dailyFeed.value = null;
  const fetchFn = url => new Promise(resolve => pending.push({url, resolve}));
  const loads = [];
  const stop = m.deferDailyFeed({current: () => selected.value, loaded: () => m.dailyFeed.peek()?.region_id,
    load: id => {const done = m.loadDailyFeed(id, fetchFn); loads.push(done); return done;}, frame: paint.frame, cancel: paint.cancel});
  assert.equal(pending.length, 0);
  paint.paint(); assert.equal(pending.length, 0);
  paint.paint(); assert.equal(pending.length, 2, 'one load reads daily and conditions');
  selected.value = 'beta'; assert.equal(pending.length, 4);
  const beta = v2Feed('beta');
  for (const req of pending.slice(2)) req.resolve(Response.json(beta));
  await loads[1]; assert.equal(m.dailyFeed.peek().region_id, 'beta');
  assert.equal(m.dailyFeed.peek().sources.buoy.data.observations[0].time, beta.sources.buoy.data.observations[0].time);
  for (const req of pending.slice(0, 2)) req.resolve(Response.json(v2Feed('alpha')));
  await loads[0]; assert.equal(m.dailyFeed.peek().region_id, 'beta', 'late alpha cannot replace beta');
  assert.deepEqual(m.feedGaps.peek(), []);
  stop();
});

test('v2 deferred load failure is reported by Brief without a retry loop', async () => {
  const m = await v2Startup(), paint = controlledPaint(), selected = m.signal('failed');
  let calls = 0, done;
  const stop = m.deferDailyFeed({current: () => selected.value, loaded: () => undefined,
    load: id => {calls++; done = m.loadDailyFeed(id, async () => {throw new Error('offline');}); return done;}, frame: paint.frame, cancel: paint.cancel});
  paint.paint(); paint.paint(); await done;
  assert.equal(m.dailyFeed.peek(), null); assert.match(m.feedGaps.peek().join(' '), /could not be read/);
  paint.paint(); assert.equal(calls, 1);
  stop();
});

test('v2 cancel before paint and an empty or already loaded region perform no daily load', async () => {
  const m = await v2Startup();
  for (const [id, loaded, cancel] of [['x', undefined, true], [null, undefined, false], ['x', 'x', false]]) {
    const paint = controlledPaint(); let calls = 0;
    const stop = m.deferDailyFeed({current: () => id, loaded: () => loaded, load: async () => {calls++;}, frame: paint.frame, cancel: paint.cancel});
    if (cancel) stop();
    paint.paint(); paint.paint(); assert.equal(calls, 0);
    stop(); assert.equal(paint.pending, 0);
  }
});
