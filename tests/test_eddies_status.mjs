import test from 'node:test';
import assert from 'node:assert/strict';
import {parseEddiesTile} from '../web/map/eddies-feed.ts';
import {eddiesStatus} from '../web/map/eddies-status.ts';

const frameTime = '2026-01-02T03:00Z';
const tile = (...features) => parseEddiesTile({frame_time: frameTime, features});
const eddy = (sense, diameter_km) => ({
  outline: [[0, 0], [1, 0], [1, 1], [0, 0]], sense, diameter_km, ow_min: -0.01,
});

test('C1: no parse result is loading, even before the dock time is valid', () => {
  assert.deepEqual(eddiesStatus(null, 'invalid'), {state: 'loading'});
});

test('C1: a parser rejection is bad-tile, not a dock-time error', () => {
  assert.deepEqual(eddiesStatus(parseEddiesTile({}), 'invalid'), {state: 'withheld', reason: 'bad-tile'});
});

test('C1: an unparseable dock time is bad-time, not a frame mismatch', () => {
  assert.deepEqual(eddiesStatus(tile(), 'invalid'), {state: 'withheld', reason: 'bad-time'});
});

test('C1: withholds a populated tile from another hour', () => {
  assert.deepEqual(eddiesStatus(tile(eddy('cw', 12)), '2026-01-02T04:00Z'),
    {state: 'withheld', reason: 'other-frame'});
});

test('C1: matches equal instants spelled differently and preserves the tile time', () => {
  assert.deepEqual(eddiesStatus(tile(eddy('ccw', 12)), '2026-01-01T19:00:00-08:00'),
    {state: 'shown', frameTime, count: 1, cw: 0, ccw: 1, largestKm: 12});
});

test('C2: an empty matching tile is shown with no largest diameter', () => {
  assert.deepEqual(eddiesStatus(tile(), frameTime),
    {state: 'shown', frameTime, count: 0, cw: 0, ccw: 0, largestKm: null});
});

test('C2: counts both senses and rounds the largest diameter, not the first or last', () => {
  const parsed = tile(eddy('cw', 12.12), eddy('ccw', 24.76), eddy('cw', 18.06));
  assert.deepEqual(eddiesStatus(parsed, frameTime),
    {state: 'shown', frameTime, count: 3, cw: 2, ccw: 1, largestKm: 24.8});
});
