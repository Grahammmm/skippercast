import assert from 'node:assert/strict';
import test from 'node:test';
import {chlorophyllReader} from '../web/map/chlorophyll-reading.ts';

const sampleAt = '2026-11-19T00:00:00Z';
const product = 'Synthetic VIIRS OCI';
const now = new Date('2026-11-19T06:00:00Z');
const sw = {lat: 35.025, lon: -120.975, value: 1.23456789};
const se = {lat: 35.025, lon: -120.925, value: 3.25};
const nw = {lat: 35.075, lon: -120.975, value: 4.75};
const ne = {lat: 35.075, lon: -120.925, value: 7.5};
const observation = (cells, overrides) => ({product, sampleAt, maxAgeMs: 86_400_000,
  resolution: [0.05, 0.05], cells, ...overrides});
const value = ({lat, lon, value: valueMgM3}) => ({kind: 'value', valueMgM3, sampleAt,
  ageMs: 21_600_000, product, cell: {lat, lon}});
const gap = {kind: 'none', reason: 'gap'};
const outside = {kind: 'none', reason: 'outside'};

// A lazy or per-tap index would make a later row visible to the existing reader.
test('C1: snapshots cells at construction, before the first tap', () => {
  const o = observation([sw, ne]);
  const read = chlorophyllReader(o);
  o.cells.push(se);
  assert.deepEqual(read(se, now), gap);
  assert.deepEqual(chlorophyllReader(o)(se, now), value(se));
});

// Duplicate points must not throw or silently select either stored value.
test('C1: a duplicate native cell makes the reader report bad-grid', () => {
  const read = chlorophyllReader(observation([sw, {...sw, value: 8}]));
  assert.deepEqual(read(sw, now), {kind: 'none', reason: 'bad-grid'});
  assert.deepEqual(read({lat: 0, lon: 0}, now), {kind: 'none', reason: 'bad-grid'});
});

// The point differs from the centre; rounding the value or substituting the tap would lose source data.
test('C2: an interior tap returns the complete source reading', () => {
  const read = chlorophyllReader(observation([ne, sw]));
  assert.deepEqual(read({lat: 35.01, lon: -120.99}, now), value(sw));
});

// An invalid Date is still a Date; it must not leak an unusable age into a reading.
test('C2: an invalid clock returns a none reading without throwing', () => {
  assert.deepEqual(chlorophyllReader(observation([sw]))(sw, new Date(NaN)), {kind: 'none', reason: 'stale'});
});

// Lookup-first would report gap or outside instead of stale; using <= would admit the age limit.
test('C3: freshness expires at maxAgeMs before classifying the point', () => {
  const read = chlorophyllReader(observation([sw, ne]));
  const expired = new Date('2026-11-20T00:00:00Z');
  for (const at of [sw, se, {lat: 0, lon: 0}]) {
    assert.deepEqual(read(at, expired), {kind: 'none', reason: 'stale'});
  }
});

// Rejecting all future samples or clamping their age would violate the feed's skew tolerance.
test('C3: one hour of future skew is fresh, with the signed age', () => {
  const future = '2026-11-19T07:00:00Z';
  const read = chlorophyllReader(observation([sw], {sampleAt: future}));
  assert.deepEqual(read(sw, now), {...value(sw), sampleAt: future, ageMs: -3_600_000});
});

// Closed bounds double-assign internal edges and falsely include outer north/east edges.
test('C4: south and west are included; north and east go to the next cell or outside', () => {
  const read = chlorophyllReader(observation([ne, sw, nw, se]));
  for (const [lat, lon, expected] of [
    [35, -120.975, value(sw)],
    [35.025, -121, value(sw)],
    [35, -121, value(sw)],
    [35.05, -120.975, value(nw)],
    [35.025, -120.95, value(se)],
    [35.05, -120.95, value(ne)],
    [35.1, -120.975, outside],
    [35.025, -120.9, outside],
    [35.1, -120.9, outside],
    [34.999, -120.975, outside],
    [35.025, -121.001, outside],
  ]) {
    assert.deepEqual(read({lat, lon}, now), expected, `tap at ${lat}, ${lon}`);
  }
});

// A missing row and a present null are both gaps, not neighbouring values or bad grids.
test('C4: holes and explicit null rows both report gap', () => {
  const read = chlorophyllReader(observation([sw, ne, {...nw, value: null}]));
  assert.deepEqual(read(se, now), gap);
  assert.deepEqual(read(nw, now), gap);
});
