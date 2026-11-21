import assert from 'node:assert/strict';
import test from 'node:test';
import {chlEdgeFeatures, chlEdgesDraw} from '../web/map/chl-edges-geojson.ts';

const observedAt = '2026-11-20T12:00:00Z';
const now = new Date(observedAt);
const edge = (parts = {}) => ({
  id: 'edge-z', observedAt, cells: 5, strength: 0.321987654, bandHalfWidthKm: 0,
  line: [[-131, 36], [-130, 37]], ...parts,
});
const doc = (parts = {}) => ({
  product: 'Synthetic chlorophyll', credit: 'Fixture credit', maxAgeMs: 172_800_000,
  observedAt, observedFraction: 0.64, withheld: null, edges: [edge()], ...parts,
});
const feature = (id, px0, strength, coordinates) => ({
  type: 'Feature', properties: {id, px0, strength}, geometry: {type: 'LineString', coordinates},
});
const collection = (...features) => ({type: 'FeatureCollection', features});

// Reversed ID order catches sorting; editing a point and appending another catches both levels of aliasing.
test('C1: project two lines in input order with independent coordinate arrays', () => {
  const input = {edges: [edge(), edge({id: 'edge-a', strength: 0.53, line: [[-129, 41], [-128, 40]]})]};
  const original = structuredClone(input);
  const result = chlEdgeFeatures(input);
  assert.deepEqual(result, collection(
    feature('edge-z', 0, 0.321987654, [[-131, 36], [-130, 37]]),
    feature('edge-a', 0, 0.53, [[-129, 41], [-128, 40]]),
  ));
  result.features[0].geometry.coordinates[0][0] = 42;
  result.features[1].geometry.coordinates.push([0, 0]);
  assert.deepEqual(input, original);
});

// 3000 m / (78271.517 * 0.8191520442889918) = 0.046789993431... px.
// These three latitudes average to 35, unlike either endpoint or their midpoint.
test('C2: round the full band width at the mean latitude of 35 N and preserve strength', () => {
  assert.deepEqual(chlEdgeFeatures({edges: [edge({bandHalfWidthKm: 1.5, line: [[-131, 32], [-130, 34], [-129, 39]]})]}),
    collection(feature('edge-z', 0.04678999, 0.321987654, [[-131, 32], [-130, 34], [-129, 39]])));
});

// At 90 degrees the floor, not cos(90 degrees), scales the full 2000 m band.
test('C2: clamp near-zero polar metres per pixel and keep a zero band at zero', () => {
  const pole = [[-131, 90], [-130, 90]];
  assert.deepEqual(chlEdgeFeatures({edges: [edge({line: pole, bandHalfWidthKm: 1}), edge({id: 'zero', line: pole})]}), collection(
    feature('edge-z', 25552.07918099, 0.321987654, [[-131, 90], [-130, 90]]),
    feature('zero', 0, 0.321987654, [[-131, 90], [-130, 90]]),
  ));
});

// The wrapper must return the actual geometry, not just an eligibility verdict.
test('C3: return draw data for a fresh observation without mutating the document', () => {
  const input = doc();
  const original = structuredClone(input);
  assert.deepEqual(chlEdgesDraw(input, now), {
    draw: true, data: collection(feature('edge-z', 0, 0.321987654, [[-131, 36], [-130, 37]])),
  });
  assert.deepEqual(input, original);
});

// No detected edge is not the same as a hidden observation.
test('C3: return an empty collection for an eligible document with no edges', () => {
  const input = doc({edges: []});
  assert.deepEqual(chlEdgeFeatures(input), collection());
  assert.deepEqual(chlEdgesDraw(input, now), {draw: true, data: collection()});
});

// An unconditional draw or a generic hidden status would lose these distinct gate reasons.
for (const [reason, parts, clock] of [
  ['withheld-clear-water', {withheld: 'too-little-clear-water', edges: []}, now],
  ['no-usable-frame', {withheld: 'no-usable-frame', observedAt: null, edges: []}, now],
  ['no-observation', {observedAt: null}, now],
  ['stale', {}, new Date('2026-11-22T12:00:00.001Z')],
  ['future', {}, new Date('2026-11-20T10:59:59.999Z')],
]) {
  test(`C3: do not draw for ${reason}`, () => {
    const input = doc(parts);
    const original = structuredClone(input);
    assert.deepEqual(chlEdgesDraw(input, clock), {draw: false, reason});
    assert.deepEqual(input, original);
  });
}
