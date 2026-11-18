import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {afterEach, test} from 'node:test';
import {ensureLandWater, keepWater, resetLandWater} from '../web/land-water.ts';

const region = 'synthetic';
// The producer's schema-v1 constants, from the synthetic fixture it rebuilds in test_land_water.py.
const {constants} = JSON.parse(readFileSync(new URL('./fixtures/land-water/coast.json', import.meta.url), 'utf8'));
const source = {sha256: 'synthetic'};
const shoreline = [[1000, 500, 0, 1000]];
const lines = JSON.stringify({schema_version: 1, product: 'land-water-lines', region_id: region,
  derived_from: source, unit: constants.unit, edge: shoreline, parity: shoreline});
const near = {latitude: 0.01, longitude: 0.01010}; // ~11 m east of the synthetic line, on the water side.
const far = {latitude: 0.01, longitude: 0.01040};  // ~45 m east of the same line.
const points = [near, far];

afterEach(resetLandWater);

async function classifier(indexConstants, cell) {
  const index = {schema_version: 1, product: 'land-water', region_id: region, status: 'available',
    bounds: [1, 1, 2000, 2000], constants: indexConstants, derived_from: source,
    lines: {sha256: createHash('sha256').update(lines).digest('hex')},
    tiles: {'12/2048/2047': `${cell}${constants.grid ** 2}`}};
  const calls = [];
  const place = await ensureLandWater(region, points, async url => {
    const file = new URL(url).pathname.split('/').at(-1);
    calls.push(file);
    if (file === 'land-water.json') return Response.json(index);
    assert.equal(file, 'land-water-lines.json');
    return new Response(lines);
  });
  return {place, calls};
}

for (const [label, cell] of [['mixed', 'm'], ['preclassified water', 'w']]) {
  test(`a 1 m index cannot supply ranked places from ${label} cells`, async () => {
    const {place, calls} = await classifier({...constants, edge_m: 1}, cell);
    assert.deepEqual(keepWater(points, place), {kept: [], withheld: 2, pending: false});
    assert.deepEqual(place(near), {state: 'unknown', reason: 'unavailable'});
    assert.deepEqual(calls, ['land-water.json'], 'refuse the index before requesting any lines');
  });
}

test('a schema-v1 25 m index withholds the 11 m control and keeps the farther water point', async () => {
  const {place, calls} = await classifier(constants, 'm');
  assert.deepEqual(place(near), {state: 'unknown', reason: 'edge'});
  assert.deepEqual(keepWater(points, place), {kept: [far], withheld: 1, pending: false});
  assert.deepEqual(calls, ['land-water.json', 'land-water-lines.json']);
});
