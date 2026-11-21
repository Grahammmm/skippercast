// SCA-583 / F15-07: a refresh that changes only geometry/pixels must not let
// picks advance past paint, or leave a reading card open from the old analysis.

import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {signal} from '@preact/signals';
import {configureStore, syncFromURL} from '../web/state.ts';
import {camera} from '../web/map/stage.ts';
import {chartMark} from '../web/map/chart.ts';
import {createFronts} from '../web/map/fronts.ts';
import {FRONTS_SOURCE} from '../web/map/layers.ts';
import {readPalette} from '../web/map/palette.ts';
import {SST_BAND_SOURCE} from '../web/map/sst-bands.ts';
import {createWaterTemp, CONTOUR_SOURCE, SST_SOURCE} from '../web/map/sst.ts';

const HOUR = 3_600_000, NOW = Date.parse('2026-11-01T19:00:00Z');
const STAMP = '2026-11-01T17:00:00Z', NEW_STAMP = '2026-11-01T18:00:00Z';
const PAGE = 'https://example.test/map', REGION = 'fixture';
const title = 'Synthetic analysis';
const shades = ['#112233', '#225566', '#447788', '#668899', '#88aacc', '#bbeeef'];
const palette = readPalette(name => name.startsWith('skl-sst-fill-ramp-stops-') ? shades[Number(name.split('-').at(-1)) % shades.length] : '#112233');
const flush = () => new Promise(resolve => setImmediate(resolve));

function setup(t, layer) {
  t.mock.timers.enable({apis: ['setTimeout']});
  const href = `${PAGE}?presentation=chart&layers=${layer}`;
  t.mock.method(globalThis, 'fetch', () => { assert.fail('unexpected network call'); });
  configureStore({v2: true, storage: null});
  syncFromURL(href);
  camera.value = null;
  let time = NOW;
  const e = {images: [], contours: [], bands: [], lines: [], setOverlay() {},
    setImage(id, texture) {
      assert.equal(id, SST_SOURCE);
      assert.ok(texture.data.some((v, i) => i % 4 === 3 && v > 0), 'texture has visible pixels');
      this.images.push(createHash('sha256').update(texture.data).digest('hex'));
    },
    setData(id, data) {
      if (id === FRONTS_SOURCE) this.lines.push(data.features.map(f => f.geometry.coordinates));
      else if (id === SST_BAND_SOURCE) this.bands.push(data.features.length);
      else {
        assert.equal(id, CONTOUR_SOURCE);
        this.contours.push(data.features.length);
      }
    }};
  return {e, options: {engine: signal(e), place: () => ({regionId: REGION}), palette: () => palette,
    now: () => new Date(time), page: () => PAGE}, async tick() {
    time += HOUR + 1000;
    t.mock.timers.tick(HOUR + 1000);
    await flush();
  }};
}

const point = (lon, lat) => ({lon, lat});
const reading = (layer, at) => layer.reading(at)?.reading ?? null;
const pan = () => { camera.value = {longitude: 2, latitude: 2, zoom: 8}; };

async function fronts(t, stamp) {
  const {e, options, tick} = setup(t, 'sst-fronts');
  const pending = [];
  const line = lat => [[0, lat], [1, lat]];
  const old = point(0.5, 0), next = point(0.5, 1);
  const doc = (lat, at) => ({schema_version: 1, region_id: REGION, layer_id: 'sst-fronts', product: title,
    max_age_hours: 72, observed_at: at, fronts: [{id: 'fixture-front', observed_at: at, strength_c_per_km: 2,
      uncertainty_c: 1, band_half_width_km: 1, geometry: {type: 'LineString', coordinates: line(lat)}}]});
  const layer = createFronts({...options, fetchFn(url) {
    assert.equal(url, `https://example.test/feeds/conditions/regions/${REGION}/sst-fronts.json`);
    return new Promise(resolve => pending.push(resolve));
  }});
  try {
    const send = (lat, at) => {
      assert.equal(pending.length, 1, 'the fixture answers exactly one pending refresh');
      pending.shift()({ok: true, json: async () => doc(lat, at)});
      return flush();
    };
    await send(0, STAMP);
    assert.deepEqual(e.lines, [[[line(0)]]]);
    chartMark.value = layer.reading(old);
    assert.ok(chartMark.value, 'old front is initially pickable');
    assert.equal(reading(layer, next), null);
    await tick();
    assert.equal(e.lines.length, 1, 'the refresh tick cannot repaint before data arrives');
    await send(1, stamp);
    const observed = {repaints: e.lines.length - 1, paint: e.lines.at(-1), cleared: chartMark.peek() === null,
      oldHit: reading(layer, old) !== null, newHit: reading(layer, next) !== null};
    pan();
    assert.equal(e.lines.length, observed.repaints + 1, 'a pan does not repaint');
    await tick(); // next read stays pending: time/pan alone must not repaint
    assert.equal(e.lines.length, observed.repaints + 1, 'a refresh tick alone does not repaint');
    return {observed, wanted: {repaints: 1, paint: [[line(1)]], cleared: true, oldHit: false, newHit: true}};
  } finally { layer.destroy(); }
}

async function sst(t, stamp) {
  const {e, options, tick} = setup(t, 'water-temp');
  const source = {id: 'fixture-sst', kind: 'analysis', outcome: 'ok', label: title};
  const report = (cell, fetchedAt) => ({data: {sources: [source], spatial: {surfaceTemperature: {
    kind: 'analysis', sourceId: source.id, analysedAt: STAMP, fetchedAt, nativeResolutionDeg: 0.1, sampleSpacingDeg: 0.1,
    points: [[0, 0, cell], [0.1, 0, 56], [0, 0.1, 58], [0.1, 0.1, 59]].map(([lon, lat, tempF]) => ({lon, lat, tempF, errorF: 1})),
  }}}});
  const data = {coastReport: signal(report(55, STAMP)), coastStatus: signal({report: 'ready'}), setPlace() {}, load() {}};
  const layer = createWaterTemp({...options, zone: () => 'UTC', data});
  try {
    const at = point(0.05, 0.05);
    assert.equal(e.images.length, 1);
    assert.ok(e.contours[0] > 0, 'the fixture has real contours');
    assert.ok(e.bands[0] > 0, 'SST-B draws edges separately from the original contours');
    chartMark.value = layer.reading(at);
    assert.match(chartMark.value?.reading ?? '', /^57\.0 °F/);
    data.coastReport.value = report(63, stamp);
    const observed = {repaints: e.images.length - 1, contourUpdates: e.contours.length - 1,
      changedPixels: e.images.at(-1) !== e.images[0], cleared: chartMark.peek() === null, pick: reading(layer, at)};
    pan();
    assert.equal(e.images.length, observed.repaints + 1, 'a pan does not rebuild the texture');
    await tick();
    assert.equal(e.images.length, observed.repaints + 1, 'a clock tick does not rebuild the texture');
    assert.equal(e.contours.length, observed.contourUpdates + 1);
    assert.equal(e.bands.length, 2, 'band edges are replaced once with the new analysis');
    return {observed, wanted: {repaints: 1, contourUpdates: 1, changedPixels: true, cleared: true, pick: '59.0 °F · analysis error 1.0 °F'}};
  } finally { layer.destroy(); }
}

for (const replay of [fronts, sst]) {
  for (const [label, stamp] of [['new timestamp (control)', NEW_STAMP], ['same timestamps and IDs (regression)', STAMP]]) {
    test(`F15-07 ${replay.name}: ${label}, one repaint, clear and new pick`, async t => {
      const {observed, wanted} = await replay(t, stamp);
      assert.deepEqual(observed, wanted);
    });
  }
}
