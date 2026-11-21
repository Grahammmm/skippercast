import test from 'node:test';
import assert from 'node:assert/strict';
import {eddyTileTap} from '../web/map/eddy-tile-tap.ts';

const frameTime = '2026-01-02T15:00Z';
const issuedAt = '2026-01-01T19:00:00-08:00';
const inside = {lon: -123, lat: 38};
const feature = {
  outline: [[-124, 37], [-122, 37], [-122, 39], [-124, 39], [-124, 37]],
  sense: 'ccw', diameter_km: 10.6, ow_min: -0.01,
};
const tile = {frame_time: frameTime, features: [feature]};

// Passing wire fields to the reader instead of parsed fields loses the diameter or frame.
test('C1: returns the full model reading inside a ccw eddy (C3)', () => {
  assert.deepEqual(eddyTileTap(tile, issuedAt, inside), {
    kind: 'eddy', sense: 'ccw', diameterKm: 11, frameTime, runHourUtc: 3, leadHours: 12, basis: 'model',
  });
});

// A later invalid feature must not allow the first eddy to be sampled, even speculatively.
test('C2: preserves the nested parser path and does not read the tap on parse failure', () => {
  const unreadable = {...feature, get ow_min() { throw new Error('unreadable'); }};
  let reads = 0;
  const at = {...inside, get lon() { reads++; return inside.lon; }};
  assert.deepEqual(eddyTileTap({...tile, features: [feature, unreadable]}, issuedAt, at), {
    kind: 'invalid', error: 'features[1].ow_min',
  });
  assert.equal(reads, 0);
});

// Substituting a default tap or treating any nonempty tile as a hit would return an eddy.
test('C3: a tap outside every eddy returns only none', () => {
  assert.deepEqual(eddyTileTap(tile, issuedAt, {lon: -121, lat: 38}), {kind: 'none'});
});

// Otherwise valid geometry must not cover for bad frame metadata.
test('C3: a bad frame_time invalidates the whole tile', () => {
  assert.deepEqual(eddyTileTap({...tile, frame_time: 'invalid'}, issuedAt, inside), {
    kind: 'invalid', error: 'frame_time',
  });
});

// Rejecting the whole tile on issuance parse failure would lose a valid spatial reading.
test('C3: an unparsable issuedAt leaves both time facts null', () => {
  assert.deepEqual(eddyTileTap(tile, 'invalid', inside), {
    kind: 'eddy', sense: 'ccw', diameterKm: 11, frameTime, runHourUtc: null, leadHours: null, basis: 'model',
  });
});
