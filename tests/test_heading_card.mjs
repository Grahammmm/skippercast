import assert from 'node:assert/strict';
import test from 'node:test';
import {headingCardPlan, wedgeOf} from '../web/brief/heading-card.ts';

const point = (latitude, longitude) => ({latitude, longitude});
const route = (...points) => ({ok: true, nm: 1, points});
const origin = point(0, 0);
const dogleg = route(point(35, -121), point(36, -121), point(38, -123));
const unmarked = {show: true, out: null, back: null};

test('C1: every half-wedge boundary rounds upward, wrapping the last to wedge zero', () => {
  // Detect floor rounding, ties going down, or an extra wedge at the wrap.
  for (const [boundary, below, above] of [
    [22.5, 0, 1], [67.5, 1, 2], [112.5, 2, 3], [157.5, 3, 4],
    [202.5, 4, 5], [247.5, 5, 6], [292.5, 6, 7], [337.5, 7, 0],
  ]) {
    assert.deepEqual(wedgeOf(boundary - 0.001), below, `below ${boundary}`);
    assert.deepEqual(wedgeOf(boundary), above, `at ${boundary}`);
    assert.deepEqual(wedgeOf(boundary + 0.001), above, `above ${boundary}`);
  }
  // Adding a full turn to an already normalized input can move it onto the tie.
  assert.deepEqual(wedgeOf(22.499999999999996), 0);
});

test('C1: signed bearings and multiple turns use the same non-negative wedge indices', () => {
  // Detect bare remainder for negatives, normalization by a single turn, or negative zero.
  for (const [bearing, wedge] of [[360, 0], [-45, 7], [765, 1], [-765, 7], [-22.5, 0], [-360, 0]]) {
    assert.deepEqual(wedgeOf(bearing), wedge, `${bearing} degrees`);
  }
});

test('C1: non-finite bearings do not become NaN wedges', () => {
  for (const bearing of [NaN, Infinity, -Infinity]) {
    assert.deepEqual(wedgeOf(bearing), null, String(bearing));
  }
});

for (const profile of ['shore', 'spear', 'kayak']) {
  test(`C2: ${profile} hides the card even with a computed route`, () => {
    assert.deepEqual(headingCardPlan(profile, dogleg), {show: false, reason: 'not-boat'});
  });
}

test('C2: a computed Boat route marks both endpoint courses independently', () => {
  // Using the first leg or adding 180° to the outbound course gives a different bearing.
  assert.deepEqual(headingCardPlan('boat', dogleg), {
    show: true, out: {deg: 332, wedge: 7}, back: {deg: 151, wedge: 3},
  });
});

test('C2: a failed route keeps the Boat card without inserting placeholder marks', () => {
  assert.deepEqual(headingCardPlan('boat', {ok: false, reason: 'no-route'}), unmarked);
});

test('C2: a null route keeps the Boat card without dereferencing a route', () => {
  assert.deepEqual(headingCardPlan('boat', null), unmarked);
});

test('C2: a route with coincident ends does not treat the first leg as a course', () => {
  assert.deepEqual(headingCardPlan('boat', route(origin, point(1, 0), origin)), unmarked);
});

test('C3: unusable coordinates return the plain plan without throwing or adding fallback copy', () => {
  assert.deepEqual(headingCardPlan('boat', route(origin, point(1, Infinity))), unmarked);
});

test('C3: a zero-degree course is a numeric mark, not missing or turned into a label', () => {
  assert.deepEqual(headingCardPlan('boat', route(origin, point(1, 0))), {
    show: true, out: {deg: 0, wedge: 0}, back: {deg: 180, wedge: 4},
  });
});
