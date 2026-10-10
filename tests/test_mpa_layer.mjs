// Protected areas on the Chart (FE-19, docs/plans/front-end/design.md § 9): the registry
// entry (always on, no rail entry, ds582 credit), the token styling, parity with v1's
// snapshot rule (dist/protected-areas.js `validMPAs`), the completeness assessment for
// every published region, the mark card and the legend row. Offline: the region files
// are the committed dist/ copies, MapLibre is a fake, and the .tsx parts are bundled
// with esbuild and rendered to strings.
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {MPA_SERVICE as V1_SERVICE, validMPAs} from '../dist/protected-areas.js';
import {lintFile} from '../scripts/check_tokens.mjs';
import {PROFILE_TABLE, RAIL_IDS} from '../web/profile.ts';
import {MPA_ATTRIBUTION, MPA_SOURCE, LAYERS, SEAFLOOR_SOURCE, layerEntry, sourceLayer} from '../web/map/layers.ts';
import {ZOOM_OFFSET} from '../web/map/engine.ts';
import {
  CDFW_MPA_PAGE, DESIGNATIONS, IDLE, LOADING, MAP_UNAVAILABLE, MPA_FILL, MPA_LABEL, MPA_LABEL_MIN_ZOOM, MPA_LINE, MPA_SERVICE, NOAA_GEA_PAGE, NOTES,
  assessMpas, covers, loadMpas, mpaLayers, mpaMark, mpaState, shownMpaState, snapshotEnvelope, validSnapshot,
} from '../web/map/mpa.ts';
import {chartMark, chartStyle, createChart, unavailable} from '../web/map/chart.ts';
import {readPalette} from '../web/map/palette.ts';
import {createStage} from '../web/map/stage.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const PAGE = 'https://s.test/map';
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const json = path => JSON.parse(read(path));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const settle = async () => { for (let i = 0; i < 8; i++) await tick(); };
const sentinel = readPalette(name => `token(${name})`);
const REGIONS = json('dist/regions/index.json').regions.map(r => r.id);
const regionFiles = id => ({config: json(`dist/regions/${id}/region.json`), coverage: json(`dist/regions/${id}/coverage.json`)});
/** The committed file under dist/ for a page-relative URL, or a 404 (as the site answers). */
const serveDist = url => {
  const file = new URL(`../dist${new URL(url).pathname}`, import.meta.url);
  return existsSync(file) ? {ok: true, json: async () => JSON.parse(readFileSync(file, 'utf8'))} : {ok: false, status: 404, json: async () => ({})};
};
/** Words that would read the map as a statement of what the rules allow, or as an absence of protection. */
const VERDICT = /\b(?:allowed|prohibited|permitted|illegal|legal to|you may|you can|open to fishing|no (?:protected|mpa)|not protected|clear of)\b/i;

test('the registry entry is always on in Chart and on the terrain, has no rail entry, owns its source and carries the ds582 credit', () => {
  const e = layerEntry('mpas');
  assert.equal(e.control, 'always');
  assert.deepEqual(e.presentations, ['chart', 'terrain']);
  assert.deepEqual(e.time, ['static']);
  assert.ok(!RAIL_IDS.includes('mpas') && !RAIL_IDS.includes(e.control), 'no rail entry');
  for (const profile of Object.values(PROFILE_TABLE)) assert.ok(!profile.defaultLayers.includes('mpas'), 'drawn whatever the profile');
  assert.deepEqual(e.sources, [MPA_SOURCE]);
  assert.equal(sourceLayer(MPA_SOURCE), 'mpas');
  assert.equal(e.basis, 'CDFW marine protected areas, ds582; boundaries are context, rules are in the regulations page.');
  assert.match(read('docs/plans/front-end/design.md'), /\| MPAs \| always \| CDFW ds582 \(existing\) \|.*"CDFW marine protected areas, ds582; boundaries are context, rules are in the regulations page\." \| FE-19 \|/);
  // The credit names what the catalog's rights block requires: the creator, the dataset and the licence.
  const source = json('catalog/sources.json').sources.find(s => s.id === 'cdfw-mpas');
  assert.equal(source.rights.license, 'CC-BY-4.0');
  assert.equal(e.attribution, MPA_ATTRIBUTION);
  assert.equal(MPA_ATTRIBUTION, 'CDFW ds582 · CC BY 4.0', 'on the map: creator, dataset, licence; the legend\'s basis names the GIS Lab and links both');
  assert.equal(source.rights.attribution, 'CDFW Marine Region GIS Lab');
  // § 9: above the swell field, under the habitat polygons.
  const ids = LAYERS.map(l => l.id);
  assert.equal(ids.indexOf('mpas'), ids.indexOf('swell') + 1);
  assert.equal(ids.indexOf('habitat'), ids.indexOf('mpas') + 1);
});

test('fill, dashed outline and names read the --mpa-* tokens; names start at ?view= zoom 11', () => {
  const [fill, line, label] = mpaLayers(sentinel);
  assert.deepEqual([fill.id, line.id, label.id], [MPA_FILL, MPA_LINE, MPA_LABEL]);
  assert.equal(fill.paint['fill-color'], sentinel.mpaFill);
  assert.deepEqual(fill.paint['fill-opacity'], ['to-number', sentinel.mpaFillOpacity], 'the fill opacity is the --mpa-fill-opacity token');
  assert.equal(line.paint['line-color'], sentinel.mpaLine);
  assert.ok(Array.isArray(line.paint['line-dasharray']) && line.paint['line-dasharray'].length === 2, 'dashed outline');
  assert.equal(label.paint['text-color'], sentinel.mpaLine);
  assert.equal(label.paint['text-halo-color'], sentinel.bg);
  assert.deepEqual(label.layout['text-field'], ['get', 'NAME']);
  assert.equal(MPA_LABEL_MIN_ZOOM, 11);
  assert.equal(label.minzoom, 11 - ZOOM_OFFSET, 'MapLibre zoom 10 is ?view= zoom 11');
  assert.equal(fill.minzoom, undefined, 'outlines draw at every zoom');
  assert.doesNotMatch(JSON.stringify(mpaLayers(sentinel)), /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?)\(/i);
  assert.deepEqual(lintFile('web/map/mpa.ts', read('web/map/mpa.ts')), []);
  // The tokens hold design D5's values.
  const css = read('web/tokens.css');
  assert.match(css, /--mpa-fill: #e8a877;\s*--mpa-fill-opacity: 0\.08;\s*--mpa-line: #e8b584;/);
  // In the Chart (§ 9): after the ENC base, under the seafloor (FE-14) and the coastline glow, with the credit on its source.
  const style = chartStyle({palette: sentinel, archive: null, page: PAGE, region: 'morro-bay', base: 'night'});
  const order = style.layers.map(l => l.id);
  const mpas = [MPA_FILL, MPA_LINE, MPA_LABEL].map(id => order.indexOf(id));
  assert.deepEqual(mpas, [mpas[0], mpas[0] + 1, mpas[0] + 2], 'fill, outline, names together');
  assert.ok(order.indexOf('chart-enc') < mpas[0]);
  const seafloor = style.layers.findIndex(l => l.source === SEAFLOOR_SOURCE);
  assert.ok(seafloor > mpas[2] && seafloor < order.indexOf('coastline-glow'), 'MPAs, then the seafloor, then the coastline');
  assert.deepEqual(style.sources[MPA_SOURCE], {type: 'geojson', data: {type: 'FeatureCollection', features: []}, attribution: MPA_ATTRIBUTION});
});

test('the snapshot rule matches v1\'s validMPAs for the region v1 loads by default', () => {
  assert.equal(MPA_SERVICE, V1_SERVICE);
  const snapshot = json('dist/data/protected-areas.geojson');
  const minimum = json('dist/regions/morro-bay/region.json').mpa.minimum_features;
  const box = {type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]]};
  const variants = {
    committed: snapshot,
    empty: {...snapshot, features: []},
    truncated: {...snapshot, exceededTransferLimit: true},
    'one short': {...snapshot, features: snapshot.features.slice(0, minimum - 1)},
    'a point': {...snapshot, features: [...snapshot.features, {type: 'Feature', properties: {NAME: 'X'}, geometry: {type: 'Point', coordinates: [0, 0]}}]},
    unnamed: {...snapshot, features: [...snapshot.features, {type: 'Feature', properties: {}, geometry: box}]},
    'not a collection': {...snapshot, type: 'Feature'},
    null: null,
  };
  for (const [name, data] of Object.entries(variants)) {
    assert.equal(validSnapshot(data) && data.features.length >= minimum, validMPAs(data), name);
  }
});

test('a snapshot covers a region only when its ds582 query envelope contains the region\'s bounds', () => {
  const url = 'https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?where=1%3D1&geometry=-121.9%2C34.95%2C-120.55%2C35.85&f=geojson';
  assert.deepEqual(snapshotEnvelope(url), [-121.9, 34.95, -120.55, 35.85]);
  assert.equal(snapshotEnvelope(url.replace('biosds582_fpu', 'other')), null, 'only the ds582 service');
  assert.equal(snapshotEnvelope(url.replace('services2.arcgis.com', 'evil.test')), null);
  assert.equal(snapshotEnvelope(undefined), null);
  assert.equal(snapshotEnvelope(url.replace('-120.55%2C', '')), null, 'four numbers');
  assert.equal(covers([-121.9, 34.95, -120.55, 35.85], [-121.9, 34.95, -120.55, 35.85]), true);
  assert.equal(covers([-121.9, 34.95, -120.55, 35.85], [-123.7, 37.95, -122.7, 38.5]), false);
  assert.equal(covers([-121.9, 34.95, -120.55, 35.85], [-121.9, 34.95, -120.55, 35.9]), false, 'one edge outside');
  assert.equal(covers([-121.9, 34.95, -120.55, 35.85], []), false, 'no bounds, no claim');
});

test('every published region: complete only when reviewed and covered; anything less says an unoutlined area may be protected', () => {
  const expected = {
    'morro-bay': 'complete', 'cambria-san-simeon': 'complete', 'southern-california': 'complete',
    // These four bind Morro Bay's shared snapshot, whose query envelope is Morro Bay's.
    'bodega-point-reyes': 'incomplete', 'crescent-city': 'incomplete', 'fort-bragg-point-arena': 'incomplete', 'humboldt-bay-cape-mendocino': 'incomplete',
  };
  for (const id of REGIONS) {
    const {config, coverage} = regionFiles(id);
    const snapshot = json(`dist/${config.assets.protected_areas}`);
    const closures = config.assets.closures ? json(`dist/${config.assets.closures}`) : undefined;
    const {state, data} = assessMpas({region: id, config, snapshot, coverage, closures});
    const review = coverage.needs.find(n => n.id === 'protected-areas');
    assert.equal(state.status, expected[id] ?? 'partial', id);
    if (state.status === 'complete') {
      assert.equal(review.status, 'ready', `${id} is complete only after its review`);
      assert.equal(state.note, `CDFW ds582 snapshot for this region, checked ${snapshot.checked_at.slice(0, 10)}.`, 'the region, not whatever is in view');
    } else {
      assert.match(state.note, /an area without an outline may still be protected\.$/, id);
      assert.ok(state.detail.length > 0, `${id} says why`);
    }
    // A partial drawing says what the data holds, never the review's v1 screening language.
    if (state.status === 'partial') assert.equal(state.detail, `Drawn: ${data.features.length} areas from the CDFW ds582 snapshot checked ${snapshot.checked_at.slice(0, 10)}. The region's review has not confirmed that this is every protected area here.`);
    assert.doesNotMatch(state.detail, /target|promotion|screen|exclud|trip-time|gate/i, id);
    assert.doesNotMatch(`${state.note} ${state.detail}`, VERDICT, id);
    // Everything valid is drawn, whatever the status: a partial drawing is still real boundaries.
    assert.equal(data.features.length, snapshot.features.length + (closures?.features.length ?? 0), id);
    assert.equal(state.count, data.features.length);
    assert.ok(data.features.every(f => f.properties.NAME && ['cdfw', 'noaa'].includes(f.properties.source)), id);
  }
  const socal = regionFiles('southern-california');
  const {data} = assessMpas({region: 'southern-california', config: socal.config, snapshot: json('dist/regions/southern-california/protected-areas.geojson'),
    coverage: socal.coverage, closures: json('dist/regions/southern-california/groundfish-exclusions.geojson')});
  assert.equal(data.features.filter(f => f.properties.source === 'noaa').length, 8, 'NOAA\'s eight groundfish exclusion areas draw with the MPAs');
  assert.ok(data.features.filter(f => f.properties.source === 'noaa').every(f => f.properties.Type === 'GEA' && f.properties.checked === '2026-09-24'));
});

test('a damaged, short or foreign snapshot is never presented as complete', () => {
  const {config, coverage} = regionFiles('morro-bay');
  const snapshot = json('dist/data/protected-areas.geojson');
  const assess = (patch, more = {}) => assessMpas({region: 'morro-bay', config, coverage, snapshot: {...snapshot, ...patch}, ...more}).state;
  for (const [name, patch] of Object.entries({truncated: {exceededTransferLimit: true}, empty: {features: []}, 'not a collection': {type: 'Feature'}})) {
    const s = assess(patch);
    assert.equal(s.status, 'unavailable', name);
    assert.equal(s.note, NOTES.unavailable);
  }
  assert.equal(assessMpas({region: 'morro-bay', config, coverage, snapshot: snapshot}).state.status, 'complete');
  assert.match(assess({features: snapshot.features.slice(0, 3)}).detail, /holds 3 areas; this region's check expects at least 8/);
  assert.match(assess({region_id: 'big-sur-coast'}).detail, /taken for another region/);
  assert.match(assess({source_url: 'https://example.test/mpas.geojson'}).detail, /does not cover this whole region/);
  assert.equal(assess({region_id: 'morro-bay'}).status, 'complete', 'its own region id is fine');
  // Closures the region names but that fail to load: the MPAs still draw, the gap is named.
  const missing = assessMpas({region: 'morro-bay', config, coverage, snapshot, closures: null});
  assert.equal(missing.state.status, 'incomplete');
  assert.match(missing.state.detail, /federal groundfish closures/);
  assert.equal(missing.data.features.length, snapshot.features.length);
  // Without the region's own review, the drawing is not called complete.
  const unreviewed = assessMpas({region: 'morro-bay', config, coverage: null, snapshot});
  assert.equal(unreviewed.state.status, 'partial');
  assert.equal(unreviewed.state.detail, 'Drawn: 8 areas from the CDFW ds582 snapshot checked 2026-09-21. This region\'s boundary review did not load, so the drawing is unconfirmed.');
  assert.equal(assessMpas({region: 'morro-bay', config, coverage: {...coverage, region_id: 'big-sur-coast'}, snapshot}).state.status, 'partial');
});

test('the legend state: loading until the Chart loads, "Map unavailable." without a map, unavailable when MapLibre fails the checked data', () => {
  const complete = assessMpas({region: 'morro-bay', ...regionFiles('morro-bay'), snapshot: json('dist/data/protected-areas.geojson')}).state;
  assert.equal(shownMpaState(complete), complete);
  assert.equal(shownMpaState(IDLE), LOADING, 'before the Chart mounts');
  assert.equal(LOADING.note, 'Loading boundaries.');
  assert.equal(shownMpaState(complete, {mapFailed: true}), MAP_UNAVAILABLE);
  assert.equal(shownMpaState(IDLE, {mapFailed: true}).note, 'Map unavailable.');
  const failed = shownMpaState(complete, {sourceFailed: true});
  assert.equal(failed.status, 'unavailable');
  assert.equal(failed.note, NOTES.unavailable, 'never the check date of data that did not draw');
  assert.match(failed.note, /an area without an outline may still be protected\.$/);
  const already = shownMpaState({...complete, status: 'unavailable', note: NOTES.unavailable, detail: 'The boundary snapshot did not load.'}, {sourceFailed: true});
  assert.equal(already.detail, 'The boundary snapshot did not load.', 'the loader\'s own reason stays');
});

test('the loader reads the region\'s own files, never an asset path outside data/ or regions/, and never throws', async () => {
  const seen = [];
  const fetchFn = async url => { seen.push(new URL(url).pathname); return serveDist(url); };
  const southern = await loadMpas('southern-california', fetchFn, PAGE);
  assert.equal(southern.state.status, 'complete');
  assert.deepEqual(seen.sort(), ['/regions/southern-california/coverage.json', '/regions/southern-california/groundfish-exclusions.geojson',
    '/regions/southern-california/protected-areas.geojson', '/regions/southern-california/region.json']);
  seen.length = 0;
  assert.equal((await loadMpas('morro-bay', fetchFn, PAGE)).state.checked, '2026-09-21');
  assert.ok(!seen.some(p => /groundfish/.test(p)), 'no closures fetched where the region names none');

  const config = json('dist/regions/morro-bay/region.json');
  const answer = (overrides) => async url => { const path = new URL(url).pathname; seen.push(path); return path in overrides ? overrides[path] : serveDist(url); };
  const notFound = {ok: false, status: 404, json: async () => ({})};
  for (const [name, overrides, detail] of [
    ['no region package', {'/regions/morro-bay/region.json': notFound}, 'The region package did not load.'],
    ['no snapshot', {'/data/protected-areas.geojson': notFound}, 'The boundary snapshot did not load.'],
    ['a foreign asset', {'/regions/morro-bay/region.json': {ok: true, json: async () => ({...config, assets: {protected_areas: 'https://evil.test/mpa.geojson'}})}}, 'This region names no boundary snapshot.'],
    ['a climbing asset', {'/regions/morro-bay/region.json': {ok: true, json: async () => ({...config, assets: {protected_areas: 'data/../x.geojson'}})}}, 'This region names no boundary snapshot.'],
  ]) {
    seen.length = 0;
    const result = await loadMpas('morro-bay', answer(overrides), PAGE);
    assert.equal(result.state.status, 'unavailable', name);
    assert.equal(result.state.detail, detail, name);
    assert.deepEqual(result.data, {type: 'FeatureCollection', features: []}, name);
    assert.ok(seen.every(p => p.startsWith('/regions/') || p.startsWith('/data/')), `${name}: ${seen}`);
  }
  const offline = await loadMpas('morro-bay', async () => { throw new Error('offline'); }, PAGE);
  assert.equal(offline.state.status, 'unavailable');
});

test('a clicked area shows its name, designation and citation, the source and check date, and links the official rules page', () => {
  const morro = json('dist/data/protected-areas.geojson').features.find(f => f.properties.NAME === 'Morro Bay SMR').properties;
  assert.deepEqual(mpaMark({...morro, source: 'cdfw', checked: '2026-09-21'}), {
    id: 'mpa:Morro Bay SMR', name: 'Morro Bay State Marine Reserve', kind: 'State Marine Reserve', reading: 'CCR Title 14, Section 632 (b) (92)',
    source: 'CDFW ds582 · checked 2026-09-21', basis: layerEntry('mpas').basis, regulations: {href: CDFW_MPA_PAGE, label: 'CDFW marine protected areas'},
  });
  const gea = mpaMark({NAME: 'Hidden Reef', FULLNAME: 'Hidden Reef Groundfish Exclusion Area', Type: 'GEA', CCR: 'NOAA groundfish closure; see controlling federal regulations', source: 'noaa', checked: '2026-09-24'});
  assert.equal(gea.kind, 'Groundfish Exclusion Area (federal)');
  assert.equal(gea.reading, 'NOAA groundfish closure; see controlling federal regulations');
  assert.equal(gea.source, 'NOAA Fisheries · checked 2026-09-24');
  assert.deepEqual(gea.regulations, {href: NOAA_GEA_PAGE, label: 'NOAA groundfish closed areas'});
  assert.equal(mpaMark({NAME: 'Gull Island FMR', FULLNAME: 'Gull Island Federal Marine Reserve', Type: 'FMR', CCR: 'N/A', source: 'cdfw'}).reading, 'Federal waters; ds582 lists no state section.');
  assert.equal(mpaMark({NAME: 'X SMCA (No-Take)', Type: 'SMCA (No-Take)', source: 'cdfw'}).kind, 'State Marine Conservation Area (no-take)');
  assert.equal(mpaMark({NAME: 'Y', Type: 'ZZ', source: 'cdfw'}).kind, 'Designation ZZ', 'an unknown code is shown as given');
  assert.equal(mpaMark({NAME: 'Y', source: 'cdfw'}).source, 'CDFW ds582 · check date not stated');
  assert.equal(mpaMark({}), null);
  assert.equal(mpaMark(null), null);
  // Every designation in the committed boundary files has a name, and no card reads as a rule.
  const files = [...new Set(REGIONS.flatMap(id => Object.entries(json(`dist/regions/${id}/region.json`).assets)
    .filter(([key]) => key === 'protected_areas' || key === 'closures').map(([, path]) => path)))];
  for (const path of files) {
    for (const f of json(`dist/${path}`).features) {
      assert.ok(DESIGNATIONS[f.properties.Type], `${path}: ${f.properties.Type}`);
      const mark = mpaMark({...f.properties, source: f.properties.Type === 'GEA' ? 'noaa' : 'cdfw', checked: '2026-09-21'});
      assert.doesNotMatch(Object.values(mark).filter(v => typeof v === 'string').join(' '), VERDICT, f.properties.NAME);
    }
  }
});

/** A fake MapLibre just big enough for the Chart: sources, layers, data, clicks and idle. */
function library() {
  const fake = {maps: [], features: [], rendered: {}};
  class FakeMap {
    constructor(options) { this.options = options; this.handlers = {}; this.data = {}; this.zoom = options.zoom; fake.maps.push(this); this.keyboard = this.touchZoomRotate = {disableRotation() {}}; }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type, event = {}) { for (const fn of this.handlers[type] ?? []) fn(event); }
    addControl() {}
    getCenter() { return {lat: this.options.center[1], lng: this.options.center[0]}; }
    getZoom() { return this.zoom; }
    jumpTo() {}
    getLayer(id) { return this.options.style.layers.some(l => l.id === id) ? {} : undefined; }
    setLayoutProperty() {}
    getSource(id) { return this.options.style.sources[id] ? {setData: data => { this.data[id] = data; }} : undefined; }
    queryRenderedFeatures(a, b) {
      const layers = (b ?? a).layers;
      return b ? fake.features.filter(f => layers.includes(f.layer.id)) : Array.from({length: fake.rendered[layers[0]] ?? 0}, () => ({}));
    }
    resize() {}
    remove() {}
  }
  const control = class {};
  fake.module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/assets/worker.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  return fake;
}

function chart(href, fetchFn) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
  const fake = library(), host = {dataset: {}};
  unavailable.value = []; chartMark.value = null;
  const manifest = {ok: false, json: async () => ({})};
  const stage = createStage({host: {shadowRoot: {replaceChildren() {}}}, load: async () => ({styles: [], mountCoast: () => ({})}), center: () => [35.37, -120.86],
    doc: {hidden: false, addEventListener() {}, removeEventListener() {}}, viewDelay: 0,
    renderers: [() => createChart({host, load: async () => fake.module, palette: () => sentinel, page: () => PAGE, viewDelay: 0,
      fetchFn: async url => (url.includes('/feeds/') ? manifest : fetchFn(url))})]});
  return {fake, host, stage};
}

test('the Chart draws the region\'s checked areas, reports their state and labels, and a click opens the area\'s card', async t => {
  t.mock.method(console, 'warn', () => {});
  const {fake, host, stage} = chart(`${PAGE}?region=morro-bay`, serveDist);
  await settle();
  const [map] = fake.maps;
  assert.equal(mpaState.value.status, 'complete');
  assert.equal(host.dataset.mpa, 'complete');
  assert.equal(map.data[MPA_SOURCE].features.length, 8);
  assert.ok(!unavailable.value.includes('mpas'));
  fake.rendered[MPA_FILL] = 5; fake.rendered[MPA_LABEL] = 3;
  map.fire('idle');
  assert.equal(host.dataset.mpaDrawn, '5', 'the areas MapLibre drew in view');
  assert.equal(host.dataset.mpaLabels, '3', 'and the names it placed');
  fake.features = [{layer: {id: MPA_FILL}, properties: map.data[MPA_SOURCE].features.find(f => f.properties.NAME === 'Cambria SMCA').properties}];
  map.fire('click', {point: {x: 1, y: 1}});
  assert.equal(chartMark.value.name, 'Cambria State Marine Conservation Area');
  assert.equal(chartMark.value.source, 'CDFW ds582 · checked 2026-09-21');

  setParams({region: 'bodega-point-reyes'});
  assert.equal(host.dataset.mpa, 'loading', 'a region change says it is checking, never "none"');
  await settle();
  assert.equal(host.dataset.mpa, 'incomplete');
  assert.equal(mpaState.value.note, NOTES.incomplete);
  stage.destroy();
  assert.deepEqual(mpaState.value, IDLE);
});

test('boundaries that do not load leave the layer unavailable and named, and draw nothing', async t => {
  t.mock.method(console, 'warn', () => {});
  const {fake, host, stage} = chart(`${PAGE}?region=morro-bay`, url => (url.endsWith('protected-areas.geojson') ? {ok: false, status: 503} : serveDist(url)));
  await settle();
  assert.equal(host.dataset.mpa, 'unavailable');
  assert.ok(unavailable.value.includes('mpas'));
  assert.deepEqual(fake.maps[0].data[MPA_SOURCE], {type: 'FeatureCollection', features: []});
  assert.equal(mpaState.value.note, NOTES.unavailable);
  stage.destroy();
});

let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'mpa-')), 'mpa.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {Legend, MpaRow} from './web/app/Legend.tsx';
      export {MarkCard, currentMark} from './web/app/MarkCard.tsx';
      export {mpaState, LOADING, NOTES} from './web/map/mpa.ts';
      export {chartFailed, unavailable} from './web/map/chart.ts';
      export {shownPresentation, terrainPick} from './web/map/stage.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}],
  });
  ui = await import(pathToFileURL(out).href);
  return ui;
}

test('the legend row says what the drawing covers, links the official rules and carries the ds582 credit', async () => {
  const {Legend, MpaRow, mpaState: state, NOTES: notes, LOADING: loading, chartFailed, unavailable: failedLayers, render, h, state: store} = await components();
  store.configureStore({v2: true, storage: null});
  store.syncFromURL(`${PAGE}?region=morro-bay&layers=none`);
  state.value = {status: 'complete', note: 'CDFW ds582 snapshot for this region, checked 2026-09-21.', detail: '', checked: '2026-09-21', count: 8};
  const row = render(h(MpaRow, {}));
  assert.match(row, /^<li class="app-legend-mpa" data-mpa="complete">/);
  assert.match(row, /<span class="app-swatch" data-layer="mpas" aria-hidden="true"><\/span>Marine protected areas/);
  assert.match(row, /<p class="app-mpa-note">CDFW ds582 snapshot for this region, checked 2026-09-21\.<\/p>/);
  assert.match(row, new RegExp(`<a class="app-mpa-rules" href="${CDFW_MPA_PAGE}" target="_blank" rel="noopener">Official rules and boundaries \\(CDFW\\)</a>`));
  // The credit sits in the basis disclosure: creator, dataset, licence, and that the selection is SkipperCast's.
  assert.match(row, /<details class="ui-popover ui-popover--icon"[^>]*>.*Regional selection by SkipperCast from <a href="https:\/\/filelib\.wildlife\.ca\.gov\/public\/BDB\/GIS\/BIOS\/metadata\/DS0582\.html"[^>]*>CDFW\s+Marine Region GIS Lab, California MPAs ds582<\/a>, <a href="https:\/\/creativecommons\.org\/licenses\/by\/4\.0\/"[^>]*>CC BY 4\.0<\/a>\./s);
  // MapLibre failed to draw the checked data: the row says unavailable, not the check date.
  failedLayers.value = ['mpas'];
  const broken = render(h(MpaRow, {}));
  assert.match(broken, /data-mpa="unavailable"/);
  assert.match(broken, /<p class="app-mpa-note">Boundaries did not load, so none are drawn; an area without an outline may still be protected\.<\/p>/);
  assert.doesNotMatch(broken, /checked 2026-09-21/);
  failedLayers.value = [];
  chartFailed.value = true;
  assert.match(render(h(MpaRow, {})), /data-mpa="unavailable".*<p class="app-mpa-note">Map unavailable\.<\/p>/s);
  chartFailed.value = false;
  state.value = {status: 'idle', note: '', detail: '', checked: null, count: 0};
  assert.match(render(h(MpaRow, {})), /data-mpa="loading".*<p class="app-mpa-note">Loading boundaries\.<\/p>/s, 'before the Chart loads');
  state.value = {status: 'partial', note: notes.partial, detail: 'Drawn: 4 areas from the CDFW ds582 snapshot checked 2026-09-25.', checked: '2026-09-25', count: 4};
  const partial = render(h(MpaRow, {}));
  assert.match(partial, /data-mpa="partial"/);
  assert.match(partial, /<p class="app-mpa-note">Boundary review for this region is partial; an area without an outline may still be protected\.<\/p>/);
  assert.match(partial, /Drawn: 4 areas from the CDFW ds582 snapshot checked 2026-09-25\. Regional selection/);
  state.value = loading;
  assert.match(render(h(MpaRow, {})), /<p class="app-mpa-note">Loading boundaries\.<\/p>/);
  // The legend shows the row on the Chart, under the rail's layers, and names an unavailable load only in the row.
  state.value = {status: 'unavailable', note: notes.unavailable, detail: 'The boundary snapshot did not load.', checked: null, count: 0};
  const legend = render(h(Legend, {}));
  assert.match(legend, /<ul><li class="app-legend-mpa" data-mpa="unavailable">/, 'no "No layers on." while the areas draw');
  assert.match(legend, /Boundaries did not load, so none are drawn; an area without an outline may still be protected\./);
  assert.doesNotMatch(legend, /data-unavailable="mpas"/);
  // FE-82: in Terrain the areas drape too, so the row stays; the Chart's own failure does not speak for the drape.
  store.syncFromURL(`${PAGE}?region=morro-bay&layers=none&presentation=3d`);
  chartFailed.value = true;
  state.value = {status: 'complete', note: 'CDFW ds582 snapshot for this region, checked 2026-09-21.', detail: '', checked: '2026-09-21', count: 8};
  assert.match(render(h(Legend, {})), /<ul><li class="app-legend-mpa" data-mpa="complete">/);
  chartFailed.value = false;
});

test('FE-82: an area picked on the terrain fills the mark card in 2D and 3D, never on the Chart', async () => {
  const {MarkCard, currentMark, terrainPick, render, h, state: store} = await components();
  store.configureStore({v2: true, storage: null});
  store.syncFromURL(`${PAGE}?region=morro-bay&presentation=3d`);
  const area = mpaMark({NAME: 'Cambria SMCA', FULLNAME: 'Cambria State Marine Conservation Area', Type: 'SMCA', CCR: 'Section 632 (b) (95)', source: 'cdfw', checked: '2026-09-21'});
  terrainPick.value = area;
  assert.equal(currentMark.value, area);
  assert.match(render(h(MarkCard, {})), /<h2 tabindex="-1">Cambria State Marine Conservation Area<\/h2>/);
  store.syncFromURL(`${PAGE}?region=morro-bay&presentation=chart`);
  assert.equal(currentMark.value, null, 'the Chart shows its own selection');
  terrainPick.value = null;
});

test('the mark card turns Regulations into a link to the official page for an area, and keeps it disabled otherwise', async () => {
  const {MarkCard, render, h} = await components();
  const area = mpaMark({NAME: 'Morro Bay SMR', FULLNAME: 'Morro Bay State Marine Reserve', Type: 'SMR', CCR: 'Section 632 (b) (92)', source: 'cdfw', checked: '2026-09-21'});
  const html = render(h(MarkCard, {mark: area}));
  assert.match(html, new RegExp(`<a class="ui-button ui-button--ghost ui-button--sm" href="${CDFW_MPA_PAGE}" target="_blank" rel="noopener" aria-label="Regulations: CDFW marine protected areas \\(official page, opens in a new tab\\)">`));
  assert.match(html, /<p class="app-mark-kind">State Marine Reserve<\/p><p class="ui-reading">CCR Title 14, Section 632 \(b\) \(92\)<\/p><p class="app-mark-source ui-mono">CDFW ds582 · checked 2026-09-21<\/p>/);
  const shore = render(h(MarkCard, {mark: {id: 'c', name: 'Shoreline', kind: 'k', reading: 'r', source: 's', basis: 'b'}}));
  assert.match(shore, /<button disabled type="button" class="ui-button ui-button--ghost ui-button--sm">.*Regulations<\/button>/s);
});
