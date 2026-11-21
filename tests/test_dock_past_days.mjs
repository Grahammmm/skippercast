import assert from 'node:assert/strict';
import test from 'node:test';
import {pastDays} from '../web/hour.ts';

const zone = 'America/Los_Angeles';

// Unsorted frames with gaps and duplicates catch slicing entries before grouping,
// filling absent dates, or keeping the oldest days rather than the latest ones.
test('keeps the most recent observed days in ascending local-day order', () => {
  const now = new Date('2026-11-20T20:00:00Z');
  const available = [20, 19, 2, 14, 11, 18, 13, 16, 12, 19, 21]
    .map(day => `2026-11-${String(day).padStart(2, '0')}T12:00:00Z`);
  const expected = [
    {day: '2026-11-12', weekday: 'Thu'},
    {day: '2026-11-13', weekday: 'Fri'},
    {day: '2026-11-14', weekday: 'Sat'},
    {day: '2026-11-16', weekday: 'Mon'},
    {day: '2026-11-18', weekday: 'Wed'},
    {day: '2026-11-19', weekday: 'Thu'},
  ];
  // Seven distinct days, of eight eligible, with no fabricated Nov 15 or Nov 17.
  assert.deepEqual(pastDays(now, zone, available), [{day: '2026-11-11', weekday: 'Wed'}, ...expected]);
  assert.deepEqual(pastDays(now, zone, available, 2), expected.slice(-2));
  assert.deepEqual(pastDays(now, zone, available, 0), []);
  assert.deepEqual(pastDays(now, zone, []), []);
});

// Using UTC or hard-coding the west coast would exclude the first frame too.
test('uses the supplied zone across a half-hour offset and a local year boundary', () => {
  const now = new Date('2025-12-31T18:30:00.000Z');
  assert.deepEqual(pastDays(now, 'Asia/Kolkata', ['2025-12-31T18:29:59.999Z', now.toISOString()]), [
    {day: '2025-12-31', weekday: 'Wed'},
  ]);
});

// A permissive Date parse can roll dates forward or interpret offset-free values
// in the host zone, both of which would invent an observed day.
test('ignores malformed instants but accepts a valid offset and fractional seconds', () => {
  const available = [
    'not a date', '2026-02-30T12:00:00Z', '2026-03-03', '2026-03-04T12:00:00',
    'March 5 2026', '2026-03-06T12:00:00+25:00', '2026-03-07T00:30:00.125+01:00',
  ];
  assert.deepEqual(pastDays(new Date('2026-03-10T12:00:00Z'), zone, available), [
    {day: '2026-03-06', weekday: 'Fri'},
  ]);
});

// A fixed offset or 24-hour subtraction would misclassify at least one edge
// of these 23- and 25-hour local days. The repeated fall hour is one day.
for (const fixture of [
  {
    name: 'spring forward', date: '2026-03-08', previous: '2026-03-07',
    start: '2026-03-08T08:00:00.000Z', beforeStart: '2026-03-08T07:59:59.999Z',
    transition: ['2026-03-08T09:59:59.999Z', '2026-03-08T10:00:00.000Z'],
    beforeEnd: '2026-03-09T06:59:59.999Z', end: '2026-03-09T07:00:00.000Z',
  },
  {
    name: 'fall back', date: '2026-11-01', previous: '2026-10-31',
    start: '2026-11-01T07:00:00.000Z', beforeStart: '2026-11-01T06:59:59.999Z',
    transition: ['2026-11-01T08:30:00.000Z', '2026-11-01T09:30:00.000Z'],
    beforeEnd: '2026-11-02T07:59:59.999Z', end: '2026-11-02T08:00:00.000Z',
  },
]) {
  test(`uses both local midnight boundaries across ${fixture.name}`, () => {
    const {start, end, beforeStart, beforeEnd, transition, date, previous} = fixture;
    const saturday = {day: previous, weekday: 'Sat'}, sunday = {day: date, weekday: 'Sun'};
    assert.deepEqual(pastDays(new Date(beforeStart), zone, [beforeStart, start]), []);
    assert.deepEqual(pastDays(new Date(start), zone, [beforeStart, start]), [saturday]);
    assert.deepEqual(pastDays(new Date(beforeEnd), zone, [start, beforeEnd, end]), []);
    // Each instant alone must qualify; another frame must not mask a dropped edge or repeat.
    for (const frame of [start, ...transition, beforeEnd]) {
      assert.deepEqual(pastDays(new Date(end), zone, [frame, end]), [sunday], frame);
    }
    assert.deepEqual(pastDays(new Date(end), zone, [end, beforeEnd, beforeStart, ...transition, start]), [saturday, sunday]);
  });
}
