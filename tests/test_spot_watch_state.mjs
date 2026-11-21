import test from 'node:test';
import assert from 'node:assert/strict';
import {conditionMet, nextWatchState} from '../server/spot-watch-state.ts';

const cond = {op: '>=', a: 58};
const initial = Object.freeze({state: 'unknown', lastSampleAt: null});
const last = '2026-11-19T12:00:00Z';
const newer = '2026-11-20T12:00:00Z';
const older = '2026-11-18T12:00:00Z';

// Strict inequalities would miss exact-threshold readings; treating a gap as
// false would incorrectly arm a watch. Test each operator at both kinds of edge.
test('watch comparisons use inclusive bounds and distinguish unavailable readings from false', () => {
  for (const [condition, rows] of [
    [cond, [[57.9, false], [58, true], [58.1, true]]],
    [{op: '<=', a: 58}, [[57.9, true], [58, true], [58.1, false]]],
    [{op: 'between', a: 58, b: 60}, [[57.9, false], [58, true], [59, true], [60, true], [60.1, false]]],
  ]) {
    for (const [value, met] of [...rows, [null, null], [NaN, null], [Infinity, null]]) {
      assert.equal(conditionMet(value, condition), met, `${condition.op}: ${value}`);
    }
  }
});

const results = [['false', 57.8], ['true', 58.4], ['unknown', null]];

// R4 truth table: columns are new readings of false / true / unknown. With
// the same or an older sample, none of the three readings can change anything.
// This catches refiring, resetting on gaps, and accepting a late publication.
test('every prior state × result × timestamp order', () => {
  for (const [state, onNewer] of [
    ['false', [['false', false], ['true', true], ['false', false]]],
    ['true', [['false', false], ['true', false], ['true', false]]],
    ['unknown', [['false', false], ['true', false], ['unknown', false]]],
  ]) {
    const prev = Object.freeze({state, lastSampleAt: last});
    for (const [i, [result, value]] of results.entries()) {
      const [next, fire] = onNewer[i];
      assert.deepEqual(nextWatchState(prev, value, newer, cond), {state: next, fire, lastSampleAt: newer}, `${state} / ${result} / newer`);
      for (const [order, sampleAt] of [['same', last], ['older', older]]) {
        assert.deepEqual(nextWatchState(prev, value, sampleAt, cond), {...prev, fire: false}, `${state} / ${result} / ${order}`);
      }
    }
  }
});

// "It fires only on a false → true transition" (R4): no synthetic false on creation.
test('first evaluation sets a baseline without firing', () => {
  for (const [state, value] of results) {
    assert.deepEqual(nextWatchState(initial, value, last, cond), {state, fire: false, lastSampleAt: last});
  }
});

// A newer withheld sample must advance the clock, without losing the last known
// false. A delayed reading must not fire; the next genuinely newer true must.
test('a withheld sample advances evaluation time without rearming or disarming the watch', () => {
  const below = nextWatchState(initial, 57.8, older, cond);
  const withheld = nextWatchState(below, null, newer, cond);
  assert.deepEqual(nextWatchState(withheld, 58.4, last, cond), {state: 'false', fire: false, lastSampleAt: newer});
  const fresh = '2026-11-21T12:00:00Z';
  const crossed = nextWatchState(withheld, 58.4, fresh, cond);
  assert.deepEqual(crossed, {state: 'true', fire: true, lastSampleAt: fresh});
  assert.deepEqual(nextWatchState(crossed, 58.4, fresh, cond), {...crossed, fire: false});
});

// An equivalent offset spelling (or a missing/unusable clock) cannot make a
// true reading newer. A genuinely newer offset timestamp need not sort later.
test('sample order uses instants, not timestamp text', () => {
  const prev = {state: 'false', lastSampleAt: last};
  for (const at of ['2026-11-19T13:00:00+01:00', null, 'not a time']) {
    assert.deepEqual(nextWatchState(prev, 58.4, at, cond), {...prev, fire: false});
  }
  const at = '2026-11-19T11:30:00-01:00';
  assert.deepEqual(nextWatchState(prev, 58.4, at, cond), {state: 'true', fire: true, lastSampleAt: at});
});
