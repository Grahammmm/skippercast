import assert from 'node:assert/strict';
import test from 'node:test';
import {runBearings} from '../web/brief/heading.ts';

const point = (latitude, longitude) => ({latitude, longitude});
const route = (...points) => ({ok: true, nm: 1, points});
const origin = point(0, 0);

test('equatorial east and meridian north are clockwise from true north', () => {
  // Swapped axes or a mathematical angle from east breaks these cardinal courses.
  assert.deepEqual(runBearings(route(origin, point(0, 5))), {out: 90, back: 270});
  assert.deepEqual(runBearings(route(origin, point(1, 0))), {out: 0, back: 180});
});

test('a dogleg uses the polyline endpoints, not either local leg', () => {
  assert.deepEqual(runBearings(route(origin, point(4, 0), point(4, 3))), {out: 37, back: 217});
});

test('a synthetic California route has two independently computed initial courses', () => {
  // A unit-sphere tangent-plane projection gives 332.403° and 151.213°.
  // Adding 180° to the outbound bearing would give 152°, not 151°.
  assert.deepEqual(runBearings(route(point(35, -121), point(38, -123))), {out: 332, back: 151});
});

test('a rounded heading of 360 wraps to 0 without wrapping 359', () => {
  // Just west of north: catches negative headings, flooring, and wrapping before rounding only.
  assert.deepEqual(runBearings(route(origin, point(1, -0.005))), {out: 0, back: 180});
  assert.deepEqual(runBearings(route(origin, point(1, -0.02))), {out: 359, back: 179});
});

test('crossing the antimeridian eastward is still eastward', () => {
  // Comparing the raw longitude values would reverse the displayed courses.
  assert.deepEqual(runBearings(route(point(0, 179), point(0, -179))), {out: 90, back: 270});
});

test('unavailable routes and undefined bearings give two nulls, never a numeric course or NaN', () => {
  const cases = [
    ['failed route with no points field', {ok: false, reason: 'no-route'}],
    ['empty route', route()],
    ['single point', route(origin)],
    ['duplicate point values', route(origin, point(0, 0))],
    ['loop with distinct interior point but coincident ends', route(origin, point(1, 0), origin)],
    ['same endpoint on either label for the antimeridian', route(point(5, -180), point(5, 180))],
    ['same pole at different longitudes', route(point(90, 12), point(90, 34))],
    ['antipodal ends', route(point(5, -121), point(-5, 59))],
    ['opposite poles regardless of longitude', route(point(-90, 12), point(90, 34))],
    ['NaN latitude at start', route(point(NaN, 0), origin)],
    ['infinite longitude at end', route(origin, point(1, Infinity))],
    ['non-finite interior point with otherwise valid endpoints', route(origin, point(-Infinity, 1), point(1, 2))],
  ];
  for (const [label, input] of cases) {
    assert.deepEqual(runBearings(input), {out: null, back: null}, label);
  }
});
