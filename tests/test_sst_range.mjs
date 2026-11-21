import test from 'node:test';
import assert from 'node:assert/strict';
import {viewSamples, rangeOf, shownRange} from '../web/map/sst-range.ts';

test('C1: sample the cell centres west-to-east, then south-to-north', () => {
  const calls = [];
  const values = viewSamples((lon, lat) => {
    calls.push([lon, lat]);
    return lon + 10 * lat;
  }, [-4, 10, 4, 14], 2);
  assert.deepEqual(calls, [[-2, 11], [2, 11], [-2, 13], [2, 13]]);
  assert.deepEqual(values, [108, 112, 128, 132]);
});

test('C1: default to all 1024 centres of a 32 by 32 grid', () => {
  const values = viewSamples((lon, lat) => lon + 32 * lat, [-0.5, -0.5, 31.5, 31.5]);
  assert.deepEqual(values, Array.from({length: 1024}, (_, i) => i));
});

test('C1: n=1 takes the midpoint even when subtracting the bounds overflows', () => {
  const edge = Number.MAX_VALUE;
  assert.deepEqual(viewSamples((lon, lat) => lon + lat, [-edge, -edge, edge, edge], 1), [0]);
});

test('C1: skip missing, non-finite and throwing cells without dropping later values', () => {
  const cells = [null, 0, NaN, Infinity, undefined, 44, -Infinity, new Error('bad cell'), 38];
  let calls = 0;
  const values = viewSamples(() => {
    const cell = cells[calls++];
    if (cell instanceof Error) throw cell;
    return cell;
  }, [0, 0, 3, 3], 3);
  assert.equal(calls, 9);
  assert.deepEqual(values, [0, 44, 38]);
});

test('C1: valid bounds with no finite sample yield an empty array', () => {
  assert.deepEqual(viewSamples(() => null, [0, 0, 2, 2], 1), []);
});

for (const [label, bounds, n] of [
  ['non-finite west', [-Infinity, 0, 2, 2], 2],
  ['non-finite south', [0, -Infinity, 2, 2], 2],
  ['non-finite east', [0, 0, Infinity, 2], 2],
  ['non-finite north', [0, 0, 2, NaN], 2],
  ['zero width', [0, 0, 0, 2], 2],
  ['inverted longitude', [2, 0, 0, 2], 2],
  ['zero height', [0, 0, 2, 0], 2],
  ['inverted latitude', [0, 2, 2, 0], 2],
  ['zero n', [0, 0, 2, 2], 0],
  ['negative n', [0, 0, 2, 2], -1],
  ['fractional n', [0, 0, 2, 2], 1.5],
  ['infinite n', [0, 0, 2, 2], Infinity],
  ['NaN n', [0, 0, 2, 2], NaN],
]) {
  test(`C1: ${label} yields no samples and never calls the sampler`, () => {
    let calls = 0;
    assert.deepEqual(viewSamples(() => ++calls, bounds, n), []);
    assert.equal(calls, 0);
  });
}

test('C2: return null when the sample list is empty', () => {
  assert.deepEqual(rangeOf([]), null);
});

test('C2: return null when samples exist but none are finite', () => {
  assert.deepEqual(rangeOf([NaN, Infinity, -Infinity]), null);
});

test('C2: use the finite extrema of unsorted samples, not the first and last values', () => {
  assert.deepEqual(rangeOf([58, Infinity, 64, 47, NaN, -Infinity, 55]), {min: 47, max: 64});
});

test('C2: widen a uniform sampled field by half a degree on each side', () => {
  const samples = viewSamples(() => 58, [0, 0, 2, 2], 2);
  assert.deepEqual(rangeOf(samples), {min: 57.5, max: 58.5});
});

const analysis = {min: 50, max: 70};
const view = {min: 49.5, max: 50.5};
const previous = {min: 52, max: 59};

test('C3: analysis mode ignores view and previous ranges', () => {
  assert.deepEqual(shownRange({mode: 'analysis'}, analysis, view, previous),
    {min: 50, max: 70, mode: 'analysis', note: null});
});

test('C3: a view range takes precedence over previous and is not clamped', () => {
  assert.deepEqual(shownRange({mode: 'view'}, analysis, view, previous),
    {min: 49.5, max: 50.5, mode: 'view', note: null});
});

test('C3: an empty view retains the previous range and notes the lack of water', () => {
  assert.deepEqual(shownRange({mode: 'view'}, analysis, null, previous),
    {min: 52, max: 59, mode: 'view', note: 'no-water-in-view'});
});

test('C3: an empty view without a previous range uses analysis but stays in view mode', () => {
  const expected = {min: 50, max: 70, mode: 'view', note: 'no-water-in-view'};
  assert.deepEqual(shownRange({mode: 'view'}, analysis, null), expected);
  assert.deepEqual(shownRange({mode: 'view'}, analysis, null, null), expected);
});

for (const [label, min, max, expected] of [
  ['inside', 54, 63, {min: 54, max: 63, mode: 'custom', note: null}],
  ['equal to analysis', 50, 70, {min: 50, max: 70, mode: 'custom', note: null}],
  ['one end below analysis', 47, 63, {min: 50, max: 63, mode: 'custom', note: 'clamped'}],
  ['one end above analysis', 54, 73, {min: 54, max: 70, mode: 'custom', note: 'clamped'}],
  ['both ends outside analysis', 47, 73, {min: 50, max: 70, mode: 'custom', note: 'clamped'}],
  ['infinite inputs with finite intersection', -Infinity, Infinity,
    {min: 50, max: 70, mode: 'custom', note: 'clamped'}],
]) {
  test(`C3: custom range ${label} returns the intersection with the right note`, () => {
    assert.deepEqual(shownRange({mode: 'custom', min, max}, analysis, view, previous), expected);
  });
}

for (const [label, min, max, limits] of [
  ['disjoint range', 40, 48, analysis],
  ['touching at one end', 70, 75, analysis],
  ['equal custom ends', 56, 56, analysis],
  ['reversed custom ends', 65, 54, analysis],
  ['NaN lower end', NaN, 65, analysis],
  ['NaN upper end', 55, NaN, analysis],
  ['non-finite lower intersection end', -Infinity, 65, {min: -Infinity, max: 70}],
  ['non-finite upper intersection end', 55, Infinity, {min: 50, max: Infinity}],
]) {
  test(`C3: custom range with ${label} reverts to the analysis range`, () => {
    assert.deepEqual(shownRange({mode: 'custom', min, max}, limits, view, previous),
      {min: limits.min, max: limits.max, mode: 'analysis', note: 'reverted'});
  });
}
