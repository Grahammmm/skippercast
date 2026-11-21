import test from 'node:test';
import assert from 'node:assert/strict';
import {RANGE_MODES, modeKey, chooseRangeMode, rememberCustom} from '../web/map/sst-range-control.ts';
import {shownRange} from '../web/map/sst-range.ts';

test('C1: modes follow analysis, view, custom order', () => {
  assert.deepEqual(RANGE_MODES, ['analysis', 'view', 'custom']);
});

// Pin each key's destination independently of the exported order, including both stops.
for (const [current, left, right, home, end] of [
  ['analysis', 'analysis', 'view', 'analysis', 'custom'],
  ['view', 'analysis', 'custom', 'analysis', 'custom'],
  ['custom', 'view', 'custom', 'analysis', 'custom'],
]) {
  test(`C1: arrows, Home and End from ${current} do not wrap`, () => {
    assert.equal(modeKey(current, 'ArrowLeft'), left);
    assert.equal(modeKey(current, 'ArrowRight'), right);
    assert.equal(modeKey(current, 'Home'), home);
    assert.equal(modeKey(current, 'End'), end);
  });
}

const analysis = {min: 50, max: 70};
const fractionalView = {min: 51.2, max: 64.8};
const shown = shownRange({mode: 'view'}, analysis, fractionalView);
const remembered = {min: 55.2, max: 60.9};

test('C2: analysis and view do not carry custom ends', () => {
  assert.deepEqual(chooseRangeMode('analysis', shown, remembered), {mode: 'analysis'});
  assert.deepEqual(chooseRangeMode('view', shown, remembered), {mode: 'view'});
});

test('C2: remembered ends take priority over even an invalid shown range, without rounding', () => {
  assert.deepEqual(chooseRangeMode('custom', {...shown, min: NaN}, remembered),
    {mode: 'custom', min: 55.2, max: 60.9});
});

test('C2: fractional in-bounds view seeds inward and stays unclamped', () => {
  const seed = chooseRangeMode('custom', shown, null);
  assert.deepEqual(seed, {mode: 'custom', min: 51.5, max: 64.5});
  assert.deepEqual(shownRange(seed, analysis, fractionalView),
    {mode: 'custom', min: 51.5, max: 64.5, note: null});
});

test('C2: exact half-degree view ends stay unchanged even outside analysis bounds', () => {
  const shown = shownRange({mode: 'view'}, analysis, {min: 49.5, max: 50.5});
  assert.deepEqual(chooseRangeMode('custom', shown, null), {mode: 'custom', min: 49.5, max: 50.5});
});

for (const [label, min, max] of [
  ['equal', 51.2, 51.8],
  ['reversed', 51.6, 51.8],
]) {
  test(`C2: keep the unrounded shown ends when rounded ends are ${label}`, () => {
    assert.deepEqual(chooseRangeMode('custom', {...shown, min, max}, null), {mode: 'custom', min, max});
  });
}

// The same invalid ends must be ignored as memory, but must not seed a new range.
for (const [label, min, max] of [
  ['non-finite lower end', -Infinity, 60],
  ['non-finite upper end', 55, Infinity],
  ['equal ends', 55, 55],
  ['reversed ends', 60, 55],
]) {
  test(`C2: reject ${label} in remembered and shown ranges`, () => {
    assert.deepEqual(chooseRangeMode('custom', shown, {min, max}),
      {mode: 'custom', min: 51.5, max: 64.5});
    assert.deepEqual(chooseRangeMode('custom', {...shown, min, max}, null), {mode: 'analysis'});
  });
}

test('C3: a custom edit replaces saved ends and survives custom → view → custom', () => {
  const saved = rememberCustom({min: 52, max: 64}, {mode: 'custom', ...remembered});
  assert.deepEqual(saved, remembered);
  const view = chooseRangeMode('view', shown, saved);
  assert.deepEqual(view, {mode: 'view'});
  const afterView = rememberCustom(saved, view);
  assert.equal(afterView, saved);
  assert.deepEqual(chooseRangeMode('custom', shown, afterView), {mode: 'custom', min: 55.2, max: 60.9});
});

test('C3: analysis leaves existing or empty memory intact', () => {
  assert.equal(rememberCustom(remembered, {mode: 'analysis'}), remembered);
  assert.equal(rememberCustom(null, {mode: 'analysis'}), null);
});
