// SST-B visible-water selection and the band-null repaint (MSKL-2 checkpoint fix, web/map/sst.ts).
// Fake engine and synthetic 0.02° analysis (as tests/test_field_texture.mjs); no GPU, library or network.
import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {mercatorDisplay, sampleDisplay, textureSize} from '../web/map/field.ts';
import {readPalette} from '../web/map/palette.ts';
import {createWaterTemp, SST_SOURCE, visibleSamples, waterTempState} from '../web/map/sst.ts';
import {SST_BAND_SOURCE} from '../web/map/sst-bands.ts';
import {surfaceField} from '../web/map/surface-field.js';
import {configureStore, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map', TZ = 'America/Los_Angeles';
const NOW = new Date('2026-10-09T03:00:00Z');
const WEST = -121.0, SOUTH = 35.2, STEP = 0.02, COLS = 12, ROWS = 9;
const sentinel = readPalette(name => /^map-.*-(?:opacity|width)$/.test(name) ? '1' : `token(${name})`);

function points() {
  const out = [];
  for (let j = 0; j < ROWS; j++) for (let i = 0; i < COLS; i++) {
    out.push({lon: +(WEST + i * STEP).toFixed(6), lat: +(SOUTH + j * STEP).toFixed(6), tempF: 57.3 + i * 0.1 + j * 0.05 + i * j * 0.06, errorF: 0.5});
  }
  return out;
}
const MUR = {id: 'mur-surface-temperature', label: 'NASA JPL MUR · surface temperature analysis', url: 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.csv', kind: 'analysis', outcome: 'ok', fetchedAt: '2026-10-09T02:17:42.000Z'};
function report(analysedAt) {
  return {schemaVersion: 1, countyId: 'slo', generatedAt: '2026-10-09T02:20:00.000Z', forecasts: [], observations: [], tides: [], tideEvents: [], alerts: [], catches: [], catchStatus: '',
    visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, habitatStatus: '', sources: [MUR],
    spatial: {surfaceTemperature: {sourceId: MUR.id, analysedAt, fetchedAt: '2026-10-09T02:17:42.000Z', nativeResolutionDeg: 0.01, sampleSpacingDeg: STEP, points: points(), url: MUR.url, kind: 'analysis'}}};
}

/** The display grid of the synthetic analysis, as the layer builds it. */
function grid() {
  const field = surfaceField(points().map(p => ({lon: p.lon, lat: p.lat, values: [p.tempF, p.errorF]})), {step: [STEP, STEP]});
  const {width, height} = textureSize(field);
  const view = mercatorDisplay(field.bounds, width, height);
  return {width, height, view, samples: sampleDisplay(view, (lon, lat) => field.sample(lon, lat)?.[0] ?? NaN)};
}

test('a viewport lying strictly between four sample centres still selects the bracketing cells (high zoom is not empty)', () => {
  const {width, view, samples} = grid();
  const x = 5, y = 4;
  const lon = (view.lon[x] + view.lon[x + 1]) / 2, lat = (view.lat[y] + view.lat[y + 1]) / 2;
  const dx = (view.lon[x + 1] - view.lon[x]) / 10, dy = (view.lat[y] - view.lat[y + 1]) / 10;
  const picked = visibleSamples(view, samples, width, {lon: lon - dx, lat: lat + dy}, {lon: lon + dx, lat: lat - dy});
  assert.ok(picked.length >= 1, 'at least one sample');
  assert.equal(picked.length, 4, 'the four cells around the viewport');
  assert.ok([...picked].every(Number.isFinite), 'finite temperatures');
});

test('a viewport wholly outside the raster selects nothing; one covering it selects every sample', () => {
  const {width, view, samples} = grid();
  assert.equal(visibleSamples(view, samples, width, {lon: -100, lat: 10}, {lon: -99, lat: 9}).length, 0, 'off the raster');
  assert.equal(visibleSamples(view, samples, width, {lon: -122, lat: 40}, {lon: -119, lat: 34}).length, samples.length, 'whole raster');
});

function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}

test('a new analysis whose viewport has no supported water blanks the previous analysis pixels and legend band', t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  browser(`${PAGE}?region=morro-bay&layers=water-temp`);
  // The viewport: over the raster first, then wholly outside it (no water to stretch).
  let box = {nw: {lon: WEST, lat: SOUTH + 0.2}, se: {lon: WEST + 0.3, lat: SOUTH}};
  const log = [];
  const e = {
    view: {size: () => ({width: 100, height: 100}), unproject: (x) => (x === 0 ? box.nw : box.se), on() {}},
    setOverlay() {}, setRasterOpacity() {}, setCamera() {}, setVisible() {}, destroy() {},
    setImage(id, texture) { log.push(['image', id, texture]); },
    setData(id, data) { log.push(['data', id, data]); },
  };
  const coastReport = signal({data: report('2026-10-07T09:00:00.000Z')});
  const data = {coastReport, coastStatus: signal({report: 'ready', ocean: 'idle', history: 'idle'}), setPlace() {}, load: async () => {}};
  const w = createWaterTemp({engine: signal(e), zone: () => TZ, place: () => ({regionId: 'morro-bay'}), data, palette: () => sentinel, now: () => NOW});
  t.after(() => w.destroy());

  const imagesOf = () => log.filter(([kind, id]) => kind === 'image' && id === SST_SOURCE).map(l => l[2]);
  assert.equal(imagesOf().length, 1, 'analysis A is painted');
  const a = imagesOf()[0];
  assert.ok(a.data.some(v => v !== 0), 'A has coloured pixels');
  const bandA = waterTempState.value.drawn.range;
  assert.match(waterTempState.value.basis, /^SST °F, 1° bands/, 'A shows its band legend');

  box = {nw: {lon: WEST + 5, lat: SOUTH + 5.2}, se: {lon: WEST + 5.3, lat: SOUTH + 5}};
  coastReport.value = {data: report('2026-10-08T09:00:00.000Z')};

  const images = imagesOf(), last = images.at(-1);
  assert.notEqual(last, a, 'the last SST image is not analysis A');
  assert.equal(last.data.length, last.width * last.height * 4);
  assert.ok(last.data.every(v => v === 0), 'B has no supported water in view: blank pixels, never A\'s');
  assert.deepEqual(last.coordinates, a.coordinates, 'at the same coordinates');
  const bands = log.filter(([kind, id]) => kind === 'data' && id === SST_BAND_SOURCE).at(-1);
  assert.deepEqual(bands[2], {type: 'FeatureCollection', features: []}, 'band edges are emptied');
  assert.doesNotMatch(waterTempState.value.basis, /^SST °F, 1° bands/, 'the legend does not carry A\'s band');
  assert.notDeepEqual(waterTempState.value.drawn.range, bandA, 'nor A\'s range');

  // Back over water, the next band repaints.
  box = {nw: {lon: WEST, lat: SOUTH + 0.2}, se: {lon: WEST + 0.3, lat: SOUTH}};
  e.view.on = undefined;
  coastReport.value = {data: report('2026-10-09T01:00:00.000Z')};
  assert.ok(imagesOf().at(-1).data.some(v => v !== 0), 'a later analysis with water in view paints again');
});
