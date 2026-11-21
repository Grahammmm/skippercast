import assert from 'node:assert/strict';
import test from 'node:test';
import {SSH_MIN_LIMIT_CM, SSH_STEP_CM, sshOutside, sshPosition, sshScale} from '../web/map/ssh-scale.ts';

test('C1: floor and rounding step stay fixed', () => {
  assert.equal(SSH_MIN_LIMIT_CM, 5);
  assert.equal(SSH_STEP_CM, 5);
});

test('C2: empty or entirely non-finite data does not produce a scale', () => {
  assert.equal(sshScale([]), null);
  assert.equal(sshScale([NaN, NaN]), null);
  assert.equal(sshScale([-Infinity, Infinity]), null);
});

test('C2: valid zero and small magnitudes use the minimum without rounding half ticks', () => {
  for (const values of [[-0], [-4.9, 1, 4.9], [-5, 5]]) {
    const result = sshScale(values);
    assert.deepEqual(result, {limitCm: 5, ticks: [-5, -2.5, 0, 2.5, 5]});
    assert.equal(Object.is(result.ticks[2], +0), true);
  }
});

test('C2: rounding from the largest magnitude steps only above the boundary', () => {
  assert.deepEqual(sshScale([5.1]), {limitCm: 10, ticks: [-10, -5, 0, 5, 10]});
  assert.deepEqual(sshScale([-9.9, 2]), {limitCm: 10, ticks: [-10, -5, 0, 5, 10]});
  assert.deepEqual(sshScale([3, -10]), {limitCm: 10, ticks: [-10, -5, 0, 5, 10]});
  assert.deepEqual(sshScale([-10.1, 3]), {limitCm: 15, ticks: [-15, -7.5, 0, 7.5, 15]});
});

test('C2: a generator needs no array methods and non-finite entries cannot poison its scale', () => {
  function* readings() {
    yield NaN;
    yield -Infinity;
    yield 12.6;
    yield -2;
    yield Infinity;
  }
  assert.deepEqual(sshScale(readings()), {limitCm: 15, ticks: [-15, -7.5, 0, 7.5, 15]});
});

test('C3: positions preserve the zero centre, quarter points and both clamped ends', () => {
  for (const [value, expected] of [[-10.1, 0], [-10, 0], [-5, 0.25], [0, 0.5], [5, 0.75], [10, 1], [10.1, 1]]) {
    assert.equal(sshPosition(value, 10), expected, `value ${value}`);
  }
});

test('C3: a finite limit whose doubled width overflows still gives valid positions', () => {
  const limit = Number.MAX_VALUE;
  assert.equal(sshPosition(-limit, limit), 0);
  assert.equal(sshPosition(0, limit), 0.5);
  assert.equal(sshPosition(limit / 2, limit), 0.75);
  assert.equal(sshPosition(limit, limit), 1);
});

test('C4: outside flags use strict inequalities, so neither endpoint is outside', () => {
  for (const [value, expected] of [[-10.1, 'below'], [-10, null], [0, null], [10, null], [10.1, 'above']]) {
    assert.equal(sshOutside(value, 10), expected, `value ${value}`);
  }
});

const invalidInputs = [
  [NaN, 10], [-Infinity, 10], [Infinity, 10],
  [1, NaN], [1, -Infinity], [1, Infinity], [1, 0], [1, -10],
];

test('C3: invalid readings or limits do not get a position', () => {
  for (const [value, limit] of invalidInputs) {
    assert.equal(sshPosition(value, limit), null, `value ${value}, limit ${limit}`);
  }
});

test('C4: invalid readings or limits do not appear outside the range', () => {
  for (const [value, limit] of invalidInputs) {
    assert.equal(sshOutside(value, limit), null, `value ${value}, limit ${limit}`);
  }
});
