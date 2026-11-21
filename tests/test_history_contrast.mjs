import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {habitatManifestURL, regionalContrast, SST_LAYER_ID} from '../web/map/habitat-feed.ts';
import {historyContrast} from '../web/map/history-contrast.ts';

// Put the measurements in a different order from the usual analysis layout.
const FIELDS = ['latitude', 'longitude', 'thermal_contrast_supported', 'temperature_gradient_c_per_km', 'analysis_error_c', 'temperature_c'];
const DAY = {state: 'ready', sampleAt: '2026-11-18T00:00:00Z', fields: FIELDS, resolution: [0.05, 0.05], rows: [
  [35.025, -120.875, 1, 0.4, 0.3, 14],
  [35.025, -120.975, true, 0.2, -0.1, 15],
  [35.075, -120.925, 0, 0, null, 16],
  [35.075, -120.975, false, 0.1, 0, 17],
  [35.125, -120.975, 2, true, null, false],
  [35.125, -120.925, null, null, null, null],
]};

// C1: an empty day with the necessary columns must not be mistaken for an unsupported layout.
test('C1: a ready day with gradient fields can return an empty sample array', () => {
  assert.deepEqual(historyContrast({...DAY, rows: []}), {gradients: true, samples: []});
});

// C2: each column matters independently, even when other columns contain usable data.
for (const missing of FIELDS.slice(2)) {
  test(`C2: missing ${missing} returns no gradients`, () => {
    const fields = FIELDS.filter(field => field !== missing);
    const rows = DAY.rows.map(row => row.filter((_, i) => FIELDS[i] !== missing));
    assert.deepEqual(historyContrast({...DAY, fields, rows}), {gradients: false});
  });
}

// C2: fixed offsets, truthiness, dropping incomplete rows, or applying Water temp's unit conversion
// would diverge from today's Temp contrast on the same tile rows.
test('C2: preserves row order and matches regionalContrast, including flag and error normalization', async () => {
  const actual = historyContrast(DAY);
  assert.deepEqual(actual, {gradients: true, samples: [
    {lat: 35.025, lon: -120.875, tempC: 14, errorC: 0.3, gradientCPerKm: 0.4, supported: 1},
    {lat: 35.025, lon: -120.975, tempC: 15, errorC: null, gradientCPerKm: 0.2, supported: 1},
    {lat: 35.075, lon: -120.925, tempC: 16, errorC: null, gradientCPerKm: 0, supported: 0},
    {lat: 35.075, lon: -120.975, tempC: 17, errorC: 0, gradientCPerKm: 0.1, supported: 0},
    {lat: 35.125, lon: -120.975, tempC: null, errorC: null, gradientCPerKm: null, supported: null},
    {lat: 35.125, lon: -120.925, tempC: null, errorC: null, gradientCPerKm: null, supported: null},
  ]});

  const page = 'https://s.test/map', region = 'test-coast', id = SST_LAYER_ID;
  const time = Date.parse(DAY.sampleAt) / 1000, bounds = [-121, 35, -120.8, 35.2];
  const {fields, resolution: resolution_degrees, rows: cells} = DAY;
  const body = Buffer.from(JSON.stringify({schema_version: 1, region_id: region, layer_id: id, fields,
    resolution_degrees, bounds, frames: [{time, cells}]}));
  const sha256 = createHash('sha256').update(body).digest('hex');
  const path = `habitat-tiles/${id}-0-0-${sha256.slice(0, 16)}.json`;
  const layer = {id, kind: 'analysis', fields, resolution_degrees, status: 'ok', max_age_hours: 24,
    frames: [{time}], tiles: [{path, bounds, sha256, bytes: body.length}]};
  const manifest = {schema_version: 1, region_id: region, layers: {[id]: layer},
    sources: {[id]: {name: 'Fixture', data_retrieved_at: DAY.sampleAt}}};
  const manifestURL = habitatManifestURL(region, page);
  const live = await regionalContrast(region, {page, now: new Date('2026-11-18T12:00:00Z'), fetchFn: async url => {
    if (url === manifestURL) return Response.json(manifest);
    if (url === new URL(path, manifestURL).href) return new Response(body);
    throw new Error(`Unexpected fixture request: ${url}`);
  }});
  assert.equal(live.state, 'ready');
  assert.deepEqual(actual, {gradients: true, samples: live.samples});
});
