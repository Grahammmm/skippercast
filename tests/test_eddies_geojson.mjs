import test from 'node:test';
import assert from 'node:assert/strict';
import {eddiesGeoJSON} from '../web/map/eddies-geojson.ts';

const frameTime = '2026-01-02T03:04Z';
const eddy = (outline, sense = 'cw', diameterKm = 12.36) => ({outline, sense, diameterKm, owMin: -0.025});
const collection = (...features) => ({type: 'FeatureCollection', features});
const polygon = (index, ring, sense, diameter_km) => ({
  type: 'Feature',
  geometry: {type: 'Polygon', coordinates: [ring]},
  properties: {kind: 'eddy', index, sense, diameter_km, frame_time: frameTime},
});
const arrow = (index, coordinates, sense, bearing) => ({
  type: 'Feature',
  geometry: {type: 'Point', coordinates},
  properties: {kind: 'eddy-sense', index, sense, bearing},
});

test('C1: groups three outlines before three arrows in input order without mutating the tile', () => {
  // Per-eddy emission would interleave geometries; in-place closure or sorting would write to frozen input.
  const frozenEddy = (value) => {
    value.outline.forEach(Object.freeze);
    Object.freeze(value.outline);
    return Object.freeze(value);
  };
  const tile = Object.freeze({frameTime, eddies: Object.freeze([
    frozenEddy(eddy([[6, 1], [7, 1], [7, 2], [6, 2]], 'cw', 21.24)),
    frozenEddy(eddy([[3, 2], [4, 3], [4, 1], [3, 2]], 'ccw', 8)),
    frozenEddy(eddy([[1, 3], [2, 2], [1, 2], [1, 3]], 'cw', 31.75)),
  ])});
  assert.deepEqual(eddiesGeoJSON(tile), collection(
    polygon(0, [[6, 1], [7, 1], [7, 2], [6, 2], [6, 1]], 'cw', 21.2),
    polygon(1, [[3, 2], [4, 3], [4, 1], [3, 2]], 'ccw', 8),
    polygon(2, [[1, 3], [2, 2], [1, 2], [1, 3]], 'cw', 31.8),
    arrow(0, [6, 2], 'cw', 90), arrow(1, [4, 3], 'ccw', 270), arrow(2, [1, 3], 'cw', 90),
  ));
});

// A reference comparison would append to the closed ring; a one-coordinate comparison
// would leave one of the open rings unclosed. Both components of closure matter.
for (const [name, end, closingPoints] of [
  ['closes a ring open only in longitude', [1, 0], [[0, 0]]],
  ['closes a ring open only in latitude', [0, 1], [[0, 0]]],
  ['does not append to a ring already closed by value', [0, 0], []],
]) {
  test(`C2: ${name} and rounds the diameter`, () => {
    const value = eddy([[0, 0], [2, 1], [1, 2], end]);
    assert.deepEqual(eddiesGeoJSON({frameTime, eddies: [value]}), collection(
      polygon(0, [[0, 0], [2, 1], [1, 2], end, ...closingPoints], 'cw', 12.4),
      arrow(0, [1, 2], 'cw', 90),
    ));
  });
}

test('C3: selects the westernmost northern vertex regardless of tie order, with the bearing for each sense', () => {
  // Picking the first or last tied vertex, or minimizing longitude without checking latitude, misplaces an arrow.
  const eastFirst = [[-6, -4], [-3, -2], [-5, -2], [-6, -4]];
  const westFirst = [[-6, -4], [-5, -2], [-3, -2], [-6, -4]];
  assert.deepEqual(eddiesGeoJSON({frameTime, eddies: [eddy(eastFirst), eddy(westFirst, 'ccw')]}), collection(
    polygon(0, eastFirst, 'cw', 12.4), polygon(1, westFirst, 'ccw', 12.4),
    arrow(0, [-5, -2], 'cw', 90), arrow(1, [-5, -2], 'ccw', 270),
  ));
});

test('C4: returns an empty FeatureCollection for an empty tile', () => {
  // Empty data is not an exception, null, or a placeholder arrow.
  assert.deepEqual(eddiesGeoJSON({frameTime, eddies: []}), {type: 'FeatureCollection', features: []});
});
