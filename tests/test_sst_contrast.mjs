// CI6-03: Temp contrast. web/map/habitat-feed.ts `regionalContrast` reads the region's published
// surface-temperature analysis with its two gradient fields; web/map/contrast.ts draws only the cells
// the pipeline flags supported (src/skippercast/pipeline/habitat_dynamics.py `gradients`) whose change
// across neighbouring cells, checked again here, exceeds their summed analysis error, and withholds the
// layer past 72 hours. The feed here is synthetic, in the pipeline's shape, with the pipeline's rule.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {signal} from '@preact/signals';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {chartMark} from '../web/map/chart.ts';
import {
  CONTRAST_BASIS, CONTRAST_LAYER, CONTRAST_SCALE, F_PER_NMI, MAX_AGE_MS, contrastCells, contrastFeatures, contrastMark, contrastOverlay, contrastState,
  contrastStatus, createContrast,
} from '../web/map/contrast.ts';
import {DEPTH_BOTTOM, contoursOverlay} from '../web/map/depth-contours.ts';
import {windOverlay} from '../web/map/wind.ts';
import {createEngine} from '../web/map/engine.ts';
import {regionalContrast} from '../web/map/habitat-feed.ts';
import {CONTRAST_SOURCE, LAYERS, layerEntry, railNotes} from '../web/map/layers.ts';
import {MPA_FILL} from '../web/map/mpa.ts';
import {readPalette} from '../web/map/palette.ts';
import {CONTOUR_LABELS, CONTOUR_LAYER, SST_LAYER, waterTempOverlay} from '../web/map/sst.ts';
import {ISOLINE_LABELS, ISOLINE_LAYER, STROKE_CASING, STROKE_LAYER, SWELL_LAYER, swellOverlay} from '../web/map/swell.ts';
import {PROFILE_TABLE, RAIL_IDS} from '../web/profile.ts';
import {configureStore, layers, setParams, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map', TZ = 'America/Los_Angeles', REGION = 'test-coast', HOUR = 3_600_000;
const SAMPLE_AT = '2026-10-15T12:00:00Z', TIME = Date.parse(SAMPLE_AT) / 1000, RETRIEVED = '2026-10-16T06:00:00Z';
const NOW = new Date('2026-10-16T12:00:00Z'), AT = NOW;
const FIELDS = ['latitude', 'longitude', 'temperature_c', 'analysis_error_c', 'temperature_gradient_c_per_km', 'thermal_contrast_supported'];
const BASE = `${PAGE.replace('/map', '')}/feeds/conditions/regions/${REGION}/`;
const STEP = 0.05, ERROR = 0.3;
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const sentinel = readPalette(name => `token(${name})`);
const lat = j => +(35.025 + j * STEP).toFixed(3), lon = i => +(-120.975 + i * STEP).toFixed(3);

/**
 * 5 × 5 cells 0.05° apart. Columns 0–2 are 14 °C and columns 3–4 15.5 °C (a 1.5 °C step against a summed error of
 * 0.6 °C), so only the interior cells beside the step, columns 2 and 3 of rows 1–3, are supported.
 * Gradient and flag follow habitat_dynamics.py `gradients`; `flag` may overwrite a cell's flag.
 */
function rows({temp = (i, j) => (i >= 3 ? 15.5 : 14) + j * 0.01, error = () => ERROR, flag = () => undefined} = {}) {
  const t = new Map(), e = new Map(), k = (i, j) => `${i},${j}`;
  for (let j = 0; j < 5; j++) for (let i = 0; i < 5; i++) { t.set(k(i, j), temp(i, j)); e.set(k(i, j), error(i, j)); }
  const out = [];
  for (let j = 0; j < 5; j++) for (let i = 0; i < 5; i++) {
    const n = [[i - 1, j], [i + 1, j], [i, j - 1], [i, j + 1]].map(([a, b]) => k(a, b));
    let gradient = null, supported = null;
    if (n.every(x => t.get(x) !== undefined && t.get(x) !== null)) {
      const [w, east, s, north] = n.map(x => t.get(x));
      const gx = (east - w) / (2 * STEP * 111.195 * Math.cos(lat(j) * Math.PI / 180)), gy = (north - s) / (2 * STEP * 111.195);
      gradient = +Math.hypot(gx, gy).toFixed(5);
      if (n.every(x => e.get(x) !== null)) {
        const [ew, ee, es, en] = n.map(x => e.get(x));
        supported = Math.abs(east - w) > ee + ew || Math.abs(north - s) > en + es ? 1 : 0;
      }
    }
    const f = flag(i, j);
    out.push([lat(j), lon(i), t.get(k(i, j)), e.get(k(i, j)), gradient, f === undefined ? supported : f]);
  }
  return out;
}

/** The manifest and two tiles (columns 0–2 and 3–4) in the pipeline's shape. */
function feed({cells = rows(), fields = FIELDS, status = 'ok', maxAge = 72, sampleAt = SAMPLE_AT, retrieved = RETRIEVED, record = r => r} = {}) {
  const width = fields.length;
  const tiles = [[-121.0, 35.0, -120.85, 35.25], [-120.85, 35.0, -120.75, 35.25]].map((bounds, k) => {
    const mine = cells.filter(c => (k === 0 ? c[1] < -120.85 : c[1] > -120.85)).map(c => c.slice(0, width));
    const body = {schema_version: 1, region_id: REGION, layer_id: 'sst-analysis', bounds, resolution_degrees: [STEP, STEP], fields, frames: [{time: TIME, cells: mine}]};
    const bytes = Buffer.from(JSON.stringify(body));
    return {bytes, record: record({path: `habitat-tiles/sst-analysis-${k}-0-${sha(bytes).slice(0, 16)}.json`, bounds, sha256: sha(bytes), bytes: bytes.length}, k)};
  });
  const manifest = {schema_version: 1, region_id: REGION,
    layers: {'sst-analysis': {id: 'sst-analysis', kind: 'analysis', sample_at: sampleAt, resolution_degrees: [STEP, STEP], fields, status, max_age_hours: maxAge,
      native_stride: 1, source_id: 'noaa-blended-sst', frames: [{time: Date.parse(sampleAt) / 1000, valid_cells: 25, total_cells: 25}], tiles: tiles.map(t => t.record)}},
    sources: {'sst-analysis': {id: 'sst-analysis', name: 'NOAA Geo-Polar Blended night SST, 5 km', kind: 'analysis',
      url: 'https://coastwatch.noaa.gov/cwn/products/noaa-geo-polar-blended-global-sea-surface-temperature-analysis-level-4.html',
      max_age_hours: maxAge, status, data_retrieved_at: retrieved, rights: {license: 'public-domain', attribution: 'NOAA CoastWatch / OSPO'}}}};
  return {manifest, tiles};
}
function server({manifest, tiles}) {
  const asked = [];
  const fetchFn = async url => {
    asked.push(url);
    if (url === `${BASE}habitat-dynamics.json`) return Response.json(manifest);
    const t = tiles.find(t => url === BASE + t.record.path);
    return t ? new Response(t.bytes) : new Response('Not found', {status: 404});
  };
  return {fetchFn, asked};
}
const read = (f, now = NOW) => regionalContrast(REGION, {fetchFn: server(f).fetchFn, page: PAGE, now});
const where = cells => cells.map(c => [c.lon, c.lat]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
const SUPPORTED = [2, 3].flatMap(i => [1, 2, 3].map(j => [lon(i), lat(j)]));

test('Step 0 shape: the feed\'s analysis with both gradient fields loads, checked, as open-water samples', async () => {
  const got = await read(feed());
  assert.equal(got.state, 'ready');
  const {samples, ...rest} = got;
  assert.deepEqual(rest, {state: 'ready', product: 'NOAA Geo-Polar Blended night SST', sourceId: 'noaa-blended-sst', analysedAt: '2026-10-15T12:00:00.000Z',
    fetchedAt: RETRIEVED, maxAgeMs: 72 * HOUR, spacingDeg: [STEP, STEP], nativeResolutionDeg: STEP, credit: 'NOAA CoastWatch / OSPO',
    url: 'https://coastwatch.noaa.gov/cwn/products/noaa-geo-polar-blended-global-sea-surface-temperature-analysis-level-4.html'});
  assert.equal(samples.length, 25);
  assert.deepEqual(samples.filter(s => s.supported === 1).length, 6);
  assert.ok(samples.filter(s => s.supported === null).every(s => s.gradientCPerKm === null), 'edge cells carry no gradient');

  const noGradient = await read(feed({fields: FIELDS.slice(0, 4)}));
  assert.deepEqual(noGradient, {state: 'listed', product: 'NOAA Geo-Polar Blended night SST', analysedAt: '2026-10-15T12:00:00.000Z', maxAgeMs: 72 * HOUR, layerStatus: 'ok', gradients: false});
  assert.equal((await read(feed({record: (r, k) => (k ? {...r, sha256: 'f'.repeat(64)} : r)}))).state, 'error', 'one failed tile refuses the layer');
  const stale = server(feed());
  assert.equal((await regionalContrast(REGION, {fetchFn: stale.fetchFn, page: PAGE, now: new Date(Date.parse(SAMPLE_AT) + 72 * HOUR)})).state, 'listed');
  assert.equal(stale.asked.length, 1, 'past its age limit no tile is fetched');
});

test('only supported cells draw: a change within the summed analysis error never draws, whatever its flag', async () => {
  const ready = await read(feed());
  assert.deepEqual(where(contrastCells(ready.samples, ready.spacingDeg)), SUPPORTED);
  const c = contrastCells(ready.samples, ready.spacingDeg)[0];
  assert.ok(Math.abs(c.fPerNmi - c.cPerKm * 1.8 * 1.852) < 1e-12 && F_PER_NMI === 1.8 * 1.852, '°F per nautical mile from °C per km');

  // A cell flagged supported whose neighbours change by less than their summed error (column 1), one whose
  // neighbour has no error, and a strong gradient flagged 0: none of them draws.
  const tampered = await read(feed({cells: rows({error: (i, j) => (i === 0 && j === 1 ? null : ERROR),
    flag: (i, j) => (i === 1 && (j === 2 || j === 1) ? 1 : i === 2 && j === 3 ? 0 : undefined)})}));
  assert.deepEqual(where(contrastCells(tampered.samples, tampered.spacingDeg)), SUPPORTED.filter(([x, y]) => !(x === lon(2) && y === lat(3))));
  // A step of 0.5 °C against the same 0.6 °C summed error: a gradient, and nothing drawn.
  const weak = await read(feed({cells: rows({temp: (i, j) => (i >= 3 ? 14.5 : 14) + j * 0.01})}));
  assert.ok(weak.samples.some(s => s.gradientCPerKm > 0));
  assert.deepEqual(contrastCells(weak.samples, weak.spacingDeg), []);
  const status = contrastStatus(true, weak, AT, NOW, TZ);
  assert.equal(status.drawn, null);
  assert.equal(status.note, 'no contrast above the error · Oct 15');
  assert.equal(status.reason, 'Nothing drawn: in the NOAA Geo-Polar Blended night SST analysis for Oct 15, no cell\'s change across neighbouring cells exceeds their summed analysis error.');
});

test('the withhold rule: past 72 hours, past the layer\'s own shorter limit, a stale retrieval or a later analysis draws nothing', async () => {
  const ready = await read(feed());
  const drawn = contrastStatus(true, ready, AT, NOW, TZ);
  assert.equal(drawn.note, 'analysis Oct 15 · 24 h old');
  assert.equal(drawn.drawn.limitMs, MAX_AGE_MS);
  const withheld = 'Temp contrast withheld: the latest NOAA Geo-Polar Blended night SST analysis, for Oct 15, is past its 72-hour age limit.';
  const past = new Date(Date.parse(SAMPLE_AT) + 72 * HOUR);
  assert.deepEqual([contrastStatus(true, ready, AT, past, TZ).drawn, contrastStatus(true, ready, AT, past, TZ).reason], [null, withheld]);
  assert.ok(contrastStatus(true, ready, AT, new Date(past.getTime() - 60_000), TZ).drawn, 'a minute inside the limit it still draws');

  // A layer that names 96 hours is still withheld at 72.
  const long = await read(feed({maxAge: 96}), past);
  assert.equal(long.state, 'ready', 'the feed reads it inside its own 96 hours');
  assert.equal(contrastStatus(true, long, AT, past, TZ).reason, withheld);
  // A layer that names 48 hours is withheld at 48.
  const short = await read(feed({maxAge: 48}));
  assert.equal(contrastStatus(true, short, AT, new Date(Date.parse(SAMPLE_AT) + 48 * HOUR), TZ).note, 'no fresh analysis · last Oct 15');
  // The retrieval is judged too, and an analysis later than the selected hour waits.
  const oldFetch = await read(feed({retrieved: '2026-10-12T06:00:00Z'}));
  assert.equal(contrastStatus(true, oldFetch, AT, NOW, TZ).drawn, null);
  assert.equal(contrastStatus(true, ready, new Date('2026-10-15T11:00:00Z'), NOW, TZ).note, 'analysis after this hour · Oct 15');
  // Listed layers: stale, no gradient fields, missing feed, failed feed, off.
  const listed = {state: 'listed', product: 'NOAA Geo-Polar Blended night SST', analysedAt: '2026-10-15T12:00:00.000Z', maxAgeMs: 72 * HOUR, gradients: true};
  assert.equal(contrastStatus(true, {...listed, layerStatus: 'stale'}, AT, NOW, TZ).reason, withheld);
  assert.equal(contrastStatus(true, {...listed, layerStatus: 'ok', gradients: false}, AT, NOW, TZ).reason,
    'Temp contrast unavailable: the region\'s surface-temperature analysis publishes no temperature gradient.');
  assert.equal(contrastStatus(true, {state: 'none'}, AT, NOW, TZ).note, 'no analysis for this region');
  assert.equal(contrastStatus(true, {state: 'error'}, AT, NOW, TZ).note, 'unavailable');
  assert.equal(contrastStatus(true, null, AT, NOW, TZ).note, 'loading');
  assert.deepEqual(contrastStatus(false, ready, AT, NOW, TZ), {drawn: null, note: '', reason: '', basis: CONTRAST_BASIS});
});

test('the basis names product, grid and age, the support rule and what the field is not; the registry entry carries the card', async () => {
  const s = contrastStatus(true, await read(feed()), AT, NOW, TZ);
  assert.equal(s.basis, 'NOAA Geo-Polar Blended night SST daily analysis on a 0.05° grid, for Oct 15 (24 h old), partly interpolated, with gaps under cloud filled. '
    + 'Drawn in °F per nautical mile only in the 6 of 9 cells where the change across neighbouring cells exceeds their summed analysis error, '
    + 'and withheld past its 72-hour age limit. Surface water only; a contrast cell is not a fish or catch location. Credit: NOAA CoastWatch / OSPO.');
  const e = layerEntry('sst-contrast');
  for (const phrase of ['daily sea-surface temperature analysis', 'partly interpolated', 'gaps under cloud filled', 'summed analysis error', 'product, grid and age',
    '72-hour age limit', 'Surface water only', 'not a fish or catch location']) assert.ok(e.basis.includes(phrase), phrase);
  assert.doesNotMatch(`${e.basis} ${s.basis} ${e.legend.map(l => l.label).join(' ')}`, /hotspot|feeding|bite|fish presence|productive/i);
  assert.deepEqual([e.control, e.presentations, e.time, e.sources, e.attribution], ['sst-contrast', ['chart'], ['observed'], [CONTRAST_SOURCE], 'NOAA CoastWatch SST analysis']);
  assert.match(e.legend[0].label, /°F per nautical mile/);
  const ids = LAYERS.map(l => l.id);
  assert.equal(ids.indexOf('sst-contrast'), ids.indexOf('water-temp-contours') + 1, '§ 9: above Water temp, under Swell');
  assert.equal(ids.indexOf('swell'), ids.indexOf('sst-contrast') + 1);
  assert.ok(RAIL_IDS.includes('sst-contrast'));
  for (const p of Object.values(PROFILE_TABLE)) assert.ok(!p.defaultLayers.includes('sst-contrast'), `off by default for ${p.id}`);
});

test('each drawn cell is its own grid square on the fixed °F per nautical mile scale; a click inside one reads it', async () => {
  const s = contrastStatus(true, await read(feed()), AT, NOW, TZ), d = s.drawn;
  const fc = contrastFeatures(d);
  assert.equal(fc.features.length, 6);
  const first = fc.features.find(f => f.geometry.coordinates[0][0][0] === lon(2) - STEP / 2 && f.geometry.coordinates[0][0][1] === lat(1) - STEP / 2);
  assert.ok(first, 'the square spans the cell, half a step each side');
  assert.deepEqual(first.geometry.coordinates[0][2], [lon(2) + STEP / 2, lat(1) + STEP / 2]);
  const overlay = contrastOverlay(sentinel);
  assert.deepEqual(overlay.layers.map(l => [l.id, l.type, l.source]), [[CONTRAST_LAYER, 'fill', CONTRAST_SOURCE]]);
  assert.deepEqual(overlay.layers[0].paint['fill-color'], ['interpolate', ['linear'], ['get', 'f'], 0, 'token(contrast-0)', 0.15, 'token(contrast-1)', 0.3, 'token(contrast-2)']);
  assert.deepEqual(CONTRAST_SCALE, [0, 0.3]);
  const mark = contrastMark(d, {lon: lon(3) + 0.01, lat: lat(2) - 0.01}, NOW, TZ);
  assert.equal(mark.name, 'Temperature contrast');
  assert.match(mark.reading, /^\d\.\d\d °F per nautical mile \(0\.\d{3} °C per km\)$/);
  assert.equal(mark.source, 'NOAA Geo-Polar Blended night SST · analysis Oct 15 · 24 h old');
  assert.equal(contrastMark(d, {lon: lon(1), lat: lat(2)}, NOW, TZ), null, 'an unsupported cell reads nothing');
});

test('the committed Morro Bay copy (JPL MUR, 0.01°) reads and checks; across two MUR cells no change beats the summed error, so nothing draws', async () => {
  const root = new URL('../dist/regions/morro-bay/', import.meta.url), base = `${PAGE.replace('/map', '')}/feeds/conditions/regions/morro-bay/`;
  const fetchFn = async url => {
    if (!url.startsWith(base)) return new Response('Not found', {status: 404});
    try { return new Response(await readFile(new URL(url.slice(base.length), root))); } catch { return new Response('Not found', {status: 404}); }
  };
  // An hour after the copy's retrieval, about 57 hours after its analysis.
  const manifest = JSON.parse(await readFile(new URL('habitat-dynamics.json', root), 'utf8')), at = new Date(Date.parse(manifest.sources['sst-analysis'].data_retrieved_at) + HOUR);
  const got = await regionalContrast('morro-bay', {fetchFn, page: PAGE, now: at});
  assert.equal(got.state, 'ready');
  assert.equal(got.product, 'JPL MUR sea surface temperature analysis');
  assert.deepEqual(got.spacingDeg, [0.01, 0.01]);
  assert.ok(got.samples.length > 8000 && got.samples.every(s => s.supported !== 1));
  const s = contrastStatus(true, got, at, at, TZ);
  assert.equal(s.drawn, null);
  assert.match(s.note, /^no contrast above the error · /);
});

function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}
async function until(done) { for (const end = Date.now() + 5000; !done() && Date.now() < end;) await new Promise(resolve => setTimeout(resolve, 5)); }

test('off by default; on, it reads the feed once an hour and draws; off again or stale, it withdraws', async t => {
  browser(`${PAGE}?region=${REGION}`);
  assert.ok(!layers.value.includes('sst-contrast'), 'the default rail leaves it off');
  setParams({layers: 'none'});
  const e = {overlay: undefined, before: null, data: []};
  Object.assign(e, {setOverlay(layer, overlay, before) { assert.equal(layer, 'sst-contrast'); e.overlay = overlay; e.before = before; },
    setData(id, d) { e.data.push([id, d]); }, setImage() {}, setVisible() {}, setRasterOpacity() {}, setCamera() {}, destroy() {}});
  const s = server(feed());
  let now = NOW;
  const c = createContrast({engine: signal(e), zone: () => TZ, place: () => ({regionId: REGION}), palette: () => sentinel, now: () => now, fetchFn: s.fetchFn, page: () => PAGE});
  t.after(() => c.destroy());
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(s.asked, [], 'nothing is read while it is off');

  setParams({layers: 'sst-contrast'});
  assert.equal(railNotes.value['sst-contrast'], 'loading');
  await until(() => contrastState.value.drawn);
  assert.equal(s.asked.length, 3, 'the manifest and its two tiles');
  assert.equal(railNotes.value['sst-contrast'], 'analysis Oct 15 · 24 h old');
  assert.deepEqual(e.before, [SWELL_LAYER, 'wind-casing', DEPTH_BOTTOM, MPA_FILL]);
  assert.deepEqual(e.data.at(-1)[0], CONTRAST_SOURCE);
  assert.equal(e.data.at(-1)[1].features.length, 6);
  chartMark.value = c.reading({lon: lon(2), lat: lat(2)});
  assert.ok(chartMark.value?.id.startsWith('sst-contrast:'));

  setParams({layers: 'none'});
  assert.equal(e.overlay, null, 'off removes the cells');
  assert.equal(chartMark.value, null, 'and its card');
  setParams({layers: 'sst-contrast'});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.asked.length, 3, 'read once within the hour');
  assert.ok(e.overlay);

  now = new Date(Date.parse(SAMPLE_AT) + 72 * HOUR + 1000);
  setParams({hour: '2026-10-18T12:00Z'});   // any re-judge; the timer would do the same at the limit
  await until(() => !contrastState.value.drawn);
  assert.equal(e.overlay, null, 'past 72 hours the cells are withdrawn');
  assert.equal(railNotes.value['sst-contrast'], 'no fresh analysis · last Oct 15');
});

test('in the stack Temp contrast sits over Water temp and under swell, wind and depth contours, whichever is drawn first', () => {
  const maps = [];
  class FakeMap {
    constructor(options) { this.handlers = {}; this.sources = {}; this.layers = options.style.layers.map(l => l.id); this.keyboard = this.touchZoomRotate = {disableRotation() {}}; maps.push(this); }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type) { for (const fn of this.handlers[type] ?? []) fn({}); }
    addControl() {}
    getLayer(id) { return this.layers.includes(id) ? {} : undefined; }
    getSource(id) { return this.sources[id]; }
    addSource(id, spec) { this.sources[id] = {spec, updateImage() {}, setData() {}}; }
    removeSource(id) { delete this.sources[id]; }
    addLayer(l, before) { const i = before ? this.layers.indexOf(before) : -1; this.layers.splice(i < 0 ? this.layers.length : i, 0, l.id); }
    removeLayer(id) { this.layers = this.layers.filter(l => l !== id); }
    remove() {}
  }
  const control = class {}, module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  const sst = [SST_LAYER, CONTOUR_LAYER, CONTOUR_LABELS], swell = [SWELL_LAYER, ISOLINE_LAYER, ISOLINE_LABELS, STROKE_CASING, STROKE_LAYER];
  // The production `before` lists (sst, contrast, swell, wind, depth-contours), in every arrival order.
  const contours = contoursOverlay(sentinel, {type: 'FeatureCollection', features: []}), contourIds = contours.layers.map(l => l.id);
  const wind = windOverlay(sentinel), windIds = wind.layers.map(l => l.id);
  const draw = {
    sst: eng => eng.setOverlay('water-temp', waterTempOverlay(sentinel), [CONTRAST_LAYER, SWELL_LAYER, 'wind-casing', DEPTH_BOTTOM, MPA_FILL]),
    contrast: eng => eng.setOverlay('sst-contrast', contrastOverlay(sentinel), [SWELL_LAYER, 'wind-casing', DEPTH_BOTTOM, MPA_FILL]),
    swell: eng => eng.setOverlay('swell', swellOverlay(sentinel), ['wind-casing', DEPTH_BOTTOM, MPA_FILL]),
    wind: eng => eng.setOverlay('wind', wind, [DEPTH_BOTTOM, MPA_FILL]),
    contours: eng => eng.setOverlay('depth-contours', contours, MPA_FILL),
  };
  const permutations = xs => xs.length < 2 ? [xs] : xs.flatMap((x, i) => permutations([...xs.slice(0, i), ...xs.slice(i + 1)]).map(rest => [x, ...rest]));
  const orders = permutations(Object.keys(draw));
  assert.equal(orders.length, 120);
  for (const order of orders) {
    const eng = createEngine(module, {host: {}, style: {version: 8, sources: {}, layers: [{id: 'water'}, {id: MPA_FILL}, {id: 'coastline'}]},
      camera: {latitude: 35.3, longitude: -120.9, zoom: 10}, onMove() {}, onLayerError() {}});
    const map = maps.at(-1);
    map.fire('style.load');
    for (const which of order) draw[which](eng);
    assert.deepEqual(map.layers, ['water', ...sst, CONTRAST_LAYER, ...swell, ...windIds, ...contourIds, MPA_FILL, 'coastline'], order.join(' then '));
  }
});

test('the legend gives the fixed scale in °F per nautical mile, the product and age, or why nothing draws; the rail lists the entry', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'contrast-')), 'legend.mjs');
  await build({
    stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {Legend} from './web/app/Legend.tsx';
      export {LayerRail} from './web/app/LayerRail.tsx';
      export {contrastState} from './web/map/contrast.ts';
      export {railNotes} from './web/map/layers.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  const m = await import(pathToFileURL(out).href);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(`${PAGE}?region=morro-bay&layers=sst-contrast`);
  m.contrastState.value = contrastStatus(true, await read(feed()), AT, NOW, TZ);
  m.railNotes.value = {'sst-contrast': 'analysis Oct 15 · 24 h old'};
  const legend = m.render(m.h(m.Legend));
  assert.match(legend, /data-scale="sst-contrast">0<span class="app-swatch" data-layer="sst-contrast" aria-hidden="true"><\/span><span class="app-visually-hidden"> to <\/span>0\.3\+ °F per nautical mile</);
  assert.match(legend, /data-stamp="sst-contrast">NOAA Geo-Polar Blended night SST · analysis Oct 15 · 24 h old</);
  assert.match(legend, /not a fish or catch location/);
  assert.match(m.render(m.h(m.LayerRail)), /Temp contrast<\/span><span class="ui-rail-note ui-mono">analysis Oct 15 · 24 h old<\/span>/);
  m.contrastState.value = contrastStatus(true, {state: 'listed', product: 'NOAA Geo-Polar Blended night SST', analysedAt: '2026-10-15T12:00:00.000Z', maxAgeMs: 72 * HOUR, layerStatus: 'stale', gradients: true}, AT, NOW, TZ);
  const none = m.render(m.h(m.Legend));
  assert.doesNotMatch(none, /data-scale="sst-contrast"/);
  assert.match(none, /data-reason="sst-contrast">Temp contrast withheld: the latest NOAA Geo-Polar Blended night SST analysis, for Oct 15, is past its 72-hour age limit\.</);
});
