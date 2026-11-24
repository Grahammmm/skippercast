import assert from 'node:assert/strict';
import test from 'node:test';
import {kitZoom} from '../web/map/nearshore-paint.ts';

// An unchecked flatten forwards bad stops to MapLibre, and an early singleton
// return can bypass validation. A strict order check must reject ties as well.
for (const [name, pairs, error] of [
  ['duplicate stops', [[12, 0.5], [12, 0.3]], /strictly increasing/],
  ['descending stops', [[13, 0.5], [12, 0.3]], /strictly increasing/],
  ['stops that coincide after the zoom offset', [[0, 0.5], [Number.MIN_VALUE, 0.3]], /strictly increasing/],
  ['an empty table', [], /at least one stop/],
  ['a NaN zoom', [[NaN, 0.5]], /finite numbers/],
  ['an infinite zoom', [[12, 0.5], [Infinity, 0.3]], /finite numbers/],
  ['an infinite singleton value', [[12, -Infinity]], /finite numbers/],
  ['a NaN value', [[12, 0.5], [13, NaN]], /finite numbers/],
  ['a numeric string zoom', [['12', 0.5]], /finite numbers/],
  ['a numeric string value', [[12, '0.5']], /finite numbers/],
]) {
  test(`kitZoom rejects ${name} before returning paint`, () => {
    assert.throws(() => kitZoom(pairs), error);
  });
}

// Rejecting all curves or treating a valid singleton as an expression is not a fix.
test('kitZoom preserves valid interpolation and singleton paint', () => {
  assert.deepEqual(kitZoom([[12, 0.5], [13, 0.3]]), ['interpolate', ['linear'], ['zoom'], 11, 0.5, 12, 0.3]);
  assert.equal(kitZoom([[12, 0.5]]), 0.5);
});
