import test from 'node:test';
import assert from 'node:assert/strict';
import {forecastHourFor, observedFrameFor} from '../server/catch-frames.ts';
import {localParts} from '../web/hour.ts';

const LA = 'America/Los_Angeles';
const catchAt = '2026-11-20T12:30:00Z';
const noon = Date.parse('2026-11-20T12:00:00Z');
const one = Date.parse('2026-11-20T13:00:00Z');
const badTimes = [
  ['zone-free time', '2026-11-20T12:30:00'],
  ['unparseable time with a zone', '2026-11-20T99:30:00Z'],
];

for (const [description, time] of badTimes) {
  test(`C1: ${description} is bad time, even without history`, () => {
    assert.deepEqual(observedFrameFor(time, LA, []), {missing: 'bad time'});
  });
  test(`C2: ${description} is bad time, even without held hours`, () => {
    assert.deepEqual(forecastHourFor(time, []), {missing: 'bad time'});
  });
}

test('C1: late local evening uses the region day, not the UTC day or the written day', () => {
  const sample = '2026-11-20T22:00:00Z';
  assert.deepEqual(observedFrameFor('2026-11-21T07:50:00+00:00', LA, [
    '2026-11-21T08:00:00Z', // ten minutes away, but already tomorrow in LA
    sample,
  ]), {sampleAt: sample});
});

test('C1: spring forward keeps both sides of the skipped hour on the same local day', () => {
  const beforeJump = '2026-03-08T01:50:00-08:00';
  assert.deepEqual(observedFrameFor('2026-03-08T03:05:00-07:00', LA, [
    '2026-03-08T03:06:00-07:00', // closer, but after the catch
    beforeJump,
    '2026-03-08T00:45:00-08:00', // an older prior sample, last in the list
  ]), {sampleAt: beforeJump});
});

test('C1: fall back orders the repeated hour by instant, not by wall time', () => {
  const secondHour = '2026-11-01T01:05:00-08:00';
  assert.deepEqual(observedFrameFor('2026-11-01T01:10:00-08:00', LA, [
    secondHour,
    '2026-11-01T01:55:00-07:00', // reads later but was earlier
  ]), {sampleAt: secondHour});
});

test('C1: day membership matches the clock at midnight after each DST change and in late evening', () => {
  // UTC grouping or a fixed LA offset would misclassify at least one boundary.
  for (const [time, sameDay, nextDay] of [
    ['2026-03-09T06:55:00Z', '2026-03-08T20:00:00Z', '2026-03-09T07:00:00Z'],
    ['2026-11-02T07:55:00Z', '2026-11-01T20:00:00Z', '2026-11-02T08:00:00Z'],
    ['2026-11-21T07:50:00Z', '2026-11-20T22:00:00Z', '2026-11-21T08:00:00Z'],
  ]) {
    const day = localParts(new Date(time), LA).day;
    for (const sampleAt of [sameDay, nextDay]) {
      const expected = localParts(new Date(sampleAt), LA).day === day ? {sampleAt} : {missing: 'not archived'};
      assert.deepEqual(observedFrameFor(time, LA, [sampleAt]), expected, `${time} vs ${sampleAt}`);
    }
  }
});

test('C1: a sample exactly at the catch wins over an older sample', () => {
  const exact = '2026-11-20T04:30:00-08:00';
  assert.deepEqual(observedFrameFor(catchAt, LA, ['2026-11-20T12:00:00Z', exact]), {sampleAt: exact});
});

test('C1: without a prior same-day sample, use the earliest later one', () => {
  const firstLater = '2026-11-20T14:00:00Z';
  assert.deepEqual(observedFrameFor(catchAt, LA, [
    '2026-11-20T07:59:59Z', // prior instant, but yesterday in LA
    '2026-11-20T15:00:00Z',
    firstLater,
  ]), {sampleAt: firstLater});
});

test('C1: adjacent local days cannot substitute for an unarchived day', () => {
  assert.deepEqual(observedFrameFor(catchAt, LA, ['2026-11-20T07:59:59Z', '2026-11-21T08:00:00Z']),
    {missing: 'not archived'});
});

test('C1: zone-free, non-ISO, and invalid sample strings never become candidates', () => {
  assert.deepEqual(observedFrameFor('2026-03-02T12:30:00Z', 'UTC', [
    '2026-03-02T12:00:00', '02 Mar 2026 12:00:00 GMT', '2026-03-02T12:00:00+25:00',
    '2026-02-30T12:00:00Z',
  ]), {missing: 'not archived'});
});

test('C1: a valid catch with an invalid region zone throws RangeError even without samples', () => {
  assert.throws(() => observedFrameFor(catchAt, 'Invalid/Zone', []), {constructor: RangeError});
});

test('C2: the nearest held hour can be later, regardless of list order or non-finite entries', () => {
  assert.deepEqual(forecastHourFor('2026-11-20T18:40:00+06:00', [NaN, one, Infinity, noon, -Infinity]), {at: one});
});

test('C2: a single held hour at exactly 30 minutes is included on either side', () => {
  assert.deepEqual(forecastHourFor(catchAt, [one]), {at: one});
  assert.deepEqual(forecastHourFor(catchAt, [noon]), {at: noon});
});

test('C2: the earlier hour wins a tie in either order', () => {
  assert.deepEqual(forecastHourFor(catchAt, [one, noon]), {at: noon});
  assert.deepEqual(forecastHourFor(catchAt, [noon, one]), {at: noon});
});

test('C2: one millisecond outside the held window does not count', () => {
  assert.deepEqual(forecastHourFor(catchAt, [noon - 1, one + 1]), {missing: 'not archived'});
});

test('C2: an empty publication is not archived', () => {
  assert.deepEqual(forecastHourFor(catchAt, []), {missing: 'not archived'});
});
