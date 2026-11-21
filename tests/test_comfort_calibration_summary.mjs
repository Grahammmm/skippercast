import test from 'node:test';
import assert from 'node:assert/strict';
import {calibrationSummary} from '../web/comfort-calibration-summary.ts';

function calibration([headN, headResidual], [beamN, beamResidual], [followingN, followingResidual]) {
  return Object.freeze({
    groups: Object.freeze({
      head: Object.freeze({n: headN, residual: headResidual}),
      beam: Object.freeze({n: beamN, residual: beamResidual}),
      following: Object.freeze({n: followingN, residual: followingResidual}),
    }),
    minReports: 5,
  });
}

// C1–C2: Comparing signed residuals would skip the negative residual in the roadmap example.
test('C1: summarise the six-ride roadmap example', () => {
  assert.deepEqual(calibrationSummary(calibration([6, -0.8], [0, 0], [0, 0])), {
    reports: 6, group: 'head', points: 0.8, direction: 'rougher',
  });
});

// C1: Selecting the first group unconditionally would invent a direction in either case.
test('C1: count reports with zero residuals without naming a group', () => {
  assert.deepEqual(calibrationSummary(calibration([1, 0], [2, -0], [3, 0])), {
    reports: 6, group: null, points: 0, direction: null,
  });
});

test('C1: ignore residuals in empty groups', () => {
  assert.deepEqual(calibrationSummary(calibration([0, -3], [0, 2], [0, 1])), {
    reports: 0, group: null, points: 0, direction: null,
  });
  assert.deepEqual(calibrationSummary(calibration([0, -3], [1, 0.5], [0, 1])), {
    reports: 1, group: 'beam', points: 0.5, direction: 'smoother',
  });
});

// C1: Replacing > with >= or reordering the groups changes the winner on a tie.
for (const [pair, cal, expected] of [
  ['head and beam', calibration([1, 1], [1, -1], [1, 0.5]), {reports: 3, group: 'head', points: 1, direction: 'smoother'}],
  ['head and following', calibration([1, -1], [1, 0.5], [1, 1]), {reports: 3, group: 'head', points: 1, direction: 'rougher'}],
  ['beam and following', calibration([1, 0.5], [1, -1], [1, 1]), {reports: 3, group: 'beam', points: 1, direction: 'rougher'}],
]) {
  test(`C1: keep the earlier group when ${pair} tie in magnitude`, () => {
    assert.deepEqual(calibrationSummary(cal), expected);
  });
}

// C1–C2: Ranking by rounded points would tie these groups and incorrectly select head.
test('C2: select by raw magnitude and round 0.05 up', () => {
  assert.deepEqual(calibrationSummary(calibration([1, 0.06], [1, 0.07], [1, -0.08])), {
    reports: 3, group: 'following', points: 0.1, direction: 'rougher',
  });
  assert.deepEqual(calibrationSummary(calibration([0, 0], [1, -0.05], [0, 0])), {
    reports: 1, group: 'beam', points: 0.1, direction: 'rougher',
  });
});

// C2: Choosing a group only when rounded points are positive would lose its direction.
test('C2: retain the group and direction when 0.04 rounds to zero', () => {
  assert.deepEqual(calibrationSummary(calibration([0, 0], [0, 0], [1, 0.04])), {
    reports: 1, group: 'following', points: 0, direction: 'smoother',
  });
});

// C2: Legacy clamping to ±2 or in-place normalization fails on these frozen fixtures.
for (const [residual, direction] of [[-3, 'rougher'], [3, 'smoother']]) {
  test(`C2: preserve residual ${residual} as ${direction} without mutating calibration`, () => {
    assert.deepEqual(calibrationSummary(calibration([1, residual], [0, 0], [0, 0])), {
      reports: 1, group: 'head', points: 3, direction,
    });
  });
}
