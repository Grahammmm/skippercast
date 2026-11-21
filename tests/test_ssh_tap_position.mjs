import assert from 'node:assert/strict';
import test from 'node:test';
import {sshReader} from '../web/map/ssh-reading.ts';
import {sshTapPosition} from '../web/map/ssh-tap-position.ts';

const validAt = '2026-11-19T06:00:00Z';
const issuedAt = '2026-11-19T03:00:00Z';
const sw = {lat: 35.025, lon: -120.975};
const ne = {lat: 35.075, lon: -120.925};
const product = 'WCOFS';

function reading(sshCm) {
  return {kind: 'value', sshCm, validAt, issuedAt, product, cell: sw};
}

// Clamping the reading itself would hide how far beyond the legend it was.
test('C1: place the unmodified value inside the legend or at the correct outside end', () => {
  for (const [sshCm, position, outside] of [[5, 0.75, null], [-12, 0, 'below'], [12, 1, 'above']]) {
    assert.deepEqual(sshTapPosition(reading(sshCm), 10), {kind: 'value', sshCm, position, outside});
  }
});

// Looking at the scale first would mask the reader's gap when the limit is invalid.
test('C2: preserve the gap reason even with a bad limit', () => {
  assert.deepEqual(sshTapPosition({kind: 'none', reason: 'gap'}, 0), {kind: 'none', reason: 'gap'});
});

// Skipping the null check would return a value without a usable position.
test('C2: refuse non-finite and non-positive limits', () => {
  for (const limitCm of [NaN, Infinity, -Infinity, 0, -10]) {
    assert.deepEqual(sshTapPosition(reading(5), limitCm), {kind: 'none', reason: 'bad-scale'}, `limit ${limitCm}`);
  }
});

// The real reader supplies signed values and gaps, not absolute heights or missing-as-zero.
test('C3: project two native cells and preserve an unsampled grid cell', () => {
  const read = sshReader({product, issuedAt, resolution: [0.05, 0.05], frames: [
    {validAt, cells: [{...sw, sshCm: -5}, {...ne, sshCm: 15}]},
  ]});
  assert.deepEqual(sshTapPosition(read(sw, validAt), 10), {kind: 'value', sshCm: -5, position: 0.25, outside: null});
  assert.deepEqual(sshTapPosition(read(ne, validAt), 10), {kind: 'value', sshCm: 15, position: 1, outside: 'above'});
  assert.deepEqual(sshTapPosition(read({lat: sw.lat, lon: ne.lon}, validAt), 10), {kind: 'none', reason: 'gap'});
});
