import assert from 'node:assert/strict';
import test from 'node:test';
import {windReadingAt} from '../web/map/wind-reading.ts';

const at = Object.freeze({lon: -122, lat: 35});
const point = (dlon = 0, dlat = 0) => Object.freeze({lon: at.lon + dlon, lat: at.lat + dlat, knots: 0, from: 270});
const frame = points => Object.freeze({
  key: 'test-frame', validAt: 1795176000000, stamp: 'test forecast hour',
  step: Object.freeze([2, 0.5]), points: Object.freeze(points),
});
const reading = sample => ({ok: true, sample, validAt: 1795176000000, stamp: 'test forecast hour'});
const noFrame = {ok: false, reason: 'no-frame'};
const noSample = {ok: false, reason: 'no-sample-near'};

// Catch a dropped calm reading, a changed result shape or mutation of the frame.
test('C1: returns the whole reading for a calm sample at the tap', () => {
  const sample = point();
  assert.deepEqual(windReadingAt(frame([sample]), at), reading(sample));
});

// Catch missing guards that dereference absent input or misreport it as a sample miss.
test('C2: null frame returns no-frame', () => {
  assert.deepEqual(windReadingAt(null, at), noFrame);
});

test('C2: missing step returns no-frame', () => {
  const {step, ...withoutStep} = frame([point()]);
  assert.deepEqual(windReadingAt(withoutStep, at), noFrame);
});

// Exercise each slot independently so checking just one axis cannot pass.
test('C2: rejects missing, non-numeric, non-finite and non-positive step components', () => {
  const f = frame([point()]);
  for (const invalid of [undefined, '1', NaN, Infinity, -Infinity, 0, -1]) {
    assert.deepEqual(windReadingAt({...f, step: [invalid, 0.5]}, at), noFrame, `longitude: ${invalid}`);
    assert.deepEqual(windReadingAt({...f, step: [2, invalid]}, at), noFrame, `latitude: ${invalid}`);
  }
});

test('C2: rejects non-finite tap coordinates on either axis', () => {
  const f = frame([point()]);
  for (const invalid of [NaN, Infinity, -Infinity]) {
    assert.deepEqual(windReadingAt(f, {...at, lon: invalid}), noFrame, `longitude: ${invalid}`);
    assert.deepEqual(windReadingAt(f, {...at, lat: invalid}), noFrame, `latitude: ${invalid}`);
  }
});

// Catch strict comparisons, swapped spacing, or using a radius instead of a box.
test('C3: includes both sides of each half-step boundary and a corner', () => {
  for (const sample of [point(-1), point(1), point(0, -0.25), point(0, 0.25), point(1, 0.25)]) {
    assert.deepEqual(windReadingAt(frame([sample]), at), reading(sample));
  }
});

test('C3: rejects points just beyond either half-step even with the other axis centered', () => {
  for (const sign of [-1, 1]) {
    const justOver = 1 / 1024;
    assert.deepEqual(windReadingAt(frame([point(sign * (1 + justOver))]), at), noSample);
    assert.deepEqual(windReadingAt(frame([point(0, sign * (0.25 + justOver))]), at), noSample);
  }
});

// The first sample is closer in raw degrees, but farther in grid units.
test('C3: normalizes longitude and latitude by their own step before selecting', () => {
  const winner = point(0.5);
  assert.deepEqual(windReadingAt(frame([point(0, 0.1875), winner]), at), reading(winner));
});

// The axial sample would win with summed (unsquared) offsets; the diagonal wins here.
test('C3: compares the sum of both squared normalized offsets', () => {
  const winner = point(0.5, 0.125);
  assert.deepEqual(windReadingAt(frame([point(0.75), winner]), at), reading(winner));
  const axial = point(0.625);
  assert.deepEqual(windReadingAt(frame([winner, axial]), at), reading(axial));
});

// Catch replacing the incumbent on equality or preferring a particular grid axis.
test('C3: equal normalized distances keep the earliest sample', () => {
  const a = point(-0.5), b = point(0, 0.125);
  assert.deepEqual(windReadingAt(frame([a, b]), at), reading(a));
  assert.deepEqual(windReadingAt(frame([b, a]), at), reading(b));
});

// A corrupt value at the tap must not win over a more distant finite sample.
test('C3: skips a non-finite value in any sample field', () => {
  const valid = point(0.5);
  for (const field of ['lon', 'lat', 'knots', 'from']) {
    for (const invalid of [NaN, Infinity, -Infinity]) {
      const bad = {...point(), [field]: invalid};
      assert.deepEqual(windReadingAt(frame([bad]), at), noSample, `${field}: ${invalid}`);
      assert.deepEqual(windReadingAt(frame([bad, valid]), at), reading(valid), `${field}: ${invalid}`);
    }
  }
});

// An empty points array is still a frame, and must not throw or invent a reading.
test('C3: an empty frame returns no-sample-near', () => {
  assert.deepEqual(windReadingAt(frame([]), at), noSample);
});
