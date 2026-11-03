import test from 'node:test';
import assert from 'node:assert/strict';
import {TOUR_STEPS, tourTransition} from '../web/tour.ts';

const IMPOSSIBLE = [NaN, -1, 2.5, 4, 99, Infinity, -Infinity];
const ACTIONS = ['replay', 'next', 'back', 'close'];

test('next/back from an impossible step closes the tour', () => {
  for (const step of IMPOSSIBLE) {
    assert.equal(tourTransition(step, 'next'), null, `next from ${step}`);
    assert.equal(tourTransition(step, 'back'), null, `back from ${step}`);
  }
});

test('replay from an impossible step starts at 0; close gives null', () => {
  for (const step of IMPOSSIBLE) {
    assert.equal(tourTransition(step, 'replay'), 0, `replay from ${step}`);
    assert.equal(tourTransition(step, 'close'), null, `close from ${step}`);
  }
});

test('valid steps walk unchanged', () => {
  assert.equal(TOUR_STEPS.length, 4);
  assert.equal(tourTransition(0, 'next'), 1);
  assert.equal(tourTransition(1, 'next'), 2);
  assert.equal(tourTransition(2, 'next'), 3);
  assert.equal(tourTransition(3, 'next'), null);
  assert.equal(tourTransition(2, 'back'), 1);
  assert.equal(tourTransition(0, 'back'), 0);
});

test('an unknown action closes the tour', () => {
  assert.equal(tourTransition(1, 'jump'), null);
  assert.equal(tourTransition(0, ''), null);
});

test('every result is null or a whole step in range', () => {
  for (let step = -2; step <= 6; step++) {
    for (const action of ACTIONS) {
      const r = tourTransition(step, action);
      assert.ok(r === null || (Number.isInteger(r) && r >= 0 && r < TOUR_STEPS.length),
        `${action} from ${step} gave ${r}`);
    }
  }
});
