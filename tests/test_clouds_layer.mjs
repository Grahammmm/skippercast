// Clouds (FE-22, docs/plans/front-end/dev-plan.md): the GOES observed-frame loop
// over a fake engine and a fake MapLibre, so no GPU, library or network is needed.
// Frames come only from a published time list (FE-44's goes-times.json shape),
// inside packages/coast's gate; the loop steps, holds the newest frame, and stops
// when the page is hidden, the Chart is not shown, the viewer holds it or motion
// is reduced; other days show nothing. Fixtures are synthetic. web/map/*.ts run
// by type stripping; the legend and rail are bundled with esbuild and rendered.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {signal} from '@preact/signals';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {
  CLOUD_INDEX, CLOUD_OPACITY, FRAME_MS, HOLD_MS, INDEX_REFRESH_MS, MAX_FRAMES, NO_FRAMES, OTHER_DAY,
  cloudHeld, cloudIndex, cloudOverlay, cloudStamp, cloudStatus, createClouds, frameId, frameLabel,
} from '../web/map/clouds.ts';
import {createEngine, mapOptions} from '../web/map/engine.ts';
import {COASTLINE_GLOW} from '../web/map/coastline.ts';
import {MARK_PICK} from '../web/map/marks.ts';
import {railNotes} from '../web/map/layers.ts';
import {unavailable} from '../web/map/chart.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const TZ = 'America/Los_Angeles';
const MIN = 60_000;
/** 8 pm on 1 October in Los Angeles. */
const NOW = Date.parse('2026-10-02T03:00:00Z');
const iso = ms => new Date(ms).toISOString();
const flush = () => new Promise(resolve => setImmediate(resolve));
/** goes-times.json as FE-44 publishes it: 24 five-minute frames, the newest `ageMin` minutes before `at`. */
const index = (at = NOW, ageMin = 7) => {
  const times = Array.from({length: 24}, (_, i) => iso(at - ageMin * MIN - (23 - i) * 5 * MIN));
  return {id: 'goes-longwave', kind: 'observation', observedAt: times.at(-1), fetchedAt: iso(at - 5 * MIN), availableTimes: times,
    layer: 'goes_longwave_imagery', url: 'https://nowcoast.noaa.gov/', attribution: 'NOAA / NESDIS · GOES', license: 'public-domain-us-gov',
    limitations: 'Observed frames only.'};
};
const timeOf = url => decodeURIComponent(new URL(url.replace('{bbox-epsg-3857}', '0,0,1,1')).searchParams.get('time'));

test('a frame is a raster source pinned to its listed acquisition time, drawn transparent until shown', () => {
  const cloud = index(), at = cloud.availableTimes.at(-1);
  const {sources, layers} = cloudOverlay(cloud, [at, '2026-10-02T02:54:00.000Z'], new Date(NOW));
  assert.deepEqual(Object.keys(sources), [frameId(at)], 'a time not in the list gets no source');
  const source = sources[frameId(at)];
  assert.equal(source.type, 'raster');
  assert.equal(source.tileSize, 512);
  assert.equal(new URL(source.tiles[0].replace('{bbox-epsg-3857}', '0,0,1,1')).origin, 'https://nowcoast.noaa.gov');
  assert.equal(timeOf(source.tiles[0]), at);
  assert.doesNotMatch(source.tiles[0], /current|latest/);
  assert.deepEqual(layers.map(l => [l.id, l.source, l.type]), [[frameId(at), frameId(at), 'raster']]);
  assert.equal(layers[0].paint['raster-opacity'], 0);
  assert.equal(layers[0].paint['raster-saturation'], -1, 'monochrome');
  assert.equal(layers[0].paint['raster-fade-duration'], 0, 'a frame change is a cut, not a blend');
});

test('labels name the acquisition time and age; the rail says why nothing draws', () => {
  const now = new Date(NOW), cloud = index();
  assert.equal(frameLabel('2026-10-02T02:53:00.000Z', now, TZ), 'observed 7:53 pm · 7 min ago');
  assert.equal(frameLabel('2026-10-02T02:59:40.000Z', now, TZ), 'observed 7:59 pm · under 1 min ago');
  assert.equal(cloudStatus(cloud, ['2026-10-02T02:53:00.000Z'], now, now, TZ), 'observed 7:53 pm · 7 min ago', 'the newest frame drawn');
  assert.equal(cloudStatus(null, [], now, now, TZ), NO_FRAMES);
  assert.equal(cloudStatus(cloud, [], new Date('2026-10-02T17:00:00Z'), now, TZ), OTHER_DAY, 'tomorrow');
  assert.equal(cloudStatus(index(NOW, 120), [], now, now, TZ), 'no fresh frame · last 6:00 pm', 'a stale list names its newest time');
  assert.equal(cloudStatus(index(NOW, 26 * 60), [], now, now, TZ), 'no fresh frame · last 2026-09-30 6:00 pm', 'with its day when that is not today');
  for (const text of [NO_FRAMES, OTHER_DAY, frameLabel('2026-10-02T02:53:00.000Z', now, TZ), cloudStatus(index(NOW, 120), [], now, now, TZ)]) assert.doesNotMatch(text, /visib|forecast|cover|%/i);
});

test('the index is FE-44\'s goes-times.json under /feeds/, admitted only in the CloudImage shape', async () => {
  const seen = [];
  const reply = (body, ok = true) => async url => { seen.push(url); return {ok, json: async () => body}; };
  assert.equal((await cloudIndex(reply(index()), PAGE)).observedAt, index().observedAt);
  assert.deepEqual(seen, [`https://s.test/${CLOUD_INDEX}`]);
  assert.equal(CLOUD_INDEX, 'feeds/conditions/goes-times.json');
  assert.equal(await cloudIndex(reply({...index(), observedAt: 'latest'}), PAGE), null);
  assert.equal(await cloudIndex(reply(index(), false), PAGE), null);
  assert.equal(await cloudIndex(async () => { throw new Error('offline'); }, PAGE), null);
});

/** A browser just big enough for navigate() (as tests/test_map_layers.mjs). */
function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}
/** A page whose visibility, and a media query whose match, the test flips. */
const watched = state => {
  const fns = new Set();
  return Object.assign(state, {addEventListener: (_t, fn) => fns.add(fn), removeEventListener: (_t, fn) => fns.delete(fn), fire() { for (const fn of [...fns]) fn(); }});
};
/** An engine that records the overlay it was given, every tile URL it would request and each frame's opacity. */
function engine() {
  const e = {calls: 0, overlay: null, before: null, tiles: [], opacity: {}};
  Object.assign(e, {
    setOverlay(layer, overlay, before) { assert.equal(layer, 'clouds'); e.calls++; e.overlay = overlay; e.before = before; for (const s of Object.values(overlay?.sources ?? {})) e.tiles.push(...s.tiles); },
    setRasterOpacity(id, value) { e.opacity[id] = value; },
    setCamera() {}, setVisible() {}, setData() {}, destroy() {},
  });
  return e;
}
const shown = e => (e.overlay?.layers ?? []).filter(l => e.opacity[l.id] === CLOUD_OPACITY).map(l => l.id.slice('clouds:'.length));

/** Clouds over a fake engine at a hand-driven clock; `answers` are the index replies, in order (the last repeats). */
async function clouds(t, {href = `${PAGE}?region=morro-bay&layers=clouds`, answers = [index()], reduced = false, reported = () => null, live = null} = {}) {
  t.mock.timers.enable({apis: ['setTimeout', 'setInterval']});
  browser(href);
  cloudHeld.value = false; unavailable.value = [];
  const clock = {now: NOW}, e = engine(), doc = watched({hidden: false}), motion = watched({matches: reduced}), fetched = [];
  const fetchFn = async url => { fetched.push(url); const body = answers[Math.min(fetched.length - 1, answers.length - 1)]; return {ok: body !== null, json: async () => body}; };
  const c = createClouds({engine: live ?? signal(e), zone: () => TZ, fetchFn, page: () => PAGE, now: () => new Date(clock.now), doc, motion, reported});
  await flush();
  const advance = async ms => { clock.now += ms; t.mock.timers.tick(ms); await flush(); };
  return {c, e, doc, motion, fetched, clock, advance};
}

test('only listed times are ever requested, across index refreshes and an ageing clock', async t => {
  const first = index(), later = index(NOW + INDEX_REFRESH_MS);
  const {c, e, fetched, advance} = await clouds(t, {answers: [first, later]});
  assert.equal(fetched.length, 1, 'the index is read when Clouds turns on');
  assert.equal(e.before, MARK_PICK, 'under the marks, the selection and the coastline glow, above the fields (§ 9)');
  assert.equal(e.overlay.layers.length, MAX_FRAMES, 'the newest frames inside the 90-minute gate');
  for (let i = 0; i < 30; i++) await advance(MIN);
  assert.equal(fetched.length, 4, 'read again every ten minutes while on');
  const listed = new Set([...first.availableTimes, ...later.availableTimes]);
  assert.ok(e.tiles.some(url => Date.parse(timeOf(url)) > Date.parse(first.observedAt)), 'the refreshed list\'s newer frames are drawn');
  for (const url of e.tiles) {
    assert.ok(listed.has(timeOf(url)), `requested an unlisted time: ${timeOf(url)}`);
    assert.doesNotMatch(url, /current|latest/);
  }
  assert.ok(e.overlay.layers.every(l => NOW + 30 * MIN - Date.parse(l.id.slice(7)) <= 90 * MIN), 'frames leave as they pass 90 minutes');
  c.destroy();
});

test('the loop steps oldest to newest, holds the newest, and stops while the page is hidden', async t => {
  const {c, e, doc, advance} = await clouds(t);
  const frames = e.overlay.layers.map(l => l.id.slice(7));
  assert.deepEqual(shown(e), [frames.at(-1)], 'it opens on the newest frame');
  assert.equal(cloudStamp.value.label, 'observed 7:53 pm · 7 min ago');
  assert.equal(cloudStamp.value.canLoop, true);
  await advance(HOLD_MS);
  assert.deepEqual(shown(e), [frames[0]], 'then from the oldest');
  await advance(FRAME_MS);
  assert.deepEqual(shown(e), [frames[1]]);
  assert.match(cloudStamp.value.label, /^observed 7:03 pm · 57 min ago$/, 'each frame carries its own time and age');
  doc.hidden = true; doc.fire();
  await advance(10 * FRAME_MS);
  assert.deepEqual(shown(e), [frames[1]], 'no step while hidden');
  doc.hidden = false; doc.fire();
  await advance(FRAME_MS);
  assert.deepEqual(shown(e), [frames[2]], 'and on again when shown');
  for (let i = 3; i < frames.length; i++) await advance(FRAME_MS);
  assert.deepEqual(shown(e), [frames.at(-1)]);
  await advance(FRAME_MS);
  assert.deepEqual(shown(e), [frames.at(-1)], 'the newest frame is held');
  await advance(HOLD_MS - FRAME_MS);
  assert.deepEqual(shown(e), [frames[0]]);
  c.destroy();
  assert.equal(cloudStamp.value, null);
});

test('the loop also stops while the viewer holds it or the Chart is not shown; reduced motion keeps the newest frame', async t => {
  let run = await clouds(t);
  const frames = run.e.overlay.layers.map(l => l.id.slice(7));
  cloudHeld.value = true;
  await run.advance(HOLD_MS + 5 * FRAME_MS);
  assert.deepEqual(shown(run.e), [frames.at(-1)], 'held');
  cloudHeld.value = false;
  setParams({presentation: '3d'});
  await run.advance(HOLD_MS + 5 * FRAME_MS);
  assert.deepEqual(shown(run.e), [frames.at(-1)], 'no loop behind the terrain');
  assert.equal(cloudStamp.value, null, 'and no label for a frame nobody sees');
  run.c.destroy();
  t.mock.timers.reset();

  run = await clouds(t, {reduced: true});
  await run.advance(HOLD_MS + 5 * FRAME_MS);
  assert.deepEqual(shown(run.e), [frames.at(-1)], 'reduced motion: the newest frame, still');
  assert.equal(cloudStamp.value.canLoop, false, 'and no loop toggle');
  run.c.destroy();
});

test('no label and no step while MapLibre is still loading or after the Chart failed', async t => {
  const live = signal(null);
  const run = await clouds(t, {live});
  await run.advance(HOLD_MS + 5 * FRAME_MS);
  assert.equal(cloudStamp.value, null, 'loading: the legend labels no frame');
  assert.equal(run.e.overlay, null, 'and nothing is drawn');
  live.value = run.e;
  await flush();
  const frames = run.e.overlay.layers.map(l => l.id.slice(7));
  assert.deepEqual(shown(run.e), [frames.at(-1)], 'the map up: it opens on the newest frame, not mid-loop');
  assert.equal(cloudStamp.value.label, 'observed 7:53 pm · 7 min ago');
  await run.advance(HOLD_MS);
  assert.deepEqual(shown(run.e), [frames[0]], 'and loops');
  live.value = null;
  await flush();
  assert.equal(cloudStamp.value, null, 'no map (chartFailed, or the Chart torn down): no label');
  const label = cloudStamp.value;
  await run.advance(HOLD_MS + 5 * FRAME_MS);
  assert.equal(cloudStamp.value, label, 'and no step');
  assert.deepEqual(shown(run.e), [frames[0]], 'the last map is not stepped either');
  run.c.destroy();
});

test('withheld on other days, off without an index, and an ocean packet with newer times wins', async t => {
  let run = await clouds(t, {href: `${PAGE}?region=morro-bay&layers=clouds&day=2026-10-02`});
  assert.equal(run.e.overlay, null, 'tomorrow shows no loop');
  assert.equal(railNotes.value.clouds, OTHER_DAY);
  setParams({day: null});
  await flush();
  assert.equal(run.e.overlay.layers.length, MAX_FRAMES, 'today does');
  setParams({hour: '2026-10-02T06:00Z'});
  assert.equal(run.e.overlay.layers.length, MAX_FRAMES, 'a later hour of today keeps the observed loop: nothing is projected forward');
  setParams({hour: '2026-10-02T08:00Z'});
  assert.equal(run.e.overlay, null, '1 am tomorrow does not');
  setParams({layers: 'none', hour: null});
  assert.equal(run.e.overlay, null);
  assert.equal(railNotes.value.clouds, '');
  run.c.destroy();
  t.mock.timers.reset();

  run = await clouds(t, {answers: [null]});
  assert.equal(run.e.overlay, null);
  assert.equal(railNotes.value.clouds, NO_FRAMES);
  run.c.destroy();
  t.mock.timers.reset();

  const packet = index(NOW, 2);
  run = await clouds(t, {reported: () => packet});
  assert.equal(shown(run.e)[0], packet.observedAt, 'the bound report\'s newer list');
  run.c.destroy();
});

/** A fake MapLibre map for the engine's overlay calls. */
function library() {
  const fake = {maps: []};
  class FakeMap {
    constructor(options) {
      this.handlers = {}; this.sources = {}; this.layers = (options.style.layers ?? []).map(l => l.id); this.paint = {}; this.log = [];
      this.keyboard = {disableRotation() {}}; this.touchZoomRotate = {disableRotation() {}};
      fake.maps.push(this);
    }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type, event = {}) { for (const fn of this.handlers[type] ?? []) fn(event); }
    addControl() {}
    getLayer(id) { return this.layers.includes(id) ? {} : undefined; }
    getSource(id) { return this.sources[id]; }
    addSource(id, spec) { this.sources[id] = spec; this.log.push(`+source ${id}`); }
    removeSource(id) { delete this.sources[id]; this.log.push(`-source ${id}`); }
    addLayer(layer, before) { const i = before ? this.layers.indexOf(before) : -1; this.layers.splice(i < 0 ? this.layers.length : i, 0, layer.id); this.log.push(`+layer ${layer.id}`); }
    removeLayer(id) { this.layers = this.layers.filter(l => l !== id); this.log.push(`-layer ${id}`); }
    setPaintProperty(id, name, value) { this.paint[id] = [name, value]; }
    remove() {}
  }
  const control = class {};
  fake.module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  return fake;
}

test('the engine adds an overlay once the style loads, keeps drawn frames, and routes their errors to the layer', t => {
  t.mock.method(console, 'error', () => {});
  const fake = library(), errors = [];
  const eng = createEngine(fake.module, {host: {}, style: {version: 8, sources: {}, layers: [{id: 'water'}, {id: COASTLINE_GLOW}, {id: 'coastline'}]},
    camera: {latitude: 35.37, longitude: -120.86, zoom: 12}, onMove() {}, onLayerError: (layer, error) => errors.push([layer, error.message])});
  const [map] = fake.maps;
  const cloud = index(), [a, b, c] = cloud.availableTimes.slice(-3), now = new Date(NOW);
  eng.setOverlay('clouds', cloudOverlay(cloud, [a, b], now), COASTLINE_GLOW);
  eng.setRasterOpacity(frameId(b), CLOUD_OPACITY);
  assert.deepEqual(map.log, [], 'nothing before the style has loaded');
  map.fire('style.load');
  assert.deepEqual(map.layers, ['water', frameId(a), frameId(b), COASTLINE_GLOW, 'coastline'], 'in order, under the coastline glow');
  assert.deepEqual(map.paint[frameId(b)], ['raster-opacity', CLOUD_OPACITY]);
  map.log = [];
  eng.setOverlay('clouds', cloudOverlay(cloud, [b, c], now), COASTLINE_GLOW);
  assert.deepEqual(map.log, [`-layer ${frameId(a)}`, `-source ${frameId(a)}`, `+source ${frameId(c)}`, `+layer ${frameId(c)}`], 'a drawn frame keeps its tiles');
  map.fire('error', {sourceId: frameId(c), error: new Error('503')});
  map.fire('error', {sourceId: frameId(a), error: new Error('gone')});
  assert.deepEqual(errors, [['clouds', '503']], 'a frame\'s tile error marks Clouds only; a removed frame owns nothing');
  eng.setOverlay('clouds', null);
  assert.deepEqual(map.layers, ['water', COASTLINE_GLOW, 'coastline']);
  assert.deepEqual(Object.keys(map.sources), []);
  // MapLibre fetches raster tiles while refreshExpiredTiles is on (its default), so server/security-headers.ts lists nowCOAST under connect-src.
  assert.equal(mapOptions({}, {version: 8, sources: {}, layers: []}, {latitude: 0, longitude: 0, zoom: 8}).refreshExpiredTiles, undefined);
});

test('the legend labels the frame on screen with a loop toggle; the rail names the newest frame', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'clouds-')), 'legend.mjs');
  await build({
    stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {Legend} from './web/app/Legend.tsx';
      export {LayerRail} from './web/app/LayerRail.tsx';
      export {cloudHeld, cloudStamp} from './web/map/clouds.ts';
      export {railNotes} from './web/map/layers.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  const m = await import(pathToFileURL(out).href);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(`${PAGE}?region=morro-bay&layers=clouds`);
  m.cloudStamp.value = {at: '2026-10-02T02:28:00.000Z', label: 'observed 7:28 pm · 32 min ago', canLoop: true};
  m.railNotes.value = {clouds: 'observed 7:53 pm · 7 min ago'};
  let legend = m.render(m.h(m.Legend));
  assert.match(legend, /Clouds<span class="app-legend-note ui-mono">observed 7:28 pm · 32 min ago<\/span>/);
  assert.match(legend, /<button aria-label="Cloud loop"[^>]*aria-pressed="true"[^>]*><svg[^>]*data-icon="pause"/);
  m.cloudHeld.value = true;
  legend = m.render(m.h(m.Legend));
  assert.match(legend, /<button aria-label="Cloud loop"[^>]*aria-pressed="false"[^>]*><svg[^>]*data-icon="play"/, 'held');
  m.cloudStamp.value = {...m.cloudStamp.value, canLoop: false};
  assert.doesNotMatch(m.render(m.h(m.Legend)), /Cloud loop/, 'one frame, or reduced motion: no toggle');
  assert.match(m.render(m.h(m.LayerRail)), /Clouds<\/span><span class="ui-rail-note ui-mono">observed 7:53 pm · 7 min ago<\/span>/);
});
