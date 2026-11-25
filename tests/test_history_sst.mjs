import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {habitatManifestURL, regionalSST, SST_LAYER_ID} from '../web/map/habitat-feed.ts';
import {historySurfaceTemperature} from '../web/map/history-sst.ts';

const source = {sourceId: 'fixture-sst', fetchedAt: '2026-11-20T12:00:00Z', url: 'https://source.test/sst', stride: 1};
const day = {
  state: 'ready', sampleAt: '2026-11-14T00:00:00Z',
  fields: ['latitude', 'longitude', 'analysis_error_c', 'temperature_c'],
  resolution: [0.125, 0.125], rows: [[35, -121, 0, 15]],
};

// A past observation must keep its own date, not the current feed's retrieval date.
test('C1: converts a ready history day into the Water temp field', () => {
  assert.deepEqual(historySurfaceTemperature({...day, resolution: [0.02, 0.02]}, {...source, stride: 2}), {
    sourceId: source.sourceId, analysedAt: day.sampleAt, fetchedAt: source.fetchedAt,
    nativeResolutionDeg: 0.02, sampleSpacingDeg: 0.04,
    points: [{lat: 35, lon: -121, tempF: 59, errorF: 0}], url: source.url, kind: 'analysis',
  });
});

// An unnamed column must not be accepted merely because its usual slot has a number.
test('C2: refuses either missing analysis field', () => {
  for (const field of day.fields.slice(2)) {
    const fields = day.fields.map(f => f === field ? 'other' : f);
    assert.equal(historySurfaceTemperature({...day, fields}, source), null, field);
  }
});

test('C2: requires finite positive square cells and finite sampled spacing', () => {
  for (const resolution of [[0.02, 0.04], [0, 0], [-0.02, -0.02], [Infinity, Infinity],
    [NaN, NaN], ['0.02', '0.02'], [Number.MAX_VALUE, Number.MAX_VALUE]]) {
    assert.equal(historySurfaceTemperature({...day, resolution}, {...source, stride: 2}), null, String(resolution));
  }
});

// A check that only requires finite values >= 1 invents 0.03° spacing from 0.02° native cells.
test('C2: requires a positive safe-integer stride on the native grid', () => {
  for (const stride of [1.5, Number.MAX_SAFE_INTEGER + 1, -1, 0, 0.5, NaN, Infinity, '2']) {
    assert.equal(historySurfaceTemperature({...day, resolution: [0.02, 0.02]}, {...source, stride}), null, String(stride));
  }
});

// An empty or unusable grid must not appear as a ready field with zero points.
test('C2: returns null when no row yields a finite temperature and usable error', () => {
  for (const rows of [[], [[35, -121, 0, Infinity], [35, -121, NaN, 15]]]) {
    assert.equal(historySurfaceTemperature({...day, rows}, source), null);
  }
});

// Keep the live and historical conversions aligned: named fields, row order,
// unit conversion, and filtering without coercing null or boolean cells to zero.
test('C3: converts the same rows as regionalSST, in order, skipping unusable cells', async () => {
  const rows = [
    [35, -120.875, 1, 10],
    [35, -120.75, -1, 10],
    [35, -120.625, null, 10],
    [35, -120.5, 1, null],
    [35, -120.375, false, 10],
    [35, -120.25, 1, true],
    day.rows[0],
  ];
  const expected = {
    sourceId: source.sourceId, analysedAt: day.sampleAt, fetchedAt: source.fetchedAt,
    nativeResolutionDeg: 0.125, sampleSpacingDeg: 0.125,
    points: [{lat: 35, lon: -120.875, tempF: 50, errorF: 1.8}, {lat: 35, lon: -121, tempF: 59, errorF: 0}],
    url: source.url, kind: 'analysis',
  };
  const history = historySurfaceTemperature({...day, rows}, source);
  assert.deepEqual(history, expected);

  const page = 'https://s.test/map', region = 'test-coast', id = SST_LAYER_ID;
  const currentAt = '2026-11-20T00:00:00.000Z', time = Date.parse(currentAt) / 1000;
  const manifestURL = habitatManifestURL(region, page);
  const bounds = [-121.0625, 34.9375, -120.1875, 35.0625];
  const grid = {fields: day.fields, resolution_degrees: day.resolution};
  const bytes = Buffer.from(JSON.stringify({schema_version: 1, region_id: region, layer_id: id,
    bounds, ...grid, frames: [{time, cells: rows}]}));
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  const path = `habitat-tiles/sst-analysis-${sha256.slice(0, 16)}.json`;
  const manifest = {schema_version: 1, region_id: region,
    layers: {[id]: {id, kind: 'analysis', ...grid, status: 'ok', source_id: source.sourceId, native_stride: source.stride,
      max_age_hours: 24, frames: [{time, valid_cells: 2}], tiles: [{path, bounds, sha256, bytes: bytes.length}]}},
    sources: {[id]: {name: 'Fixture', url: source.url, data_retrieved_at: source.fetchedAt}},
  };
  const live = await regionalSST(region, {page, now: new Date(source.fetchedAt), fetchFn: async address => {
    if (address === manifestURL) return Response.json(manifest);
    if (address === new URL(path, manifestURL).href) return new Response(bytes);
    throw new Error(`Unexpected fixture URL: ${address}`);
  }});
  assert.deepEqual(live, {state: 'ready', product: 'Fixture', maxAgeMs: 86_400_000,
    sst: {...expected, analysedAt: currentAt}});
  assert.deepEqual(history.points, live.sst.points);
});
