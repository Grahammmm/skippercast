import assert from 'node:assert/strict';
import test from 'node:test';
import {ROSE_SIZE, ROSE_CENTRE, ROSE_COURSES, roseWedges, roseArrow, roseRows} from '../web/brief/heading-rose.ts';

const sectors = [
  [0, 7, 'go'],
  [45, 6.99, 'marginal'],
  [90, 4, 'marginal'],
  [135, 3.99, 'no-go'],
  [180, null, 'unknown'],
  [225, NaN, 'unknown'],
  [270, Infinity, 'unknown'],
  [315, -Infinity, 'unknown'],
];
const scores = sectors.map(([course, score]) => ({course, score}));
const invalidScores = [
  ['missing sector', scores.slice(1)],
  ['extra sector', [...scores, {course: 360, score: null}]],
  ['swapped sectors', [scores[1], scores[0], ...scores.slice(2)]],
  ['duplicate sector', [scores[1], ...scores.slice(1)]],
  ['sparse scores', Array(8)],
];

test('C1: fixed canvas and compass order', () => {
  // Prevent a viewbox/geometry mismatch or an east-first course list.
  assert.deepEqual([ROSE_SIZE, ROSE_CENTRE, ROSE_COURSES], [120, 60, [0, 45, 90, 135, 180, 225, 270, 315]]);
});

for (const [label, input] of invalidScores) {
  test(`C1: rejects ${label} for wedges`, () => {
    // Length alone, or validation with a hole-skipping iterator, can accept invalid slots.
    assert.throws(() => roseWedges(input), RangeError);
  });
}

for (const radius of [0, -1, 60.01, NaN, Infinity, -Infinity]) {
  test(`C1: rejects wedge radius ${radius}`, () => {
    // Bound-only comparisons can admit NaN, and rounding first can admit out-of-range radii.
    assert.throws(() => roseWedges(scores, radius), RangeError);
  });
}

function expectedWedges(paths) {
  return sectors.map(([course, , verdict], i) => ({course, verdict, d: paths[i]}));
}

test('C2: all default SVG paths with C1 verdicts at and around the thresholds', () => {
  // A rotated compass, reversed sweep or coerced missing score changes the full result.
  // The edge offsets are the signed permutations of 54 * sin(22.5°) and 54 * cos(22.5°).
  assert.deepEqual(roseWedges(scores), expectedWedges([
    'M60 60 L39.34 10.11 A54 54 0 0 1 80.66 10.11 Z',
    'M60 60 L80.66 10.11 A54 54 0 0 1 109.89 39.34 Z',
    'M60 60 L109.89 39.34 A54 54 0 0 1 109.89 80.66 Z',
    'M60 60 L109.89 80.66 A54 54 0 0 1 80.66 109.89 Z',
    'M60 60 L80.66 109.89 A54 54 0 0 1 39.34 109.89 Z',
    'M60 60 L39.34 109.89 A54 54 0 0 1 10.11 80.66 Z',
    'M60 60 L10.11 80.66 A54 54 0 0 1 10.11 39.34 Z',
    'M60 60 L10.11 39.34 A54 54 0 0 1 39.34 10.11 Z',
  ]));
});

test('C2: all SVG paths at the inclusive maximum radius', () => {
  // The maximum is legal, and both endpoints and arc radii must use the override.
  assert.deepEqual(roseWedges(scores, 60), expectedWedges([
    'M60 60 L37.04 4.57 A60 60 0 0 1 82.96 4.57 Z',
    'M60 60 L82.96 4.57 A60 60 0 0 1 115.43 37.04 Z',
    'M60 60 L115.43 37.04 A60 60 0 0 1 115.43 82.96 Z',
    'M60 60 L115.43 82.96 A60 60 0 0 1 82.96 115.43 Z',
    'M60 60 L82.96 115.43 A60 60 0 0 1 37.04 115.43 Z',
    'M60 60 L37.04 115.43 A60 60 0 0 1 4.57 82.96 Z',
    'M60 60 L4.57 82.96 A60 60 0 0 1 4.57 37.04 Z',
    'M60 60 L4.57 37.04 A60 60 0 0 1 37.04 4.57 Z',
  ]));
});

test('C2: format a positive radius that rounds to zero without trailing zeros', () => {
  // Validating the formatted radius or using toFixed would break this small-radius case.
  assert.deepEqual(roseWedges(scores, 0.004), expectedWedges(Array(8).fill('M60 60 L60 60 A0 0 0 0 1 60 60 Z')));
});

for (const [bearing, expected] of [
  [0, {bearing: 0, x: 60, y: 6}],
  [-0, {bearing: 0, x: 60, y: 6}],
  [90, {bearing: 90, x: 114, y: 60}],
  [359.6, {bearing: 359.6, x: 59.62, y: 6}],
  [-10, {bearing: 350, x: 50.62, y: 6.82}],
  [720, {bearing: 0, x: 60, y: 6}],
  [null, null],
  [NaN, null],
  [Infinity, null],
  [-Infinity, null],
]) {
  test(`C3: exact default arrow for ${Object.is(bearing, -0) ? '-0' : bearing}`, () => {
    // A default north arrow for unavailable data, premature rounding, or signed remainder leaks here.
    assert.deepEqual(roseArrow(bearing), expected);
  });
}

test('C3: round the tip at a custom radius without negative zero', () => {
  // Ignoring the override gives y=6; keeping signed zero leaks -0 into the tip.
  assert.deepEqual(roseArrow(0, 60.004), {bearing: 0, x: 60, y: 0});
});

function expectedRows(outCourse, backCourse) {
  return sectors.map(([course, score, verdict]) => ({
    course, verdict, score, out: course === outCourse, back: course === backCourse,
  }));
}

for (const [boundary, before, after] of [
  [22.5, 0, 45], [67.5, 45, 90], [112.5, 90, 135], [157.5, 135, 180],
  [202.5, 180, 225], [247.5, 225, 270], [292.5, 270, 315], [337.5, 315, 0],
]) {
  test(`C4: ${boundary} belongs to the clockwise row for either mark`, () => {
    // An inclusive upper edge double-marks boundaries; swapped marks fail these mixed cases.
    assert.deepEqual(roseRows(scores, {out: boundary, back: boundary - 0.001}), expectedRows(after, before));
    assert.deepEqual(roseRows(scores, {out: boundary - 0.001, back: boundary}), expectedRows(before, after));
    assert.deepEqual(roseRows(scores, {out: boundary + 0.001, back: boundary + 0.001}), expectedRows(after, after));
  });
}

for (const [out, back, outCourse, backCourse] of [
  [360, 360, 0, 0],
  [350, -45, 0, 315],
  [null, 90, null, 90],
  [180, null, 180, null],
  [null, null, null, null],
  [NaN, Infinity, null, null],
  [-Infinity, NaN, null, null],
]) {
  test(`C4: exact rows for out=${out} and back=${back}`, () => {
    // Wrapping, missing marks, or normalising the score itself can change an otherwise plausible row.
    assert.deepEqual(roseRows(scores, {out, back}), expectedRows(outCourse, backCourse));
  });
}

for (const [label, input] of invalidScores) {
  test(`C4: rejects ${label} for rows`, () => {
    // Screen-reader rows must not silently accept invalid input even without arrow marks.
    assert.throws(() => roseRows(input, {out: null, back: null}), RangeError);
  });
}
