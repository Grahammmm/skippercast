import assert from 'node:assert/strict';
import test from 'node:test';
import {cellIndex, HabitatGridError, sampleAt} from '../web/map/habitat-sample.ts';

const fields = ['latitude', 'longitude', 'temperature_c', 'temperature_gradient_c_per_km'];
const reading = (lat, lon, value) => ({value, cell: {lat, lon}});
const gap = {value: null, reason: 'gap'};
const outside = {value: null, reason: 'outside'};

// Each query is independent of row order; a nearest-neighbour sampler would fill the hole
// or expand the extent. A zero reading must survive, and a present null must stay unknown.
test('samples only the requested field of the containing cell', () => {
  const index = cellIndex([
    [35.125, -120.875, 17, 0.8], [35.025, -120.975, 0, 0.2], [35.075, -120.925, 16, null],
  ], [0.05, 0.05], fields);
  assert.deepEqual(sampleAt(index, 35.01, -120.99), reading(35.025, -120.975, 0));
  assert.deepEqual(sampleAt(index, 35.14, -120.86), reading(35.125, -120.875, 17));
  assert.deepEqual(sampleAt(index, 35.025, -120.925), gap);
  assert.deepEqual(sampleAt(index, 35.149, -120.999), gap);
  assert.deepEqual(sampleAt(index, 35.151, -120.875), outside);
  assert.deepEqual(sampleAt(cellIndex([], [0.05, 0.05], fields), 35.025, -120.975), outside);

  const gradient = cellIndex([[35.025, -120.975, 15, 0.2], [35.075, -120.975, 16, null]],
    [0.05, 0.05], fields, 'temperature_gradient_c_per_km');
  assert.deepEqual(sampleAt(gradient, 35.025, -120.975), reading(35.025, -120.975, 0.2));
  assert.deepEqual(sampleAt(gradient, 35.075, -120.975), reading(35.075, -120.975, null));
});

// Probe one representable number on each side; adding an epsilon to the query or
// flooring the raw quotient can return the wrong cell at or just below an edge.
function adjacent(n, direction) {
  const bytes = new DataView(new ArrayBuffer(8));
  bytes.setFloat64(0, n);
  bytes.setBigUint64(0, bytes.getBigUint64(0) + BigInt(n < 0 ? -direction : direction));
  return bytes.getFloat64(0);
}

test('half-open footprint edges with shifted, unequal steps at positive and negative coordinates', () => {
  const columns = ['latitude', 'longitude', 'chlorophyll_mg_m3'];
  const sw = [-1.00625, 120.03, 2], se = [-1.00625, 120.08, 3];
  const nw = [-0.96875, 120.03, 5], ne = [-0.96875, 120.08, 7];
  const index = cellIndex([ne, sw, nw, se], [0.0375, 0.05], columns);
  // Include an internal corner and each outer edge, with one axis held inside.
  for (const [edge, other, latAxis, expected] of [
    [-1.025, 120.03, true, [outside, reading(...sw), reading(...sw)]],
    [-0.9875, 120.03, true, [reading(...sw), reading(...nw), reading(...nw)]],
    [-0.95, 120.03, true, [reading(...nw), outside, outside]],
    [120.005, -1.00625, false, [outside, reading(...sw), reading(...sw)]],
    [120.055, -1.00625, false, [reading(...sw), reading(...se), reading(...se)]],
    [120.105, -1.00625, false, [reading(...se), outside, outside]],
  ]) {
    const actual = [adjacent(edge, -1), edge, adjacent(edge, 1)]
      .map(q => latAxis ? sampleAt(index, q, other) : sampleAt(index, other, q));
    assert.deepEqual(actual, expected, `edge ${edge}`);
  }
  assert.deepEqual(sampleAt(index, -0.9875, 120.055), reading(...ne));
});

// The second centre is rounded to five decimals. Use the shared native edge, not
// a tolerance around the query, or an edge derived separately from each rounded row.
test('accepts five-decimal wire rounding without moving query points across edges', () => {
  const columns = fields.slice(0, 3);
  const first = [1.00001, -120.025, 10], second = [1.01002, -120.025, 20];
  const index = cellIndex([second, first], [0.010005, 0.05], columns);
  assert.deepEqual(sampleAt(index, 1.00501, -120.025), reading(...first));
  assert.deepEqual(sampleAt(index, 1.0050125, -120.025), reading(...second));
  assert.deepEqual(sampleAt(index, 1.00502, -120.025), reading(...second));
});

// Rounding an arbitrary row to the nearest address silently shifts it; ordinary
// Map.set would also silently select one of two readings for a duplicate address.
test('refuses off-lattice and duplicate rows with a named error', () => {
  const columns = fields.slice(0, 3), res = [0.05, 0.05], row = [35.025, -120.975, 14];
  assert.throws(() => cellIndex([row, [35.076, -120.925, 15]], res, columns),
    {name: 'HabitatGridError', message: /off the habitat grid lattice/});
  for (const duplicate of [row, [35.025005, -120.975, 15]]) {
    assert.throws(() => cellIndex([row, duplicate], res, columns),
      error => error instanceof HabitatGridError && /Duplicate habitat cell/.test(error.message));
  }
});
