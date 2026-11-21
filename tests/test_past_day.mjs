import assert from 'node:assert/strict';
import test from 'node:test';
import {parsePastOffset, pastDayParam, resolvePastDay} from '../web/past-day.ts';

const zone = 'America/Los_Angeles';
const offsets = [1, 2, 3, 4, 5, 6, 7];

// Catch returning the signed wire value or excluding either endpoint.
test('C1: parses each of the seven literal values as a positive offset', () => {
  assert.deepEqual(['-1', '-2', '-3', '-4', '-5', '-6', '-7'].map(parsePastOffset), offsets);
});

// Coercion, trimming, Unicode digits, and prefix matching would admit aliases.
test('C1: rejects noncanonical spellings', () => {
  for (const value of [
    null, '', '-0', '-8', '-9', '-10', '-01', ' -1', '-1 ', '\t-1', '-1\n',
    '-1\r', '-1\u2028', '\u00a0-1', '- 1', '−1', '-１', '+1', '+-1', '1',
    '-1.0', '-1e0', '-1x', '--1', '2026-03-08',
  ]) {
    assert.equal(parsePastOffset(value), null, JSON.stringify(value));
  }
});

// Falls back before doing any calendar work, even with an unusable zone.
test('C2: absent and malformed offsets select today', () => {
  const now = new Date('2026-03-09T07:00:00Z');
  for (const value of [null, '-8', '2026-03-08']) {
    assert.deepEqual(resolvePastDay(value, now, 'Invalid/Zone', []), {kind: 'today'});
  }
});

// Subtracting 24 elapsed hours at this boundary lands on Saturday instead.
test('C2: selects Sunday at the first local midnight after spring forward', () => {
  const now = new Date('2026-03-09T07:00:00Z');
  const available = ['2026-03-07T12:00:00Z', '2026-03-09T06:59:59Z'];
  assert.deepEqual(resolvePastDay('-1', now, zone, available), {
    kind: 'past', offset: 1, day: '2026-03-08', weekday: 'Sun',
  });
});

// Near the end of the 25-hour Sunday, both subtracting 24 elapsed hours
// and treating the UTC date as Today would target Sunday instead of Saturday.
test('C2: selects Saturday late on the local fall-back Sunday', () => {
  const now = new Date('2026-11-02T07:59:59Z');
  const available = ['2026-10-31T12:00:00Z', '2026-11-01T09:30:00Z'];
  assert.deepEqual(resolvePastDay('-1', now, zone, available), {
    kind: 'past', offset: 1, day: '2026-10-31', weekday: 'Sat',
  });
});

// The oldest allowed offset crosses both month and year; UTC is still Dec 31.
test('C2: resolves the seventh local day across a month and year boundary', () => {
  const now = new Date('2025-12-31T18:30:00Z');
  assert.deepEqual(resolvePastDay('-7', now, 'Asia/Kolkata', ['2025-12-25T12:00:00Z']), {
    kind: 'past', offset: 7, day: '2025-12-25', weekday: 'Thu',
  });
});

// A sparse feed cannot shift the offset to the second observation or reset it to Today.
test('C2: reports the selected date when it has no observation', () => {
  const now = new Date('2026-04-02T07:00:00Z');
  const available = ['2026-04-01T12:00:00Z', '2026-03-30T12:00:00Z'];
  assert.deepEqual(resolvePastDay('-2', now, zone, available), {
    kind: 'unshown', offset: 2, day: '2026-03-31', reason: 'not-observed',
  });
});

// A bad zone for a valid selection must not be silently replaced by UTC.
test('C2: propagates the invalid-zone RangeError', () => {
  assert.throws(
    () => resolvePastDay('-1', new Date('2026-03-09T07:00:00Z'), 'Invalid/Zone', []),
    {constructor: RangeError},
  );
});

// Independent expected spellings catch a parser and formatter agreeing on the wrong wire form.
test('C3: formats and round-trips all seven offsets', () => {
  const params = offsets.map(pastDayParam);
  assert.deepEqual(params, ['-1', '-2', '-3', '-4', '-5', '-6', '-7']);
  assert.deepEqual(params.map(parsePastOffset), offsets);
});

// Bounds alone would admit a fractional offset or NaN.
test('C3: throws RangeError for invalid offsets', () => {
  for (const offset of [0, -0, -1, 8, 1.5, NaN, Infinity, -Infinity]) {
    assert.throws(() => pastDayParam(offset), {constructor: RangeError}, String(offset));
  }
});
