import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PENDING_MAX_AGE_DAYS, PENDING_BATCH_MAX, expiredConditions, pendingBatch,
} from '../server/catch-conditions-pending.ts';
import { parseConditionsV1 } from '../server/conditions-v1.ts';

const now = new Date('2026-11-20T12:00:00.000Z');
const row = (id, started_at = '2026-11-20T11:00:00Z', conditions = { v: 1, pending: true }) =>
  ({ id, started_at, conditions });

// Changing either constant would silently move an operational limit.
test('C1: exported age and batch caps', () => {
  assert.deepEqual([PENDING_MAX_AGE_DAYS, PENDING_BATCH_MAX], [8, 100]);
});

// Checking only for a truthy pending field admits invalid variants; decoding only one format loses valid work.
test('C1: only validator-approved pending snapshots participate, in either storage form', () => {
  const revoked = Proxy.revocable({}, {});
  revoked.revoke();
  const rows = [
    row('object'),
    row('json', '2026-11-20T10:00:00Z', '{"v":1,"pending":true}'),
    row('complete', '2026-11-20T08:00:00Z', { v: 1, at: '2026-11-20T08:00:00Z', layers: {} }),
    row('missing', '2026-11-11T08:00:00Z', '{"v":1,"missing":"no region"}'),
    row('wrong-version', '2026-11-20T08:00:00Z', { v: 2, pending: true }),
    row('not-pending', '2026-11-20T08:00:00Z', { v: 1, pending: false }),
    row('extra-key', '2026-11-20T08:00:00Z', { v: 1, pending: true, extra: true }),
    row('malformed-json', '2026-11-20T08:00:00Z', '{"v":1,"pending":true'),
    row('no-value', '2026-11-20T08:00:00Z', null),
    row('revoked', '2026-11-20T08:00:00Z', revoked.proxy),
  ];
  assert.deepEqual(pendingBatch(rows, now, 100), { fill: ['json', 'object'], expire: [], skipped: 0 });
});

// Inclusive comparisons would misclassify rows exactly at the two time cutoffs.
test('C2: the 8-day and 5-minute boundaries are inclusive for fill', () => {
  const rows = [
    row('just-too-far', '2026-11-20T12:05:00.001Z'),
    row('future-boundary', '2026-11-20T12:05:00.000Z'),
    row('just-in-time', '2026-11-12T12:00:00.001Z'),
    row('past-boundary', '2026-11-12T12:00:00.000Z'),
    row('just-too-old', '2026-11-12T11:59:59.999Z'),
  ];
  assert.deepEqual(pendingBatch(rows, now, 100), {
    fill: ['past-boundary', 'just-in-time', 'future-boundary'], expire: ['just-too-old'], skipped: 1,
  });
});

// A truthiness check alone admits numeric IDs; Date.parse alone admits local times and rolls invalid days.
test('C2: invalid pending metadata is skipped, not filled or expired', () => {
  for (const invalid of [
    row('not-a-time', 'not a time'), row('local', '2026-11-20T11:00:00'),
    row('rolled', '2026-09-31T01:00:00Z'), row('end-of-day', '2026-11-19T24:00:00Z'),
    row('overflow', '2026-11-20T11:99:00Z'), row('non-text-time', 0), row(''), row(1),
  ]) {
    assert.deepEqual(pendingBatch([invalid], now, 100), { fill: [], expire: [], skipped: 1 });
  }
  assert.deepEqual(pendingBatch([row('utc', '2026-11-20T11:00+00:00')], now, 1), {
    fill: ['utc'], expire: [], skipped: 0,
  });
});

// Taking the first rows before ordering loses older work and gives input-order ties at the cutoff.
test('C3: oldest first, ascending ID fill ties, and independent oldest-first expiry', () => {
  const rows = Object.freeze([
    row('older-expiry', '2026-11-10T00:00:00Z'), row('z'), row('first', '2026-11-14T00:00:00Z'),
    row('a', '2026-11-20T11:00:00.000Z'), row('oldest-expiry', '2026-11-09T00:00:00Z'),
  ].map(entry => Object.freeze({ ...entry, conditions: Object.freeze(entry.conditions) })));
  assert.deepEqual(pendingBatch(rows, now, 2), {
    fill: ['first', 'a'], expire: ['oldest-expiry', 'older-expiry'], skipped: 0,
  });
  assert.deepEqual(now, new Date('2026-11-20T12:00:00.000Z'));
});

// An early exit for a zero cap would lose expiry and skip reporting; slice can coerce bad limits.
test('C3: zero and invalid fill limits leave expiry and skipped intact', () => {
  const rows = [row('fill'), row('expire', '2026-11-11T00:00:00Z'), row('skip', 'invalid')];
  for (const limit of [0, -1, 1.5, NaN, Infinity, '1']) {
    assert.deepEqual(pendingBatch(rows, now, limit), { fill: [], expire: ['expire'], skipped: 1 });
  }
});

// A shared or missing cap could either drop expiry work or let fill exceed its hard maximum.
test('C3: the hard cap applies only to fill', () => {
  const fill = Array.from({ length: 100 }, (_, i) => `fill-${String(i).padStart(3, '0')}`);
  const expire = Array.from({ length: 101 }, (_, i) => `expire-${i}`);
  const rows = [row('fill-100'), ...fill.slice().reverse().map(id => row(id)),
    ...expire.map((id, i) => row(id, new Date(Date.UTC(2026, 10, 11, 0, 0, i)).toISOString()))];
  assert.deepEqual(pendingBatch(rows, now, 101), { fill, expire, skipped: 0 });
});

// NaN age can otherwise pass both comparisons and queue fills without a usable clock.
test('C3: empty work and an invalid clock return whole results without throwing', () => {
  assert.deepEqual(pendingBatch([], now, 1), { fill: [], expire: [], skipped: 0 });
  assert.deepEqual(pendingBatch([row('pending')], new Date(NaN), 1), { fill: [], expire: [], skipped: 1 });
});

// Reusing a mutable sentinel can corrupt the next expired entry.
test('C3: expiry yields a fresh validator-approved missing snapshot', () => {
  const expected = { v: 1, missing: 'not archived' };
  const first = expiredConditions();
  assert.deepEqual(first, expected);
  first.missing = 'changed';
  const next = expiredConditions();
  assert.deepEqual(next, expected);
  assert.deepEqual(parseConditionsV1(next), { ok: true, value: expected });
});
