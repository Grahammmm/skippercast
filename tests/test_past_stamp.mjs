import assert from 'node:assert/strict';
import test from 'node:test';
import {pastStamp} from '../web/map/past-stamp.ts';

const invalidZone = 'Invalid/Zone';
const past = (day) => ({kind: 'past', offset: 1, day, weekday: 'Mon'});

test('C1: today takes priority over a missing frame', () => {
  assert.deepEqual(pastStamp({kind: 'today'}, null, invalidZone), {show: false, reason: 'today'});
});

test('C1: an unshown choice takes priority over a missing frame', () => {
  const choice = {kind: 'unshown', offset: 1, day: '2026-03-08', reason: 'not-observed'};
  assert.deepEqual(pastStamp(choice, null, invalidZone), {show: false, reason: 'unshown'});
});

test('C1: a shown choice without a frame has no stamp before time validation', () => {
  assert.deepEqual(pastStamp(past('2026-03-08'), null, invalidZone), {show: false, reason: 'no-frame'});
});

test('C1: a zone-less time is not resolved in the host zone', () => {
  assert.deepEqual(pastStamp(past('2026-03-08'), '2026-03-08T12:00:00', invalidZone), {
    show: false, reason: 'bad-time',
  });
});

test('C1: February 30 is not rolled into a matching March day', () => {
  assert.deepEqual(pastStamp(past('2026-03-02'), '2026-02-30T12:00:00Z', 'UTC'), {
    show: false, reason: 'bad-time',
  });
});

test('C1: a syntactically shaped but impossible offset never reaches localParts', () => {
  assert.deepEqual(pastStamp(past('2026-03-08'), '2026-03-08T12:00:00+24:00', 'UTC'), {
    show: false, reason: 'bad-time',
  });
});

// At UTC−12 the final UTC second that can still be on the previous local day is 11:59:59.
const utcLateForPreviousDay = '2026-03-08T11:59:59Z';

test('C2: a UTC date matching the choice does not excuse a local-day mismatch', () => {
  assert.deepEqual(pastStamp(past('2026-03-08'), utcLateForPreviousDay, 'Etc/GMT+12'), {
    show: false, reason: 'day-mismatch',
  });
});

test('C2: a previous local day uses the frame weekday, not the choice weekday', () => {
  assert.deepEqual(pastStamp(past('2026-03-07'), utcLateForPreviousDay, 'Etc/GMT+12'), {
    show: true, day: '2026-03-07', weekday: 'Sat',
  });
});

test('C2: local midnight moves in UTC after spring forward', () => {
  const zone = 'America/Los_Angeles';
  assert.deepEqual(pastStamp(past('2026-03-07'), '2026-03-08T07:30:00Z', zone), {
    show: true, day: '2026-03-07', weekday: 'Sat',
  });
  assert.deepEqual(pastStamp(past('2026-03-09'), '2026-03-09T07:30:00Z', zone), {
    show: true, day: '2026-03-09', weekday: 'Mon',
  });
});

test('C2: applying the frame offset can move the stamp across a date boundary', () => {
  assert.deepEqual(pastStamp(past('2024-02-29'), '2024-03-01T00:15:30.125+0130', 'UTC'), {
    show: true, day: '2024-02-29', weekday: 'Thu',
  });
});

test('C2: an invalid region zone with a valid instant is not replaced by UTC', () => {
  assert.throws(() => pastStamp(past('2026-03-08'), '2026-03-08T12:00:00Z', invalidZone), RangeError);
});
