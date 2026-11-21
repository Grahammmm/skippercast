import assert from 'node:assert/strict';
import test from 'node:test';
import {catchTide} from '../server/catch-tide.ts';
import {catchPatterns} from '../web/catch-patterns.ts';

const station = 'fixture-station';
const time = (minutes) => `2026-01-01T00:${minutes}:00Z`;
const point = (minutes, heightFt) => ({at: time(minutes), heightFt});
const curve = [point('10', 1.236), point('25', 2), point('35', 0), point('45', 0.002)];

// Frozen inputs catch accidental mutation by a caller-facing pure rule.
test('C1: a readonly curve returns only the full tide reading', () => {
  const points = Object.freeze(curve.map(p => Object.freeze({...p})));
  assert.deepEqual(catchTide(points, time('10'), station), {
    stage: 'rising', height_ft: 1.24, station, at: time('10'),
  });
});

test('C2: station absence takes precedence over an invalid time and an empty archive', () => {
  for (const absent of [null, '']) {
    assert.deepEqual(catchTide([], 'not a time', absent), {missing: 'no station'});
  }
});

test('C2: naive, date-only and unparseable zoned times are bad before considering archive coverage', () => {
  for (const invalid of ['2026-01-01T00:10:00', '2026-01-01', '2026-01-01T25:10:00Z']) {
    assert.deepEqual(catchTide([], invalid, station), {missing: 'bad time'}, invalid);
  }
});

test('C2: fractional seconds with numeric offsets match the equivalent UTC instant', () => {
  const expected = catchTide(curve, '2026-01-01T00:10:00.123Z', station);
  assert.deepEqual(expected, {stage: 'rising', height_ft: 1.24, station, at: time('10')});
  for (const at of ['2026-01-01T00:10:00.123+00:00', '2026-01-01T01:10:00.123+0100',
    '2025-12-31T19:10:00.123-05:00']) {
    assert.deepEqual(catchTide(curve, at, station), expected, at);
  }
});

test('C2: archive requires two usable points, not just two input rows', () => {
  for (const points of [[], [curve[0]], [curve[0], {at: 'invalid', heightFt: 2}, point('11', Infinity)]]) {
    assert.deepEqual(catchTide(points, time('10'), station), {missing: 'not archived'});
  }
});

test('C2: unusable points cannot extend either end of the archive', () => {
  const points = [point('00', NaN), ...curve, point('52', -Infinity)];
  assert.deepEqual(catchTide(points, time('05'), station), {missing: 'not archived'});
  assert.deepEqual(catchTide(points, time('50'), station), {missing: 'not archived'});
});

test('C2: the match window is inclusive at both archive ends', () => {
  assert.deepEqual(catchTide(curve, time('06'), station), {
    stage: 'rising', height_ft: 1.24, station, at: time('10'),
  });
  assert.deepEqual(catchTide(curve, time('49'), station), {
    stage: null, height_ft: 0, station, at: time('45'),
  });
});

test('C2: an in-archive gap is not a missing archive or an interpolated reading', () => {
  assert.deepEqual(catchTide(curve, time('16'), station), {missing: 'no tide curve'});
});

test('C3: stage comes from original heights rather than the rounded snapshot', () => {
  assert.deepEqual(catchTide(curve, time('25'), station), {
    stage: 'falling', height_ft: 2, station, at: time('25'),
  });
  const points = [point('35', 1.004), point('45', 1.006)];
  assert.deepEqual(catchTide(points, time('35'), station), {
    stage: 'turning', height_ft: 1, station, at: time('35'),
  });
});

test('C3: a next point more than 15 minutes away does not discard the matched height', () => {
  assert.deepEqual(catchTide([point('10', -1.236), point('26', 2)], time('10'), station), {
    stage: null, height_ft: -1.24, station, at: time('10'),
  });
});

test('C3: the first match wins over a closer point, even with an out-of-order successor', () => {
  const at = '2025-12-31T19:14:00-05:00';
  const points = [point('05', 0), {at, heightFt: 3.674}, point('11', 2), point('25', 1)];
  assert.deepEqual(catchTide(points, '2026-01-01T01:11:00+01:00', station), {
    stage: null, height_ft: 3.67, station, at,
  });
});

test('C3: a non-finite first raw match is skipped for both height and trend', () => {
  const points = [point('00', NaN), point('02', 1.234), point('12', 2)];
  assert.deepEqual(catchTide(points, time('02'), station), {
    stage: 'rising', height_ft: 1.23, station, at: time('02'),
  });
});

test('C3: catch entries bucket by the stored stage (and null remains unknown)', () => {
  const minutes = ['10', '25', '35', '45', '10', '25', '35', '45', '10', '25'];
  const entries = minutes.map((minute, i) => ({
    outcome: i < 4 ? 'fish' : 'blank',
    conditions: {v: 1, layers: {water_temp: {value: 56.5, unit: 'F'},
      tide: catchTide(curve, time(minute), station)}},
  }));
  assert.deepEqual(catchPatterns(entries), {n: 10, shown: true, bands: [
    {bandF: 56, tide: 'falling', fish: 1, blank: 2},
    {bandF: 56, tide: 'rising', fish: 1, blank: 2},
    {bandF: 56, tide: 'turning', fish: 1, blank: 1},
    {bandF: 56, tide: 'unknown', fish: 1, blank: 1},
  ]});
});
