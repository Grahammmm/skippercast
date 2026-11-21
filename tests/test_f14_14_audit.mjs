import test from 'node:test';
import assert from 'node:assert/strict';
import {checkGpx} from '../web/gpx-check.ts';

const wrap = body => `<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">${body}</gpx>`;
const point = '<wpt lat="0" lon="0"';
const expected = {waypoints: 1};
const named = wrap(`${point}><name>Synthetic mark</name></wpt>`);

test('a paired waypoint without a name fails the delivery check', () => {
  assert.deepEqual(checkGpx(wrap(`${point}></wpt>`), expected).problems, ['Waypoint name missing']);
});

test('a self-closing waypoint cannot skip the delivery name check', () => {
  assert.deepEqual(checkGpx(wrap(`${point}/>`), expected).problems, ['Waypoint name missing']);
});

test('a named waypoint passes structure but remains subject to geographic refusal', () => {
  assert.equal(checkGpx(named, expected).ok, true);
  const screen = {ready: () => true, pointAllowed: () => false};
  assert.deepEqual(checkGpx(named, expected, screen).problems, ['Inside or near a protected area']);
  assert.deepEqual(checkGpx(wrap(`${point}/>`), expected, screen).problems,
    ['Waypoint name missing', 'Inside or near a protected area']);
});
