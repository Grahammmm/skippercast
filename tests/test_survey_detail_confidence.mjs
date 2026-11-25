import assert from 'node:assert/strict';
import test from 'node:test';
import {decodeSurveyDetail, surveyDetailLayers} from '../web/map/survey-detail.ts';

const region = 'test-coast';
const sourceName = 'Synthetic provider';
const sourceId = 'reviewed-test-survey';
const reviewed = new Set([sourceId]);
const survey = {source: sourceName, sources: [sourceId]};
const estimated = {tier: 'estimated', grid_m: 5, ...survey};
const gap = {tier: 'none', sources: []};
const geometry = {type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]]};
const feature = properties => ({type: 'Feature', geometry, properties});
const collection = (...features) => ({type: 'FeatureCollection', region, navigation: 'NOT FOR NAVIGATION', features});
const decode = (...properties) => decodeSurveyDetail(region, collection(...properties.map(feature)), reviewed);
const layers = light => surveyDetailLayers('detail-data', 'detail', 'gap-pattern', {
  mapSurveyInk: '#111111', mapSurveyHalo: '#ffffff',
  mapSurveyTint1: '#112233', mapSurveyTint2: '#223344', mapSurveyTint5: '#334455',
}, light);

// A generic estimated label loses the grid; using provenance as text leaks the provider.
test('C1: the map symbol uses only the confidence label for every tier', () => {
  const specs = layers(false);
  const textFields = specs.flatMap(({layout}) => layout && 'text-field' in layout ? [layout['text-field']] : []);
  assert.deepEqual(textFields, [['get', 'label']]);
  const symbols = specs.filter(({type}) => type === 'symbol');
  assert.deepEqual(symbols.map(({id}) => id), ['detail-label']);
  assert.doesNotMatch(JSON.stringify(symbols), /sourceId|reviewed-test-survey|Synthetic provider/);
  assert.equal(symbols[0].layout['icon-image'], undefined);
  const [, labelProperty] = textFields[0];
  const detail = decode(
    {tier: '1m-measured', grid_m: 1, ...survey},
    {tier: '2m', grid_m: 2, ...survey},
    {tier: '5m', grid_m: 5, ...survey},
    estimated,
    gap,
  );
  assert.deepEqual(detail.features.map(({properties}) => properties[labelProperty]),
    ['1 m measured', '2 m', '5 m', 'estimated (5 m grid)', 'No survey']);
});

// Source-free text must not make uncredited or unreviewed footprints eligible.
for (const [name, patch] of [
  ['missing source', {source: undefined}],
  ['blank source', {source: '  '}],
  ['non-text source', {source: 7}],
  ['missing sources', {sources: undefined}],
  ['non-array sources', {sources: sourceId}],
  ['empty sources', {sources: []}],
  ['multiple sources', {sources: [sourceId, sourceId]}],
  ['non-text source ID', {sources: [7]}],
  ['unreviewed source ID', {sources: ['unreviewed']}],
]) {
  test(`C2: ${name} rejects the entire collection`, () => {
    assert.equal(decode(gap, {...estimated, ...patch}), null);
  });
}

test('C2: no survey requires an empty sources array and admits no provenance', () => {
  assert.equal(decode({tier: 'none'}), null);
  assert.equal(decode({...gap, ...survey}), null);
  assert.deepEqual(decode({...gap, source: sourceName}), {
    type: 'FeatureCollection', features: [feature({tier: 'none', label: 'No survey'})],
  });
});

// A nonblank check (or Date.parse alone) can pass February 30 to the Chart readout.
test('C2: a reviewed footprint retains only real survey dates at their supplied precision', () => {
  const grid_tier = '4-16m-compiled';
  const metadata = {tier: 'estimated', grid_m: 5, grid_tier, source: sourceName,
    sourceId, label: 'estimated (5 m grid)'};
  for (const date of ['2024-06-12', '2024-02-29', '2024-06', '2024']) {
    assert.deepEqual(decode({...estimated, grid_tier, date}), {
      type: 'FeatureCollection', features: [feature({...metadata, date})],
    }, date);
  }
  for (const date of ['2030-02-30', '1900-02-29', '2024-04-31', '2024-00-12', '2024-13',
    '0000', '2024-06-00', '2024-6-12', '2024-06-12T00:00:00Z', '2024-06-12\n', 'unstated', ' ', 2024, null]) {
    assert.deepEqual(decode({...estimated, grid_tier, date}), {
      type: 'FeatureCollection', features: [feature(metadata)],
    }, JSON.stringify(date));
  }
});

// Do not infer a measured tier from grid size, or relax the measured grid ceilings.
for (const [name, patch] of [
  ['missing grid', {grid_m: undefined}],
  ['text grid', {grid_m: '5'}],
  ['nonfinite grid', {grid_m: Infinity}],
  ['nonpositive grid', {grid_m: 0}],
  ['unknown tier', {tier: 'unknown'}],
  ['oversize 1 m grid', {tier: '1m-measured', grid_m: 1.01}],
  ['oversize 2 m grid', {tier: '2m', grid_m: 2.01}],
  ['oversize 5 m grid', {tier: '5m', grid_m: 5.01}],
  ['unknown compiled marker', {grid_tier: 'unknown'}],
  ['compiled marker on a measured grid', {tier: '5m', grid_tier: '4-16m-compiled'}],
]) {
  test(`C3: ${name} is withheld`, () => {
    assert.equal(decode({...estimated, ...patch}), null);
  });
}

// The caller toggles layers after the first one; moving the hatch would hide survey gaps.
test('C3: the no-survey hatch is the always-on first layer in either theme', () => {
  for (const light of [false, true]) {
    const [hatch, tint] = layers(light);
    assert.deepEqual(hatch, {id: 'detail-hatch', source: 'detail-data', type: 'fill',
      filter: ['==', ['get', 'tier'], 'none'],
      paint: {'fill-pattern': 'gap-pattern', 'fill-opacity': 0.9, 'fill-antialias': false}});
    assert.deepEqual(tint.filter, ['in', ['get', 'tier'], ['literal', ['1m-measured', '2m', '5m']]]);
  }
});

// R8 phone QA: on the light theme the 1.4 px estimated outline merged with the
// shoreline at z15. Only the light estimated boundary is wider; dark and measured stay put.
test('C3: the light-theme estimated boundary is drawn wider than measured outlines', () => {
  const outline = light => layers(light).find(({id}) => id === 'detail-outline');
  assert.deepEqual(outline(true).paint['line-width'], ['case', ['==', ['get', 'tier'], 'estimated'], 2.8, 1.4]);
  assert.equal(outline(false).paint['line-width'], 1.4);
  for (const light of [false, true]) assert.deepEqual(outline(light).paint['line-dasharray'], [4, 3]);
});
