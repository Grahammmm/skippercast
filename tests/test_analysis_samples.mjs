import assert from 'node:assert/strict';
import test from 'node:test';
import {analysisAlertCandidates} from '../server/analysis-alerts.ts';
import {analysisSamples} from '../server/analysis-samples.ts';

const region = 'bay';
const sst = 'sst-analysis';
const chl = 'chlorophyll-observation';

function manifest(sstFrames = [{time: 60}], chlFrames = [{time: 120}]) {
  const layer = (id, kind, field, frames, status) => ({
    id, kind, fields: ['latitude', 'longitude', field], frames, status,
    resolution_degrees: [0.05, 0.05], tiles: [], max_age_hours: 24,
  });
  return {
    schema_version: 1, region_id: region,
    layers: {
      [chl]: layer(chl, 'observation', 'chlorophyll_mg_m3', chlFrames, 'retained'),
      [sst]: layer(sst, 'analysis', 'temperature_c', sstFrames, 'ok'),
    },
    sources: {[sst]: {name: 'Fixture temperature'}, [chl]: {name: 'Fixture chlorophyll'}},
  };
}

const onlySst = {[sst]: '1970-01-01T00:01:00.000Z'};
const onlyChl = {[chl]: '1970-01-01T00:02:00.000Z'};

// Picking the last listed frame, interpreting seconds as milliseconds, or using manifest key order is wrong.
test('C1: returns the latest populated time for ok and retained layers in analysis order', () => {
  for (const valid_cells of [1, undefined, 'unknown', Infinity]) {
    const data = manifest([
      {time: 180, valid_cells: 0}, {time: 60.125, valid_cells},
      {time: 15, valid_cells: 2}, {time: 240, valid_cells: -1},
    ]);
    const result = analysisSamples(data, region);
    assert.deepEqual(result, {[sst]: '1970-01-01T00:01:00.125Z', ...onlyChl});
    assert.deepEqual(Object.keys(result), [sst, chl]);
  }
});

// Merely listed layers, including those with current-looking frames, must not count as samples.
test('C2: omits a withheld layer or an absent layer without suppressing its neighbor', () => {
  const withheld = manifest();
  withheld.layers[sst].status = 'withheld';
  assert.deepEqual(analysisSamples(withheld, region), onlyChl);

  const absent = manifest();
  delete absent.layers[chl];
  assert.deepEqual(analysisSamples(absent, region), onlySst);
});

// Neither a latest zero-count frame nor a layer-level timestamp substitutes for a populated frame.
test('C2: omits layers with only unpopulated frames or no frames', () => {
  const data = manifest([{time: 60, valid_cells: 0}, {time: 120, valid_cells: -1}], []);
  data.layers[sst].sample_at = '1970-01-01T00:02:00Z';
  assert.deepEqual(analysisSamples(data, region), {});
});

// Bypassing layerOf could accept the wrong kind/field; catching outside the loop would hide the good layer.
test('C2: isolates malformed layers that lack their required kind or field', () => {
  const wrongField = manifest();
  wrongField.layers[sst].fields = ['latitude', 'longitude', 'analysis_error_c'];
  assert.deepEqual(analysisSamples(wrongField, region), onlyChl);

  const wrongKind = manifest();
  wrongKind.layers[chl].kind = 'analysis';
  assert.deepEqual(analysisSamples(wrongKind, region), onlySst);
});

// Falling back to an older populated frame could make an invalid publication look current.
test('C2: an unconvertible newest populated time omits only that layer, without fallback', () => {
  const data = manifest([{time: 60, valid_cells: 1}, {time: 8640000000001, valid_cells: 1}]);
  assert.deepEqual(analysisSamples(data, region), onlyChl);
});

// Reading the layer keys without validating the manifest could misattribute or throw on invalid input.
test('C2: another region or a non-object manifest yields no samples', () => {
  assert.deepEqual(analysisSamples(manifest(), 'other-bay'), {});
  assert.deepEqual(analysisSamples('not a manifest', region), {});
});

// An incompatible timestamp spelling would make the real alert evaluator drop a genuinely newer sample.
test('C3: the real alert evaluator accepts both consecutive publications', () => {
  const previous = analysisSamples(manifest([{time: 0}], [{time: 8639999999999}]), region);
  const current = analysisSamples(manifest([{time: 60}], [{time: 8640000000000}]), region);
  assert.deepEqual(previous, {[sst]: '1970-01-01T00:00:00.000Z', [chl]: '+275760-09-12T23:59:59.000Z'});
  assert.deepEqual(current, {...onlySst, [chl]: '+275760-09-13T00:00:00.000Z'});
  assert.deepEqual(analysisAlertCandidates({
    subscriptions: [{owner: 'owner-A', region, layers: [sst, chl]}],
    previous: {[region]: previous}, current: {[region]: current},
  }), [
    {owner: 'owner-A', region, layer: chl, sampleAt: '+275760-09-13T00:00:00.000Z'},
    {owner: 'owner-A', region, layer: sst, sampleAt: '1970-01-01T00:01:00.000Z'},
  ]);
});
