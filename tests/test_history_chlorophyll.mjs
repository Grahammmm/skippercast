import assert from 'node:assert/strict';
import test from 'node:test';
import {historyChlorophyll} from '../web/map/history-chlorophyll.ts';

const source = {product: 'Fixture chlorophyll', maxAgeMs: 86_400_000, stride: 1};
const day = {
  state: 'ready', sampleAt: '2026-11-18T00:00:00Z', fields: ['latitude', 'longitude', 'chlorophyll_mg_m3'],
  resolution: [0.05, 0.1], rows: [[35.025, -121.05, 2]],
};
const observation = {
  product: 'Fixture chlorophyll', sampleAt: '2026-11-18T00:00:00Z', maxAgeMs: 86_400_000, resolution: [0.05, 0.1],
  cells: [{lat: 35.025, lon: -121.05, value: 2}],
};

test('C1: converts a ready day using the named field, not a fixed value column', () => {
  assert.deepEqual(historyChlorophyll({...day, fields: ['latitude', 'longitude', 'other', 'chlorophyll_mg_m3'],
    rows: [[35.025, -121.05, 7, 2]]}, source), observation);
});

test('C2: does not substitute another value column when chlorophyll is missing', () => {
  assert.equal(historyChlorophyll({...day, fields: ['latitude', 'longitude', 'other']}, source), null);
});

test('C2: does not present a stride-2 frame as native cells', () => {
  assert.equal(historyChlorophyll(day, {...source, stride: 2}), null);
});

test('C2: retains inclusive native-cell limits in row order and drops invalid rows', () => {
  const rows = [
    [90, 180, 100],
    [0, 0, 0.0009], [0, 0, 100.001],
    [-90.01, 0, 1], [90.01, 0, 1], [0, -180.01, 1], [0, 180.01, 1],
    [0, 0, null], [0, 0, '2'],
    [-90, -180, 0.001],
  ];
  assert.deepEqual(historyChlorophyll({...day, rows}, source), {...observation, cells: [
    {lat: 90, lon: 180, value: 100},
    {lat: -90, lon: -180, value: 0.001},
  ]});
});

test('C2: returns no observation if the frame is empty or all rows are rejected', () => {
  assert.equal(historyChlorophyll({...day, rows: []}, source), null);
  assert.equal(historyChlorophyll({...day, rows: [[35.025, -121.05, null]]}, source), null);
});

test('C3: preserves the past frame timestamp verbatim rather than applying the live age gate', () => {
  assert.deepEqual(historyChlorophyll({...day, sampleAt: '2020-11-17T16:00:00-08:00'}, {...source, maxAgeMs: 1}),
    {...observation, sampleAt: '2020-11-17T16:00:00-08:00', maxAgeMs: 1});
});
