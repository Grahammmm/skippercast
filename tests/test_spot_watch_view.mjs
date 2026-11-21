import assert from 'node:assert/strict';
import {test} from 'node:test';
import {watchList, watchView} from '../server/spot-watch-view.ts';

const row = Object.freeze({
  id: 'watch-a', owner: 'fixture-owner', spot_id: 'spot-a', layer: 'water-temp', op: '>=',
  a: 58, b: null, enabled: 1, last_state: 'true', last_sample_at: '2026-11-19T12:00:00Z',
  last_fired_at: '2026-11-19T12:01:00Z', created_at: '2026-11-19T11:00:00Z',
});
const view = {
  id: 'watch-a', spotId: 'spot-a', layer: 'water-temp', op: '>=', a: 58, b: null,
  enabled: true, lastState: 'true', lastSampleAt: '2026-11-19T12:00:00Z',
  lastFiredAt: '2026-11-19T12:01:00Z', createdAt: '2026-11-19T11:00:00Z',
};

// Spreading the source row can leak private or internal columns and reorder the keys.
test('C1: projects a full row in key order without exposing private or extra fields', () => {
  const projected = watchView(Object.freeze({...row, internal: 'fixture-only'}));
  assert.deepEqual(projected, view);
  assert.deepEqual(Object.keys(projected), Object.keys(view));
});

// Using write-side validation here can reject readable stored data or erase its state.
test('C1: preserves stored values for the remaining operations, layers, and states', () => {
  const {b, ...withoutB} = row;
  const single = Object.assign(Object.create(null), withoutB, {
    layer: 'chlorophyll', op: '<=', a: 0, enabled: 0, last_state: 'false',
    last_sample_at: null, last_fired_at: null,
  });
  assert.deepEqual(watchView(single), {...view, layer: 'chlorophyll', op: '<=', a: 0,
    enabled: false, lastState: 'false', lastSampleAt: null, lastFiredAt: null});
  assert.deepEqual(watchView({...row, layer: 'sst-contrast', op: 'between', a: 1, b: 2,
    last_state: 'unknown', last_sample_at: '', last_fired_at: ''}),
  {...view, layer: 'sst-contrast', op: 'between', a: 1, b: 2, lastState: 'unknown',
    lastSampleAt: '', lastFiredAt: ''});
  assert.deepEqual(watchView({...row, last_state: null}), {...view, lastState: null});
});

// Checking only field values would also admit decorated arrays and class instances.
for (const [label, malformed] of [
  ['null', null], ['missing', undefined], ['scalar', 'row'],
  ['decorated function', Object.assign(() => {}, row)],
  ['array with ordinary prototype', Object.setPrototypeOf(Object.assign([], row), Object.prototype)],
  ['class instance', Object.assign(new (class StoredRow {})(), row)],
]) {
  test(`C1: rejects a ${label} row`, () => assert.deepEqual(watchView(malformed), null));
}

// The decoder must not coerce stored types, silently fill required values, or accept bad bounds.
for (const [field, badValues, overrides = {}] of [
  ['id', ['', 7, undefined]],
  ['spot_id', ['', 7, undefined]],
  ['created_at', ['', 7, undefined]],
  ['layer', ['wind', undefined]],
  ['op', ['>', undefined]],
  ['a', ['58', NaN, Infinity, -Infinity, null, undefined]],
  ['b', [60, undefined]],
  ['b', [null, undefined, '60', NaN, Infinity, -Infinity, 58, 57], {op: 'between'}],
  ['enabled', [true, false, 2, '1', null, undefined]],
  ['last_state', ['TRUE', true, undefined]],
  ['last_sample_at', [1, undefined]],
  ['last_fired_at', [1, undefined]],
]) {
  for (const value of badValues) {
    test(`C1: rejects ${field} = ${String(value)} (${typeof value}, ${overrides.op ?? row.op})`, () => {
      assert.deepEqual(watchView({...row, ...overrides, [field]: value}), null);
    });
  }
}

test('C1: rejects a between row with no upper column', () => {
  const {b, ...withoutB} = row;
  assert.deepEqual(watchView({...withoutB, op: 'between'}), null);
});

// A broken column must neither escape as an exception nor produce a partial view.
function unreadable(column, values = row) {
  return Object.defineProperty({...values}, column, {get() { throw new Error('unreadable column'); }});
}
for (const column of ['spot_id', 'id', 'b']) {
  test(`C1: returns null when ${column} throws`, () => {
    assert.deepEqual(watchView(unreadable(column)), null);
  });
}

// A foreign or inherited spot must not contribute even to the malformed count.
test('C2: ignores rows without an own matching spot ID', () => {
  const {spot_id, ...withoutSpot} = row;
  const ignored = [null, ...['spot-b', 7].map(spot_id => ({...row, spot_id})),
    unreadable('id', {...row, spot_id: 'spot-b'}), unreadable('spot_id'),
    Object.assign(Object.create({spot_id}), withoutSpot), withoutSpot];
  assert.deepEqual(watchList([], 'spot-a'), {watches: [], dropped: 0});
  assert.deepEqual(watchList(ignored, 'spot-a'), {watches: [], dropped: 0});
});

// Input order, ID-only sorting, or filtering after validation can misorder or miscount this list.
test('C2: sorts a fresh list by creation time then ID and counts only matching malformed rows', () => {
  const earlier = '2026-11-18T11:00:00Z';
  const rows = Object.freeze([
    Object.freeze({...row, id: 'watch-z'}),
    Object.freeze({...row, id: 'watch-zz', created_at: earlier}),
    Object.freeze({...row, enabled: 2}),
    row,
    Object.freeze({...row, enabled: 0}),
    unreadable('id'),
    Object.assign([], row),
    Object.assign(() => {}, row),
    {...row, spot_id: 'spot-b', enabled: 2},
  ]);
  assert.deepEqual(watchList(rows, 'spot-a'), {watches: [
    {...view, id: 'watch-zz', createdAt: earlier}, view, {...view, enabled: false}, {...view, id: 'watch-z'},
  ], dropped: 4});
  assert.deepEqual(watchList([{...row, spot_id: ''}], ''), {watches: [], dropped: 1});
});
