// Aerial base (FE-23, docs/plans/front-end/dev-plan.md): the USDA NAIP mosaic as an
// optional Chart base, offered only where the region's package names it
// (region.json basemap.aerial, FE-45), drawn from packages/coast's naipSource()
// and labelled with the acquisition window the package records. A fake engine and
// a fake MapLibre stand in for the map, so no GPU, library or network is needed;
// the region records are the committed ones. web/map/*.ts run by type stripping;
// the rail is bundled with esbuild and rendered.
import assert from 'node:assert/strict';
import {existsSync, readFileSync, readdirSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {signal} from '@preact/signals';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {mapSourceHosts, naipSource} from '../packages/coast/src/map-sources.ts';
import {
  AERIAL_CATALOG_ID, AERIAL_OPACITY, aerialAttribution, aerialBase, aerialId, aerialOffer, aerialOverlay, createAerial, flownText,
} from '../web/map/aerial.ts';
import {ENC_LAYER, chartStyle, unavailable} from '../web/map/chart.ts';
import {createEngine} from '../web/map/engine.ts';
import {readPalette} from '../web/map/palette.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const json = path => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const regionIds = readdirSync(new URL('../regions/', import.meta.url), {withFileTypes: true})
  .filter(entry => entry.isDirectory() && existsSync(new URL(`../regions/${entry.name}/region.json`, import.meta.url))).map(entry => entry.name);
const MORRO = aerialBase(json('dist/regions/morro-bay/region.json'));
const origin = template => new URL(template.replace('{bbox-epsg-3857}', '0,0,1,1')).origin;

test('the aerial base is read from the region package, only where it names usgs-naip with ordered dates', () => {
  const config = json('regions/morro-bay/region.json').basemap.aerial;
  assert.deepEqual(MORRO, {source: AERIAL_CATALOG_ID, first: config.acquired.first, last: config.acquired.last, checkedAt: config.checked_at, note: config.note});
  assert.deepEqual(aerialBase(json('regions/morro-bay/region.json')), MORRO, 'the published package carries the source record');
  for (const id of regionIds.filter(id => id !== 'morro-bay')) assert.equal(aerialBase(json(`regions/${id}/region.json`)), null, `${id} offers no aerial base`);
  const aerial = patch => ({basemap: {aerial: {...config, ...patch}}});
  assert.equal(aerialBase(aerial({source: 'usgs-imagery-only'})), null, 'another imagery service is never substituted');
  assert.equal(aerialBase(aerial({acquired: {first: config.acquired.last, last: config.acquired.first}})), null);
  assert.equal(aerialBase(aerial({checked_at: '2022-05-01'})), null, 'checked before it was flown');
  assert.equal(aerialBase(aerial({acquired: {first: '2022-5-13', last: config.acquired.last}})), null);
  assert.equal(aerialBase(aerial({note: undefined})), null);
  for (const value of [null, {}, {basemap: {}}, {basemap: {aerial: 'usgs-naip'}}]) assert.equal(aerialBase(value), null);
});

test('the label is the acquisition window, and the credit is naipSource()\'s own followed by it', () => {
  assert.equal(flownText(MORRO), 'flown 13–29 May 2022');
  assert.equal(flownText({first: '2022-05-30', last: '2022-06-02'}), 'flown 30 May – 2 Jun 2022');
  assert.equal(flownText({first: '2021-12-29', last: '2022-01-03'}), 'flown 29 Dec 2021 – 3 Jan 2022');
  assert.equal(flownText({first: '2022-05-13', last: '2022-05-13'}), 'flown 13 May 2022');
  assert.equal(aerialAttribution(MORRO), `${naipSource().attribution} · flown 13–29 May 2022`);
  for (const text of [flownText(MORRO), aerialAttribution(MORRO), MORRO.note]) assert.doesNotMatch(text, /\b(?:live|current|today|now|latest|real-time)\b/i, 'dated imagery, never current conditions');
});

test('the overlay is naipSource()\'s one raster source at the fixed USGS host, at 0.92 opacity and desaturated', () => {
  const {sources, layers} = aerialOverlay(MORRO), id = aerialId(MORRO);
  assert.deepEqual(Object.keys(sources), [id]);
  assert.deepEqual(sources[id], {...naipSource(), attribution: aerialAttribution(MORRO)}, 'the template, zooms and tile size are packages/coast\'s');
  assert.deepEqual(sources[id].tiles.map(origin), ['https://imagery.nationalmap.gov']);
  assert.ok(sources[id].tiles.every(t => mapSourceHosts.includes(origin(t))));
  assert.deepEqual(layers.map(l => [l.id, l.type, l.source]), [[id, 'raster', id]]);
  assert.equal(layers[0].paint['raster-opacity'], AERIAL_OPACITY);
  assert.ok(layers[0].paint['raster-saturation'] < 0);
  assert.notEqual(aerialId({...MORRO, first: '2024-06-01', last: '2024-06-09'}), id, 'another window replaces the source and its credit');
});

/** A browser just big enough for navigate() (as tests/test_map_layers.mjs). */
function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}
/** An engine that records the aerial overlay it was given and every tile template it would request. */
function engine() {
  const e = {overlay: null, before: null, tiles: [], calls: 0};
  Object.assign(e, {
    setOverlay(layer, overlay, before) { assert.equal(layer, 'aerial'); e.calls++; e.overlay = overlay; e.before = before; for (const s of Object.values(overlay?.sources ?? {})) e.tiles.push(...s.tiles); },
    setRasterOpacity() {}, setCamera() {}, setVisible() {}, setData() {}, destroy() {},
  });
  return e;
}

test('nothing is requested until Aerial is chosen, nor in a region without the flag; off removes it', () => {
  browser(`${PAGE}?region=morro-bay`);
  const e = engine(), offer = signal(MORRO), live = signal(null);
  const a = createAerial({engine: live, offer: () => offer.value});
  assert.equal(aerialOffer.value, MORRO, 'offered before MapLibre loads, so the rail can show it');
  live.value = e;
  assert.equal(e.calls, 0, 'the chart base: no source, no tiles');
  setParams({base: 'aerial'});
  assert.equal(e.overlay.layers[0].id, aerialId(MORRO));
  assert.equal(e.before, ENC_LAYER, 'above the basemap, under the ENC chart and everything over it (§ 9)');
  setParams({base: 'chart'});
  assert.equal(e.overlay, null, 'one base at a time');
  setParams({base: 'aerial'});
  offer.value = null;
  assert.equal(e.overlay, null, 'a region without basemap.aerial draws none, whatever ?base= says');
  assert.equal(aerialOffer.value, null);
  assert.ok(e.tiles.length > 0 && e.tiles.every(t => origin(t) === 'https://imagery.nationalmap.gov'), 'only the fixed USGS host');
  a.destroy();
  assert.equal(aerialOffer.value, null);

  browser(`${PAGE}?region=southern-california&base=aerial`);
  const other = engine();
  const b = createAerial({engine: signal(other), offer: () => aerialBase(json('regions/southern-california/region.json'))});
  assert.equal(other.calls, 0);
  assert.equal(aerialOffer.value, null);
  b.destroy();
});

test('a tile error marks only Aerial unavailable, and choosing it again retries', t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay&base=aerial`);
  unavailable.value = ['clouds'];
  const e = engine(), a = createAerial({engine: signal(e), offer: () => MORRO});
  unavailable.value = [...unavailable.value, 'aerial'];
  setParams({base: 'night'});
  assert.deepEqual(unavailable.value, ['clouds']);
  a.destroy();
  unavailable.value = [];
});

/** A fake MapLibre map for the engine's overlay calls (as tests/test_clouds_layer.mjs). */
function library() {
  const fake = {maps: []};
  class FakeMap {
    constructor(options) {
      this.handlers = {}; this.sources = {}; this.layers = (options.style.layers ?? []).map(l => l.id); this.paint = {};
      this.keyboard = {disableRotation() {}}; this.touchZoomRotate = {disableRotation() {}};
      fake.maps.push(this);
    }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type, event = {}) { for (const fn of this.handlers[type] ?? []) fn(event); }
    addControl() {}
    getLayer(id) { return this.layers.includes(id) ? {} : undefined; }
    getSource(id) { return this.sources[id]; }
    addSource(id, spec) { this.sources[id] = spec; }
    removeSource(id) { delete this.sources[id]; }
    addLayer(layer, before) { const i = before ? this.layers.indexOf(before) : -1; this.layers.splice(i < 0 ? this.layers.length : i, 0, layer.id); }
    removeLayer(id) { this.layers = this.layers.filter(l => l !== id); }
    remove() {}
  }
  const control = class {};
  fake.module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  return fake;
}

test('in the Chart style the base waits for style.load, then sits over the basemap and under the ENC chart', t => {
  t.mock.method(console, 'error', () => {});
  const fake = library(), errors = [];
  const style = chartStyle({palette: readPalette(name => `token(${name})`), archive: 'https://s.test/feeds/tiles/basemap/x.pmtiles', page: PAGE, region: 'morro-bay', base: 'aerial'});
  const eng = createEngine(fake.module, {host: {}, style, camera: {latitude: 35.37, longitude: -120.86, zoom: 12}, onMove() {},
    onLayerError: (layer, error) => errors.push([layer, error.message])});
  const [map] = fake.maps, id = aerialId(MORRO);
  eng.setOverlay('aerial', aerialOverlay(MORRO), ENC_LAYER);
  assert.equal(map.getSource(id), undefined, 'nothing before the style has loaded');
  map.fire('style.load');
  const at = map.layers.indexOf(id), basemap = style.layers.filter(l => l.source === 'basemap').map(l => map.layers.indexOf(l.id));
  assert.ok(basemap.length && basemap.every(i => i < at), 'over every basemap layer');
  assert.equal(map.layers[at + 1], ENC_LAYER, 'directly under the ENC chart, so under the fields, marks and coastline');
  map.fire('error', {sourceId: id, error: new Error('503')});
  assert.deepEqual(errors, [['aerial', '503']]);
  eng.setOverlay('aerial', null);
  assert.equal(map.getSource(id), undefined);
  assert.equal(map.layers.indexOf(id), -1);
});

test('the rail\'s base choice offers Aerial only where the region has it, labelled with its dates', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'aerial-')), 'rail.mjs');
  await build({
    stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {LayerRail} from './web/app/LayerRail.tsx';
      export {aerialOffer} from './web/map/aerial.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  const m = await import(pathToFileURL(out).href);
  // FE-20 replaced FE-23's Aerial toggle with the rail's one base select (Night, Chart detail, Aerial where offered).
  const choice = () => m.render(m.h(m.LayerRail)).match(/<div class="app-rail-base">.*?<\/div>$/s)[0];
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(`${PAGE}?region=southern-california&base=aerial`);
  assert.doesNotMatch(choice(), /Aerial/, 'absent without basemap.aerial');
  assert.match(choice(), /<option selected value="night">Night<\/option>/, 'an aerial base no region offers draws the basemap alone');
  m.aerialOffer.value = MORRO;
  m.state.syncFromURL(`${PAGE}?region=morro-bay`);
  let item = choice();
  assert.match(item, /<option selected value="night">Night<\/option><option value="chart">Chart detail<\/option><option value="aerial">Aerial<\/option><\/select>/);
  assert.ok(item.includes(MORRO.note), 'the basis carries the package\'s note');
  assert.match(item, /requests its tiles from USGS/);
  m.state.syncFromURL(`${PAGE}?region=morro-bay&base=aerial`);
  item = choice();
  assert.match(item, /<option selected value="aerial">Aerial<\/option>/);
  assert.match(item, /<span id="app-rail-base-note" class="ui-rail-note ui-mono">flown 13–29 May 2022<\/span>/);
  m.aerialOffer.value = null;
});
