import assert from 'node:assert/strict';
import test from 'node:test';
import {planWatchRun} from '../server/spot-watch-run.ts';
import {watchFeedLayers} from '../server/watch-feed-layers.ts';

const region = 'test-coast';
const sst = 'sst-analysis';
const chl = 'chlorophyll-observation';
const unrelated = 'other-analysis';
const row = (id, kind, field, status) => ({
  id, kind, fields: ['latitude', 'longitude', field], status,
  resolution_degrees: [0.05, 0.05], frames: [], tiles: [], max_age_hours: 72,
});
const sstRow = (status = 'ok') => row(sst, 'analysis', 'temperature_c', status);
const chlRow = (status = 'retained') => row(chl, 'observation', 'chlorophyll_mg_m3', status);
const manifest = (...rows) => ({
  schema_version: 1,
  region_id: region,
  layers: Object.fromEntries(rows.map(layer => [layer.id, layer])),
  sources: Object.fromEntries(rows.map(({id}) => [id, {name: 'Synthetic product', status: 'stale'}])),
});

test('C1: use layer statuses and first-seen watch-feed order, not source or manifest order', () => {
  // SST deliberately has no contrast field; the duplicate mapping must not impose it.
  const data = manifest(chlRow(), row(unrelated, 'analysis', 'temperature_c', 'ok'), sstRow());
  assert.deepEqual(Object.entries(watchFeedLayers(data, region)), [
    [sst, {status: 'ok'}],
    [chl, {status: 'retained'}],
  ]);
});

test('C2: skip absent entries instead of synthesizing statuses', () => {
  assert.deepEqual(watchFeedLayers(manifest(chlRow()), region), {[chl]: {status: 'retained'}});
});

test('C2: a malformed SST layer does not hide valid chlorophyll', () => {
  const malformed = {...sstRow(), fields: ['latitude', 'longitude', 'temperature_gradient_c_per_km']};
  assert.deepEqual(watchFeedLayers(manifest(malformed, chlRow()), region), {[chl]: {status: 'retained'}});
});

test('C2: chlorophyll must have both the observation kind and the required field', () => {
  for (const malformed of [{...chlRow(), kind: 'analysis'}, {...chlRow(), fields: ['latitude', 'longitude']}]) {
    assert.deepEqual(watchFeedLayers(manifest(sstRow(), malformed), region), {[sst]: {status: 'ok'}});
  }
});

test('C2: a foreign region cannot supply statuses', () => {
  assert.deepEqual(watchFeedLayers(manifest(sstRow(), chlRow()), 'other-coast'), {});
});

test('C2: non-object manifests do not throw or supply statuses', () => {
  for (const value of [null, undefined, 'not a manifest', []]) {
    assert.deepEqual(watchFeedLayers(value, region), {});
  }
});

test('C3: pipe manifest statuses into the exact plans without conflating stale and missing', () => {
  const publication = 'fixture|2026-11-20T12:00:00Z';
  const watches = [
    {id: 'temp', layer: 'water-temp'},
    {id: 'contrast', layer: 'sst-contrast'},
    {id: 'chl', layer: 'chlorophyll'},
  ].map(watch => ({...watch, enabled: true, createdAt: '2026-11-19T12:00:00Z'}));
  const plan = data => planWatchRun({degraded: false, publication, watches, layers: watchFeedLayers(data, region)});

  assert.deepEqual(plan(manifest(sstRow(), chlRow())), {
    run: true, publication, evaluate: ['chl', 'contrast', 'temp'], unknown: [], deferred: [],
  });
  assert.deepEqual(plan(manifest(sstRow('stale'))), {
    run: true, publication, evaluate: [], unknown: [
      {id: 'chl', reason: 'layer-missing'},
      {id: 'contrast', reason: 'layer-withheld'},
      {id: 'temp', reason: 'layer-withheld'},
    ], deferred: [],
  });
});
