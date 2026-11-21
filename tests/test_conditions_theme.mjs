// THEME-COND: the six conditions overlays (wind, swell, Water temp, chlorophyll, Temp contrast, Temp fronts)
// follow a live theme switch in place. Each overlay carries `themePaint`, which re-runs its own pure layer
// builder with the new palette (web/map/theme-restyle.ts paintEdits); the image-source textures of swell and
// Water temp are repainted from the same field. Real token palettes (web/tokens.css), no browser, no network.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {themes} from '../scripts/check_contrast.mjs';
import {chlorophyllCells, chlorophyllOverlay} from '../web/map/chlorophyll.ts';
import {contrastOverlay} from '../web/map/contrast.ts';
import {fieldTexture} from '../web/map/field.ts';
import {parseForecast, WAVE_MODEL} from '../web/map/forecast-grid.ts';
import {frontsOverlay} from '../web/map/fronts.ts';
import {PALETTE_TOKENS, ramps, readPalette} from '../web/map/palette.ts';
import {analysisStatus, createWaterTemp, waterTempOverlay} from '../web/map/sst.ts';
import {HEIGHT_SCALE, createSwell, swellOverlay, swellPartition, swellState} from '../web/map/swell.ts';
import {windOverlay} from '../web/map/wind.ts';
import {configureStore, syncFromURL} from '../web/state.ts';
import {runThemePaintOracle, assertThemePaintOracle, fakeMap} from './theme-paint-oracle.mjs';
import {NEARSHORE_HIT, NEARSHORE_LAYER, ringHitLayer, ringLayer} from '../web/map/nearshore.ts';
import {paintEdits, restyle} from '../web/map/theme-restyle.ts';
import {createEngine} from '../web/map/engine.ts';

const css = readFileSync(new URL('../web/tokens.css', import.meta.url), 'utf8');
const colours = themes(css), controls = {'map-road-opacity': '0.65', 'map-label-opacity': '0.75'};
const paletteOf = (theme, override = {}) => readPalette(name => override[name] ?? controls[name] ?? colours[theme][name] ?? '1');
const palettes = {dark: paletteOf('dark'), light: paletteOf('light')};

const observation = {resolution: [0.01, 0.01], cells: [{lat: 35.4, lon: -120.8, value: 0.3}, {lat: 35.41, lon: -120.8, value: 4}]};
const builders = {
  wind: p => windOverlay(p),
  'swell field': p => swellOverlay(p),
  'swell field + rings': p => swellOverlay(p, {rings: true}),
  'swell rings only': p => swellOverlay(p, {field: false, rings: true}),
  'water temp': p => waterTempOverlay(p),
  chlorophyll: p => chlorophyllOverlay(observation, p, chlorophyllCells(observation)),
  'temp contrast': p => contrastOverlay(p),
  'temp fronts': p => frontsOverlay(p),
};
/** What the engine does: the overlay installed in the current theme supplies `themePaint`, bound to itself. */
const providerOf = build => { const installed = build(palettes.dark); return {themePaint: installed.themePaint.bind(installed), themePatterns: installed.themePatterns?.bind(installed)}; };

// Contract: after dark -> light -> dark, every layer an overlay builds holds exactly the paint a fresh build of
// that theme has. Bug it catches: a builder paint that `themePaint` forgets, so one overlay keeps its dark colours
// on the light water (the stale-paint failure MB-21's engine seam cannot see on its own).
for (const [name, build] of Object.entries(builders)) {
  test(`${name}: themePaint equals a fresh build in both directions (paint oracle)`, () => {
    const report = assertThemePaintOracle({build, provider: providerOf(build), palettes});
    assert.deepEqual([report.addImage, report.updateImage, report.missing], [0, 0, []], 'no image is registered by these overlays');
  });

  // Contract: the oracle is not vacuous here. Bug: an overlay whose paint never depends on the palette would pass
  // the test above without any `themePaint`; this fails then, naming the builder to drop from the list.
  test(`${name}: without themePaint the light paints go stale (the oracle would notice)`, () => {
    const stale = runThemePaintOracle({build, provider: {}, palettes});
    assert.deepEqual(stale.steps[0].mismatches, [], 'the install theme is right');
    assert.ok(stale.steps[1].mismatches.length > 0, 'light differs from dark in at least one paint');
  });
}

// Contract: the same layer and source IDs, in the same order, in both themes, so a switch is in place: the engine
// adds no layer, removes no source and keeps the § 9 draw order. Bug: a builder branching on the theme by id.
test('layer and source IDs and their order are identical in both themes', () => {
  for (const [name, build] of Object.entries(builders)) {
    const [dark, light] = [build(palettes.dark), build(palettes.light)];
    assert.deepEqual(light.layers.map(l => l.id), dark.layers.map(l => l.id), name);
    assert.deepEqual(Object.keys(light.sources), Object.keys(dark.sources), name);
    assert.deepEqual(light.layers.map(l => [l.type, l.source]), dark.layers.map(l => [l.type, l.source]), name);
  }
});

/** A browser just big enough for the layer's state (as tests/test_swell_layer.mjs). */
function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}
/** An engine that records every call, in order. */
function engine(id) {
  const e = {overlay: null, calls: [], images: []};
  return Object.assign(e, {
    setOverlay(layer, overlay) { assert.equal(layer, id); e.overlay = overlay; e.calls.push(['overlay', overlay === null ? null : overlay.layers.length]); },
    setImage(source, texture) { e.images.push([source, texture]); e.calls.push(['image', source]); },
    setData(source) { e.calls.push(['data', source]); },
    setRasterOpacity() {}, setCamera() {}, setVisible() {}, destroy() {},
  });
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const same = (a, b) => Buffer.from(a.data).equals(Buffer.from(b.data));

// Swell feed: a 3 × 3 grid 0.25° apart where Morro Bay's offshore forecast points lie, height rising east and north.
const HOUR = 3_600_000, NOW = new Date('2026-10-09T18:00:00Z'), ISSUED = Date.parse('2026-10-09T06:00:00Z'), PAGE = 'https://s.test/map', TZ = 'America/Los_Angeles';
const LATS = [35.05, 35.3, 35.55], LONS = [-121.75, -121.5, -121.25];
const times = Array.from({length: 48}, (_, k) => ISSUED / 1000 + k * 3600);
function feed() {
  const units = {time: 'unixtime', ...Object.fromEntries(['swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'wind_wave_height', 'wind_wave_period', 'wind_wave_direction',
    'secondary_swell_wave_height', 'secondary_swell_wave_period', 'secondary_swell_wave_direction'].map(v => [v, v.endsWith('_height') ? 'ft' : v.endsWith('_period') ? 's' : '°']))};
  const at = (i, j) => {
    const h = times.map((_, k) => [2 + i * 0.5 + j * 0.3 + k * 0.5, 11.2 + i * 1.2, 290 + j * 5]);
    return {utc_offset_seconds: 0, hourly_units: units, hourly: {time: times, swell_wave_height: h.map(v => v[0]), swell_wave_period: h.map(v => v[1]), swell_wave_direction: h.map(v => v[2]),
      wind_wave_height: h.map(v => v[0] / 3), wind_wave_period: h.map(v => v[1] - 5), wind_wave_direction: h.map(v => (v[2] + 90) % 360),
      secondary_swell_wave_height: h.map(v => v[0] * 2 / 3), secondary_swell_wave_period: h.map(v => v[1] + 4), secondary_swell_wave_direction: h.map(v => (v[2] + 180) % 360)}};
  };
  const points = [['north', 35.45, -121.02], ['central', 35.36, -120.94]], series = [at(0, 0), at(0, 0)];
  for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) { points.push([`offshore-${j}-${i}`, LATS[j], LONS[i]]); series.push(at(i, j)); }
  return {region_id: 'morro-bay', requested_points: points, retrieved: NOW.getTime() - HOUR,
    models: {[WAVE_MODEL.id]: {data: series, meta: {last_run_initialisation_time: ISSUED / 1000, data_end_time: times.at(-1)}}, gfs_global: {data: [], meta: {}}}};
}

// Contract: a live switch repaints the swell texture (its ramp is --swell-*, which MB-20's light theme changes)
// from the same field, with no overlay removal, no setData and no feed request; the layer paints follow too.
// Bug: the layer paints restyle but the texture keeps the dark ramp, so the light chart shows a dark swell field.
test('swell: a switch repaints the texture from the same field and the paints, with no removal, setData or request', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  browser(`${PAGE}?region=morro-bay&layers=swell&hour=2026-10-09T20:00Z`);
  swellPartition.value = 'primary';
  const e = engine('swell'), asked = [];
  const fetchFn = async url => { asked.push(url); return {ok: true, json: async () => feed()}; };
  const s = createSwell({engine: signal(e), zone: () => TZ, fetchFn, page: () => PAGE, palette: () => palettes.dark, now: () => NOW});
  t.after(() => s.destroy());
  await flush();
  const frame = swellState.value.drawn, [, first] = e.images.at(-1);
  assert.ok(frame && e.images.length === 1 && asked.length === 1, 'drawn once, one feed request');
  assert.ok(same(first, fieldTexture(frame.field, HEIGHT_SCALE, ramps(palettes.dark).swell, v => v[0])));
  const installed = e.overlay, before = e.calls.length;

  const editsFor = theme => installed.themePaint(palettes[theme]);
  const light = editsFor('light');
  assert.equal(e.images.length, 2, 'the light ramp repaints the texture once');
  assert.ok(same(e.images.at(-1)[1], fieldTexture(frame.field, HEIGHT_SCALE, ramps(palettes.light).swell, v => v[0])), 'with the light ramp');
  assert.ok(!same(e.images.at(-1)[1], first), 'and different pixels');
  assert.deepEqual(light.map(({layer, property, value}) => [layer, property, value]),
    swellOverlay(palettes.light).layers.flatMap(({id, paint}) => Object.entries(paint ?? {}).map(([property, value]) => [id, property, value])));
  assert.deepEqual(e.calls.slice(before), [['image', 'swell']], 'only the image: no overlay, no setData');
  editsFor('light');
  assert.equal(e.images.length, 2, 'the same ramp again repaints nothing');
  editsFor('dark');
  assert.equal(e.images.length, 3);
  assert.ok(same(e.images.at(-1)[1], first), 'back to the install pixels');
  assert.equal(asked.length, 1, 'no feed request on a switch');
});

// Contract: Water temp's texture follows a ramp change but is left alone while the ramp is the same. MB-20 keeps
// --sst-* identical in both themes (it must equal packages/coast temperatureColors), so a real switch repaints no
// pixels; if a theme ever changed the ramp, the texture would follow. Bug: a repaint per switch (wasted work and a
// flash), or never (a stale ramp).
test('water temp: a switch repaints the texture only when the ramp changes, never setData', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  browser(`${PAGE}?region=morro-bay&layers=water-temp`);
  const points = [];
  for (let j = 0; j < 9; j++) for (let i = 0; i < 12; i++) points.push({lon: +(-121 + i * 0.02).toFixed(6), lat: +(35.2 + j * 0.02).toFixed(6), tempF: 57.3 + i * 0.1 + j * 0.05, errorF: 0.4});
  const source = {id: 'mur-surface-temperature', label: 'NASA JPL MUR · surface temperature analysis', url: 'https://example.test/mur', kind: 'analysis', outcome: 'ok', fetchedAt: '2026-10-09T02:17:42.000Z'};
  const report = {schemaVersion: 1, countyId: 'slo', generatedAt: '2026-10-09T02:20:00.000Z', forecasts: [], observations: [], tides: [], tideEvents: [], alerts: [], catches: [], catchStatus: '',
    visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, habitatStatus: '', sources: [source],
    spatial: {surfaceTemperature: {sourceId: source.id, analysedAt: '2026-10-07T09:00:00.000Z', fetchedAt: '2026-10-09T02:17:42.000Z', nativeResolutionDeg: 0.01, sampleSpacingDeg: 0.02, points, url: source.url, kind: 'analysis'}}};
  const e = engine('water-temp');
  const data = {coastReport: signal({data: report}), coastStatus: signal({report: 'ready', ocean: 'idle', history: 'idle'}), setPlace() {}, load: async () => {}};
  const now = new Date('2026-10-09T03:00:00Z');
  const w = createWaterTemp({engine: signal(e), zone: () => TZ, place: () => ({regionId: 'morro-bay'}), data, palette: () => palettes.dark, now: () => now});
  t.after(() => w.destroy());
  const a = analysisStatus(true, 'ready', report, now, now, TZ).drawn, installed = e.overlay, before = e.calls.length;
  assert.ok(a && e.images.length === 1);

  installed.themePaint(palettes.light);
  installed.themePaint(palettes.dark);
  assert.equal(e.images.length, 1, 'the real tokens share one ramp: no repaint');

  const shifted = paletteOf('dark', {'skl-sst-fill-ramp-stops-0': '#ff00ff'});
  installed.themePaint(shifted);
  assert.equal(e.images.length, 2, 'a changed ramp repaints once');
  assert.ok(!same(e.images.at(-1)[1], e.images[0][1]));
  assert.deepEqual(e.calls.slice(before), [['image', 'water-temp']], 'only the image: no overlay, no setData');
});

// Contract: the nearshore rings are mounted inside Swell's overlay, so a live switch must restyle them through that
// same overlay's `themePaint`, in field + rings and in rings-only mode. This drives the overlay createSwell actually
// mounts (bound report, fake engine) through the engine's restyle and compares every layer with a fresh build.
// Bug: ring layers built by ringHitLayer/ringLayer but left out of the overlay's themePaint (or only handled for the
// field), so the rings keep the dark --blue on the light chart.
async function mountedSwell(t, body) {
  t.mock.timers.enable({apis: ['setTimeout']});
  browser(`${PAGE}?region=morro-bay&layers=swell&hour=2026-10-09T20:00Z`);
  swellPartition.value = 'primary';
  const first = Date.parse('2026-10-09T12:00:00Z'), iso = ms => new Date(ms).toISOString();
  const site = {id: 'SL345', name: 'Morro Rock', areaId: 'central', lat: 35.36503, lon: -120.87659, sourceId: 'cdip-mop', issuedAt: iso(NOW - 6 * HOUR), fetchedAt: iso(NOW - HOUR),
    url: 'https://example.test/cdip', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 60, waterDepthM: 15, depthDatum: 'MSL',
    directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: null,
    hours: Array.from({length: 25}, (_, i) => ({at: iso(first + i * HOUR), waveFt: 3 + i * 0.1, periodS: 13, directionDeg: 290, qualityFlag: 0, secondaryFlag: 0}))};
  const source = {id: 'cdip-mop', label: 'CDIP MOP · nearshore wave model', url: 'https://example.test/cdip', kind: 'forecast', outcome: 'ok', fetchedAt: iso(NOW - HOUR)};
  const report = {schemaVersion: 1, countyId: 'slo', generatedAt: iso(NOW - HOUR), forecasts: [], observations: [], tides: [], tideEvents: [], alerts: [], sources: [source], catches: [], catchStatus: '',
    habitatStatus: '', visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, nearshore: [site]};
  const e = engine('swell');
  const data = {coastReport: signal({data: report}), coastBinding: signal({areaId: 'central'}), setPlace() {}, load: async () => {}};
  const s = createSwell({engine: signal(e), zone: () => TZ, fetchFn: async () => ({ok: true, json: async () => body}), page: () => PAGE, palette: () => palettes.dark, now: () => NOW,
    place: () => ({regionId: 'morro-bay'}), data});
  t.after(() => s.destroy());
  await flush();
  return {e};
}
for (const [name, body, field] of [['rings only', {region_id: 'morro-bay', retrieved: NOW.getTime() - HOUR, requested_points: [['a', 35.4, -121.0], ['b', 35.3, -121.1]], models: {}}, false],
  ['field and rings', feed(), true]]) {
  test(`swell ${name}: the mounted overlay restyles the nearshore rings with the rest`, async t => {
    const {e} = await mountedSwell(t, body);
    const mounted = e.overlay, ids = mounted.layers.map(l => l.id);
    assert.ok(ids.includes(NEARSHORE_HIT) && ids.includes(NEARSHORE_LAYER), 'the rings are mounted');
    assert.equal(ids.includes('swell'), field, 'the field is mounted only with a grid');
    const map = fakeMap(mounted.layers);
    restyle(map.target, palettes.light, [mounted]);
    const fresh = swellOverlay(palettes.light, {field, rings: true}).layers;
    assert.deepEqual(fresh.map(l => l.id), ids, 'the same layers a fresh light build has');
    for (const {id, paint} of fresh) assert.deepEqual(map.paints.get(id), paint ?? {}, `${id} paints equal a fresh light build`);
    const ringEdits = mounted.themePaint(palettes.light).filter(({layer}) => layer === NEARSHORE_HIT || layer === NEARSHORE_LAYER);
    assert.deepEqual(ringEdits, paintEdits([ringHitLayer(palettes.light), ringLayer(palettes.light)]), 'exactly the ring builders\' paints');
    assert.ok(ringEdits.length >= 6, 'ring edits are present');
  });
}

// Contract: a theme that changes while the style is still loading leaves the swell texture in the FINAL theme. The
// overlay and its first (dark) texture are queued by the real engine; the switch to light comes before `style.load`;
// the engine installs the overlay (its `themePaint` repaints the texture light) and then must not flush the older
// queued dark texture over it. Bug: the flush wins, so the light chart shows a dark swell field until the next switch,
// while the closure's bookkeeping already says "light" (so nothing repaints it).
test('swell: a theme switch before the style loads leaves the light texture, not the queued dark one', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  browser(`${PAGE}?region=morro-bay&layers=swell&hour=2026-10-09T20:00Z`);
  swellPartition.value = 'primary';
  const dataset = {theme: 'dark'}, tokens = new Map(Object.entries(PALETTE_TOKENS).map(([key, token]) => [`--${token}`, key]));
  const globals = {document: {documentElement: {dataset}}, getComputedStyle: () => ({getPropertyValue: name => palettes[dataset.theme][tokens.get(name)]}),
    MutationObserver: class { observe() {} disconnect() {} }};
  const old = Object.fromEntries(Object.keys(globals).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.assign(globalThis, globals);
  t.after(() => { for (const [key, desc] of Object.entries(old)) { if (desc) Object.defineProperty(globalThis, key, desc); else delete globalThis[key]; } });
  const maps = [];
  class FakeMap {
    constructor(options) { this.handlers = {}; this.sources = {}; this.layers = options.style.layers.map(l => l.id); this.images = []; this.keyboard = this.touchZoomRotate = {disableRotation() {}}; maps.push(this); }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type) { for (const fn of this.handlers[type] ?? []) fn({}); }
    addControl() {}
    getLayer(id) { return this.layers.includes(id) ? {} : undefined; }
    getSource(id) { return this.sources[id]; }
    addSource(id, spec) { const map = this; this.sources[id] = {spec, updateImage(o) { map.images.push([id, o]); }, setData() {}}; }
    removeSource(id) { delete this.sources[id]; }
    addLayer(l) { this.layers.push(l.id); }
    removeLayer(id) { this.layers = this.layers.filter(l => l !== id); }
    setPaintProperty() {}
    hasImage() { return false; }
    addImage() {}
    updateImage() {}
    remove() {}
  }
  const control = class {}, module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  const eng = createEngine(module, {host: {}, style: {version: 8, sources: {}, layers: [{id: 'water'}]}, camera: {latitude: 35.3, longitude: -120.9, zoom: 10}, onMove() {}, onLayerError() {}});
  const [map] = maps;
  const s = createSwell({engine: signal(eng), zone: () => TZ, fetchFn: async () => ({ok: true, json: async () => feed()}), page: () => PAGE, palette: () => palettes[dataset.theme], now: () => NOW});
  t.after(() => s.destroy());
  await flush();
  const frame = swellState.value.drawn;
  assert.ok(frame && map.images.length === 0, 'the overlay and its dark texture are queued: nothing is painted before the style loads');

  dataset.theme = 'light';
  map.fire('style.load');
  const shown = map.images.at(-1)[1].image, light = fieldTexture(frame.field, HEIGHT_SCALE, ramps(palettes.light).swell, v => v[0]);
  assert.ok(same(shown, light), 'the last pixels painted are the light ramp\'s');
  assert.ok(!same(shown, fieldTexture(frame.field, HEIGHT_SCALE, ramps(palettes.dark).swell, v => v[0])), 'and not the queued dark ones');
});
