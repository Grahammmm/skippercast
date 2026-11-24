import test from 'node:test';
import assert from 'node:assert/strict';
import {CURRENTS_HEADS, CURRENTS_LINES, currentsOverlay} from '../web/map/preview/currents.ts';

const image = {url: 'data:image/png;base64,AA==', coordinates: [[-2, 1], [1, 1], [1, -1], [-2, -1]]};
const size = 0.01;
const tip = [0, 0], incoming = [-1, 0];
const turn = [[0, -1], incoming, tip];

function heads(coords) {
  return currentsOverlay([{coords}], image, size).sources[CURRENTS_HEADS].data.features;
}

function headRing(coords) {
  const features = heads(coords);
  assert.equal(features.length, 1, 'one head for a directed streamline');
  return features[0].geometry.coordinates[0];
}

function assertEast(ring) {
  const [point, a, b, close] = ring;
  assert.deepEqual(point, tip);
  assert.deepEqual(close, tip);
  assert.ok(a[0] < tip[0] && b[0] < tip[0], `both barbs must trail west of the tip: ${JSON.stringify([a, b])}`);
  assert.ok((a[1] - tip[1]) * (b[1] - tip[1]) < 0, 'the barbs straddle the eastward segment');
  for (const [x, y] of [a, b]) assert.ok(Math.abs(Math.hypot(x, y) - size) < 1e-12, 'head size is preserved at the equator');
}

// Looking back two vertices uses a northward chord across the turn rather than the eastward segment drawn at the tip.
test('a sharp turn points east along the incoming terminal segment', () => {
  assertEast(headRing(turn));
});

test('a straight eastward streamline still points east at the same size', () => {
  assertEast(headRing([[-2, 0], incoming, tip]));
});

test('repeated tip positions do not change the terminal head', () => {
  const ring = headRing(turn);
  assert.deepEqual(headRing([...turn, [...tip]]), ring);
  assert.deepEqual(headRing([...turn, [...tip], [...tip], [...tip]]), ring);
});

test('only streamlines with no direction omit the head', () => {
  for (const coords of [[], [tip], [tip, [...tip], [...tip]]]) {
    const {sources} = currentsOverlay([{coords}], image, size);
    assert.deepEqual(sources[CURRENTS_HEADS].data.features, []);
    assert.deepEqual(sources[CURRENTS_LINES].data.features[0].geometry.coordinates, coords);
  }
  assertEast(headRing([incoming, tip]));
});
