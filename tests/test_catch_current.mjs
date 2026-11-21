import assert from 'node:assert/strict';
import test from 'node:test';
import {catchCurrent} from '../server/catch-current.ts';

const issuedAt = '2026-11-19T07:00:00-08:00';
const validAt = '2026-11-19T08:00:00-08:00';
const cell = (lat, lon, speedKnots, towardDeg) => ({lat, lon, speedKnots, towardDeg, uMs: 0.01, vMs: 0.02});
// Deliberately not in geographic order, with a hole in the northwest cell.
const frame = {validAt, cells: [cell(41, -124.5, 2.36, 181.4), cell(40, -125, 0.05, 359.6), cell(40, -124.5, 1.24, 89.6)]};
const duplicateFrame = {validAt, cells: [...frame.cells, cell(40, -125, 5, 270)]};
const input = {issuedAt, frame, resolution: [1, 0.5], lat: 40, lon: -125};
const southwest = {kn: 0.1, toward_deg: 0, run: issuedAt, valid_at: validAt};
const southeast = {kn: 1.2, toward_deg: 90, run: issuedAt, valid_at: validAt};
const northeast = {kn: 2.4, toward_deg: 181, run: issuedAt, valid_at: validAt};

// An in-place sort, reverse or normalization would modify a frame shared by callers.
test('C1: samples a frozen frame without changing it', () => {
  const frozen = structuredClone(frame);
  frozen.cells.forEach(Object.freeze);
  Object.freeze(frozen.cells);
  Object.freeze(frozen);
  assert.deepEqual(catchCurrent({...input, frame: frozen}), southwest);
  assert.deepEqual(frozen, frame);
});

// Reject malformed grid contents without leaking the shared sampler's exception.
test('C1: returns a whole missing result rather than throwing on an invalid cell coordinate', () => {
  const invalid = {validAt, cells: [cell(NaN, -125, 0.05, 359.6)]};
  assert.deepEqual(catchCurrent({...input, frame: invalid}), {missing: 'bad grid'});
});

// Checking position or indexing first can hide an absent frame or issue timestamp.
test('C2: no frame wins over no position and bad grid', () => {
  const expected = {missing: 'no frame'};
  assert.deepEqual(catchCurrent({...input, frame: null}), expected);
  assert.deepEqual(catchCurrent({...input, frame: null, lat: null, resolution: [0, 1]}), expected);
  for (const missingTime of [null, 'not an instant']) {
    for (const overrides of [{}, {lat: null}, {lat: null, frame: duplicateFrame}, {frame: duplicateFrame}]) {
      assert.deepEqual(catchCurrent({...input, ...overrides, issuedAt: missingTime}), expected);
    }
  }
});

// Invalid coordinates must not be mistaken for finite positions outside the grid.
test('C2: either missing or non-finite coordinate wins over grid validation and sampling', () => {
  for (const coordinate of ['lat', 'lon']) {
    for (const value of [null, NaN, Infinity, -Infinity]) {
      for (const currentFrame of [frame, duplicateFrame]) {
        assert.deepEqual(catchCurrent({...input, frame: currentFrame, [coordinate]: value}), {missing: 'no position'});
      }
    }
  }
});

// An early bounds check or a last-write-wins index would hide these grid errors.
test('C2: duplicate rows and bad resolution win over gap and outside coverage', () => {
  for (const overrides of [{frame: duplicateFrame}, {resolution: [1, 0]}]) {
    for (const lat of [40, 41, 42]) {
      assert.deepEqual(catchCurrent({...input, ...overrides, lat}), {missing: 'bad grid'});
    }
  }
});

// A bounding-box-only or nearest-cell reading would incorrectly fill the hole.
test('C2: distinguishes a gap, outside coverage and an empty footprint', () => {
  assert.deepEqual(catchCurrent({...input, lat: 41}), {missing: 'gap'});
  assert.deepEqual(catchCurrent({...input, lat: 42}), {missing: 'outside coverage'});
  assert.deepEqual(catchCurrent({...input, frame: {validAt, cells: []}}), {missing: 'outside coverage'});
});

// Reading the first row or rounding the components instead of the cell's own values fails here.
test('C3: uses the containing cell, rounds its speed and bearing, and preserves both timestamps', () => {
  assert.deepEqual(catchCurrent({...input, lat: 40.2, lon: -124.8}), southwest);
});

// Inclusive north/east comparisons or snapping to a nearby centre would choose the wrong row.
test('C3: samples half-open inner and outer edges', () => {
  for (const [lat, lon, expected] of [
    [39.5, -125.25, southwest],
    [40, -124.75, southeast],
    [40.5, -124.5, northeast],
    [40.5, -124.75, northeast],
    [41.5, -124.5, {missing: 'outside coverage'}],
    [41, -124.25, {missing: 'outside coverage'}],
  ]) {
    assert.deepEqual(catchCurrent({...input, lat, lon}), expected, `edge at ${lat}, ${lon}`);
  }
});
