import test from 'node:test';
import assert from 'node:assert/strict';
import {snapshotAction, isPending, pendingBatch} from '../server/catch-conditions-plan.ts';

const now = new Date('2026-11-20T12:00:00Z');
const entry = Object.freeze({started_at: '2026-11-20T11:00:00Z', lat: null, lon: null});
const future = {...entry, started_at: '2026-11-20T12:00:00.001Z'};
const pending = Object.freeze({v: 1, pending: true});

// An unreadable field must not turn a planning decision into a thrown error.
test('C1: an unreadable start yields a complete bad-time action', () => {
  const unreadable = {...entry, get started_at() { throw new Error('unreadable'); }};
  assert.deepEqual(snapshotAction(null, unreadable, now, false), {action: 'store', conditions: {v: 1, missing: 'bad time'}});
});

// Raw string equality would recompute the same instant; testing only normal
// mode and past entries would miss keep being placed too late in the rules.
test('C2: unchanged patches keep before checking zone, future, or degraded state', () => {
  assert.deepEqual(snapshotAction(entry, {...entry, started_at: '2026-11-20T06:00:00-05:00'}, now, false), {action: 'keep'});
  for (const unchanged of [entry, future, {...entry, started_at: '2026-11-20'}]) {
    assert.deepEqual(snapshotAction(unchanged, unchanged, now, true), {action: 'keep'});
  }
});

// Date.parse accepts zone-less input, and degraded mode must not hide bad time.
test('C2: create and changed patch reject zone-less and unparseable starts before degraded mode', () => {
  for (const started_at of ['2026-11-21', '2026-11-21T12:00:00', '2026-11-21 12:00:00 (UTC)', 'not a time Z']) {
    for (const before of [null, entry]) {
      assert.deepEqual(snapshotAction(before, {...entry, started_at}, now, true), {action: 'store', conditions: {v: 1, missing: 'bad time'}}, started_at);
    }
  }
  const bad = {...entry, started_at: '2026-13-20T12:00:00Z'};
  assert.deepEqual(snapshotAction(bad, bad, now, false), {action: 'store', conditions: {v: 1, missing: 'bad time'}});
});

// A future entry must not get queued merely because feeds are degraded.
test('C2: create and changed patch store future time before pending', () => {
  for (const before of [null, entry]) {
    for (const degraded of [false, true]) {
      assert.deepEqual(snapshotAction(before, future, now, degraded), {action: 'store', conditions: {v: 1, missing: 'future time'}});
    }
  }
});

// Both axes independently invalidate keep; exact clock equality is not future.
test('C2: create and changes to time or either coordinate compute or store pending', () => {
  const atNow = {...entry, started_at: 'Fri, 20 Nov 2026 12:00:00 GMT'};
  for (const [before, after] of [[null, atNow], [entry, atNow], [entry, {...entry, lat: 1}], [entry, {...entry, lon: 1}]]) {
    assert.deepEqual(snapshotAction(before, after, now, false), {action: 'compute'});
    assert.deepEqual(snapshotAction(before, after, now, true), {action: 'store', conditions: {v: 1, pending: true}});
  }
});

// === for position would conflate signed zero and treat unchanged NaN as a move.
test('C2: coordinate equality uses Object.is on both axes', () => {
  for (const key of ['lat', 'lon']) {
    assert.deepEqual(snapshotAction({...entry, [key]: 0}, {...entry, [key]: -0}, now, false), {action: 'compute'});
    assert.deepEqual(snapshotAction({...entry, [key]: NaN}, {...entry, [key]: NaN}, now, true), {action: 'keep'});
  }
});

// Truthiness, structural look-alikes with non-plain prototypes, or unguarded
// marker reads could send a malformed value to the filler or stop the batch.
test('C3: only a plain object with exact marker values is pending', () => {
  assert.deepEqual(isPending(pending), true);
  assert.deepEqual(isPending(Object.assign(Object.create(null), pending)), true);
  class Marker { v = 1; pending = true; }
  for (const value of [null, 'pending', {}, {pending: true}, {v: 1}, {v: '1', pending: true},
    {v: 2, pending: true}, {v: 1, pending: 1}, {v: 1, pending: false},
    Object.setPrototypeOf(Object.assign([], pending), null), new Marker(), Object.create(pending)]) {
    assert.deepEqual(isPending(value), false);
  }
});

test('C3: throwing marker getters and a revoked proxy are not pending', () => {
  function unreadable() { throw new Error('unreadable'); }
  const revoked = Proxy.revocable(pending, {});
  revoked.revoke();
  for (const value of [{get v() { return unreadable(); }, pending: true}, {v: 1, get pending() { return unreadable(); }}, revoked.proxy]) {
    assert.deepEqual(isPending(value), false);
  }
});

function row(id, created_at, conditions = pending) {
  return Object.freeze({id, created_at, conditions});
}

// Sorting strings or using input order for ties/NaN produces a different batch.
// Applying the limit before filtering loses the first usable entry.
test('C4: filter pending, sort by instant then id with unparseable times last, and cap the result', () => {
  const rows = Object.freeze([
    row('b', 'bad-z'), row('z', '2026-11-20T04:00:00Z'), row('later', '2026-11-20T03:00:00-05:00'),
    row('ignored', '2026-11-19T12:00:00Z', {v: 1, get pending() { throw new Error('unreadable'); }}),
    row('a', 'bad-a'), row('A', '2026-11-19T23:00:00-05:00'), row('first', '2026-11-20T02:00:00Z'),
    row('done', '2026-11-18T12:00:00Z', {v: 1, missing: 'bad time'}),
    {get conditions() { throw new Error('unreadable row'); }},
  ]);
  assert.deepEqual(pendingBatch(rows, 500), ['first', 'A', 'z', 'later', 'a', 'b']);
  assert.deepEqual(pendingBatch(rows, 1), ['first']);
  assert.deepEqual(pendingBatch(rows, 5), ['first', 'A', 'z', 'later', 'a']);
  assert.deepEqual(pendingBatch([], 1), []);
});

// A valid upper bound still has to truncate when the queue is longer.
test('C4: 500 is an inclusive maximum and caps the returned ids', () => {
  const ids = Array.from({length: 500}, (_, i) => String(i).padStart(3, '0'));
  const rows = ['500', ...ids].map(id => row(id, '2026-11-20T04:00:00Z'));
  assert.deepEqual(pendingBatch(rows, 500), ids);
});

// Reject instead of clamping, coercing or silently accepting an off-by-one cap.
test('C4: an invalid max throws exactly RangeError before scanning', () => {
  const unreadable = {get conditions() { throw new Error('should not scan'); }};
  for (const max of [-1, 0, 1.5, 501, NaN, Infinity, '1']) {
    assert.throws(() => pendingBatch([unreadable], max), error => error.constructor === RangeError, String(max));
  }
});
