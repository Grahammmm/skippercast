// Chart presentation (FE-11, docs/plans/front-end/design.md § 3, § 3A.2, § 9):
// the layer registry, the coastline glow, MapLibre init and the Chart adapter
// over a fake MapLibre and a fake terrain, so neither a GPU nor the library is
// needed. The web/map/*.ts files run by type stripping.
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import test from 'node:test';
import {RAIL_IDS} from '../web/profile.ts';
import {COASTLINE_SOURCE, ENC_SOURCE, LAYERS, attributionFor, layerEntry, layersIn, railLayers, sourceLayer} from '../web/map/layers.ts';
import {COASTLINE_GLOW, COASTLINE_LINE, COASTLINE_PICK, coastlineLayers, coastlineMark, coastlineSource, shorelineURL} from '../web/map/coastline.ts';
import {VIEW_ZOOM, ZOOM_OFFSET, createEngine, mapOptions} from '../web/map/engine.ts';
import {BASEMAP_MANIFEST, ENC_LAYER, basemapArchive, chartFailed, chartMark, chartStyle, createChart, unavailable} from '../web/map/chart.ts';
import {readPalette} from '../web/map/palette.ts';
import {BASEMAP_ATTRIBUTION, BASEMAP_SOURCE} from '../web/map/style.ts';
import {camera, cameraParam, choosePresentation, createStage, terrainFailed, zoomForSpan} from '../web/map/stage.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const sentinel = readPalette(name => `token(${name})`);
const SENTINELS = new Set(Object.values(sentinel));

// design.md § 9, "Draw order, bottom to top", as entry ids; the ENC chart base sits with the bases.
const DESIGN_ORDER = ['basemap', 'aerial', 'chart', 'relief', 'water-temp', 'water-temp-contours', 'swell', 'mpas', 'habitat',
  'shore-runs', 'seafloor', 'charter-grounds', 'commercial-ais', 'fleet-heat', 'fleet-tracks', 'fleet-events', 'currents',
  'clouds', 'marks', 'selection', 'coastline'];

test('the registry is in § 9 draw order and every entry declares its presentations, time and basis', () => {
  assert.deepEqual(LAYERS.map(e => e.id), DESIGN_ORDER);
  const design = readFileSync(new URL('../docs/plans/front-end/design.md', import.meta.url), 'utf8');
  assert.match(design, /Draw order, bottom\s+to top: basemap, aerial, ENC chart, relief, water temperature field, contours, swell\s+field, MPAs, habitat polygons, shore runs, seafloor candidates, charter\s+grounds, commercial AIS, fleet heat, fleet tracks, fleet events, currents\s+streamlines \(canvas\), clouds \(raster, above fields so the loop reads as\s+sky\), marks, selection, coastline glow\./, 'the design states the order this test pins');
  for (const e of LAYERS) {
    assert.ok(e.presentations.length > 0 && e.presentations.every(p => p === 'chart' || p === 'terrain'), `${e.id} presentations`);
    assert.ok(e.time.length > 0 && e.time.every(t => ['static', 'hour', 'observed'].includes(t)), `${e.id} time`);
    assert.match(e.basis, /^[A-Z].+\.$/, `${e.id} basis is one sentence`);
    assert.match(e.task, /^FE-\d+$/);
  }
  assert.equal(new Set(LAYERS.map(e => e.id)).size, LAYERS.length, 'ids are unique');
  const owned = LAYERS.flatMap(e => e.sources);
  assert.equal(new Set(owned).size, owned.length, 'a source has one owner');
  for (const rail of RAIL_IDS) assert.ok(railLayers(rail).length > 0, `rail ${rail} owns layers`);
  assert.deepEqual(layerEntry('relief').presentations, ['terrain'], 'relief is the terrain\'s own');
  assert.deepEqual(layerEntry('currents').presentations, ['chart', 'terrain'], 'currents draw in both (setCurrentLayer)');
  assert.ok(!layersIn('chart').some(e => e.id === 'relief'));
  assert.throws(() => layerEntry('hotspots'), /Unknown map layer/);
});

test('a source error routes to the layer that owns it; attribution follows the drawn layers', () => {
  assert.equal(sourceLayer(BASEMAP_SOURCE), 'basemap');
  assert.equal(sourceLayer(COASTLINE_SOURCE), 'coastline');
  assert.equal(sourceLayer(ENC_SOURCE), 'chart');
  assert.equal(sourceLayer('mystery'), null);
  assert.equal(sourceLayer(undefined), null);
  assert.equal(attributionFor(['basemap', 'coastline']), `${BASEMAP_ATTRIBUTION} · NOAA NGS · CUSP shoreline`);
  assert.equal(layerEntry('basemap').attribution, '© OpenStreetMap contributors, © Protomaps');
});

test('the coastline is a glow under a crisp line, coloured from the palette, and drawn last', () => {
  const layers = coastlineLayers(sentinel);
  assert.deepEqual(layers.map(l => l.id), [COASTLINE_GLOW, COASTLINE_LINE]);
  assert.ok(layers[0].paint['line-blur'] > 0 && layers[1].paint['line-blur'] === undefined, 'blurred under crisp');
  for (const l of layers) assert.ok(SENTINELS.has(l.paint['line-color']), `${l.id} colour comes from the palette`);
  assert.equal(shorelineURL('morro-bay'), 'regions/morro-bay/shoreline.geojson');
  assert.deepEqual(coastlineSource('morro-bay', PAGE), {type: 'geojson', data: 'https://s.test/regions/morro-bay/shoreline.geojson', attribution: 'NOAA NGS · CUSP shoreline'});
  const style = chartStyle({palette: sentinel, archive: 'https://s.test/feeds/tiles/basemap/ca-coast-20261008.pmtiles', page: PAGE, region: 'morro-bay', base: 'night'});
  assert.deepEqual(style.layers.slice(-2).map(l => l.id), [COASTLINE_GLOW, COASTLINE_LINE], 'coastline glow tops the draw order');
  assert.equal(style.sources[BASEMAP_SOURCE].url, 'pmtiles://https://s.test/feeds/tiles/basemap/ca-coast-20261008.pmtiles');
  const enc = style.layers.find(l => l.id === ENC_LAYER);
  assert.equal(enc.layout.visibility, 'none', 'the ENC base is off by default');
  assert.equal(enc.minzoom, 10 - ZOOM_OFFSET, 'from ?view= zoom 10');
  assert.equal(chartStyle({palette: sentinel, archive: null, page: PAGE, region: 'morro-bay', base: 'chart'}).layers.find(l => l.id === ENC_LAYER).layout.visibility, 'visible');
  const bare = chartStyle({palette: sentinel, archive: null, page: PAGE, region: 'morro-bay', base: 'night'});
  assert.equal(bare.sources[BASEMAP_SOURCE], undefined, 'no archive, no basemap source');
  assert.ok(bare.layers.every(l => l.source !== BASEMAP_SOURCE) && bare.layers[0].type === 'background', 'water background and the coastline still draw');
});

test('a shoreline click becomes a mark with its own source date and stated accuracy', () => {
  const props = {SOURCE_ID: 'CA13JA', SRC_DATE: '20101101', HOR_ACC: '3.14', ATTRIBUTE: 'Natural.Mean High Water', DATA_SOURC: 'Lidar', source_date: '2010-11-01', source_tile: '12/666/1610'};
  assert.deepEqual(coastlineMark(props), {
    id: 'coastline:CA13JA', name: 'Shoreline', kind: 'Mean High Water · Natural', reading: 'Lidar · ±3.14 m stated',
    source: 'NOAA NGS CUSP · source date 2010-11-01', basis: 'NOAA NGS CUSP shoreline, 1994–2010 sources.',
  });
  assert.equal(coastlineMark({...props, source_date: 'unknown'}), null, 'undated segments are not selectable');
  assert.equal(coastlineMark(null), null);
  assert.equal(coastlineMark({source_date: '1994-02-28'}).reading, 'Accuracy not stated');
});

test('the basemap archive comes from FE-10\'s manifest, and only a tiles/basemap/*.pmtiles key is accepted', async () => {
  const reply = (body, ok = true) => async url => { assert.equal(url, `https://s.test/${BASEMAP_MANIFEST}`); return {ok, json: async () => body}; };
  assert.equal(await basemapArchive(reply({key: 'tiles/basemap/ca-coast-20261008.pmtiles'}), PAGE), 'https://s.test/feeds/tiles/basemap/ca-coast-20261008.pmtiles');
  for (const key of ['tiles/basemap/../secret.pmtiles', 'https://evil.test/x.pmtiles', 'tiles/seafloor/a.pmtiles', 42]) assert.equal(await basemapArchive(reply({key}), PAGE), null, String(key));
  assert.equal(await basemapArchive(reply({}, false), PAGE), null);
  assert.equal(await basemapArchive(async () => { throw new Error('offline'); }, PAGE), null);
});

/** A fake MapLibre: one Map per construction, recording options, controls, handlers and camera calls. */
function library() {
  const fake = {maps: [], workerUrls: [], protocols: [], features: []};
  class FakeMap {
    constructor(options) {
      this.options = options; this.handlers = {}; this.controls = []; this.jumps = []; this.visibility = {}; this.data = {};
      this.center = {lat: options.center[1], lng: options.center[0]}; this.zoom = options.zoom; this.removed = false;
      this.keyboard = {disableRotation: () => { this.keyboardRotation = false; }};
      this.touchZoomRotate = {disableRotation: () => { this.touchRotation = false; }};
      if (fake.throws) throw new Error('Failed to initialize WebGL');
      fake.maps.push(this);
    }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type, event = {}) { for (const fn of this.handlers[type] ?? []) fn(event); }
    addControl(control, position) { this.controls.push([control, position]); }
    getCenter() { return this.center; }
    getZoom() { return this.zoom; }
    jumpTo({center, zoom}) { this.jumps.push({center, zoom}); this.center = {lat: center[1], lng: center[0]}; this.zoom = zoom; this.fire('moveend'); }
    move(lat, lng, zoom) { this.center = {lat, lng}; this.zoom = zoom; this.fire('moveend'); }
    // With `fake.lateStyle`, the style's layers and sources exist only once a test sets `styled` (as MapLibre's before `style.load`).
    get loaded() { return this.styled ?? !fake.lateStyle; }
    getLayer(id) { return this.loaded && this.options.style.layers.some(l => l.id === id) ? {} : undefined; }
    setLayoutProperty(id, name, value) { this.visibility[id] = value; (this.layoutCalls ??= []).push([id, value]); }
    getSource(id) { return this.loaded && this.options.style.sources[id] ? {setData: data => { this.data[id] = data; (this.dataCalls ??= []).push([id, data]); }} : undefined; }
    queryRenderedFeatures(_point, {layers}) { return fake.features.filter(f => layers.includes(f.layer.id)); }
    resize() {}
    remove() { this.removed = true; }
  }
  const control = kind => class { constructor(options) { this.kind = kind; this.options = options; } };
  fake.module = {
    lib: {
      Map: FakeMap, NavigationControl: control('navigation'), ScaleControl: control('scale'), AttributionControl: control('attribution'),
      setWorkerUrl: url => fake.workerUrls.push(url), addProtocol: (name, fn) => fake.protocols.push([name, fn]),
    },
    workerUrl: '/assets/maplibre-gl-worker.0123456789.js',
    Protocol: class { constructor() { this.tile = () => {}; } },
  };
  return fake;
}

test('MapLibre init: north up, nautical scale, worker and protocol once, and errors routed to their layer', t => {
  const fake = library(), errors = [], moves = [];
  t.mock.method(console, 'error', () => {});
  const host = {};
  const options = {host, style: {version: 8, sources: {}, layers: []}, camera: {latitude: 35.37, longitude: -120.86, zoom: 12},
    onMove: c => moves.push(c), onLayerError: (layer, error) => errors.push([layer, error.message])};
  createEngine(fake.module, options);
  const second = createEngine(fake.module, options);
  assert.deepEqual(fake.workerUrls, [fake.module.workerUrl], 'the worker URL is set once');
  assert.deepEqual(fake.protocols.map(([name]) => name), ['pmtiles'], 'the pmtiles protocol is registered once');
  const [map] = fake.maps;
  assert.equal(map.options.container, host);
  assert.deepEqual(map.options.center, [-120.86, 35.37]);
  assert.equal(map.options.zoom, 11, 'MapLibre zoom is the ?view= zoom less one');
  assert.equal(map.options.minZoom, VIEW_ZOOM.min - 1);
  assert.equal(map.options.maxZoom, VIEW_ZOOM.max - 1);
  for (const key of ['dragRotate', 'pitchWithRotate', 'touchPitch', 'rollEnabled']) assert.equal(map.options[key], false, key);
  assert.equal(map.options.maxPitch, 0);
  assert.equal(map.keyboardRotation, false);
  assert.equal(map.touchRotation, false);
  assert.deepEqual(map.controls.map(([c, at]) => [c.kind, at]), [['navigation', 'bottom-right'], ['scale', 'bottom-right'], ['attribution', 'bottom-right']]);
  assert.equal(map.controls[0][0].options.showCompass, false, 'no compass: the chart never rotates');
  assert.equal(map.controls[1][0].options.unit, 'nautical');
  assert.deepEqual(mapOptions(host, options.style, options.camera).locale, {'Map.Title': 'Chart'});

  map.fire('error', {sourceId: COASTLINE_SOURCE, error: new Error('404')});
  map.fire('error', {sourceId: 'mystery', error: new Error('glyphs')});
  map.fire('error', {error: new Error('style')});
  assert.deepEqual(errors, [['coastline', '404']], 'only an owned source marks a layer');
  map.move(35.4, -120.9, 10.5);
  assert.deepEqual(moves.at(-1), {latitude: 35.4, longitude: -120.9, zoom: 11.5});
  second.destroy();
  assert.equal(fake.maps[1].removed, true);
});

test('the engine\'s style gate: calls before style.load wait, then apply once with the latest value per layer and source', () => {
  const fake = library();
  fake.lateStyle = true;
  const style = {version: 8, sources: {[COASTLINE_SOURCE]: {type: 'geojson', data: 'start'}}, layers: [{id: COASTLINE_LINE, type: 'line', source: COASTLINE_SOURCE}]};
  const engine = createEngine(fake.module, {host: {}, style, camera: {latitude: 35.37, longitude: -120.86, zoom: 12}, onMove() {}, onLayerError() {}});
  const [map] = fake.maps;
  engine.setVisible(COASTLINE_LINE, false);
  engine.setVisible(COASTLINE_LINE, true);
  engine.setData(COASTLINE_SOURCE, 'first');
  engine.setData(COASTLINE_SOURCE, 'latest');
  engine.setVisible('not-in-style', true);
  engine.setData('not-in-style', 'ignored');
  assert.deepEqual([map.layoutCalls, map.dataCalls], [undefined, undefined], 'nothing applies before the style has loaded');
  map.styled = true;
  map.fire('style.load');
  assert.deepEqual(map.layoutCalls, [[COASTLINE_LINE, 'visible']], 'once, with the latest visibility');
  assert.deepEqual(map.dataCalls, [[COASTLINE_SOURCE, 'latest']], 'once, with the latest data');
  engine.setData(COASTLINE_SOURCE, 'after');
  engine.setVisible(COASTLINE_LINE, false);
  map.fire('style.load');
  assert.deepEqual(map.dataCalls.map(([, data]) => data), ['latest', 'after'], 'after the style loads, calls apply at once and nothing replays');
  assert.deepEqual(map.layoutCalls.map(([, value]) => value), ['visible', 'none']);
});

/** A browser just big enough for navigate() (as tests/test_map_stage.mjs). */
function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
  return {params: () => new URL(location.href).searchParams};
}
const doc = () => ({hidden: false, addEventListener() {}, removeEventListener() {}});

/** A fake terrain whose renderer reports a camera through onView. */
function terrain() {
  const fake = {options: null};
  const handle = {load: async () => true, destroy() {}};
  for (const name of ['setPerspective', 'setLocation', 'setSpecies', 'setHour', 'setDepthLimit', 'setCurrentLayer', 'selectHabitat', 'setVisible']) handle[name] = () => true;
  fake.module = {styles: [], mountCoast(_host, options) { fake.options = options; return handle; }};
  return fake;
}

/** The published file under dist/ for a page-relative URL (the region packages FE-19's protected areas read), or a 404. */
function serveDist(url) {
  const file = new URL(`../dist${new URL(url).pathname}`, import.meta.url);
  return existsSync(file) ? {ok: true, json: async () => JSON.parse(readFileSync(file, 'utf8'))} : {ok: false, status: 404, json: async () => ({})};
}

function chartStage({manifest = {key: 'tiles/basemap/ca-coast-20261008.pmtiles'}} = {}) {
  const fake = library(), land = terrain();
  const host = {dataset: {}};
  const fetches = [];
  const fetchFn = async url => {
    fetches.push(url);
    if (/^https:\/\/s\.test\/(?:regions|data)\//.test(url)) return serveDist(url);
    return manifest ? {ok: true, json: async () => manifest} : {ok: false, json: async () => ({})};
  };
  terrainFailed.value = false; chartFailed.value = false; chartMark.value = null; unavailable.value = [];
  const stage = createStage({host: {shadowRoot: {replaceChildren() {}}}, load: async () => land.module, center: () => [35.37, -120.86], doc: doc(), viewDelay: 0,
    renderers: [() => createChart({host, load: async () => fake.module, fetchFn, palette: () => sentinel, page: () => PAGE, viewDelay: 0})]});
  return {fake, land, host, stage, fetches};
}

test('the Chart mounts on its first view with the basemap and coastline, and follows the shared camera both ways', async t => {
  t.mock.method(console, 'warn', () => {});
  const nav = browser(`${PAGE}?region=morro-bay&presentation=chart`);
  const {fake, host, stage, fetches} = chartStage();
  await tick(); await tick();
  assert.equal(fake.maps.length, 1, 'one map');
  const [map] = fake.maps;
  // The boat profile's default layers include Seafloor (FE-14), which checks its own publication; the
  // protected areas (FE-19) read only the region's own files.
  assert.deepEqual(fetches.filter(url => !url.startsWith('https://s.test/regions/') && !url.startsWith('https://s.test/data/')),
    [`https://s.test/${BASEMAP_MANIFEST}`, '/feeds/tiles/seafloor/manifest-morro-bay.json']);
  assert.ok(map.options.style.sources[BASEMAP_SOURCE], 'basemap source');
  assert.equal(map.controls[2][0].options.customAttribution, BASEMAP_ATTRIBUTION, 'the basemap credit always shows while it draws');
  assert.equal(map.options.style.sources[COASTLINE_SOURCE].data, 'https://s.test/regions/morro-bay/shoreline.geojson');
  assert.deepEqual(map.options.center, [-120.86, 35.37], 'the region centre');
  assert.equal(host.dataset.view, '35.37000,-120.86000,12');

  map.move(35.4, -120.9, 10);  // a pan and zoom out by the user
  await tick();
  assert.deepEqual(camera.value, {latitude: 35.4, longitude: -120.9, zoom: 11});
  assert.equal(nav.params().get('view'), '35.40000,-120.90000,11', 'a settled move writes ?view=');
  const jumps = map.jumps.length;
  setParams({view: '35.40000,-120.90000,11'});
  assert.equal(map.jumps.length, jumps, 'the chart is not sent back where it already is');
  setParams({view: '35.30000,-120.80000,13'});
  assert.deepEqual(map.jumps.at(-1), {center: [-120.8, 35.3], zoom: 12}, 'a new ?view= moves the chart');

  setParams({base: 'chart'});
  assert.equal(map.visibility[ENC_LAYER], 'visible', '?base=chart shows the ENC base');
  setParams({base: 'night'});
  assert.equal(map.visibility[ENC_LAYER], 'none');
  stage.destroy();
  assert.equal(map.removed, true, 'the stage destroys its renderers');
});

test('Chart → 3D → Chart keeps the centre within one zoom step', async t => {
  t.mock.method(console, 'warn', () => {});
  const nav = browser(`${PAGE}?region=morro-bay&presentation=chart&view=35.38000,-120.88000,12`);
  const {fake, land, stage} = chartStage();
  await tick(); await tick();
  const [map] = fake.maps;
  choosePresentation('3d');
  await tick(); await tick();
  // The renderer reports where it looks (a span in metres), slightly off the camera it was sent.
  land.options.onView({latitude: 35.381, longitude: -120.879, span: 7300 * 1.3});
  assert.ok(Math.abs(camera.value.latitude - 35.381) < 1e-9);
  choosePresentation('chart');
  await tick();
  const back = {latitude: map.center.lat, longitude: map.center.lng, zoom: map.zoom + ZOOM_OFFSET};
  assert.ok(Math.abs(back.latitude - 35.38) < 0.01 && Math.abs(back.longitude + 120.88) < 0.01, 'same centre');
  assert.ok(Math.abs(back.zoom - 12) <= 1, `within one zoom step (${back.zoom})`);
  assert.equal(back.zoom, Math.round(zoomForSpan(7300 * 1.3) * 100) / 100);
  assert.equal(nav.params().get('presentation'), 'chart');
  stage.destroy();
});

test('a failing source marks its layer unavailable and the rest of the Chart keeps drawing', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay`);
  const {fake, stage} = chartStage({manifest: null});
  await tick(); await tick();
  const [map] = fake.maps;
  assert.deepEqual(unavailable.value, ['basemap'], 'no manifest: the basemap is unavailable');
  assert.equal(map.controls[2][0].options.customAttribution, undefined, 'and is not credited');
  assert.ok(map.options.style.sources[COASTLINE_SOURCE], 'the coastline still draws');
  map.fire('error', {sourceId: COASTLINE_SOURCE, error: new Error('503')});
  map.fire('error', {sourceId: COASTLINE_SOURCE, error: new Error('503 again')});
  assert.deepEqual(unavailable.value, ['basemap', 'coastline'], 'each layer once');
  assert.equal(map.removed, false);
  assert.equal(chartFailed.value, false, 'a source error never fails the chart');
  setParams({region: 'cambria-san-simeon'});
  await tick();
  assert.deepEqual(unavailable.value, ['basemap'], 'a new region retries its coastline');
  assert.equal(map.data[COASTLINE_SOURCE], 'https://s.test/regions/cambria-san-simeon/shoreline.geojson');
  stage.destroy();
  assert.deepEqual(unavailable.value, []);
});

test('a shoreline click fills the mark card; empty water clears it; no WebGL fails only the Chart', async t => {
  t.mock.method(console, 'warn', () => {});
  t.mock.method(console, 'error', () => {});
  browser(`${PAGE}?region=morro-bay`);
  const first = chartStage();
  await tick(); await tick();
  const [map] = first.fake.maps;
  first.fake.features = [{layer: {id: COASTLINE_PICK}, properties: {SOURCE_ID: 'S1', ATTRIBUTE: 'Natural.Mean High Water', HOR_ACC: '2', source_date: '2010-11-01'}}];
  map.fire('click', {point: {x: 1, y: 1}});
  assert.equal(chartMark.value.name, 'Shoreline');
  assert.equal(chartMark.value.source, 'NOAA NGS CUSP · source date 2010-11-01');
  first.fake.features = [];
  map.fire('click', {point: {x: 2, y: 2}});
  assert.equal(chartMark.value, null);
  first.stage.destroy();

  const second = chartStage();
  second.fake.throws = true;
  await tick(); await tick();
  assert.equal(chartFailed.value, true, 'the stage shows "Map unavailable."');
  assert.equal(terrainFailed.value, false, 'the terrain is unaffected');
  second.stage.destroy();
});
