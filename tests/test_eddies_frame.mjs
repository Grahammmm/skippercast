import test from 'node:test';
import assert from 'node:assert/strict';
import {eddiesFrameFor, eddiesFrameTimes} from '../web/map/eddies-frame.ts';

const hour = '2026-01-02T03:00:00Z';
const offsetHour = '2026-01-01T22:00:00-05:00';
const later = '2026-01-02T04:00:00Z';
const emptyTile = (frame_time = hour) => ({frame_time, features: []});

test('C1: sorts by instant, not text, retaining the first spelling of each valid time', () => {
  const earlier = '2026-01-02T02:00:00Z';
  const frames = Object.freeze([later, offsetHour, 'invalid', earlier, hour, '1970-01-01'].map(validAt =>
    Object.freeze({validAt, get tile() { throw new Error('time listing should not read tiles'); }})));
  assert.deepEqual(eddiesFrameTimes(frames), ['1970-01-01', earlier, offsetHour, later]);
});

test('C1: lists nothing when all manifest times are invalid', () => {
  assert.deepEqual(eddiesFrameTimes([{validAt: 'invalid', tile: emptyTile()}]), []);
});

// A raw-tile passthrough would return wire keys; in-place edits would fail on the frozen input.
test('C2: returns the parsed eddies at the exact requested hour without mutating input', () => {
  const outline = Object.freeze([[-124, 37], [-123, 37], [-123, 38], [-124, 37]].map(point => Object.freeze(point)));
  const feature = Object.freeze({outline, sense: 'ccw', diameter_km: 34, ow_min: -0.025});
  const tile = Object.freeze({frame_time: hour, features: Object.freeze([feature])});
  const frames = Object.freeze([Object.freeze({validAt: hour, tile})]);
  assert.deepEqual(eddiesFrameFor(frames, hour), {state: 'ready', frameTime: hour, eddies: [{
    outline: [[-124, 37], [-123, 37], [-123, 38], [-124, 37]], sense: 'ccw', diameterKm: 34, owMin: -0.025,
  }]});
});

test('C2: matches equivalent timestamps, ignores later duplicates and returns the tile spelling', () => {
  const tileTime = '2026-01-02T03:00Z';
  const frames = [
    {validAt: later, tile: emptyTile(later)},
    {validAt: 'invalid', tile: null},
    {validAt: offsetHour, tile: emptyTile(tileTime)},
    {validAt: hour, tile: null},
  ];
  assert.deepEqual(eddiesFrameFor(frames, '2026-01-02T03:00:00+00:00'),
    {state: 'ready', frameTime: tileTime, eddies: []});
});

test('C2: does not round a request within the same hour to a manifest frame', () => {
  assert.deepEqual(eddiesFrameFor([{validAt: hour, tile: emptyTile()}], '2026-01-02T03:00:00.001Z'),
    {state: 'none', reason: 'no-frame'});
});

test('C2: refuses a bad request time even if the manifest has the same invalid spelling', () => {
  assert.deepEqual(eddiesFrameFor([{validAt: 'invalid', tile: emptyTile()}], 'invalid'),
    {state: 'none', reason: 'bad-time'});
});

test('C3: refuses malformed features even when the tile time matches, without falling through to a duplicate', () => {
  const frames = [
    {validAt: offsetHour, tile: {...emptyTile(), features: [null]}},
    {validAt: hour, tile: emptyTile()},
  ];
  assert.deepEqual(eddiesFrameFor(frames, hour), {state: 'none', reason: 'bad-tile'});
});

test('C3: refuses a valid tile from a different instant even within the same hour', () => {
  assert.deepEqual(eddiesFrameFor([{validAt: hour, tile: emptyTile('2026-01-02T03:00:01Z')}], hour),
    {state: 'none', reason: 'bad-tile'});
});

test('C3: refuses a tile property that throws before the parser can read it', () => {
  const frame = {validAt: hour, get tile() { throw new Error('unreadable'); }};
  assert.deepEqual(eddiesFrameFor([frame], hour), {state: 'none', reason: 'bad-tile'});
});
