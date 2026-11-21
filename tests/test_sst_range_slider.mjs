import test from 'node:test';
import assert from 'node:assert/strict';
import {customMode, keyHandle, moveHandle, sliderBounds, STEP_F} from '../web/map/sst-range-slider.ts';
import {shownRange} from '../web/map/sst-range.ts';

const analysis = {min: 50.1, max: 69.9};
const bounds = {lo: 50.5, hi: 69.5};
const range = Object.freeze({min: 55, max: 65});

test('C1: round fractional bounds inward, not to the nearest or outward step', () => {
  assert.deepEqual(STEP_F, 0.5);
  assert.deepEqual(sliderBounds(analysis), bounds);
});

test('C1: accept an exact one-step span rather than discarding it', () => {
  assert.deepEqual(sliderBounds({min: 55, max: 55.5}), {lo: 55, hi: 55.5});
});

for (const [label, limits] of [
  ['one point on the grid after inward rounding', {min: 54.9, max: 55.4}],
  ['no points on the grid', {min: 55.1, max: 55.4}],
  ['non-finite min', {min: -Infinity, max: 65}],
  ['non-finite max', {min: 55, max: Infinity}],
  ['NaN that would bypass a width comparison', {min: 55, max: NaN}],
]) {
  test(`C1: reject ${label}`, () => {
    assert.deepEqual(sliderBounds(limits), null);
  });
}

for (const [label, which, input, expected] of [
  ['round down just below the midpoint', 'min', 57.249, {min: 57, max: 65}],
  ['round up at the midpoint', 'min', 57.25, {min: 57.5, max: 65}],
  ['round up just above the midpoint', 'max', 62.251, {min: 55, max: 62.5}],
  ['round down on the other half-step interval', 'max', 62.749, {min: 55, max: 62.5}],
  ['round up at the other midpoint', 'max', 62.75, {min: 55, max: 63}],
  ['clamp below the lower bound', 'min', 49.9, {min: 50.5, max: 65}],
  ['clamp above the upper bound', 'max', 70.2, {min: 55, max: 69.5}],
  ['allow exactly a one-step gap from min', 'min', 64.5, {min: 64.5, max: 65}],
  ['allow exactly a one-step gap from max', 'max', 55.5, {min: 55, max: 55.5}],
  ['stop min a step away when snapping would make the handles meet', 'min', 64.75, {min: 64.5, max: 65}],
  ['stop max a step away when snapping would make the handles meet', 'max', 55.24, {min: 55, max: 55.5}],
  ['stop min rather than let it cross max', 'min', 67, {min: 64.5, max: 65}],
  ['stop max rather than let it cross min', 'max', 52, {min: 55, max: 55.5}],
]) {
  test(`C2: ${label} without moving the other handle`, () => {
    assert.deepEqual(moveHandle(range, which, input, bounds), expected);
  });
}

test('C2: round a negative tie toward the higher temperature, not away from zero', () => {
  assert.deepEqual(moveHandle({min: -4, max: -1}, 'min', -2.25, {lo: -5, hi: 0}),
    {min: -2, max: -1});
});

for (const input of [NaN, Infinity, -Infinity]) {
  test(`C2: copy the unchanged range for ${input} instead of returning an alias or clamping it`, () => {
    const result = moveHandle(range, 'min', input, bounds);
    assert.deepEqual(result, {min: 55, max: 65});
    assert.notStrictEqual(result, range);
  });
}

for (const [which, key, expected] of [
  ['min', 'ArrowLeft', {min: 54.5, max: 65}],
  ['max', 'ArrowDown', {min: 55, max: 64.5}],
  ['min', 'ArrowRight', {min: 55.5, max: 65}],
  ['max', 'ArrowUp', {min: 55, max: 65.5}],
  ['min', 'PageDown', {min: 52.5, max: 65}],
  ['max', 'PageUp', {min: 55, max: 67.5}],
  ['min', 'Home', {min: 50.5, max: 65}],
  ['max', 'End', {min: 55, max: 69.5}],
  ['max', 'Home', {min: 55, max: 55.5}],
  ['min', 'End', {min: 64.5, max: 65}],
  ['min', 'Enter', null],
]) {
  test(`C3: route ${key} on ${which} to the expected value or ignore it`, () => {
    assert.deepEqual(keyHandle(range, which, key, bounds), expected);
  });
}

test('C3: convert slider endpoints to custom mode without reclamping in shownRange', () => {
  const {lo, hi} = sliderBounds(analysis);
  const mode = customMode({min: lo, max: hi});
  assert.deepEqual(mode, {mode: 'custom', min: 50.5, max: 69.5});
  assert.deepEqual(shownRange(mode, analysis, null),
    {min: 50.5, max: 69.5, mode: 'custom', note: null});
});
