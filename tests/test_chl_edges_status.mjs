import assert from 'node:assert/strict';
import test from 'node:test';
import {chlEdgesStatus, observedPercent} from '../web/map/chl-edges-status.ts';

const observedAt = '2026-11-20T12:00:00Z';
const now = new Date(observedAt);
const doc = {
  product: 'Synthetic chlorophyll', credit: 'Fixture credit', maxAgeMs: 172_800_000,
  observedAt, observedFraction: 0.5, withheld: null, edges: [],
};
const ready = overrides => ({state: 'ready', doc: {...doc, ...overrides}});

// Loading, a missing feed, and an error must not collapse into the same rail state.
test('C1: distinguish loading, none and error', () => {
  assert.deepEqual(chlEdgesStatus(null, now), {state: 'loading'});
  assert.deepEqual(chlEdgesStatus({state: 'none'}, now), {state: 'none'});
  assert.deepEqual(chlEdgesStatus({state: 'error'}, now), {state: 'error'});
});

// An empty edge list isn't withholding; a populated list reports its count, not just its presence.
test('C1: show zero or several eligible edges and retain the observed percent', () => {
  assert.deepEqual(chlEdgesStatus(ready({observedFraction: null}), now),
    {state: 'shown', edges: 0, observedPct: null});
  const edges = ['one', 'two', 'three'].map(id => ({
    id, observedAt, cells: 5, strength: 0.32, bandHalfWidthKm: 1.5, line: [[-131, 36], [-130, 37]],
  }));
  assert.deepEqual(chlEdgesStatus(ready({edges, observedFraction: 0.9999}), now),
    {state: 'shown', edges: 3, observedPct: 99});
});

// Keep the feed's exact reasons and coverage rather than treating all withholding as cloud or zero coverage.
for (const [reason, overrides, observedPct] of [
  ['withheld-clear-water', {withheld: 'too-little-clear-water', observedFraction: 0.004}, 1],
  ['no-usable-frame', {withheld: 'no-usable-frame', observedAt: null, observedFraction: null}, null],
  ['no-observation', {observedAt: null, observedFraction: null}, null],
  ['stale', {observedAt: '2026-11-17T12:00:00Z'}, 50],
  ['future', {observedAt: '2026-11-20T14:00:00Z'}, 50],
]) {
  test(`C1: project ${reason} with its observed percent`, () => {
    assert.deepEqual(chlEdgesStatus(ready(overrides), now), {state: 'withheld', reason, observedPct});
  });
}

// Distinguish unknown from zero, floor rather than round, and reserve the endpoints for exact coverage.
test('C2: convert observed fractions without implying zero or complete coverage', () => {
  for (const [fraction, expected] of [
    [null, null], [0, 0], [-0, 0], [0.004, 1], [0.01, 1], [0.016, 1], [0.5, 50],
    [0.999, 99], [0.9999, 99], [1 - Number.EPSILON / 2, 99], [1, 100],
  ]) assert.deepEqual(observedPercent(fraction), expected, String(fraction));
});
