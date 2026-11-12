// Chart presentation (FE-11, docs/plans/front-end/design.md § 3, § 3A.2, § 9):
// the layer registry, the coastline glow, MapLibre init and the Chart adapter
// over a fake MapLibre and a fake terrain, so neither a GPU nor the library is
// needed. The web/map/*.ts files run by type stripping.
import assert from 'node:assert/strict';
import util from 'node:util';
import {existsSync, readFileSync} from 'node:fs';
import test from 'node:test';
import {RAIL_IDS} from '../web/profile.ts';
import {COASTLINE_SOURCE, ENC_SOURCE, LAYERS, attributionFor, drapeStyle, drawsIn, layerEntry, layersIn, railLayers, setTerrainLayer, sourceLayer, terrainLayers} from '../web/map/layers.ts';
import {COAST_OVERLAY_COLORS} from '../packages/coast/src/palette.ts';
import {groundsOverlay} from '../web/map/charter-grounds.ts';
import {markData, markScreen, markStyle} from '../web/map/marks.ts';
import {assessScreen, CHECKING} from '../web/map/habitat.ts';
import {beginWaypointPlacement, cancelWaypointPlacement, placementRefused, waypointPlacement} from '../web/waypoint-placement.ts';
import {COASTLINE_GLOW, COASTLINE_LINE, COASTLINE_PICK, coastlineLayers, coastlineMark, coastlineSource, shorelineURL, SHORELINE_DETAIL_ZOOM} from '../web/map/coastline.ts';
import {VIEW_ZOOM, ZOOM_OFFSET, collapseAttribution, createEngine, mapOptions} from '../web/map/engine.ts';
import {BASEMAP_MANIFEST, ENC_LAYER, basemapArchive, chartFailed, chartMark, chartStyle, createChart, unavailable} from '../web/map/chart.ts';
import {readPalette} from '../web/map/palette.ts';
import {mpaLayers, mpaMark, mpaQuery} from '../web/map/mpa.ts';
import {BASEMAP_ATTRIBUTION, BASEMAP_SOURCE} from '../web/map/style.ts';
import {camera, cameraParam, choosePresentation, createStage, drape, terrainCoarsened, terrainFailed, terrainPick, zoomForSpan} from '../web/map/stage.ts';
import {appView, configureStore, region, setParams, syncFromURL} from '../web/state.ts';
import {effect} from '@preact/signals';
import {publishedChartFiles} from '../web/chart-files.ts';
import {settlePicks} from './helpers/pick-settle.mjs';

const PAGE = 'https://s.test/map';
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const sentinel = readPalette(name => /^map-.*-(?:opacity|width)$/.test(name) ? '1' : `token(${name})`);
const SENTINELS = new Set(Object.values(sentinel));

// design.md § 9, "Draw order, bottom to top", as entry ids; the ENC chart base sits with the bases.
const DESIGN_ORDER = ['basemap', 'aerial', 'chart', 'relief', 'water-temp', 'water-temp-contours', 'sst-contrast', 'sst-fronts', 'chlorophyll', 'swell', 'wind', 'depth-contours', 'mpas', 'habitat',
  'shore-runs', 'seafloor', 'charter-grounds', 'commercial-ais', 'fleet-heat', 'fleet-tracks', 'fleet-events', 'currents',
  'clouds', 'reach', 'marks', 'selection', 'trip-ranked', 'saved-spots', 'stations', 'coastline'];

test('the registry is in § 9 draw order and every entry declares its presentations, time and basis', () => {
  assert.deepEqual(LAYERS.map(e => e.id), DESIGN_ORDER);
  const design = readFileSync(new URL('../docs/plans/front-end/design.md', import.meta.url), 'utf8');
  assert.match(design, /Draw order, bottom\s+to top: basemap, aerial, ENC chart, relief, water temperature field, contours,\s+temperature contrast cells, chlorophyll, swell field, wind arrows, depth contours, MPAs, habitat polygons,\s+shore runs,\s+seafloor candidates, charter\s+grounds, commercial AIS, fleet heat, fleet tracks, fleet events, currents\s+streamlines \(canvas\), clouds \(raster, above fields so the loop reads as\s+sky\), reach ring, marks, selection, ranked trip spots, private saved spots, station pins, coastline glow\./, 'the design states the order this test pins');
  for (const e of LAYERS) {
    assert.ok(e.presentations.length > 0 && e.presentations.every(p => p === 'chart' || p === 'terrain'), `${e.id} presentations`);
    assert.ok(e.time.length > 0 && e.time.every(t => ['static', 'hour', 'observed'].includes(t)), `${e.id} time`);
    assert.match(e.basis, /^[A-Z].+\.$/, `${e.id} basis is one sentence`);
    assert.match(e.task, /^(FE|CI\d+|SC\d+)-\d+$/, `${e.id} names its dev-plan or roadmap task`);
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
  const {copy, ...mark} = coastlineMark(props);
  assert.ok(copy, 'the display wording rides beside the unchanged English fields (SC1352-08)');
  assert.deepEqual(mark, {
    id: 'coastline:CA13JA', name: 'Shoreline', kind: 'Mean High Water · Natural', reading: 'Lidar · ±3.14 m stated',
    source: 'NOAA NGS CUSP · source date 2010-11-01', basis: 'NOAA NGS CUSP shoreline, 1994–2010 sources.',
  });
  assert.equal(coastlineMark({...props, source_date: 'unknown'}), null, 'undated segments are not selectable');
  assert.equal(coastlineMark(null), null);
  assert.equal(coastlineMark({source_date: '1994-02-28'}).reading, 'Accuracy not stated');
});

test('every import line reads the same mark from the published shoreline (schema_version 2)', () => {
  // The platform build merges import features with identical properties into one MultiLineString
  // and rounds coordinates to 5 decimals; a click on any line must still give its old mark card.
  const source = JSON.parse(readFileSync(new URL('../catalog/shoreline/morro-bay.geojson', import.meta.url), 'utf8'));
  const published = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/shoreline.geojson', import.meta.url), 'utf8'));
  assert.equal(published.type, 'FeatureCollection');
  assert.equal(published.schema_version, 2);
  const key = p => JSON.stringify(Object.keys(p).sort().map(k => [k, p[k]]));
  const lines = g => g.type === 'LineString' ? [g.coordinates] : g.coordinates;
  const byProps = new Map(published.features.map(f => [key(f.properties), f]));
  assert.equal(byProps.size, published.features.length, 'one published feature per property set');
  let matched = 0;
  for (const feature of source.features) {
    const merged = byProps.get(key(feature.properties));
    assert.ok(merged, `${feature.id} has a published feature`);
    assert.deepEqual(merged.properties, feature.properties);
    assert.deepEqual(coastlineMark(merged.properties), coastlineMark(feature.properties));
    assert.ok(coastlineMark(merged.properties), `${feature.id} stays selectable`);
    for (const line of lines(feature.geometry)) {
      const same = lines(merged.geometry).some(c => c.length === line.length && c.every(([x, y], i) => Math.abs(x - line[i][0]) <= 6e-6 && Math.abs(y - line[i][1]) <= 6e-6));
      assert.ok(same, `${feature.id}: its line is in ${merged.id}`);
      matched++;
    }
  }
  assert.equal(published.features.reduce((n, f) => n + lines(f.geometry).length, 0), matched, 'no line added or lost');
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
      this.options = options; this.handlers = {}; this.controls = []; this.jumps = []; this.visibility = {}; this.data = {}; this.sources = {};
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
    getSource(id) { return this.loaded && this.options.style.sources[id] ? this.sources[id] ??= {setData: data => { this.data[id] = data; (this.dataCalls ??= []).push([id, data]); }} : undefined; }
    queryRenderedFeatures(point, options) { const {layers} = options ?? point; return fake.features.filter(f => layers.includes(f.layer.id)); }
    resize() {}
    remove() { this.removed = true; }
    // The flyover (#646): eases are recorded; the pitch and bearing stay as the last ease or jump left them.
    off(type, fn) { this.handlers[type] = (this.handlers[type] ?? []).filter(f => f !== fn); }
    easeTo(o) { (this.eases ??= []).push(o); this.easing = true; }
    // As MapLibre's: stopping a running ease fires moveend where the camera is.
    stop() { if (this.easing) { this.easing = false; this.fire('moveend'); } }
    getPitch() { return 0; }
    getBearing() { return 0; }
    setMaxPitch(p) { this.maxPitch = p; }
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

test('the MapLibre fake filters layers for both point and options-only rendered queries', () => {
  const fake = library();
  const map = new fake.module.lib.Map({center: [0, 0], zoom: 1});
  const selected = {layer: {id: 'selected'}}, unrelated = {layer: {id: 'unrelated'}};
  fake.features = [selected, unrelated];
  assert.deepEqual(map.queryRenderedFeatures({layers: ['selected']}), [selected]);
  assert.deepEqual(map.queryRenderedFeatures([10, 20], {layers: ['selected']}), [selected]);
  assert.deepEqual(map.queryRenderedFeatures({layers: []}), []);
  assert.deepEqual(map.queryRenderedFeatures([10, 20], {layers: []}), []);
});

test('MapLibre init: north up, nautical scale, worker and protocol once, and errors routed to their layer', t => {
  const fake = library(), errors = [], moves = [];
  t.mock.method(console, 'error', () => {});
  const host = {};
  const options = {host, style: {version: 8, sources: {}, layers: []}, camera: {latitude: 35.37, longitude: -120.86, zoom: 12},
    onMove: c => moves.push(c), onLayerError: (layer, error) => errors.push([layer, error.message])};
  createEngine(fake.module, options);
  const second = createEngine(fake.module, options);
  assert.deepEqual(fake.workerUrls, [fake.module.workerUrl], 'the worker URL is set once');
  assert.deepEqual(fake.protocols.map(([name]) => name), ['pmtiles', 'nowcoast-frame'], 'the pmtiles and Clouds frame protocols are registered once each');
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

test('a still engine (the landing\'s night map, FE-25) takes no input, fades no label and adds no control', () => {
  const fake = library(), style = {version: 8, sources: {}, layers: []}, camera = {latitude: 35.4, longitude: -121.2, zoom: 10.2};
  createEngine(fake.module, {host: {}, style, camera, onMove() {}, onLayerError() {}, still: true});
  const [map] = fake.maps;
  assert.equal(map.options.interactive, false);
  assert.equal(map.options.fadeDuration, 0);
  assert.deepEqual(map.controls, [], 'the page credits the basemap itself');
  assert.equal(map.handlers.resize ?? map.handlers.styledata, undefined, 'and folds no attribution');
  assert.equal(mapOptions({}, style, camera).interactive, undefined, 'the Chart keeps its gestures');
});

/** A fake attribution <details>: its classes and whether it is `open`. */
function attribElement(...classes) {
  const names = new Set(classes), attributes = new Set(['open']);
  return {names, attributes, classList: {contains: n => names.has(n), remove: n => names.delete(n)}, removeAttribute: n => attributes.delete(n)};
}
const state = el => [[...el.names].sort().join(' '), el.attributes.has('open')];

test('BL-SC-1: collapseAttribution folds an opened compact control and leaves a folded or desktop one alone', () => {
  const opened = attribElement('maplibregl-ctrl-attrib', 'maplibregl-compact', 'maplibregl-compact-show');
  collapseAttribution(opened);
  assert.deepEqual(state(opened), ['maplibregl-compact maplibregl-ctrl-attrib', false]);
  collapseAttribution(opened);
  assert.deepEqual(state(opened), ['maplibregl-compact maplibregl-ctrl-attrib', false], 'a second fold changes nothing');
  const minimized = attribElement('maplibregl-ctrl-attrib', 'maplibregl-compact'), desktop = attribElement('maplibregl-ctrl-attrib');
  for (const el of [minimized, desktop]) { const before = state(el); collapseAttribution(el); assert.deepEqual(state(el), before); }
});

test('BL-SC-1: the Chart\'s attribution uses MapLibre\'s width rule and folds each time it turns compact, not while it stays so', () => {
  const fake = library(), style = {version: 8, sources: {}, layers: []}, camera = {latitude: 35.37, longitude: -120.86, zoom: 12};
  createEngine(fake.module, {host: {}, style, camera, onMove() {}, onLayerError() {}});
  createEngine(fake.module, {host: {}, style, camera, onMove() {}, onLayerError() {}, attribution: '© OSM'});
  assert.deepEqual(fake.maps.map(m => m.controls[2][0].options), [{}, {customAttribution: '© OSM'}], 'no compact: false; the credit text is unchanged');
  const [map] = fake.maps, el = map.controls[2][0]._container = attribElement('maplibregl-ctrl-attrib', 'maplibregl-compact', 'maplibregl-compact-show');
  map.fire('styledata');
  assert.deepEqual(state(el), ['maplibregl-compact maplibregl-ctrl-attrib', false], 'opened on load at phone width → folded');
  el.names.add('maplibregl-compact-show'); el.attributes.add('open'); // one tap opens it
  map.fire('resize'); map.fire('sourcedata');
  assert.equal(el.names.has('maplibregl-compact-show'), true, 'a resize while compact keeps the reader\'s open panel');
  el.names.delete('maplibregl-compact'); el.names.delete('maplibregl-compact-show'); // MapLibre: wider than 640 px
  map.fire('resize');
  assert.deepEqual(state(el), ['maplibregl-ctrl-attrib', true], 'the desktop width stays expanded');
  el.names.add('maplibregl-compact').add('maplibregl-compact-show'); // MapLibre reopens it on narrowing
  map.fire('resize');
  assert.deepEqual(state(el), ['maplibregl-compact maplibregl-ctrl-attrib', false], 'narrow → wide → narrow ends folded');
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

/** A fake terrain whose renderer reports a camera through onView and keeps the overlays it is given. */
function terrain() {
  // `coarse` names the ids the renderer drapes coarser, `refuse` the ids it throws on; `silent` makes every answer null (a destroyed handle).
  const fake = {options: null, overlays: new Map(), sets: 0, coarse: new Set(), refuse: new Set(), silent: false, ready: true, destroys: 0};
  const handle = {load: async () => fake.ready, destroy() { fake.destroys++; },
    setOverlay(id, overlay) {
      if (fake.refuse.has(id)) throw new Error('refused');
      fake.sets++; fake.overlays.set(id, overlay);
      return fake.silent ? null : {cell: 1, step: fake.coarse.has(id) ? 3 : 1, coarsened: fake.coarse.has(id)};
    }, removeOverlay: id => fake.overlays.delete(id)};
  for (const name of ['setPerspective', 'setLocation', 'setSpecies', 'setHour', 'setDepthLimit', 'setCurrentLayer', 'selectHabitat', 'setVisible']) handle[name] = () => true;
  fake.module = {styles: [], mountCoast(_host, options) { fake.options = options; return handle; }};
  return fake;
}

/** The published file under dist/ for a page-relative URL (the region packages FE-19's protected areas read), or a 404. */
function serveDist(url) {
  const file = new URL(`../dist${new URL(url).pathname}`, import.meta.url);
  return existsSync(file) ? {ok: true, json: async () => JSON.parse(readFileSync(file, 'utf8'))} : {ok: false, status: 404, json: async () => ({})};
}

function chartStage({manifest = {key: 'tiles/basemap/ca-coast-20261008.pmtiles'}, overlayPalette, flyoverGate} = {}) {
  const fake = library(), land = terrain();
  const host = {dataset: {}};
  const fetches = [];
  const fetchFn = async url => {
    fetches.push(url);
    if (/^https:\/\/s\.test\/(?:regions|data)\//.test(url)) return serveDist(url);
    return manifest ? {ok: true, json: async () => manifest} : {ok: false, json: async () => ({})};
  };
  terrainFailed.value = false; chartFailed.value = false; chartMark.value = null; unavailable.value = [];
  const stage = createStage({host: {dataset: {}, shadowRoot: {replaceChildren() {}}}, load: async () => land.module, center: () => [35.37, -120.86], doc: doc(), viewDelay: 0,
    overlayPalette, renderers: [() => createChart({host, load: async () => fake.module, fetchFn, palette: () => sentinel, page: () => PAGE, viewDelay: 0, flyoverGate})]});
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
  // protected areas (FE-19) read only the region's own files. The reef marks' run-time screen (#489) asks
  // v1's live ds582 query, then the daily feed's boundary record (the Worker's part, else the whole feed).
  assert.deepEqual(fetches.filter(url => !url.startsWith('https://s.test/regions/') && !url.startsWith('https://s.test/data/')).sort(), [
    `https://s.test/${BASEMAP_MANIFEST}`, '/feeds/tiles/seafloor/manifest-morro-bay.json', mpaQuery([-121.9, 34.95, -120.55, 35.85]),
    'https://s.test/api/daily?region=morro-bay&part=mpa-boundaries', 'https://s.test/feeds/data/regions/morro-bay/latest.json',
  ].sort());
  assert.ok(map.options.style.sources[BASEMAP_SOURCE], 'basemap source');
  assert.equal(map.controls[2][0].options.customAttribution, BASEMAP_ATTRIBUTION, 'the basemap credit always shows while it draws');
  // #617: the first view (?view= zoom 12, MapLibre 11) draws the overview shoreline.
  assert.equal(map.options.style.sources[COASTLINE_SOURCE].data, 'https://s.test/regions/morro-bay/shoreline-overview.geojson');
  // The startup budget: the style's own source loads the shoreline once (it is not set again for the
  // region the Chart opened on), and the marks and protected areas share each region file.
  assert.deepEqual((map.dataCalls ?? []).filter(([id]) => id === COASTLINE_SOURCE), [], 'the shoreline is not requested twice');
  const statics = fetches.filter(url => url.startsWith('https://s.test/regions/') || url.startsWith('https://s.test/data/'));
  assert.deepEqual(statics, [...new Set(statics)], 'each committed region file is requested once');
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
  // At the detail zoom (MapLibre 12) the full shoreline replaces the overview, and stays on zooming back out.
  const shore = () => (map.dataCalls ?? []).filter(([id]) => id === COASTLINE_SOURCE).map(([, data]) => data);
  assert.deepEqual(shore(), ['https://s.test/regions/morro-bay/shoreline.geojson']);
  setParams({view: '35.30000,-120.80000,11'});
  assert.deepEqual(shore(), ['https://s.test/regions/morro-bay/shoreline.geojson'], 'no second request on zooming out');

  setParams({base: 'chart'});
  assert.equal(map.visibility[ENC_LAYER], 'visible', '?base=chart shows the ENC base');
  setParams({base: 'night'});
  assert.equal(map.visibility[ENC_LAYER], 'none');
  stage.destroy();
  assert.equal(map.removed, true, 'the stage destroys its renderers');
});

test('the first idle of a home-framed Chart flies once (#646); a linked view or a closed gate never does', async t => {
  t.mock.method(console, 'warn', () => {});
  const open = linked => ({reduced: false, saveData: false, hidden: false, linked, seen: false});
  const nav = browser(`${PAGE}?region=morro-bay&presentation=chart`);
  let run = chartStage({flyoverGate: open});
  await tick(); await tick();
  let [map] = run.fake.maps;
  map.fire('idle'); map.fire('idle');
  assert.equal(run.host.dataset.flyover, 'flying');
  assert.equal(map.eases.length, 1, 'one flight, on the first idle only');
  assert.equal(map.maxPitch, 50);
  camera.value = {latitude: 35.2, longitude: -120.7, zoom: 11};  // a camera move from outside the map (a region change, Back)
  await tick();
  assert.equal(run.host.dataset.flyover, 'stopped', 'a new camera stops it');
  assert.equal(nav.params().get('view'), null, 'stopping writes no ?view=');
  assert.deepEqual(camera.value, {latitude: 35.2, longitude: -120.7, zoom: 11}, 'the new camera stands');
  assert.equal(map.maxPitch, 0);
  run.stage.destroy();

  browser(`${PAGE}?region=morro-bay&presentation=chart`);
  run = chartStage({flyoverGate: open});
  await tick(); await tick();
  [map] = run.fake.maps;
  map.fire('idle');
  assert.equal(run.host.dataset.flyover, 'flying');
  setParams({presentation: '3d'});
  assert.equal(run.host.dataset.flyover, 'stopped', 'another presentation stops it');
  assert.equal(map.maxPitch, 0);
  run.stage.destroy();

  browser(`${PAGE}?region=morro-bay&presentation=chart&view=35.38000,-120.88000,12`);
  run = chartStage({flyoverGate: open});
  await tick(); await tick();
  [map] = run.fake.maps;
  map.fire('idle');
  assert.equal(run.host.dataset.flyover, undefined, 'a link that names a view is not toured');
  assert.equal(map.eases, undefined);
  run.stage.destroy();

  browser(`${PAGE}?region=morro-bay&presentation=chart`);
  run = chartStage({flyoverGate: () => ({...open(false), reduced: true})});
  await tick(); await tick();
  [map] = run.fake.maps;
  map.fire('idle');
  assert.equal(map.eases, undefined, 'reduced motion never moves the camera');
  run.stage.destroy();

  browser(`${PAGE}?region=morro-bay&presentation=chart`);
  run = chartStage();
  await tick(); await tick();
  [map] = run.fake.maps;
  map.fire('idle');
  assert.equal(map.eases, undefined, 'outside a browser the default gate never flies');
  run.stage.destroy();
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
  assert.equal(map.data[COASTLINE_SOURCE], 'https://s.test/regions/cambria-san-simeon/shoreline-overview.geojson');
  stage.destroy();
  assert.deepEqual(unavailable.value, []);
});

test('RF2205-9: an overview-only region never sends the full shoreline URL, at any zoom or after an overview error', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay&presentation=chart&view=35.38000,-120.88000,14`);
  publishedChartFiles.value = {region: 'morro-bay', files: ['shoreline-overview.geojson']};
  t.after(() => { publishedChartFiles.value = null; });
  const {fake, stage} = chartStage();
  await tick(); await tick();
  const [map] = fake.maps;
  const OVERVIEW = 'https://s.test/regions/morro-bay/shoreline-overview.geojson';
  const shore = () => (map.dataCalls ?? []).filter(([id]) => id === COASTLINE_SOURCE).map(([, data]) => data);
  assert.equal(map.options.style.sources[COASTLINE_SOURCE].data, OVERVIEW, 'opened at a detail zoom: still the overview');
  for (const zoom of [8, 16, 20]) { map.jumpTo({center: [-120.88, 35.38], zoom}); map.fire('moveend'); await tick(); }
  map.fire('error', {sourceId: COASTLINE_SOURCE, error: new Error('503')});
  map.fire('error', {sourceId: COASTLINE_SOURCE, error: new Error('503 again')});
  map.jumpTo({center: [-120.88, 35.38], zoom: 18}); map.fire('moveend'); await tick();
  assert.equal(shore().some(data => typeof data === 'string' && data.endsWith('/shoreline.geojson')), false, 'the full URL is never sent');
  assert.deepEqual(unavailable.value.filter(layer => layer === 'coastline'), ['coastline'], 'Coastline unavailable exactly once');
  assert.equal(chartFailed.value, false);
  assert.equal(map.removed, false);
  stage.destroy();
});

test('RF2205-9: both files listed still falls back to the full shoreline once, then marks only Coastline unavailable', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay&presentation=chart`);
  publishedChartFiles.value = {region: 'morro-bay', files: ['shoreline-overview.geojson', 'shoreline.geojson']};
  t.after(() => { publishedChartFiles.value = null; });
  const {fake, stage} = chartStage();
  await tick(); await tick();
  const [map] = fake.maps;
  const shore = () => (map.dataCalls ?? []).filter(([id]) => id === COASTLINE_SOURCE).map(([, data]) => data);
  map.fire('error', {sourceId: COASTLINE_SOURCE, error: new Error('overview 503')});
  assert.deepEqual(shore(), ['https://s.test/regions/morro-bay/shoreline.geojson'], 'one fallback to the full file');
  assert.deepEqual(unavailable.value.filter(layer => layer === 'coastline'), []);
  map.fire('error', {sourceId: COASTLINE_SOURCE, error: new Error('full 503')});
  assert.deepEqual(unavailable.value.filter(layer => layer === 'coastline'), ['coastline']);
  stage.destroy();
});

test('RF0850-2: the Chart asks for no shoreline while region.json loads, and none once the loaded list lacks it (mount and region change)', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay&presentation=chart`);
  // As App.tsx's module effect, which exists before any Chart: a region change marks its list pending first.
  const app = effect(() => { const id = region.value; publishedChartFiles.value = id ? {region: id, files: null, pending: true} : null; });
  t.after(() => { app(); publishedChartFiles.value = null; });
  const {fake, stage} = chartStage();
  await tick(); await tick();
  const [map] = fake.maps;
  const shore = () => (map.dataCalls ?? []).filter(([id]) => id === COASTLINE_SOURCE).map(([, data]) => data);
  const EMPTY = {type: 'FeatureCollection', features: []};
  assert.deepEqual(map.options.style.sources[COASTLINE_SOURCE].data, EMPTY, 'mounted while pending: the style asks for no shoreline');
  assert.deepEqual(shore(), []);
  assert.equal(unavailable.value.includes('coastline'), false, 'not judged before the list is known');
  publishedChartFiles.value = {region: 'morro-bay', files: ['shoreline.geojson', 'shoreline-overview.geojson']};
  await tick();
  assert.deepEqual(shore(), ['https://s.test/regions/morro-bay/shoreline-overview.geojson'], 'listed: asked once the list is known');

  setParams({region: 'cambria-san-simeon'});
  await tick();
  assert.deepEqual(shore(), ['https://s.test/regions/morro-bay/shoreline-overview.geojson'], 'pending for the new region: nothing asked');
  assert.equal(unavailable.value.includes('coastline'), false);
  publishedChartFiles.value = {region: 'cambria-san-simeon', files: []};
  await tick();
  assert.deepEqual(shore(), ['https://s.test/regions/morro-bay/shoreline-overview.geojson', EMPTY], 'no shoreline URL: the old one is cleared');
  assert.deepEqual(unavailable.value.filter(layer => layer === 'coastline'), ['coastline'], 'marked unavailable');
  publishedChartFiles.value = {region: 'cambria-san-simeon', files: []};  // republished, as by a retry
  await tick();
  assert.deepEqual(unavailable.value.filter(layer => layer === 'coastline'), ['coastline'], 'once');
  assert.equal(shore().filter(data => typeof data === 'string' && data.includes('cambria')).length, 0, 'Cambria\'s shoreline is never requested');
  stage.destroy();
});

test('ENC recovers only from a loaded tile of the current source and region generation', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay&base=chart`);
  const {fake, stage} = chartStage({manifest: null});
  t.after(() => stage.destroy());
  await tick(); await tick();
  const [map] = fake.maps;
  const fail = () => map.fire('error', {sourceId: ENC_SOURCE, error: new Error('ENC 503')});
  const begin = (sourceId = ENC_SOURCE) => {
    const tile = {state: 'loading'};
    map.fire('sourcedataloading', {sourceId, tile});
    return tile;
  };
  const complete = (tile, sourceId = ENC_SOURCE) => {
    tile.state = 'loaded';
    map.fire('sourcedata', {sourceId, tile});
  };
  fail();
  assert.deepEqual(unavailable.value, ['basemap', 'chart']);
  map.fire('idle');
  map.fire('sourcedata', {sourceId: ENC_SOURCE, sourceDataType: 'metadata', isSourceLoaded: true});
  complete({state: 'loading'});
  const errored = begin(); errored.state = 'errored';
  map.fire('sourcedata', {sourceId: ENC_SOURCE, tile: errored});
  complete(begin(COASTLINE_SOURCE), COASTLINE_SOURCE);
  assert.deepEqual(unavailable.value, ['basemap', 'chart'], 'idle, metadata, untracked, failed and unrelated tiles cannot recover ENC');

  const replaced = begin();
  map.sources[ENC_SOURCE] = {};
  complete(replaced);
  assert.deepEqual(unavailable.value, ['basemap', 'chart'], 'a replaced source cannot recover from its old tile');
  const wrongSource = begin();
  complete(wrongSource, COASTLINE_SOURCE);
  assert.deepEqual(unavailable.value, ['basemap', 'chart'], 'the completion must name the request source');

  const stale = begin();
  setParams({region: 'cambria-san-simeon'});
  await tick();
  fail();
  complete(stale);
  assert.ok(unavailable.value.includes('chart'), 'old-region success cannot clear the current failure');
  const away = begin();
  setParams({region: 'morro-bay'});
  await tick();
  complete(away);
  complete(stale);
  assert.ok(unavailable.value.includes('chart'), 'switching back does not revive old requests');

  complete(begin());
  assert.deepEqual(unavailable.value, ['basemap'], 'verified ENC recovery preserves an unrelated failure');
  fail();
  assert.deepEqual(unavailable.value, ['basemap', 'chart'], 'a later failure is still reported');
});

test('a shoreline click fills the mark card; empty water clears it; no WebGL fails only the Chart', async t => {
  t.mock.method(console, 'warn', () => {});
  t.mock.method(console, 'error', () => {});
  browser(`${PAGE}?region=morro-bay`);
  const first = chartStage();
  await tick(); await tick();
  const [map] = first.fake.maps;
  first.fake.features = [{layer: {id: COASTLINE_PICK}, properties: {SOURCE_ID: 'S1', ATTRIBUTE: 'Natural.Mean High Water', HOR_ACC: '2', source_date: '2010-11-01'}}];
  map.fire('click', {point: {x: 1, y: 1}}); settlePicks();
  assert.equal(chartMark.value.name, 'Shoreline');
  assert.equal(chartMark.value.source, 'NOAA NGS CUSP · source date 2010-11-01');
  first.fake.features = [];
  map.fire('click', {point: {x: 2, y: 2}}); settlePicks();
  assert.equal(chartMark.value, null);
  first.stage.destroy();

  const second = chartStage();
  second.fake.throws = true;
  await tick(); await tick();
  assert.equal(chartFailed.value, true, 'the stage shows "Map unavailable."');
  assert.equal(terrainFailed.value, false, 'the terrain is unaffected');
  second.stage.destroy();
});

test('SC1952-06: an armed Chart tap is screened by the current region\'s marks screen at the click; a refused tap is consumed, never selects a mark, and the placement stays armed', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay`);
  const {fake, stage} = chartStage();
  await tick(); await tick(); await tick();
  const [map] = fake.maps;
  const NAME = '<img src=x onerror=alert(1)> Reserve';
  const BOX = {type: 'Polygon', coordinates: [[[-121.01, 34.99], [-120.99, 34.99], [-120.99, 35.01], [-121.01, 35.01], [-121.01, 34.99]]]};
  const ready = () => assessScreen({areas: [{type: 'Feature', properties: {NAME, Type: 'SMR'}, geometry: BOX}], checkedAt: new Date().toISOString(), live: true}, Date.now());
  const data = id => ({region: {id}, atlas: null, survey: null, geology: null});
  const tap = (lat, lon) => { map.fire('click', {point: {x: 1, y: 1}, lngLat: {lng: lon, lat}}); settlePicks(); };
  // A shoreline feature sits under every tap: a tap that is not consumed would select it.
  fake.features = [{layer: {id: COASTLINE_PICK}, properties: {SOURCE_ID: 'S1', ATTRIBUTE: 'Natural.Mean High Water', HOR_ACC: '2', source_date: '2010-11-01'}}];
  const got = [];
  try {
    chartMark.value = null;
    beginWaypointPlacement('morro-bay', at => got.push(at));
    // Marks not loaded / still checking: not checked, refused.
    markData.value = null; markScreen.value = CHECKING;
    tap(35, -121);
    assert.equal(got.length, 0); assert.equal(chartMark.value, null, 'consumed: no mark selected'); assert.equal(placementRefused.value.screened, false);
    markData.value = data('morro-bay'); markScreen.value = CHECKING;
    tap(36, -121);
    assert.equal(got.length, 0); assert.equal(placementRefused.value.screened, false, 'checking is not clear');
    // Another region's marks and screen are never this region's verdict.
    markData.value = data('other-region'); markScreen.value = ready();
    tap(36, -121);
    assert.equal(got.length, 0); assert.equal(placementRefused.value.screened, false, 'a foreign region\'s screen reads not checked');
    // The current region's screen, read at the click: inside and within the margin are refused; the placement stays armed.
    markData.value = data('morro-bay'); markScreen.value = ready();
    tap(35, -121);
    assert.equal(got.length, 0); assert.equal(placementRefused.value.inside, true); assert.equal(placementRefused.value.name, NAME);
    tap(35, -120.99 + 30 / (111412.84 * Math.cos(35 * Math.PI / 180)));
    assert.equal(got.length, 0); assert.equal(placementRefused.value.inside, false); assert.ok(placementRefused.value.distanceM <= 70);
    assert.equal(chartMark.value, null, 'refused taps select nothing'); assert.equal(waypointPlacement.value, 'morro-bay', 'still armed');
    // A clear tap completes exactly once; the next tap is the Chart's own selection again.
    tap(36, -121);
    assert.equal(got.length, 1); assert.deepEqual([got[0].latitude, got[0].longitude, got[0].screen.screened, got[0].screen.inside], [36, -121, true, false]);
    assert.equal(waypointPlacement.value, null); assert.equal(placementRefused.value, null); assert.equal(chartMark.value, null, 'the completing tap selects nothing');
    tap(36, -121);
    assert.equal(got.length, 1); assert.equal(chartMark.value.name, 'Shoreline');
    // The screen changing between taps is read at the next click, not at mount: unchecked -> refused, then current -> clear tap completes.
    chartMark.value = null; beginWaypointPlacement('morro-bay', at => got.push(at));
    markScreen.value = CHECKING; tap(36, -121);
    assert.equal(got.length, 1);
    markScreen.value = ready(); tap(36, -121);
    assert.equal(got.length, 2);
  } finally { cancelWaypointPlacement(); markData.value = null; markScreen.value = CHECKING; stage.destroy(); }
});

// FE-82: registry layers on the terrain (packages/coast setOverlay, FE-81).
const OVERLAY_PALETTE = readPalette(name => (name === 'mpa-fill-opacity' ? '0.18' : /^map-.*-(?:opacity|width)$/.test(name) ? '1' : `token(${name})`));

test('FE-82: protected areas, reef marks and charter grounds drape on the terrain in their Chart style\'s token roles', () => {
  assert.deepEqual(LAYERS.filter(e => e.terrain).map(e => e.id), ['mpas', 'charter-grounds', 'marks']);
  for (const e of LAYERS.filter(x => x.terrain)) {
    assert.ok(e.presentations.includes('chart') && e.presentations.includes('terrain'), `${e.id} draws in both`);
    for (const role of [e.terrain.color, e.terrain.outline].filter(Boolean)) assert.ok(COAST_OVERLAY_COLORS.includes(role), `${e.id}: ${role} is an overlay role`);
  }
  // The same tokens as the Chart's layers.
  const [mpaFill, mpaLine] = mpaLayers(sentinel), mpas = layerEntry('mpas').terrain;
  assert.deepEqual([sentinel[mpas.color], sentinel[mpas.outline], mpas.opacity], [mpaFill.paint['fill-color'], mpaLine.paint['line-color'], 'mpaFillOpacity']);
  assert.deepEqual(mpaFill.paint['fill-opacity'], ['to-number', sentinel.mpaFillOpacity], 'both read --mpa-fill-opacity');
  // Coast overlays retain their general UI roles; the Chart's independent roles have equal defaults.
  const ring = markStyle({...sentinel, mapInkHalo: sentinel.bg, markRing: sentinel.mint}).marks.find(l => l.id === 'marks-ring').paint, marks = layerEntry('marks').terrain;
  assert.deepEqual([marks.kind, sentinel[marks.color], marks.opacity, sentinel[marks.outline]], ['point', ring['circle-color'], ring['circle-opacity'], ring['circle-stroke-color']]);
  assert.equal(marks.size, ring['circle-radius'] * 2, 'the ring\'s diameter');
  const grounds = groundsOverlay(sentinel, {outlines: {type: 'FeatureCollection', features: []}, hatch: {type: 'FeatureCollection', features: []}});
  const charter = layerEntry('charter-grounds').terrain;
  assert.deepEqual([sentinel[charter.color], sentinel[charter.outline]], [grounds.layers.find(l => l.id === 'charter-grounds-line').paint['line-color'], sentinel.amber]);
  // "Chart only" leaves the entries the terrain now draws: the Charter fleet rail entry (its grounds).
  assert.equal(drawsIn('fleet', '3d'), true);
  assert.equal(drawsIn('fleet', '2d'), true);
  assert.deepEqual(drapeStyle(mpas, OVERLAY_PALETTE), {color: 'mpaFill', opacity: 0.18, outline: 'mpaLine'}, 'roles stay roles; the opacity token is a number');
  assert.deepEqual(drapeStyle(marks, OVERLAY_PALETTE), {color: 'bg', opacity: 0.75, outline: 'mint', size: 18});
});

test('FE-82: the stage drapes each feed in § 9 order, replaces what changed, removes what went and survives a refusal', t => {
  const warn = t.mock.method(console, 'warn', () => {});
  const calls = [];
  const h = {setOverlay: (id, o) => { calls.push(['set', id, o.order, o.features.length]); if (id === 'charter-grounds' && o.features.length > 1) throw new Error('too big'); return {cell: 1, step: 1, coarsened: false}; },
    removeOverlay: id => { calls.push(['remove', id]); return true; }};
  const point = id => ({id, geometry: {type: 'Point', coordinates: [-120.9, 35.4]}});
  const marks = {features: [point('a')], pick: () => null}, mpas = {features: [point(0)], pick: () => null};
  let draped = drape(h, {marks, mpas, swell: marks}, OVERLAY_PALETTE);
  const order = id => LAYERS.findIndex(e => e.id === id);
  assert.deepEqual(calls, [['set', 'mpas', order('mpas'), 1], ['set', 'marks', order('marks'), 1]], 'bottom to top; an entry without a drape is ignored');
  calls.length = 0;
  draped = drape(h, {marks, mpas}, OVERLAY_PALETTE, draped);
  assert.deepEqual(calls, [], 'an unchanged feed is not sent again');
  draped = drape(h, {marks: {...marks}, mpas: {features: [], pick: () => null}, 'charter-grounds': {features: [point('x'), point('y')], pick: () => null}}, OVERLAY_PALETTE, draped);
  assert.deepEqual(calls, [['remove', 'mpas'], ['set', 'charter-grounds', order('charter-grounds'), 2], ['set', 'marks', order('marks'), 1]]);
  assert.equal(warn.mock.callCount(), 1, 'the refusal is logged');
  assert.deepEqual([...draped.keys()], ['marks'], 'the refused overlay is not counted as draped');
});

// SC0452-04: the stage keeps which draped fills the renderer sampled coarser, for the Legend's note.
const CAP = (c, id) => ({cell: 1, step: c.has(id) ? 3 : 1, coarsened: c.has(id)});
const featureAt = id => ({id, geometry: {type: 'Point', coordinates: [-120.9, 35.4]}});
const layerOf = (...ids) => ({features: ids.map(featureAt), pick: () => null});

test('SC0452-04: drape keeps a coarsened flag while the same feed stays draped and clears it on removal, refusal, a null result and a finer replacement', t => {
  t.mock.method(console, 'warn', () => {});
  const coarse = new Set(['mpas', 'charter-grounds', 'marks']), sets = [], refuse = new Set();
  let silent = false;
  const h = {setOverlay: (id, o) => { if (refuse.has(id)) throw new Error('refused'); sets.push(id); return silent ? null : CAP(coarse, id); }, removeOverlay: () => true};
  const flags = new Set();
  const mpas = layerOf(0), grounds = layerOf('g'), marks = layerOf('m');
  let draped = drape(h, {mpas, 'charter-grounds': grounds}, OVERLAY_PALETTE, new Map(), flags);
  assert.deepEqual([...flags].sort(), ['charter-grounds', 'mpas'], 'each capped fill is flagged on its own');
  sets.length = 0;
  draped = drape(h, {mpas, 'charter-grounds': grounds}, OVERLAY_PALETTE, draped, flags);
  assert.deepEqual([[...flags].sort(), sets], [['charter-grounds', 'mpas'], []], 'an unchanged feed keeps its flag without another set');
  // A finer replacement clears only its own id.
  coarse.delete('mpas');
  draped = drape(h, {mpas: layerOf(0), 'charter-grounds': grounds}, OVERLAY_PALETTE, draped, flags);
  assert.deepEqual([...flags], ['charter-grounds']);
  // A coarse replacement under the same id flags it again; a refusal clears it and leaves the other fill draped.
  coarse.add('mpas');
  draped = drape(h, {mpas: layerOf(0), 'charter-grounds': grounds}, OVERLAY_PALETTE, draped, flags);
  assert.deepEqual([...flags].sort(), ['charter-grounds', 'mpas']);
  refuse.add('mpas');
  draped = drape(h, {mpas: layerOf(0, 1), 'charter-grounds': grounds}, OVERLAY_PALETTE, draped, flags);
  assert.deepEqual([[...flags], [...draped.keys()]], [['charter-grounds'], ['charter-grounds']]);
  refuse.clear();
  // A null result (the renderer is gone) clears the flag and the feed is not counted as draped, so a later pass retries it.
  silent = true;
  draped = drape(h, {mpas: layerOf(0, 1), 'charter-grounds': grounds}, OVERLAY_PALETTE, draped, flags);
  assert.deepEqual([[...flags], [...draped.keys()]], [['charter-grounds'], ['charter-grounds']]);
  silent = false; sets.length = 0;
  draped = drape(h, {mpas: layerOf(0, 1), 'charter-grounds': grounds}, OVERLAY_PALETTE, draped, flags);
  assert.deepEqual([sets, [...flags].sort()], [['mpas'], ['charter-grounds', 'mpas']], 'the retry sets only the feed that was not draped');
  // Missing and empty feeds clear their flags.
  draped = drape(h, {mpas: {features: [], pick: () => null}}, OVERLAY_PALETTE, draped, flags);
  assert.deepEqual([...flags], [], 'an empty and a missing feed');
  // Reef marks are points the renderer never reports coarser.
  coarse.clear();
  drape(h, {marks}, OVERLAY_PALETTE, new Map(), flags);
  assert.deepEqual([...flags], []);
  // Without an accumulator the old call shape still works.
  assert.equal(drape(h, {marks}, OVERLAY_PALETTE).size, 1);
});

test('SC0452-04: the stage publishes the coarsened ids across 2D and 3D and clears them on removal, refusal, a null result and release', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay&presentation=3d`);
  const {land, stage} = chartStage({overlayPalette: () => OVERLAY_PALETTE});
  let destroyed = false;
  t.after(() => { if (!destroyed) stage.destroy(); setTerrainLayer('mpas', null); setTerrainLayer('charter-grounds', null); });
  land.coarse.add('mpas');
  for (let i = 0; i < 8; i++) await tick();
  assert.deepEqual(terrainCoarsened.value, ['mpas'], 'the capped checked areas');
  setTerrainLayer('charter-grounds', layerOf('g1'));
  assert.deepEqual(terrainCoarsened.value, ['mpas'], 'nominal grounds are not flagged');
  land.coarse.add('charter-grounds');
  setTerrainLayer('charter-grounds', layerOf('g2'));
  assert.deepEqual(terrainCoarsened.value, ['mpas', 'charter-grounds'], 'in registry order');
  // The same feeds stay draped across a presentation change: no resend, flags kept.
  const sets = land.sets;
  choosePresentation('2d'); await tick();
  choosePresentation('3d'); await tick();
  setParams({presentation: 'chart'}); await tick();
  assert.deepEqual([land.sets, terrainCoarsened.value], [sets, ['mpas', 'charter-grounds']], 'Chart only hides the terrain; the flags wait');
  setParams({presentation: '3d'}); await tick();
  // A finer replacement clears only its id; reef marks are never flagged.
  land.coarse.delete('charter-grounds');
  setTerrainLayer('charter-grounds', layerOf('g3'));
  assert.deepEqual(terrainCoarsened.value, ['mpas']);
  // A refusal clears the flag and removes the old overlay; the other fill is untouched.
  land.refuse.add('mpas');
  setTerrainLayer('mpas', layerOf(1));
  assert.deepEqual([terrainCoarsened.value, land.overlays.has('mpas')], [[], false], 'refused: no flag, and the old overlay is removed');
  land.refuse.clear();
  land.coarse.add('mpas');
  setTerrainLayer('mpas', layerOf(2));
  assert.deepEqual(terrainCoarsened.value, ['mpas']);
  // The layer going away clears it.
  setTerrainLayer('mpas', null);
  assert.deepEqual(terrainCoarsened.value, []);
  // A null result (a handle already destroyed) leaves no flag.
  land.silent = true;
  setTerrainLayer('mpas', layerOf(3));
  assert.deepEqual(terrainCoarsened.value, []);
  land.silent = false;
  setTerrainLayer('mpas', layerOf(4));
  assert.deepEqual(terrainCoarsened.value, ['mpas']);
  // Releasing the handle clears everything, and a second destroy changes nothing.
  stage.destroy(); destroyed = true;
  assert.deepEqual(terrainCoarsened.value, []);
  setTerrainLayer('mpas', layerOf(5));
  stage.destroy();
  assert.deepEqual(terrainCoarsened.value, [], 'a late feed cannot republish after destroy');
});

test('SC0452-04: a terrain that fails to load takes its coarsened flags with it', async t => {
  t.mock.method(console, 'warn', () => {});
  t.mock.method(console, 'error', () => {});
  browser(`${PAGE}?region=morro-bay&presentation=3d`);
  const {land, stage} = chartStage({overlayPalette: () => OVERLAY_PALETTE});
  t.after(() => { stage.destroy(); terrainFailed.value = false; setTerrainLayer('mpas', null); });
  land.coarse.add('mpas'); land.ready = false;
  for (let i = 0; i < 8; i++) await tick();
  assert.equal(terrainFailed.value, true);
  assert.deepEqual(terrainCoarsened.value, [], 'the failed load released the handle');
});

test('FE-82: in Terrain the protected areas and reef marks drape without the Chart, and a pick selects what the Chart\'s would', async t => {
  t.mock.method(console, 'warn', () => {});
  const nav = browser(`${PAGE}?region=morro-bay&presentation=3d`);
  const {fake, land, stage} = chartStage({overlayPalette: () => OVERLAY_PALETTE});
  t.after(() => stage.destroy());
  for (let i = 0; i < 8; i++) await tick();
  assert.equal(fake.maps.length, 0, 'MapLibre never loads for a terrain-only visit');
  assert.equal(land.options.overlayPalette, OVERLAY_PALETTE, 'the overlay roles resolve from the token palette');
  const mpas = land.overlays.get('mpas');
  assert.deepEqual([mpas.kind, mpas.style, mpas.order], ['fill', {color: 'mpaFill', opacity: 0.18, outline: 'mpaLine'}, LAYERS.findIndex(e => e.id === 'mpas')]);
  assert.equal(mpas.features.length, 8, 'the same checked areas the Chart draws');
  // A protected area: the card the Chart's click opens for the same feature.
  const cambria = mpas.features.findIndex(f => f.properties.NAME === 'Cambria SMCA');
  land.options.onOverlayPick({overlay: 'mpas', feature: cambria, kind: 'fill', latitude: 35.5, longitude: -121.1});
  assert.deepEqual(terrainPick.value, mpaMark(mpas.features[cambria].properties));
  assert.equal(terrainPick.value.name, 'Cambria State Marine Conservation Area');
  // A reef mark: the pick selects its spot, as the Chart's click does. The fake network fails the live boundary
  // checks, so the run-time screen withholds the marks until a current check (the committed snapshot, this hour) passes.
  assert.equal(land.overlays.has('marks'), false, 'withheld marks never drape');
  const snapshot = JSON.parse(readFileSync(new URL('../dist/data/protected-areas.geojson', import.meta.url), 'utf8'));
  markScreen.value = assessScreen({areas: snapshot.features, checkedAt: new Date(Date.now() - 3_600_000).toISOString(), live: false, closures: undefined}, Date.now());
  const marks = land.overlays.get('marks');
  assert.equal(marks.kind, 'point');
  assert.deepEqual(marks.features.map(f => f.id), terrainLayers.value.marks.features.map(f => f.id));
  assert.ok(marks.features.length > 0, 'Morro Bay has reef marks for the boat default target');
  const spot = marks.features[0].id;
  land.options.onOverlayPick({overlay: 'marks', feature: spot, kind: 'point', latitude: 35.4, longitude: -120.9});
  assert.equal(nav.params().get('spot'), spot);
  assert.equal(terrainPick.value, null, 'one selection at a time');
  // A feed that goes leaves the terrain.
  setTerrainLayer('marks', null);
  assert.equal(land.overlays.has('marks'), false);
});

test('the map loads the full shoreline at the zoom the published overview was simplified for (#617)', () => {
  const overview = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/shoreline-overview.geojson', import.meta.url), 'utf8'));
  assert.equal(overview.provenance.overview.max_zoom, SHORELINE_DETAIL_ZOOM);
});

/** RF2205-5: an engine over the fake MapLibre with one pickable layer; `ctx.value` is the pick context. */
function pickEngine() {
  const fake = library(), picks = [], ctx = {value: 'a'};
  fake.features = [{layer: {id: 'pin'}, properties: {id: 'p1'}}];
  const engine = createEngine(fake.module, {host: {}, style: {version: 8, sources: {}, layers: [{id: 'pin'}]}, camera: {latitude: 35.3, longitude: -120.9, zoom: 10},
    onMove() {}, onLayerError() {}, pickLayers: ['pin'], pickContext: () => ctx.value,
    onPick: (layer, properties, at) => picks.push([layer, properties?.id ?? null, at])});
  const [map] = fake.maps;
  const click = () => map.fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -120.9, lat: 35.3}});
  return {fake, map, engine, picks, ctx, click};
}

test('chart_double_tap_never_picks: click/click/dblclick and a native touch zoom pick nothing, before or after the timers run', () => {
  const a = pickEngine();
  a.click(); a.click(); a.map.fire('dblclick');
  assert.equal(settlePicks(), 0); assert.equal(a.picks.length, 0, 'a mouse double-click picks nothing');
  const b = pickEngine();
  b.click(); b.map.fire('zoomstart'); b.map.fire('movestart');
  b.click();   // the second tap's click arrives while the zoom is moving
  assert.equal(settlePicks(), 0); assert.equal(b.picks.length, 0, 'a touch zoom with no dblclick picks nothing');
  b.map.fire('moveend');
  assert.equal(settlePicks(), 0); assert.equal(b.picks.length, 0);
  b.click();
  assert.equal(settlePicks(), 1); assert.equal(b.picks.length, 1, 'a later deliberate click after the zoom settles still picks');
});

test('chart_single_pick_settles_once: nothing at 549 ms, one pick at 550 ms, with the click\'s own feature and point', t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const a = pickEngine();
  a.click();
  t.mock.timers.tick(549);
  assert.equal(a.picks.length, 0);
  a.fake.features = [];   // the camera or layers moving later must not change what was clicked
  t.mock.timers.tick(1);
  assert.equal(a.picks.length, 1);
  assert.ok(util.isDeepStrictEqual(a.picks[0], ['pin', 'p1', {lon: -120.9, lat: 35.3}]), 'the feature and point captured at the click');
  t.mock.timers.tick(5000);
  assert.equal(a.picks.length, 1, 'once');
  a.click(); t.mock.timers.tick(550);
  assert.ok(util.isDeepStrictEqual(a.picks[1], [null, null, {lon: -120.9, lat: 35.3}]), 'empty water is a null pick');
  a.click(); a.click(); t.mock.timers.tick(550);
  assert.equal(a.picks.length, 3, 'a later click replaces the pending one');
  t.mock.timers.reset();
});

test('chart_pending_pick_context_and_lifetime: a changed pick context, setCamera and destroy drop a pending pick', () => {
  const a = pickEngine();
  a.click(); a.ctx.value = 'b'; assert.equal(settlePicks(), 1); assert.equal(a.picks.length, 0, 'region/view/waypoint change drops it');
  a.ctx.value = 'a'; a.click(); a.ctx.value = 'b'; a.ctx.value = 'a';
  assert.equal(settlePicks(), 1); assert.equal(a.picks.length, 1, 'identity equality only: the token itself changes on away-and-back (the Chart replaces the object)');
  const b = pickEngine();
  b.click(); b.engine.setCamera({latitude: 35, longitude: -121, zoom: 9});
  assert.equal(settlePicks(), 0); assert.equal(b.picks.length, 0, 'setCamera cancels');
  const c = pickEngine();
  c.click(); c.engine.destroy();
  assert.equal(settlePicks(), 0); assert.equal(c.picks.length, 0, 'destroy cancels');
});

test('chart_pending_pick_context_and_lifetime: the Chart drops a click still settling when waypoint placement is armed, and a settled click selects once', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay`);
  const {fake, stage} = chartStage();
  await tick(); await tick(); await tick();
  const [map] = fake.maps;
  fake.features = [{layer: {id: COASTLINE_PICK}, properties: {SOURCE_ID: 'S1', ATTRIBUTE: 'Natural.Mean High Water', HOR_ACC: '2', source_date: '2010-11-01'}}];
  try {
    chartMark.value = null;
    const got = [];
    map.fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -121, lat: 35}});
    beginWaypointPlacement('morro-bay', at => got.push(at));
    assert.equal(settlePicks(), 1);
    assert.equal(chartMark.value, null, 'the old click does not become a mark'); assert.equal(got.length, 0, 'nor a waypoint');
    cancelWaypointPlacement();
    map.fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -121, lat: 35}});
    cancelWaypointPlacement(); beginWaypointPlacement('morro-bay', at => got.push(at)); cancelWaypointPlacement();
    assert.equal(settlePicks(), 1); assert.equal(chartMark.value, null, 'arm and cancel in between still drops it');
    map.fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -121, lat: 35}});
    map.fire('dblclick');
    assert.equal(settlePicks(), 0); assert.equal(chartMark.value, null, 'a double tap selects nothing');
    map.fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -121, lat: 35}});
    settlePicks();
    assert.equal(chartMark.value.name, 'Shoreline', 'an isolated click still selects');
  } finally { cancelWaypointPlacement(); stage.destroy(); }
});

test('chart_closed_pick_context_never_picks: a null pick context at both the click and the dispatch drops the pick', () => {
  const a = pickEngine();
  a.ctx.value = null;   // picking is closed: null at the click and still null when the timer fires
  a.click();
  assert.equal(settlePicks(), 0); assert.equal(a.picks.length, 0, 'a click while closed schedules nothing');
  const b = pickEngine();
  b.click(); b.ctx.value = null;
  assert.equal(settlePicks(), 1); assert.equal(b.picks.length, 0, 'closed by dispatch');
  const c = pickEngine();
  c.ctx.value = null; c.click(); c.ctx.value = 'a';
  assert.equal(settlePicks(), 0); assert.equal(c.picks.length, 0, 'reopened after a closed click does not accept it');
  const fake = library(), picks = [];
  createEngine(fake.module, {host: {}, style: {version: 8, sources: {}, layers: []}, camera: {latitude: 35.3, longitude: -120.9, zoom: 10}, onMove() {}, onLayerError() {}, pickLayers: [], onPick: layer => picks.push(layer)});
  fake.maps[0].fire('click', {point: {x: 1, y: 1}});
  assert.equal(settlePicks(), 1); assert.deepEqual(picks, [null], 'an engine with no pickContext at all is not gated');
});

test('chart_closed_pick_context_never_picks: with the Chart still mounted but another view shown (Fleet), a tap selects no mark and places no waypoint', async t => {
  t.mock.method(console, 'warn', () => {});
  browser(`${PAGE}?region=morro-bay`);
  const {fake, stage} = chartStage();
  await tick(); await tick(); await tick();
  const [map] = fake.maps;
  fake.features = [{layer: {id: COASTLINE_PICK}, properties: {SOURCE_ID: 'S1', ATTRIBUTE: 'Natural.Mean High Water', HOR_ACC: '2', source_date: '2010-11-01'}}];
  const got = [];
  try {
    chartMark.value = null;
    appView.value = 'fleet';
    map.fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -121, lat: 35}});
    assert.equal(settlePicks(), 0, 'no click is left settling when the view is not the coast');
    assert.equal(chartMark.value, null, 'no mark selected from Fleet');
    beginWaypointPlacement('morro-bay', at => got.push(at));
    map.fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -121, lat: 35}});
    settlePicks();
    assert.equal(got.length, 0, 'no waypoint placed from Fleet'); assert.equal(chartMark.value, null);
    appView.value = 'coast'; cancelWaypointPlacement();
    map.fire('click', {point: {x: 1, y: 1}, lngLat: {lng: -121, lat: 35}});
    settlePicks();
    assert.equal(chartMark.value.name, 'Shoreline', 'back on the coast an isolated click selects');
  } finally { appView.value = 'coast'; cancelWaypointPlacement(); stage.destroy(); }
});
