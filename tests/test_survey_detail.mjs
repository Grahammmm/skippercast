import assert from 'node:assert/strict';
import test from 'node:test';
import {decodeSurveyDetail} from '../web/map/survey-detail.ts';

const ring = (w, s, e, n) => [[w,s], [e,s], [e,n], [w,n], [w,s]];
const feature = (properties, coordinates = [ring(-121, 35, -120.9, 35.1)]) => ({
  type: 'Feature', geometry: {type: 'Polygon', coordinates}, properties,
});
const document = features => ({type: 'FeatureCollection', region: 'test-coast', navigation: 'NOT FOR NAVIGATION', features});
const reviewed = new Set(['test-survey', 'test-compiled']);
const decode = value => decodeSurveyDetail('test-coast', value, reviewed);

// Same nominal grid can be estimated in shallow water or measured deeper down.
// An interpolated 1 m grid also stays estimated, and compiled never gets a measured tier.
test('the MB-09 per-cell tier governs copy, not the nominal resolution', () => {
  const examples = [
    [{tier: 'estimated', grid_m: 1, source: 'Test interpolation'}, 'estimated (1 m grid, Test interpolation)'],
    [{tier: 'estimated', grid_m: 2, source: 'Test survey'}, 'estimated (2 m grid, Test survey)'],
    [{tier: '2m', grid_m: 2, source: 'Test survey'}, '2 m'],
    [{tier: 'estimated', grid_m: 4, source: 'Test compiled', grid_tier: '4-16m-compiled'}, 'estimated (4 m grid, Test compiled)'],
    [{tier: '1m-measured', grid_m: 1, source: 'Test survey'}, '1 m measured'],
  ];
  assert.deepEqual(decode(document(examples.map(([p]) => feature({...p, sources: [p.grid_tier ? 'test-compiled' : 'test-survey']}))))
    .features.map(({properties}) => properties.label), examples.map(([, label]) => label));
  assert.equal(decode(document([feature({tier: 'estimated', grid_m: 2, sources: ['test-survey']})])), null, 'do not make up a source');
});

test('only explicit no-data geometry is admitted; land holes remain holes', () => {
  const outer = ring(-121, 35, -120.9, 35.1), land = ring(-120.98, 35.02, -120.96, 35.04).reverse();
  const data = document([feature({tier: 'none', sources: [], date: null}, [outer, land])]);
  assert.deepEqual(decode(data).features[0].geometry.coordinates, [outer, land]);
  assert.equal(decode(data).features[0].properties.label, 'No survey');
  assert.deepEqual(decode(document([])).features, [], 'missing footprint does not mean no survey');
  assert.equal(decode({...data, region: 'other-coast'}), null);
  assert.equal(decode(document([feature({tier: 'unknown', sources: []})])), null);
  assert.equal(decode(document([feature({tier: 'none', sources: []}, [outer.slice(0, -1)])])), null);
});

test('reject detail not supported by the reviewed inputs', () => {
  for (const p of [
    {tier: 'estimated', grid_m: 1, source: 'Unlisted', sources: ['unlisted']},
    {tier: '1m-measured', grid_m: 2, source: 'Test survey', sources: ['test-survey']},
    {tier: '2m', grid_m: 2, source: 'Test compiled', sources: ['test-compiled'], grid_tier: '4-16m-compiled'},
  ]) assert.equal(decode(document([feature(p)])), null);
});
