// The Chart's poster (#617, web/map/poster.ts): the committed Morro Bay poster parses, its numbers are the
// build's, and its placement puts a world point where MapLibre's camera would.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {loadPoster, mercator, parsePoster, poster, posterPlacement, posterURL} from '../web/map/poster.ts';

const FILE = readFileSync(new URL('../dist/regions/morro-bay/poster.svg', import.meta.url), 'utf8');
const REGION = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8'));

test('the committed poster parses: its corner is the region\'s and its path is moves and lines only', () => {
  const p = parsePoster(FILE, 'morro-bay');
  assert.ok(p);
  assert.deepEqual([p.west, p.north, p.zoom], [REGION.bounds[0], REGION.bounds[3], 12]);
  const [x0, y0] = mercator(REGION.bounds[0], REGION.bounds[3], 12), [x1, y1] = mercator(REGION.bounds[2], REGION.bounds[1], 12);
  assert.deepEqual([p.width, p.height], [Math.round(x1 - x0), Math.round(y1 - y0)]);
  assert.match(p.path, /^M\d/);
  assert.equal(posterURL('morro-bay'), 'regions/morro-bay/poster.svg');
});

test('anything but the build\'s shape is refused', () => {
  const ok = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" data-zoom="12" data-west="-121" data-north="35"><path d="M0 0l1 1"/></svg>';
  assert.ok(parsePoster(ok, 'r'));
  for (const bad of [ok.replace('M0 0l1 1', 'M0 0l1 1" onload="x'), ok.replace('l1 1', 'c1 1 2 2 3 3'), ok.replace('data-zoom="12"', ''),
    ok.replace('viewBox="0 0 10 10"', 'viewBox="0 0 0 10"'), '<html></html>', ''])
    assert.equal(parsePoster(bad, 'r'), null, bad);
});

test('placement: a world point lands where a 512-pixel MapLibre camera puts it, at any zoom', () => {
  const p = parsePoster(FILE, 'morro-bay');
  for (const zoom of [11, 12, 12.5, 14]) {
    const camera = {latitude: 35.37, longitude: -120.86, zoom}, at = posterPlacement(p, camera, 390, 844);
    // The harbor, in poster pixels, then on screen; MapLibre: centre at the middle, 512 × 2^(view zoom − 1) world pixels.
    const [hx, hy] = mercator(-120.868, 35.3667, 12), [ox, oy] = mercator(p.west, p.north, 12);
    const screen = [at.x + (hx - ox) * at.scale, at.y + (hy - oy) * at.scale];
    const [wx, wy] = mercator(-120.868, 35.3667, zoom - 1), [cx, cy] = mercator(camera.longitude, camera.latitude, zoom - 1);
    assert.ok(Math.abs(screen[0] - (195 + wx - cx)) < 1e-6 && Math.abs(screen[1] - (422 + wy - cy)) < 1e-6, `zoom ${zoom}`);
  }
});

test('the poster shows only until the Chart has drawn, and a failed file shows nothing', async () => {
  const ok = async () => ({ok: true, text: async () => FILE});
  poster.value = null;
  await loadPoster('morro-bay', 'https://s.test/map', () => true, ok);
  assert.equal(poster.value, null, 'already drawn: never shown');
  await loadPoster('morro-bay', 'https://s.test/map', () => false, async () => ({ok: false}));
  assert.equal(poster.value, null);
  await loadPoster('morro-bay', 'https://s.test/map', () => false, async () => { throw new Error('offline'); });
  assert.equal(poster.value, null);
  await loadPoster('morro-bay', 'https://s.test/map', () => false, ok);
  assert.equal(poster.value?.region, 'morro-bay');
  poster.value = null;
});
