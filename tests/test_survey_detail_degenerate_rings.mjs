import assert from 'node:assert/strict';
import test from 'node:test';
import {decodeSurveyDetail} from '../web/map/survey-detail.ts';

const exterior = [[-122, 34], [-121, 34], [-121, 35], [-122, 35], [-122, 34]];
const collinear = [[-122, 34], [-121.5, 34.5], [-121, 35], [-122, 34]];
const collapsedHole = [[-121.75, 34.25], [-121.5, 34.25], [-121.75, 34.25], [-121.75, 34.25]];
const properties = {tier: '2m', grid_m: 2, source: 'Test survey', sources: ['test-survey']};
const feature = (type, coordinates) => ({type: 'Feature', geometry: {type, coordinates}, properties});
const decode = (...features) => decodeSurveyDetail('test-coast', {
  type: 'FeatureCollection', region: 'test-coast', navigation: 'NOT FOR NAVIGATION', features,
}, new Set(properties.sources));

// Closure alone admits these rings; one bad ring must withhold the whole collection.
for (const [name, invalidFeature] of [
  ['a collinear exterior', feature('Polygon', [collinear])],
  ['a collapsed hole', feature('Polygon', [exterior, collapsedHole])],
  ['a collinear exterior in a later MultiPolygon member', feature('MultiPolygon', [[exterior], [collinear]])],
  ['a collapsed hole in a later MultiPolygon member', feature('MultiPolygon', [[exterior], [exterior, collapsedHole]])],
]) {
  test(`withholds survey detail with ${name}`, () => {
    assert.equal(decode(feature('Polygon', [exterior]), invalidFeature), null);
  });
}

test('withholds a ring whose edges are exactly retraced', () => {
  const path = [[-122.522, 35.827], [-121.775, 35.854], [-122.901, 35.712],
    [-122.278, 34.106], [-122.862, 35.968], [-121.054, 35.063]];
  const ring = [...path, ...path.slice(0, -1).reverse()];
  for (const coordinates of [[ring], [exterior, ring]]) {
    assert.equal(decode(feature('Polygon', coordinates)), null);
    assert.equal(decode(feature('Polygon', coordinates.map(r => r.toReversed()))), null);
  }
});

test('retains a nonzero ring even at subnormal scale', () => {
  const step = Number.MIN_VALUE;
  const ring = [[0, 0], [step, 0], [0, step], [0, 0]];
  assert.deepEqual(decode(feature('Polygon', [ring])).features[0].geometry.coordinates, [ring]);
});

// A sign restriction, rewinding, or an area cutoff could discard or change a real hole.
// The tiny triangle also loses its area if summed in unshifted longitude/latitude.
test('keeps a real hole and measured tier unchanged in either winding', () => {
  const x = -121.75, y = 34.25, step = 2 ** -21;
  const hole = [[x, y], [x, y + step], [x + step, y], [x, y]];
  for (const coordinates of [[exterior, hole], [exterior.toReversed(), hole.toReversed()]]) {
    for (const input of [feature('Polygon', coordinates), feature('MultiPolygon', [coordinates])]) {
      const expected = JSON.stringify(input.geometry);
      const [decoded] = decode(input).features;
      assert.equal(JSON.stringify(decoded.geometry), expected);
      assert.equal(decoded.properties.tier, '2m');
    }
  }
});
