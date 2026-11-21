import test from 'node:test';
import assert from 'node:assert/strict';
import {WATCHES_PER_SPOT, WATCHES_PER_OWNER, watchRoom} from '../server/spot-watch-limits.ts';

const spotId = 'reef';
const onSpot = count => Array.from({length: count}, () => ({spot_id: spotId}));
const elsewhere = count => Array.from({length: count}, (_, i) => ({spot_id: `reef-${i}`}));

// Catch swapped or drifting exported limits, or room reported before insertion.
test('C1: exports the limits and reports room for an empty owner', () => {
  assert.deepEqual([WATCHES_PER_SPOT, WATCHES_PER_OWNER], [5, 50]);
  assert.deepEqual(watchRoom([], spotId), {ok: true, spotLeft: 4, ownerLeft: 49});
});

// Catch spot counts that include other IDs or reject the last available slot.
test('C1: counts only matching rows toward the spot limit', () => {
  assert.deepEqual(watchRoom([...onSpot(4), ...elsewhere(3)], spotId),
    {ok: true, spotLeft: 0, ownerLeft: 42});
  assert.deepEqual(watchRoom(onSpot(5), spotId), {ok: false, limit: 'spot'});
  assert.deepEqual(watchRoom(onSpot(6), spotId), {ok: false, limit: 'spot'});
});

// Catch owner counts scoped to one spot, off-by-ones, or reversed limit priority.
test('C2: checks the owner boundary before the spot boundary', () => {
  assert.deepEqual(watchRoom([...onSpot(4), ...elsewhere(45)], spotId),
    {ok: true, spotLeft: 0, ownerLeft: 0});
  assert.deepEqual(watchRoom(elsewhere(50), spotId), {ok: false, limit: 'owner'});
  assert.deepEqual(watchRoom([...onSpot(5), ...elsewhere(45)], spotId), {ok: false, limit: 'owner'});
  assert.deepEqual(watchRoom(elsewhere(51), spotId), {ok: false, limit: 'owner'});
});

// Catch coercion or a length check that excludes the final valid length.
test('C2: accepts a 64-character ID and rejects empty, long and non-string IDs', () => {
  const longest = 'x'.repeat(64);
  assert.deepEqual(watchRoom([{spot_id: longest}], longest), {ok: true, spotLeft: 3, ownerLeft: 48});
  for (const id of ['', `${longest}x`, null, undefined, 7, false, new String(spotId)]) {
    assert.deepEqual(watchRoom([], id), {ok: false, limit: 'bad-spot'});
  }
  assert.deepEqual(watchRoom(elsewhere(50), ''), {ok: false, limit: 'bad-spot'});
});

// Catch coercion, throwing on a bad row, abandoning later rows, or mutating input.
test('C3: malformed rows occupy only owner slots without mutating the input', () => {
  const unreadable = Object.freeze({get spot_id() { throw new Error('unreadable row'); }});
  const boxedId = Object.freeze(new String(spotId));
  const existing = Object.freeze([
    null, undefined, Object.freeze({}), Object.freeze({spot_id: 7}),
    Object.freeze({spot_id: boxedId}), unreadable, ...onSpot(4).map(Object.freeze),
  ]);
  assert.deepEqual(watchRoom(existing, spotId), {ok: true, spotLeft: 0, ownerLeft: 39});
  assert.deepEqual(watchRoom([...existing, ...elsewhere(40)], spotId), {ok: false, limit: 'owner'});
});
