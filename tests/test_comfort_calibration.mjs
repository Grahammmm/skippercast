import test from 'node:test';
import assert from 'node:assert/strict';
import {MIN_REPORTS, SHRINK_K, CLAMP, calibrationGroups} from '../server/comfort-calibration.ts';

const boat = 'Fixture Boat';
const row = (overrides = {}) => ({boat, group: 'head', reported: 5, model: 6, ...overrides});
const reports = (n, overrides) => Array.from({length: n}, () => row(overrides));
const group = (n = 0, residual = 0) => ({n, residual});
const result = (head = group(), beam = group(), following = group()) => ({
  groups: {head, beam, following}, min_reports: 5,
});

test('C1: public calibration constants do not drift', () => {
  assert.deepEqual({MIN_REPORTS, SHRINK_K, CLAMP}, {MIN_REPORTS: 5, SHRINK_K: 5, CLAMP: 2});
});

test('C2: empty input still returns all three group entries', () => {
  assert.deepEqual(calibrationGroups([], boat), result());
});

test('C3: reproduce the plan example without borrowing counts across groups', () => {
  const rows = [...reports(3, {model: 5}), ...reports(3, {model: 7}), ...reports(2, {group: 'beam'})];
  assert.deepEqual(calibrationGroups(rows, boat), result(group(6, -0.55), group(2)));
});

test('C3: the threshold is per group and includes the fifth valid report', () => {
  const rows = [...reports(4, {reported: 1, model: 10}), ...reports(5, {group: 'beam', model: 4})];
  assert.deepEqual(calibrationGroups(rows, boat), result(group(4), group(5, 0.5)));
});

test('C3: invalid rows cannot inflate counts or activate a group', () => {
  const rows = [
    ...reports(4),
    row({boat: 'Other Boat'}), row({boat: null}), row({boat: boat.toLowerCase()}),
    row({group: null}), row({group: 'bow'}), row({group: 'toString'}),
    row({model: null}), row({model: NaN}), row({model: Infinity}), row({model: -Infinity}),
    row({reported: 0}), row({reported: 11}), row({reported: 2.5}),
  ];
  assert.deepEqual(calibrationGroups(rows, boat), result(group(4)));
});

test('C3: clamp the shrunk value on both sides, not the raw mean', () => {
  for (const [delta, expected] of [[3, 1.5], [4, 2], [5, 2]]) {
    const rows = [...reports(5, {reported: 10, model: 10 - delta}), ...reports(5, {group: 'following', reported: 1, model: 1 + delta})];
    assert.deepEqual(calibrationGroups(rows, boat), result(group(5, expected), group(), group(5, -expected)));
  }
});

test('C3: round negative ties toward positive infinity and normalize rounded negative zero', () => {
  const rows = [...reports(5, {model: 5.25}), ...reports(5, {group: 'beam', model: 5.005})];
  assert.deepEqual(calibrationGroups(rows, boat), result(group(5, -0.12), group(5)));
});

test('C3: extreme finite residuals can cancel before shrinkage', () => {
  const rows = [...reports(2, {model: Number.MAX_VALUE}), ...reports(2, {model: -Number.MAX_VALUE}), row({model: 7})];
  assert.deepEqual(calibrationGroups(rows, boat), result(group(5, -0.2)));
});
