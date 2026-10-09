// Water temperature field and contours (FE-16, docs/plans/front-end/dev-plan.md):
// the texture of a packages/coast surface field (web/map/field.ts), the analysis
// gate, legend range and contours (web/map/sst.ts), and the Chart layer over a
// fake engine and a fake MapLibre, so no GPU, library or network is needed.
// Analyses are synthetic: a 0.02° grid off Morro Bay with a two-cell hole, in the
// coast report's `spatial.surfaceTemperature` shape. web/map/*.ts run by type
// stripping; the legend and rail are bundled with esbuild and rendered.
import assert from 'node:assert/strict';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {signal} from '@preact/signals';
import {build} from 'esbuild';
import {fieldColor, temperatureColors} from '../packages/coast/src/map/surface-field.ts';
import {FILES, themes} from '../scripts/check_contrast.mjs';
import {chartMark} from '../web/map/chart.ts';
import {createEngine} from '../web/map/engine.ts';
import {MAX_TEXTURE, TABLE_SIZE, colourTable, fieldTexture, textureSize} from '../web/map/field.ts';
import {railNotes} from '../web/map/layers.ts';
import {MPA_FILL} from '../web/map/mpa.ts';
import {ramps, readPalette} from '../web/map/palette.ts';
import {
  CONTOUR_LABELS, CONTOUR_LAYER, CONTOUR_SOURCE, MAX_AGE_MS, SST_LAYER, SST_SOURCE, WATER_TEMP_BASIS,
  analysisStatus, contourLines, createWaterTemp, sstMark, waterTempOverlay, waterTempState,
} from '../web/map/sst.ts';
import {surfaceField} from '../web/map/surface-field.js';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map', TZ = 'America/Los_Angeles', HOUR = 3_600_000;
const NOW = new Date('2026-10-09T03:00:00Z'), AT = new Date('2026-10-09T03:00:00Z');
const WEST = -121.0, SOUTH = 35.2, STEP = 0.02, COLS = 12, ROWS = 9;
const sentinel = readPalette(name => `token(${name})`);
/** One analysis sample per cell, 57.3 °F in the south-west corner to 63.8 °F in the north-east; `hole` drops cells. */
function points({hole = (i, j) => (i === 5 || i === 6) && j === 4, step = STEP} = {}) {
  const out = [];
  for (let j = 0; j < ROWS; j++) for (let i = 0; i < COLS; i++) {
    if (hole(i, j)) continue;
    out.push({lon: +(WEST + i * step).toFixed(6), lat: +(SOUTH + j * step).toFixed(6), tempF: 57.3 + i * 0.5 + j * 0.125, errorF: 0.4 + (i % 6) * 0.1});
  }
  return out;
}
const MUR = {id: 'mur-surface-temperature', label: 'NASA JPL MUR · surface temperature analysis', url: 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.csv', kind: 'analysis', outcome: 'ok', fetchedAt: '2026-10-09T02:17:42.000Z'};
const BLENDED = {...MUR, id: 'noaa-blended-sst', label: 'NOAA Geo-Polar Blended · surface temperature analysis'};
function report({sst = {}, source = MUR, generatedAt = '2026-10-09T02:20:00.000Z'} = {}) {
  return {schemaVersion: 1, countyId: 'slo', generatedAt, forecasts: [], observations: [], tides: [], tideEvents: [], alerts: [], catches: [], catchStatus: '',
    visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, habitatStatus: '', sources: source ? [source] : [],
    spatial: {surfaceTemperature: {sourceId: source?.id ?? MUR.id, analysedAt: '2026-10-07T09:00:00.000Z', fetchedAt: '2026-10-09T02:17:42.000Z',
      nativeResolutionDeg: 0.01, sampleSpacingDeg: STEP, points: points(), url: MUR.url, kind: 'analysis', ...sst}}};
}
const status = (r = report(), at = AT, now = NOW) => analysisStatus(true, 'ready', r, at, now, TZ);
const fieldOf = (pts = points()) => surfaceField(pts.map(p => ({lon: p.lon, lat: p.lat, values: [p.tempF, p.errorF]})), {step: [STEP, STEP]});

test('the token ramp equals packages/coast temperatureColors, in every theme', async () => {
  const css = await readFile(new URL('../web/tokens.css', import.meta.url), 'utf8');
  for (const [theme, colours] of Object.entries(themes(css, FILES['web/tokens.css']))) {
    const palette = readPalette(name => colours[name] ?? (name === 'mpa-fill-opacity' ? '0.08' : ''));
    assert.deepEqual(ramps(palette).sst, temperatureColors, `${theme}: --sst-0 … --sst-5 through palette.ts`);
  }
  assert.equal(temperatureColors.length, 6);
});

test('the texture paints exactly the field\'s support, in the ramp\'s colours, feathered inward at gaps', () => {
  const field = fieldOf(), range = [57, 64], tex = fieldTexture(field, range, temperatureColors, v => v[0]);
  const {width, height} = textureSize(field);
  assert.deepEqual([tex.width, tex.height], [width, height]);
  assert.ok(width <= MAX_TEXTURE && height <= MAX_TEXTURE && width >= 64);
  assert.equal(width, (COLS - 1) * 8, 'about eight pixels per source cell');
  assert.deepEqual(tex.coordinates, [[WEST, SOUTH + (ROWS - 1) * STEP], [WEST + (COLS - 1) * STEP, SOUTH + (ROWS - 1) * STEP], [WEST + (COLS - 1) * STEP, SOUTH], [WEST, SOUTH]].map(c => c.map(n => +n.toFixed(6))));
  const [west, south, east, north] = field.bounds, merc = l => Math.log(Math.tan(Math.PI / 4 + l * Math.PI / 360)), top = merc(north), bottom = merc(south);
  const table = colourTable(temperatureColors);
  let support = 0, blank = 0, feathered = 0;
  for (let y = 0; y < height; y++) {
    const lat = (2 * Math.atan(Math.exp(top - (y + 0.5) / height * (top - bottom))) - Math.PI / 2) * 180 / Math.PI;
    for (let x = 0; x < width; x++) {
      const v = field.sample(west + (x + 0.5) / width * (east - west), lat), i = (y * width + x) * 4;
      if (!v) { assert.equal(tex.data[i + 3], 0, `no colour outside the support at ${x},${y}`); blank++; continue; }
      support++;
      assert.ok(tex.data[i + 3] >= 128, 'supported pixels stay drawn');
      if (tex.data[i + 3] < 255) feathered++;
      const t = Math.round(Math.max(0, Math.min(1, (v[0] - range[0]) / (range[1] - range[0]))) * (TABLE_SIZE - 1)) * 3;
      assert.deepEqual([...tex.data.subarray(i, i + 3)], [...table.subarray(t, t + 3)], `the colour of field.sample at ${x},${y}`);
    }
  }
  assert.ok(support > 0 && blank > 0 && feathered > 0, 'the hole is blank and its edge fades');
  // The table is packages/coast fieldColor on the ramp.
  assert.deepEqual([...table.subarray(0, 3)], fieldColor(0, 0, 1, temperatureColors));
  assert.deepEqual([...table.subarray(-3)], fieldColor(1, 0, 1, temperatureColors));
  assert.deepEqual([...table.subarray(0, 3)], [0x24, 0x4f, 0x9d], '--sst-0 at the cold end');
});

test('the legend range is the rounded extrema of the accepted analysis; its product and age are named exactly', () => {
  const s = status();
  assert.deepEqual(s.drawn.range, [57, 64], '57.3 to 63.8 °F gives whole degrees 57 to 64');
  assert.deepEqual(s.drawn.error.map(e => +e.toFixed(2)), [0.4, 0.9]);
  assert.equal(s.drawn.product, 'NASA JPL MUR', 'from the report\'s own status for the source id');
  assert.equal(s.note, 'analysis Oct 7 · 42 h old');
  assert.equal(s.basis, 'NASA JPL MUR daily analysis on a 0.01° grid sampled every 0.02°, for Oct 7 (42 h old), with an analysis error of 0.4 °F to 0.9 °F. '
    + 'Surface water only, neither bottom temperature nor a forecast; masked land and missing cells stay blank.');
  const blended = status(report({source: BLENDED, sst: {nativeResolutionDeg: 0.05, sampleSpacingDeg: 0.05, points: points({step: 0.05})}}));
  assert.equal(blended.drawn.product, 'NOAA Geo-Polar Blended');
  assert.match(blended.basis, /^NOAA Geo-Polar Blended daily analysis on a 0\.05° grid, for Oct 7/);
  assert.match(WATER_TEMP_BASIS, /^[A-Z].+\.$/);
  assert.doesNotMatch(s.basis + WATER_TEMP_BASIS, /hotspot|bite|probab|catch/i);
});

test('nothing draws without a fresh, loaded, drawable analysis, and the reason is given', () => {
  const reason = r => [r.note, r.reason, r.drawn];
  assert.deepEqual(analysisStatus(false, 'ready', report(), AT, NOW, TZ), {drawn: null, note: '', reason: '', basis: WATER_TEMP_BASIS});
  assert.deepEqual(reason(analysisStatus(true, 'unbound', null, AT, NOW, TZ)), ['no analysis for this region', 'Water temp unavailable: no local surface-temperature analysis covers this region yet.', null]);
  assert.equal(analysisStatus(true, 'error', null, AT, NOW, TZ).note, 'unavailable');
  assert.equal(analysisStatus(true, 'expired', null, AT, NOW, TZ).note, 'expired');
  assert.equal(analysisStatus(true, 'loading', null, AT, NOW, TZ).note, 'loading');
  assert.equal(status(report({source: {...MUR, outcome: 'error'}})).note, 'no analysis in the report', 'a failed source');
  assert.equal(status(report({source: null})).note, 'no analysis in the report', 'an unnamed source');
  assert.equal(status({...report(), spatial: {}}).note, 'no analysis in the report');
  const late = new Date(Date.parse('2026-10-07T09:00:00Z') + MAX_AGE_MS);
  assert.deepEqual(reason(status(report(), late, late)), ['no fresh analysis · last Oct 7', 'Water temp unavailable: the latest NASA JPL MUR analysis, for Oct 7, is past its 72-hour age limit.', null]);
  assert.equal(status(report({sst: {fetchedAt: '2026-10-06T02:00:00.000Z'}})).note, 'no fresh analysis · last Oct 7', 'retrieved over 72 h ago');
  assert.equal(status(report(), new Date('2026-10-07T08:00:00Z')).note, 'analysis after this hour · Oct 7');
  const irregular = points().map((p, k) => (k === 7 ? {...p, lon: p.lon + 0.007} : p));
  assert.deepEqual(reason(status(report({sst: {points: irregular}}))), ['grid cannot be drawn · Oct 7',
    'Water temp unavailable: the NASA JPL MUR analysis for Oct 7 is not a grid that can be drawn without bridging gaps, and no earlier analysis is shown.', null]);
  assert.equal(status(report({sst: {points: points().map(p => ({...p, tempF: Number.NaN}))}})).note, 'grid cannot be drawn · Oct 7');
});

test('contours run every 0.5 °F, join into lines, label whole degrees with the unit and stop at the hole', () => {
  const field = fieldOf(), lines = contourLines(field, [57, 64]);
  const levels = [...new Set(lines.features.map(f => f.properties.level))].sort((a, b) => a - b);
  assert.ok(levels.every(l => l * 2 === Math.round(l * 2) && l > 57 && l < 64));
  assert.ok(levels.includes(60) && levels.includes(60.5));
  for (const f of lines.features) {
    assert.equal(f.properties.major, Number.isInteger(f.properties.level));
    assert.equal(f.properties.label, Number.isInteger(f.properties.level) ? `${f.properties.level} °F` : `${f.properties.level.toFixed(1)} °F`);
    for (const [lon, lat] of f.geometry.coordinates) assert.ok(field.sample(lon, lat) !== null || field.quads.some(q => lon >= q.west - 1e-9 && lon <= q.east + 1e-9 && lat >= q.south - 1e-9 && lat <= q.north + 1e-9), 'on a complete quad');
  }
  const sixty = lines.features.filter(f => f.properties.level === 60);
  assert.ok(sixty.some(f => f.geometry.coordinates.length > 4), 'segments are joined into lines');
  // The hole (columns 5–6, row 4) has no quad, so no contour crosses it.
  const inHole = ([lon, lat]) => lon > WEST + 4 * STEP + 1e-6 && lon < WEST + 7 * STEP - 1e-6 && lat > SOUTH + 3 * STEP + 1e-6 && lat < SOUTH + 5 * STEP - 1e-6;
  assert.ok(lines.features.every(f => !f.geometry.coordinates.some(inHole)));
});

test('the overlay sits under the protected areas, coloured from the palette; a click reads the analysis with its error', () => {
  const o = waterTempOverlay(sentinel);
  assert.deepEqual(o.layers.map(l => l.id), [SST_LAYER, CONTOUR_LAYER, CONTOUR_LABELS]);
  assert.deepEqual(Object.keys(o.sources), [SST_SOURCE, CONTOUR_SOURCE]);
  assert.equal(o.sources[SST_SOURCE].type, 'image');
  assert.equal(o.sources[SST_SOURCE].url, undefined, 'no request: the pixels come from setImage');
  assert.equal(o.layers[1].paint['line-color'], sentinel.text);
  assert.equal(o.layers[2].paint['text-color'], sentinel.text);
  assert.deepEqual(o.layers[2].filter, ['get', 'major'], 'labels on whole degrees only');
  const a = status().drawn;
  const mark = sstMark(a, {lon: WEST + 0.01, lat: SOUTH + 0.01}, NOW, TZ);
  assert.equal(mark.name, 'Surface temperature');
  assert.equal(mark.kind, 'Daily analysis · Oct 7');
  assert.equal(mark.reading, '57.6 °F · analysis error 0.5 °F');
  assert.equal(mark.source, 'NASA JPL MUR · analysis Oct 7 · 42 h old');
  assert.match(mark.basis, /neither bottom temperature nor a forecast; .* Display interpolation between adjacent ocean samples, which adds no measurements\.$/);
  assert.equal(sstMark(a, {lon: WEST + 5.5 * STEP, lat: SOUTH + 4 * STEP}, NOW, TZ), null, 'the hole reads nothing');
  assert.equal(sstMark(a, {lon: WEST - 0.1, lat: SOUTH}, NOW, TZ), null);
});

/** A browser just big enough for navigate() (as tests/test_clouds_layer.mjs). */
function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}
/** An engine that records what the layer drew. */
function engine() {
  const e = {overlay: null, before: null, images: [], data: []};
  return Object.assign(e, {
    setOverlay(layer, overlay, before) { assert.equal(layer, 'water-temp'); e.overlay = overlay; e.before = before; },
    setImage(id, texture) { e.images.push([id, texture]); },
    setData(id, data) { e.data.push([id, data]); },
    setRasterOpacity() {}, setCamera() {}, setVisible() {}, destroy() {},
  });
}
function layer(t, {href = `${PAGE}?region=morro-bay&layers=water-temp`, first = report(), live = null} = {}) {
  t.mock.timers.enable({apis: ['setTimeout']});
  browser(href);
  const e = engine(), asked = [];
  const data = {coastReport: signal({data: first}), coastStatus: signal({report: 'ready', ocean: 'idle', history: 'idle'}),
    setPlace: p => asked.push(['place', p.regionId]), load: async product => { asked.push(['load', product]); }};
  const w = createWaterTemp({engine: live ?? signal(e), zone: () => TZ, place: () => ({regionId: 'morro-bay'}), data, palette: () => sentinel, now: () => NOW});
  t.after(() => w.destroy());
  return {w, e, data, asked};
}

test('a rejected replacement grid hides the previous texture and contours', t => {
  const {w, e, data, asked} = layer(t);
  assert.deepEqual(asked, [['place', 'morro-bay'], ['load', 'report']], 'the report is asked for while Water temp is on');
  assert.deepEqual(e.overlay.layers.map(l => l.id), [SST_LAYER, CONTOUR_LAYER, CONTOUR_LABELS]);
  assert.equal(e.before, MPA_FILL, 'under the protected areas (§ 9 order)');
  assert.equal(e.images.length, 1);
  assert.equal(e.images[0][0], SST_SOURCE);
  assert.ok(e.data.some(([id, d]) => id === CONTOUR_SOURCE && d.features.length > 0));
  assert.deepEqual(waterTempState.value.drawn.range, [57, 64]);
  assert.equal(railNotes.value['water-temp'], 'analysis Oct 7 · 42 h old');
  chartMark.value = w.reading({lon: WEST + 0.01, lat: SOUTH + 0.01});
  assert.equal(chartMark.value.name, 'Surface temperature');

  // The next report carries a grid the surface field refuses.
  const refused = report({generatedAt: '2026-10-09T03:20:00.000Z', sst: {analysedAt: '2026-10-08T09:00:00.000Z', points: points().map((p, k) => (k === 3 ? {...p, lat: p.lat + 0.006} : p))}});
  data.coastReport.value = {data: refused};
  assert.equal(e.overlay, null, 'the texture, contours and labels are removed');
  assert.equal(e.images.length, 1, 'no texture is painted for the refused grid');
  assert.equal(waterTempState.value.drawn, null);
  assert.equal(waterTempState.value.note, 'grid cannot be drawn · Oct 8');
  assert.equal(chartMark.value, null, 'a reading of the withdrawn analysis goes with it');
  assert.equal(w.reading({lon: WEST + 0.01, lat: SOUTH + 0.01}), null);

  data.coastReport.value = {data: report({sst: {analysedAt: '2026-10-08T09:00:00.000Z'}})};
  assert.equal(e.images.length, 2, 'a good analysis paints again');
  setParams({layers: 'none'});
  assert.equal(e.overlay, null, 'off removes it');
  assert.equal(railNotes.value['water-temp'], '');
});

test('the engine adds the image source without a request and replaces its pixels; a removed overlay leaves nothing', () => {
  const maps = [];
  class FakeMap {
    constructor(options) { this.handlers = {}; this.sources = {}; this.layers = options.style.layers.map(l => l.id); this.images = []; this.keyboard = this.touchZoomRotate = {disableRotation() {}}; maps.push(this); }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type) { for (const fn of this.handlers[type] ?? []) fn({}); }
    addControl() {}
    getLayer(id) { return this.layers.includes(id) ? {} : undefined; }
    getSource(id) { return this.sources[id]; }
    addSource(id, spec) { const map = this; this.sources[id] = {spec, updateImage(o) { map.images.push([id, o]); }, setData(d) { this.data = d; }}; }
    removeSource(id) { delete this.sources[id]; }
    addLayer(l, before) { const i = before ? this.layers.indexOf(before) : -1; this.layers.splice(i < 0 ? this.layers.length : i, 0, l.id); }
    removeLayer(id) { this.layers = this.layers.filter(l => l !== id); }
    remove() {}
  }
  const control = class {}, module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  const eng = createEngine(module, {host: {}, style: {version: 8, sources: {}, layers: [{id: 'water'}, {id: MPA_FILL}, {id: 'coastline'}]},
    camera: {latitude: 35.3, longitude: -120.9, zoom: 10}, onMove() {}, onLayerError() {}});
  const [map] = maps, a = status().drawn, tex = fieldTexture(a.field, a.range, temperatureColors, v => v[0]);
  eng.setOverlay('water-temp', waterTempOverlay(sentinel), MPA_FILL);
  eng.setImage(SST_SOURCE, tex);
  assert.deepEqual(map.images, [], 'nothing before the style has loaded');
  map.fire('style.load');
  assert.deepEqual(map.layers, ['water', SST_LAYER, CONTOUR_LAYER, CONTOUR_LABELS, MPA_FILL, 'coastline']);
  assert.equal(map.images.length, 1);
  assert.equal(map.images[0][1].image.data, tex.data, 'the pixels, not a URL');
  assert.deepEqual(map.images[0][1].coordinates, tex.coordinates);
  eng.setImage(SST_SOURCE, tex);
  assert.equal(map.images.length, 2, 'later textures apply at once');
  eng.setOverlay('water-temp', null);
  assert.deepEqual(map.layers, ['water', MPA_FILL, 'coastline']);
  assert.deepEqual(Object.keys(map.sources), []);
});

test('the legend gives the range, product and age with the basis; the rail gives the analysis date or why nothing draws', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'sst-')), 'legend.mjs');
  await build({
    stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {Legend} from './web/app/Legend.tsx';
      export {LayerRail} from './web/app/LayerRail.tsx';
      export {waterTempState} from './web/map/sst.ts';
      export {railNotes} from './web/map/layers.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}],
  });
  const m = await import(pathToFileURL(out).href);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(`${PAGE}?region=morro-bay&layers=water-temp`);
  m.waterTempState.value = status();
  m.railNotes.value = {'water-temp': 'analysis Oct 7 · 42 h old'};
  const legend = m.render(m.h(m.Legend));
  assert.match(legend, /<span class="app-swatch" data-layer="water-temp" aria-hidden="true"><\/span>Water temp<span class="app-legend-range ui-mono" data-range="water-temp">57–64 °F<\/span>/);
  assert.match(legend, /data-stamp="water-temp">NASA JPL MUR · analysis Oct 7 · 42 h old</);
  assert.match(legend, /NASA JPL MUR daily analysis on a 0\.01° grid sampled every 0\.02°/);
  assert.match(m.render(m.h(m.LayerRail)), /Water temp<\/span><span class="ui-rail-note ui-mono">analysis Oct 7 · 42 h old<\/span>/);
  m.waterTempState.value = analysisStatus(true, 'unbound', null, AT, NOW, TZ);
  const none = m.render(m.h(m.Legend));
  assert.doesNotMatch(none, /data-range/);
  assert.match(none, /data-reason="water-temp">Water temp unavailable: no local surface-temperature analysis covers this region yet\.</);
});
