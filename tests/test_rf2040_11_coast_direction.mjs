import test from 'node:test';
import assert from 'node:assert/strict';
import { direction } from '../packages/coast/src/ui/format.ts';

test('direction_negative_turns_match_positive_controls', () => {
  const cases = [[-22.5, 337.5, 'NNW'], [-382.5, 337.5, 'NNW'], [-90, 270, 'W'], [-450, 270, 'W']];
  for (const [neg, pos, label] of cases) {
    assert.equal(direction(neg), label);
    assert.equal(direction(neg), direction(pos));
  }
});

test('direction_wrap_seam_and_half_sector_boundary', () => {
  for (const d of [0, -0, 360, -360, 720, -11.25]) assert.equal(direction(d), 'N');
  assert.equal(direction(-11.26), 'NNW');
  assert.equal(direction(11.25), 'NNE');
});

test('direction_healthy_compass_and_missing_controls', () => {
  const labels = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
  labels.forEach((label, i) => assert.equal(direction(i * 22.5), label));
  for (const bad of [null, undefined, NaN, Infinity, -Infinity, '90']) assert.equal(direction(bad), '—');
});
