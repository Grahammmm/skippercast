import test from 'node:test';
import assert from 'node:assert/strict';
import {pastSampleFor, pastDayCoverage} from '../web/map/past-sample.ts';
import {pastDayGate} from '../web/map/past-day-gate.ts';

const LA = 'America/Los_Angeles';
const DAY = '2026-11-18';
const LA_LAST = '2026-11-19T07:59:59.999Z';
const LA_NEXT = '2026-11-19T08:00:00Z';
const spring = Object.freeze([
  '2026-03-08T07:59:59.999Z', '2026-03-08T08:00:00Z',
  '2026-03-09T06:59:59.999Z', '2026-03-09T07:00:00Z',
]);
const fall = Object.freeze([
  '2026-11-01T06:59:59.999Z', '2026-11-01T07:00:00Z',
  '2026-11-01T01:30:00-07:00', '2026-11-01T01:30:00-08:00',
  '2026-11-02T07:59:59.999Z', '2026-11-02T08:00:00Z',
]);
const samples = Object.freeze([LA_NEXT, '2026-11-19T15:00+0930', LA_LAST, '2026-11-18T22:00Z']);
const selections = [
  ['UTC midnight is not LA midnight; array order is not recency', samples, DAY, LA, LA_LAST],
  ['the same sample belongs to a different day in UTC', [LA_LAST], '2026-11-19', 'UTC', LA_LAST],
  ['a positive zone offset crosses into the next year', ['2026-12-31T23:30Z'], '2027-01-01', 'Asia/Tokyo', '2026-12-31T23:30Z'],
  ['a 45-minute zone offset is not rounded', ['2026-11-18T18:14:59Z', '2026-11-18T18:15:00Z'], '2026-11-19', 'Asia/Kathmandu', '2026-11-18T18:15:00Z'],
  ['spring-forward starts at midnight before the shift', [spring[1]], '2026-03-08', LA, spring[1]],
  ['spring-forward ends an hour early in UTC', spring, '2026-03-08', LA, spring[2]],
  ['fall-back starts at midnight before the shift', [fall[1]], '2026-11-01', LA, fall[1]],
  ['fall-back ends an hour late in UTC', fall, '2026-11-01', LA, fall[4]],
  ['the second 01:30 during fall-back is a later instant', fall.slice(2, 4), '2026-11-01', LA, fall[3]],
  ['a printed date and clock time do not determine recency', ['2026-11-19T13:00+05:30', '2026-11-18T23:00-08:00'], DAY, LA, '2026-11-19T13:00+05:30'],
  ['the first spelling of an equal instant wins', ['2026-11-19T07:30:00.250Z', '2026-11-18T23:30:00.2500-0800'], DAY, LA, '2026-11-19T07:30:00.250Z'],
  ['fractional precision after milliseconds still orders distinct instants', ['2026-11-18T23:30:00.25001-0800', '2026-11-19T07:30:00.2501Z'], DAY, LA, '2026-11-19T07:30:00.2501Z'],
  ['year zero is not year one', ['0000-01-01T00:00Z', '0001-01-01T00:00Z'], '0000-01-01', 'UTC', '0000-01-01T00:00Z'],
  ['an expanded UTC year can fall on a four-digit local year', ['+010000-01-01T00:00Z'], '9999-12-31', LA, '+010000-01-01T00:00Z'],
  ['a real century leap day is not rejected', ['2000-02-29T12:00Z'], '2000-02-29', 'UTC', '2000-02-29T12:00Z'],
  ['a minute-precision compact offset is not rejected', ['2026-11-19T15:00+0930'], DAY, LA, '2026-11-19T15:00+0930'],
];

for (const [label, history, day, zone, expected] of selections) {
  test(`C1: ${label}`, () => assert.deepEqual(pastSampleFor(history, day, zone), expected));
}

test('C1: no history or an adjacent day cannot fill a gap', () => {
  assert.deepEqual(pastSampleFor([], DAY, LA), null);
  assert.deepEqual(pastSampleFor([LA_NEXT], DAY, LA), null);
  assert.deepEqual(pastSampleFor([spring[0]], '2026-03-08', LA), null);
  assert.deepEqual(pastSampleFor([fall[0]], '2026-11-01', LA), null);
  // Apia skipped December 30 when it changed sides of the date line.
  assert.deepEqual(pastSampleFor(['2011-12-30T09:59:59Z', '2011-12-30T10:00:00Z'], '2011-12-30', 'Pacific/Apia'), null);
});

test('C1: malformed dock days and invalid zones fail closed', () => {
  for (const day of ['', '2026-11-8', '2026-11-18\n', '2026-02-30', '1900-02-29']) {
    assert.deepEqual(pastSampleFor(samples, day, LA), null, JSON.stringify(day));
  }
  for (const zone of ['', 'Mars/Olympus', undefined]) {
    assert.deepEqual(pastSampleFor(samples, DAY, zone), null, JSON.stringify(zone));
  }
});

test('C1: lenient parsing must not turn malformed samples into observations', () => {
  for (const [sample, day] of [
    ['2026-11-18T12:00:00', DAY], ['2026-11-18', DAY], ['2026-11-18 12:00:00Z', DAY],
    ['2026-02-30T12:00:00Z', '2026-03-02'], ['1900-02-29T12:00Z', '1900-03-01'],
    ['2026-11-17T24:01:00Z', DAY], ['2026-11-18T12:00:00+01:60', DAY],
    ['2026-11-18T12:00:00Z\n', DAY], [null, DAY],
  ]) {
    assert.deepEqual(pastSampleFor([sample], day, 'UTC'), null, JSON.stringify(sample));
  }
  // A malformed entry does not hide a valid sample later in the list.
  assert.deepEqual(pastSampleFor(['2026-11-19T07:00:00', LA_LAST], DAY, LA), LA_LAST);
});

test('C2: preserve every requested key, including gaps and malformed property names', () => {
  const days = Object.freeze([DAY, '2026-11-19', '2026-11-20', '2026-02-30', '__proto__', DAY]);
  assert.deepEqual(pastDayCoverage(samples, days, LA), {
    [DAY]: true, '2026-11-19': true, '2026-11-20': false, '2026-02-30': false, ['__proto__']: false,
  });
  assert.deepEqual(pastDayCoverage(samples, [DAY, 'bad'], 'Mars/Olympus'), {[DAY]: false, bad: false});
  assert.deepEqual(pastDayCoverage(samples, [], LA), {});
});

test('C3: every selected fixture draws in the unchanged gate without mutating the history', () => {
  for (const [label, history, day, zone] of selections) {
    const frozenHistory = Object.freeze([...history]);
    assert.deepEqual(pastDayGate('observed', day, pastSampleFor(frozenHistory, day, zone), zone),
      {draw: true, reason: null}, label);
  }
});
