import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {test} from 'node:test';
import {gunzipSync} from 'node:zlib';
import {decodeTerrain} from '../packages/coast/src/coast3d/regional.ts';

// The 43-byte overview.bin.gz emitted by `region.py terrain` on the mosaic-only
// north-fixture in test_relief_terrain.py. Retain it inline so Node CI needs no GIS.
const fixture = Buffer.from('H4sIAAAAAAAC/2NgMDjIAMYijhAaBGBsiDgjIxMjAxOQBABN1GvkLQAAAA==', 'base64');
const overview = {
  bytes: 43, decodedBytes: 45, size: 3,
  x: -29.090383789272988, z: -27.829926792334003,
  dx: 29.09038378996835, dz: 27.8298726977685,
  sha256: 'd709bc627260a621b78df1fd17befea66e5cb96cf1d3bbb4b85d17efdc1b2958',
};

test('the native decoder reads producer elevations and the zero-source validity mask', () => {
  // Protect the cross-language plane layout, little-endian elevations and
  // explicit mask ID; zero elevation alone cannot distinguish land from a hole.
  assert.equal(fixture.length, overview.bytes);
  assert.equal(createHash('sha256').update(fixture).digest('hex'), overview.sha256);
  const data = Uint8Array.from(gunzipSync(fixture)).buffer;
  assert.equal(data.byteLength, overview.decodedBytes);
  const {size, x, z, dx, dz} = overview;
  const grid = decodeTerrain(data, size, x, z, dx, dz, new Set([0, 1, 2]));
  assert.deepEqual([...grid.values], [-11, -11, 9.25, -11, 0, 9.25, -11, -11, 9.25]);
  assert.deepEqual([...grid.sources], [1, 1, 2, 1, 0, 2, 1, 1, 2]);
  assert.deepEqual([...grid.sources].map(id => id !== 0), [true, true, true, true, false, true, true, true, true]);
  assert.throws(() => decodeTerrain(data, size, x, z, dx, dz, new Set([1, 2])), /Invalid terrain sample/);
});
