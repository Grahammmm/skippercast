import assert from 'node:assert/strict';
import test from 'node:test';
import {loadPoster, poster, posterPlacement} from '../web/map/poster.ts';

const path = 'M0 0l1 1';
const svg = origin =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${origin} 10 20" data-zoom="12" data-west="-121" data-north="35"><path d="${path}"/></svg>`;

// MapStage redraws at 0 0: ignoring either origin coordinate would publish
// a path registered to a different corner (or to no valid corner at all).
for (const origin of ['1 0', '0 -2', 'x 0', '0 y']) {
  test(`loadPoster withholds the poster for viewBox origin ${origin}`, async () => {
    await load(origin);
    assert.equal(poster.value, null);
  });
}

test('loadPoster preserves dimensions and placement for viewBox origin 0 0', async () => {
  await load('0 0');
  const p = poster.value;
  assert.deepEqual(p, {region: 'r', path, width: 10, height: 20, zoom: 12, west: -121, north: 35});
  // At the poster's corner and native scale, its origin is the viewport centre.
  assert.deepEqual(posterPlacement(p, {latitude: 35, longitude: -121, zoom: 13}, 390, 844),
    {x: 195, y: 422, scale: 1});
});

async function load(origin) {
  await loadPoster('r', 'https://s.test/map', () => false, async () => new Response(svg(origin)));
}

test.afterEach(() => { poster.value = null; });
