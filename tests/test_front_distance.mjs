import test from 'node:test';
import assert from 'node:assert/strict';
import { EARTH_RADIUS_NM, frontDistanceNm } from '../server/front-distance.ts';

const front = (coordinates, type = 'LineString') => ({ geometry: { type, coordinates } });
const doc = (...fronts) => ({ fronts });
const origin = { lat: 0, lon: 0 };
const equator = doc(front([[-1, 0], [1, 0]]));

test('C1: export the nautical-mile radius, not the kilometre radius', () => {
  assert.equal(EARTH_RADIUS_NM, 3440.065);
});

test('C2: reject non-finite, out-of-range and non-numeric query coordinates', () => {
  for (const point of [
    { lat: NaN, lon: 0 }, { lat: 0, lon: Infinity }, { lat: -Infinity, lon: 0 },
    { lat: 91, lon: 0 }, { lat: -91, lon: 0 }, { lat: 0, lon: 181 }, { lat: 0, lon: -181 },
    { lat: '0', lon: 0 }, { lat: 0, lon: null }, {}, null,
  ]) {
    assert.equal(frontDistanceNm(point, equator), null);
  }
});

test('C2: reject absent or malformed documents rather than assuming a fronts array', () => {
  for (const input of [null, undefined, 1, 'fronts', [], {}, { fronts: {} }]) {
    assert.equal(frontDistanceNm(origin, input), null);
  }
});

test('C2: no usable segment', () => {
  // A vertex is not a segment, including after filtering or across separate lines.
  for (const input of [
    doc(), doc(front([])), doc(front([[0, 0]])), doc(front([[0, 0], [1, NaN]])),
    doc(front([[[0, 0]], [[1, 0]]], 'MultiLineString')),
    doc(null, false, {}, { geometry: null }, front(null), front([[0, 0], [1, 0]], 'Polygon')),
  ]) {
    assert.equal(frontDistanceNm(origin, input), null);
  }
});

test('C2: malformed object access cannot escape as an exception', () => {
  const input = { get fronts() { throw new Error('unreadable'); } };
  assert.equal(frontDistanceNm(origin, input), null);
});

test('C2: round a one-arcminute offset at 35 N to 1.00 nm', () => {
  const input = doc(front([[14.9, 35], [15.1, 35]]));
  // One arcminute is about 1.00067 nm with this radius; do not return raw precision.
  assert.equal(frontDistanceNm({ lat: 35 + 1 / 60, lon: 15 }, input), 1);
});

test('C3: a point on the interior of a segment is zero, not the distance to a vertex', () => {
  assert.equal(frontDistanceNm(origin, equator), 0);
});

test('C3: project a diagonal using cos(latitude) before measuring on the sphere', () => {
  // At 60 N, 2 degrees of longitude project to 1 degree of x. The foot is
  // [1, 60.5], whose spherical distance is 42.29 nm (the planar distance rounds to 42.45).
  assert.equal(frontDistanceNm({ lat: 60, lon: 0 }, doc(front([[0, 61], [2, 60]]))), 42.29);
});

test('C3: clamp an out-of-segment projection to the nearest endpoint in either direction', () => {
  const point = { lat: 0, lon: 2 };
  assert.equal(frontDistanceNm(point, doc(front([[0, 0], [1, 0]]))), 60.04);
  assert.equal(frontDistanceNm(point, doc(front([[1, 0], [0, 0]]))), 60.04);
});

test('C3: take the minimum across fronts, parts and segments without joining parts', () => {
  const input = doc(front([[-1, 3], [1, 3]]), front([
    null, [[-2, 0], [-2, 2], [2, 2]], [[2, 0], [2, 1], [-1, 1]],
  ], 'MultiLineString'), front([[-1, 4], [1, 4]]));
  // Only the last segment of the second part is 1 degree north.
  // Joining the opposed equatorial parts below would invent a zero distance.
  assert.equal(frontDistanceNm(origin, input), 60.04);
  assert.equal(frontDistanceNm(origin, doc(front([
    [[-2, 0], [-1, 0]], [[1, 0], [2, 0]],
  ], 'MultiLineString'))), 60.04);
});

test('C3: skip malformed vertices without breaking the line or accepting coercions', () => {
  // Breaking the chain loses the segment; coercing the string or admitting
  // the out-of-range latitude introduces a closer segment.
  const input = doc(front([
    [-1, 1], null, [], [0], [NaN, 0], [0, Infinity], [181, 0], [0, -91], ['0', 0], [1, 1],
  ]));
  assert.equal(frontDistanceNm(origin, input), 60.04);
});

test('C3: coincident endpoints still contribute, even at the coordinate bounds', () => {
  assert.equal(frontDistanceNm({ lat: 90, lon: 180 }, doc(front([[180, 89], [180, 89]]))), 60.04);
  assert.equal(frontDistanceNm({ lat: 0, lon: -180 }, doc(front([[0, 0], [0, 0]]))), 10807.28);
});
