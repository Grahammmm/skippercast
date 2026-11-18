// RF2021-11: an unsplit longitude-seam edge (raw |delta lon| > 180) is not projected across the world.
import test from 'node:test';
import assert from 'node:assert/strict';
import {yardsFromShore} from '../web/shore-distance.ts';

const YD = 111_320 / 0.9144;
const at = (lines, longitude, latitude = 0) => yardsFromShore({latitude, longitude}, lines);
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b}`);

test('unsplit_seam_edge_cannot_claim_greenwich_shore', () => {
  for (const line of [[[179, 0], [-179, 0]], [[-179, 0], [179, 0]]]) {
    for (const lon of [0, 180, -180, 179.5]) assert.equal(at([line], lon), null, `${JSON.stringify(line)} @ ${lon}`);
  }
});

test('seam_edge_guard_is_strict_and_does_not_reconnect', () => {
  near(at([[[-90, 0], [90, 0]]], 0), 0, 1e-6, 'delta exactly 180 kept');
  assert.equal(at([[[-90, 0], [90.01, 0]]], 0), null, 'delta just above 180 skipped');
  // Valid pairs either side of a skipped pair stay independent; nothing bridges them through Greenwich.
  const line = [[170, 0], [171, 0], [-170, 0], [-169, 0]];
  near(at([line], 175), 4 * YD, 1e-4, 'before skipped pair');
  near(at([line], -175), 5 * YD, 1e-4, 'after skipped pair');
  assert.ok(at([line], 0) > 1_000_000, 'no bridge at Greenwich');
});

test('healthy_split_seam_and_local_controls', () => {
  const west = [[-179.99, -1], [-179.99, 1]], east = [[179.99, -1], [179.99, 1]], local = [[10, 0], [10, 1]];
  const lines = Object.freeze([Object.freeze(west), Object.freeze(east), Object.freeze(local)]);
  near(at(lines, 180), 0.01 * YD, 1e-5, 'seam siblings');
  near(at(lines, 10), 0, 1e-6, 'local segment');
  assert.equal(yardsFromShore({latitude: 0, longitude: 0}, []), null);
  // A skipped unsplit edge beside valid siblings still lets the siblings answer.
  near(at([[[179, 0], [-179, 0]], local], 10), 0, 1e-6, 'mixed siblings');
});
