// MAPLAYER-TIDE-1: tide-layer.js state maths, wording and declutter (pure functions, no browser).
import test from 'node:test';
import assert from 'node:assert/strict';
import {tideState, colorFor, sizeFor, describe, declutter, FLOOD, EBB, STAND, MAX_FT_PER_H} from '../research/scripts/map_style/tide-layer.js';

const ex = [
  {t: '2026-11-07T03:00Z', type: 'H', v: 5.0},
  {t: '2026-11-07T09:00Z', type: 'L', v: -1.0},
  {t: '2026-11-07T15:00Z', type: 'H', v: 5.0},
];
const at = (iso) => Date.parse(iso);

test('level is the predicted height at the extremes and midway between', () => {
  assert.equal(tideState(ex, at('2026-11-07T03:00Z')).level, 5.0);
  assert.ok(Math.abs(tideState(ex, at('2026-11-07T09:00Z')).level - -1.0) < 1e-9);
  assert.ok(Math.abs(tideState(ex, at('2026-11-07T06:00Z')).level - 2.0) < 1e-9);
});

test('falling after a high, rising after a low, standing at the turn', () => {
  const mid1 = tideState(ex, at('2026-11-07T06:00Z'));
  assert.equal(mid1.state, 'falling');
  assert.ok(mid1.rate < 0);
  assert.ok(Math.abs(mid1.rate - -(6 * Math.PI / 2) / 6) < 1e-9);   // peak rate: range * pi/2 / hours
  assert.equal(tideState(ex, at('2026-11-07T12:00Z')).state, 'rising');
  assert.equal(tideState(ex, at('2026-11-07T09:05Z')).state, 'stand');
});

test('outside the predicted window is reported, never extrapolated', () => {
  assert.equal(tideState(ex, at('2026-11-07T02:00Z')).state, 'outside');
  assert.equal(tideState(ex, at('2026-11-07T16:00Z')).state, 'outside');
  const d = describe({name: 'X', extremes: ex}, at('2026-11-08T00:00Z'));
  assert.equal(d.state, 'outside');
  assert.match(d.lines[0], /Predictions end/);
});

test('colours follow the study: green flood, red ebb, grey at the stand; size grows with the rate and saturates', () => {
  assert.equal(colorFor('rising'), FLOOD);
  assert.equal(colorFor('falling'), EBB);
  assert.equal(colorFor('stand'), STAND);
  assert.equal(sizeFor(0), 20);
  assert.equal(sizeFor(-MAX_FT_PER_H), 46);
  assert.equal(sizeFor(10), 46);
  assert.ok(sizeFor(0.8) > sizeFor(0.4));
});

test('wording names the near extreme at a stand and the next one always', () => {
  const justAfterHigh = describe({name: 'A', extremes: ex}, at('2026-11-07T03:05Z'));
  assert.match(justAfterHigh.lines[0], /^Near high/);
  assert.match(justAfterHigh.lines[1], /^next low -1\.0 ft/);
  const falling = describe({name: 'A', extremes: ex}, at('2026-11-07T06:00Z'));
  assert.match(falling.lines[0], /^Falling 1\.6 ft\/h · 2\.0 ft/);
});

test('declutter keeps the first of any group closer than the limit', () => {
  const pts = {a: {x: 0, y: 0}, b: {x: 10, y: 0}, c: {x: 100, y: 0}};
  const keep = declutter([{id: 'a'}, {id: 'b'}, {id: 'c'}], (s) => pts[s.id], 34);
  assert.deepEqual(keep.map((s) => s.id), ['a', 'c']);
  assert.equal(declutter([{id: 'a'}, {id: 'b'}], (s) => pts[s.id], 0).length, 2);
});
