import test from 'node:test';
import assert from 'node:assert/strict';
import {calibrationShown, readCalibration} from '../web/comfort-calibration-view.ts';

const example = {
  groups: {head: {n: 6, residual: -0.55}, beam: {n: 2, residual: 0}, following: {n: 0, residual: 0}},
  min_reports: 5,
};

test('C1: read the plan response and rename the report threshold', () => {
  assert.deepEqual(readCalibration(example), {
    groups: {head: {n: 6, residual: -0.55}, beam: {n: 2, residual: 0}, following: {n: 0, residual: 0}},
    minReports: 5,
  });
});

test('C1: retain inclusive residual endpoints and ignore extras at every level', () => {
  assert.deepEqual(readCalibration({
    groups: {
      head: {n: 1, residual: -3, extra: true}, beam: {n: 0, residual: 0}, following: {n: 1, residual: 3},
      bow: {n: 'invalid'},
    },
    min_reports: 1,
    minReports: 99,
  }), {groups: {head: {n: 1, residual: -3}, beam: {n: 0, residual: 0}, following: {n: 1, residual: 3}}, minReports: 1});
});

// A permissive reader could treat arrays as records or silently default missing groups.
test('C1: reject invalid response and group containers', () => {
  for (const data of [undefined, null, 'response', 5, [], {}, {min_reports: 5}]) {
    assert.deepEqual(readCalibration(data), null);
  }
  for (const groups of [null, false, [], {}, Object.create(example.groups)]) {
    assert.deepEqual(readCalibration({...example, groups}), null);
  }
  for (const key of ['head', 'beam', 'following']) {
    const groups = {...example.groups};
    delete groups[key];
    assert.deepEqual(readCalibration({...example, groups}), null, `missing ${key}`);
    for (const invalid of [null, 1, [], {n: 1}, {residual: 0}]) {
      assert.deepEqual(readCalibration({...example, groups: {...groups, [key]: invalid}}), null, key);
    }
  }
});

// Coercion, rounding or a range-only check would admit malformed calibration data.
for (const [field, invalidValues] of [
  ['n', [-1, 1.5, NaN, Infinity, '6', null]],
  ['residual', [-3.01, 3.01, NaN, -Infinity, Infinity, '-0.55', null]],
]) {
  test(`C1: reject invalid ${field}`, () => {
    for (const value of invalidValues) {
      const head = {...example.groups.head, [field]: value};
      assert.deepEqual(readCalibration({...example, groups: {...example.groups, head}}), null, String(value));
    }
  });
}

test('C1: require a positive integer wire threshold without coercion', () => {
  assert.deepEqual(readCalibration({groups: example.groups, minReports: 5}), null);
  for (const min_reports of [0, -1, 1.5, NaN, Infinity, '5', null]) {
    assert.deepEqual(readCalibration({...example, min_reports}), null, String(min_reports));
  }
});

test('C1: reject a value that throws during inspection rather than propagating the error', () => {
  const data = {...example, get groups() { throw new TypeError('unreadable groups'); }};
  assert.deepEqual(readCalibration(data), null);
});

const boat = 'test boat';
const threshold = {
  groups: {head: {n: 2, residual: -0.55}, beam: {n: 1, residual: 0.75}, following: {n: 2, residual: -1}},
  minReports: 5,
};
const below = {...threshold, minReports: 6};

test('C2: off takes priority over absent calibration and a mismatched boat', () => {
  assert.deepEqual(calibrationShown(null, 'off', boat, 'other'), {apply: false, tag: false, reason: 'off'});
  assert.deepEqual(calibrationShown(threshold, 'off', boat, boat), {apply: false, tag: false, reason: 'off'});
});

test('C2: missing calibration takes priority over a mismatched boat', () => {
  assert.deepEqual(calibrationShown(null, 'auto', boat, 'other'), {apply: false, tag: false, reason: 'none'});
});

test('C2: a boat mismatch takes priority over too few reports', () => {
  assert.deepEqual(calibrationShown(below, 'auto', boat, 'other'), {apply: false, tag: false, reason: 'other-boat'});
});

test('C2: a missing boat on either side cannot match, even when both are null', () => {
  for (const [current, calibrated] of [[null, boat], [boat, null], [null, null]]) {
    assert.deepEqual(calibrationShown(threshold, 'auto', current, calibrated), {apply: false, tag: false, reason: 'other-boat'});
  }
});

test('C2: a matching boat with a total below the supplied minimum is not calibrated', () => {
  assert.deepEqual(calibrationShown(below, 'auto', boat, boat), {apply: false, tag: false, reason: 'too-few'});
});

test('C2: an exact total across all three groups applies the three distinct residuals', () => {
  assert.deepEqual(calibrationShown(threshold, 'auto', boat, boat), {
    apply: true, tag: true, offsets: {head: -0.55, beam: 0.75, following: -1},
  });
});

test('C2: above the threshold, any empty group contributes zero even with a nonzero residual', () => {
  for (const key of ['head', 'beam', 'following']) {
    const cal = {
      groups: {...threshold.groups, [key]: {n: 0, residual: 3}},
      minReports: 2,
    };
    assert.deepEqual(calibrationShown(cal, 'auto', boat, boat), {
      apply: true, tag: true, offsets: {head: -0.55, beam: 0.75, following: -1, [key]: 0},
    }, key);
  }
});
