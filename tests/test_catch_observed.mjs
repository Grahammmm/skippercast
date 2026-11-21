import assert from 'node:assert/strict';
import test from 'node:test';
import {catchChlorophyll, catchWaterTemp} from '../server/catch-observed.ts';

function fixture(layer, field, product, sampleAt, west, east) {
  return Object.freeze({
    layer, product, sampleAt,
    resolution: Object.freeze([0.5, 1]),
    fields: Object.freeze(['latitude', 'longitude', 'auxiliary', field]),
    rows: Object.freeze([
      Object.freeze([10.5, 21, 99, null]),
      Object.freeze([10, 20, 99, west]),
      Object.freeze([10, 21, 99, east]),
    ]),
  });
}

const sst = fixture('sst-analysis', 'temperature_c', 'SST fixture', '2026-11-19T04:05:06+00:00', 11.25, 12.49);
const chl = fixture('chlorophyll-observation', 'chlorophyll_mg_m3', 'Chlorophyll fixture', '2026-11-20T02:03:04Z', 1.23456, 0);
const temperature = {value: 52.3, unit: 'F', product: 'SST fixture', sample_at: '2026-11-19T04:05:06+00:00'};
const chlorophyll = {value: 1.23456, unit: 'mg/m3', product: 'Chlorophyll fixture', sample_at: '2026-11-20T02:03:04Z'};

for (const [label, read, frame, swapped, west, east] of [
  ['temperature', catchWaterTemp, sst, chl, temperature, {...temperature, value: 54.5}],
  ['chlorophyll', catchChlorophyll, chl, sst, chlorophyll, {...chlorophyll, value: 0}],
]) {
  // Sorting rows in place would break a caller's reusable frame; catch-and-hide would lose the reading.
  test(`C1: ${label} reads a frozen frame without changing it`, () => {
    const before = structuredClone(frame);
    assert.deepEqual(read(frame, 10, 20), west);
    assert.deepEqual(frame, before);
  });

  // Missing frame wins over invalid position; invalid position wins over a known bad frame.
  test(`C3: ${label} checks the archive before position, and position before frame validity`, () => {
    assert.deepEqual(read(null, 10, 20), {missing: 'not archived'});
    assert.deepEqual(read(null, null, Infinity), {missing: 'not archived'});
    for (const invalid of [null, NaN, Infinity, -Infinity]) {
      assert.deepEqual(read(swapped, invalid, 20), {missing: 'no position'});
      assert.deepEqual(read(swapped, 10, invalid), {missing: 'no position'});
    }
  });

  // The wrong layer still has the requested column; missing-column and index failures must
  // not degrade into outside coverage just because the requested point is far from the grid.
  test(`C3: ${label} rejects the wrong layer, absent column, and invalid grid before coverage`, () => {
    const wrongLayer = {...frame, layer: swapped.layer};
    const missingColumn = {...frame, fields: frame.fields.slice(0, -1), rows: []};
    const invalidGrid = {...frame, rows: [...frame.rows, frame.rows[0]]};
    assert.deepEqual(read(swapped, 10, 20), {missing: 'bad frame'});
    for (const bad of [wrongLayer, missingColumn, invalidGrid]) {
      assert.deepEqual(read(bad, 0, 0), {missing: 'bad frame'});
    }
  });

  // A nearest-neighbour fallback would invent readings for the hole or outside the footprint.
  test(`C3: ${label} distinguishes outside coverage, an absent cell, and a present null`, () => {
    assert.deepEqual(read(frame, 0, 0), {missing: 'outside coverage'});
    assert.deepEqual(read({...frame, rows: []}, 10, 20), {missing: 'outside coverage'});
    assert.deepEqual(read(frame, 10.5, 20), {missing: 'gap'});
    assert.deepEqual(read(frame, 10.5, 21), {missing: 'gap'});
  });

  // The shared half-open grid owns the tie; a rounded-nearest or closed-edge rule can shift it.
  test(`C3: ${label} includes south and west, switches at internal edges, and excludes north and east`, () => {
    assert.deepEqual(read(frame, 9.75, 19.5), west);
    assert.deepEqual(read(frame, 10, 20.499), west);
    assert.deepEqual(read(frame, 10, 20.5), east);
    assert.deepEqual(read(frame, 10.25, 21), {missing: 'gap'});
    assert.deepEqual(read(frame, 10.75, 21), {missing: 'outside coverage'});
    assert.deepEqual(read(frame, 10, 21.5), {missing: 'outside coverage'});
  });

  // Caching by frame identity could leave stale readings if a caller supplies revised rows.
  test(`C3: ${label} builds the index from the rows supplied on each call`, () => {
    const current = {...frame};
    assert.deepEqual(read(current, 10, 20), west);
    current.rows = [];
    assert.deepEqual(read(current, 10, 20), {missing: 'outside coverage'});
  });
}

// The auxiliary column is first; accidentally using it or blending neighbours changes the reading.
// 11.25 °C is 52.25 °F; a slightly colder input must round down instead.
test('C2: temperature uses the named native cell, rounds to a tenth, and preserves provenance', () => {
  assert.deepEqual(catchWaterTemp(sst, 10, 20.49), temperature);
  assert.deepEqual(catchWaterTemp(sst, 10, 20.51), {...temperature, value: 54.5});
  const belowTie = {...sst, rows: [[10, 20, 99, 11.249]]};
  assert.deepEqual(catchWaterTemp(belowTie, 10, 20), {...temperature, value: 52.2});
  const freezing = {...sst, rows: [[10, 20, 99, 0]]};
  assert.deepEqual(catchWaterTemp(freezing, 10, 20), {...temperature, value: 32});
});

// Reusing the temperature formatter could round away precision or turn a zero into a gap.
test('C2: chlorophyll preserves the named native value, zero, and provenance', () => {
  assert.deepEqual(catchChlorophyll(chl, 10, 20.49), chlorophyll);
  assert.deepEqual(catchChlorophyll(chl, 10, 20.51), {...chlorophyll, value: 0});
});
