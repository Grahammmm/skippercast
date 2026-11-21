import assert from 'node:assert/strict';
import test from 'node:test';
import { WATCH_LAYERS, WATCH_OPS, watchList } from '../web/spot-watch-list.ts';
import { WATCH_LAYERS as SERVER_LAYERS, WATCH_OPS as SERVER_OPS } from '../server/spot-watch-rules.ts';

const spot = { id: 'reef', name: 'Reef' };
const watch = (id, fields = {}) => ({ id, spot_id: spot.id, layer: 'water-temp', op: '>=', ...fields });
const row = (id, fields = {}) => ({
  id, layer: 'water-temp', op: '>=', a: null, b: null, enabled: false, firing: false, lastFiredAt: null, ...fields,
});
const group = ({ id, name }, watches) => ({ spotId: id, spotName: name, watches });

// An invalid row must not inflate the orphan count, and a later duplicate must not rename the group.
test('C1: group only valid matches and count unmatched valid watches', () => {
  const watches = [
    watch('listed'), watch('missing', { spot_id: 'missing' }), watch('no-key', { spot_id: undefined }),
    watch('no-coercion', { spot_id: ['reef'] }), watch('bad-spot-name', { spot_id: 'bad' }),
    watch('', { spot_id: 'missing' }), watch(1), watch(undefined), null, 5,
    watch('bad-layer', { layer: 'current', spot_id: 'missing' }), watch('no-layer', { layer: undefined }),
    watch('bad-op', { op: '>', spot_id: 'missing' }), watch('no-op', { op: undefined }),
  ];
  const spots = [null, 3, { id: '', name: 'Empty' }, { id: 1, name: 'Number' },
    { id: spot.id, name: 1 }, spot, { id: spot.id, name: 'Duplicate' }, { id: 'bad', name: '' }];
  assert.deepEqual(watchList(watches, spots), { groups: [group(spot, [row('listed')])], orphans: 4 });
  assert.deepEqual(watchList([watch('')], spots), { groups: [], orphans: 0 });
  assert.deepEqual(watchList([watch('listed')], []), { groups: [], orphans: 1 });
});

// Truthiness or a loose equality would make some paused rows fire.
test('C2: derive enabled and firing from the exact flag and state values', () => {
  for (const [enabled, isEnabled] of [[true, true], [1, true], [false, false], [0, false],
    [2, false], ['1', false], ['true', false], [null, false], [undefined, false]]) {
    for (const [last_state, isTrue] of [['true', true], ['false', false], ['unknown', false],
      [true, false], [null, false], [undefined, false]]) {
      assert.deepEqual(watchList([watch('flag', { enabled, last_state })], [spot]), {
        groups: [group(spot, [row('flag', { enabled: isEnabled, firing: isEnabled && isTrue })])], orphans: 0,
      }, `enabled=${typeof enabled}:${enabled}, last_state=${typeof last_state}:${last_state}`);
    }
  }
});

// Coercion, range revalidation or timestamp parsing would change the recorded row.
test('C2: copy finite numeric thresholds and string timestamps only', () => {
  const watches = [
    watch('copy', { layer: 'chlorophyll', op: 'between', a: 0, b: 1.25, last_fired_at: '2026-11-19T10:00:00Z' }),
    watch('empty', { a: null, b: '1.25', last_fired_at: '' }),
    watch('nonfinite', { a: NaN, b: -Infinity, last_fired_at: 1 }),
    watch('other', { layer: 'sst-contrast', op: '<=', a: Infinity, b: -3 }),
  ];
  assert.deepEqual(watchList(watches, [spot]), {
    groups: [group(spot, [
      row('copy', { layer: 'chlorophyll', op: 'between', a: 0, b: 1.25, lastFiredAt: '2026-11-19T10:00:00Z' }),
      row('empty', { lastFiredAt: '' }), row('nonfinite'),
      row('other', { layer: 'sst-contrast', op: '<=', b: -3 }),
    ])], orphans: 0,
  });
});

// Case-sensitive comparison or preserving arrival order would put the tied groups/rows in the wrong order.
test('C3: sort groups by base name then id, and rows by date string then id without reordering inputs', () => {
  const alphaA = { id: 'A', name: 'áLPHA' }, alphaB = { id: 'a', name: 'Alpha' };
  const spots = Object.freeze([spot, alphaB, { id: 'unused', name: 'First' }, alphaA].map(Object.freeze));
  const watches = Object.freeze([
    watch('mid-b', { created_at: '2026-11-19T09:00:00Z' }), watch('missing-b', { created_at: 3 }),
    watch('late', { created_at: '2026-11-19T10:00:00+02:00' }), watch('mid-A', { created_at: '2026-11-19T09:00:00Z' }),
    watch('missing-A'), watch('early', { created_at: '' }),
    watch('b', { spot_id: alphaB.id }), watch('a', { spot_id: alphaA.id }),
  ].map(Object.freeze));
  assert.deepEqual(watchList(watches, spots), {
    groups: [group(alphaA, [row('a')]), group(alphaB, [row('b')]),
      group(spot, ['early', 'mid-A', 'mid-b', 'late', 'missing-A', 'missing-b'].map(id => row(id)))], orphans: 0,
  });
});

// A client-side enum drifting from the rules could silently omit a valid watch.
test('C3: use the same layer and operator lists as the server', () => {
  assert.deepEqual({ layers: WATCH_LAYERS, ops: WATCH_OPS }, { layers: SERVER_LAYERS, ops: SERVER_OPS });
});

// Reading unchecked properties or iterating a revoked proxy must not break the whole list.
test('C3: tolerate uninspectable entries and lists', () => {
  const { proxy, revoke } = Proxy.revocable([], {});
  revoke();
  let getterCalls = 0;
  const accessor = { get id() { getterCalls++; } };
  assert.deepEqual(watchList([proxy, accessor, watch('ok')], [proxy, accessor, spot]), {
    groups: [group(spot, [row('ok')])], orphans: 0,
  });
  assert.deepEqual(watchList(proxy, [spot]), { groups: [], orphans: 0 });
  assert.deepEqual(watchList([watch('ok')], proxy), { groups: [], orphans: 1 });
  assert.equal(getterCalls, 0);
});
