import assert from 'node:assert/strict';
import test from 'node:test';
import {windHourReading} from '../web/map/wind-hour-reading.ts';

const hour = Date.UTC(2026, 0, 1, 12);
const otherHour = hour - 3_600_000;
const at = Object.freeze({lon: -122, lat: 35});
const sample = Object.freeze({...at, knots: 12, from: 270});
const frame = (validAt, stamp, point = sample) => Object.freeze({
  key: stamp, validAt, stamp, points: Object.freeze([point]), step: Object.freeze([2, 0.5]),
});
const noFrame = {ok: false, reason: 'no-frame'};

// An earlier frame has a usable sample but must not win on position alone.
test('C1: selects the matching hour after a nonmatching frame (C3 hit)', () => {
  const frames = Object.freeze([frame(otherHour, 'earlier'), frame(hour, 'selected')]);
  assert.deepEqual(windHourReading(frames, hour, at), {ok: true, sample, validAt: hour, stamp: 'selected'});
});

// Infinity can equal a frame timestamp, but it is not a valid dock hour.
test('C2: rejects a non-finite hour', () => {
  for (const invalid of [NaN, Infinity, -Infinity]) {
    assert.deepEqual(windHourReading([frame(invalid, 'invalid')], invalid, at), noFrame);
  }
});

// A frame held in an array-like object is still not a loaded frame array.
test('C2: rejects non-array frames', () => {
  assert.deepEqual(windHourReading({0: frame(hour, 'array-like'), length: 1}, hour, at), noFrame);
  assert.deepEqual(windHourReading(null, hour, at), noFrame);
});

// Catch falling back to the nearest hour or rounding the tap hour to the frame time.
test('C3: returns no-frame when the only frame is for another hour', () => {
  assert.deepEqual(windHourReading([frame(otherHour, 'earlier')], hour, at), noFrame);
  assert.deepEqual(windHourReading([frame(hour, 'nearby')], hour + 1, at), noFrame);
});

// An unfilled array slot must not make an otherwise empty lookup throw.
test('C2: returns no-frame for a sparse array with no frames', () => {
  assert.deepEqual(windHourReading(Array(1), hour, at), noFrame);
});

// A last-match scan would return both the wrong stamp and the wrong wind speed.
test('C3: the first frame wins when hours are equal', () => {
  const frames = [frame(hour, 'first'), frame(hour, 'second', {...sample, knots: 24})];
  assert.deepEqual(windHourReading(frames, hour, at), {ok: true, sample, validAt: hour, stamp: 'first'});
});

// A later duplicate cannot supply a reading when the first frame has no nearby sample.
test('C3: preserves no-sample-near for the selected frame', () => {
  const frames = [frame(hour, 'far', {...sample, lon: at.lon + 2}), frame(hour, 'near')];
  assert.deepEqual(windHourReading(frames, hour, at), {ok: false, reason: 'no-sample-near'});
});
