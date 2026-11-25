import assert from 'node:assert/strict';
import test from 'node:test';
import {regionPastDays} from '../web/map/region-past-days.ts';

const region = 'test-coast';
const zone = 'America/Los_Angeles';
const now = new Date('2026-03-09T07:30:00Z');
const sst = 'sst-analysis';
const chl = 'chlorophyll-observation';
const sunday = '2026-03-09T06:59:59Z';

function layer(id, kind, fields, samples) {
  return {
    id, kind, fields: ['latitude', 'longitude', ...fields], resolution_degrees: [0.05, 0.05],
    frames: [{time: now.getTime() / 1000}], tiles: [], max_age_hours: 24, status: 'ok',
    history: samples.map(sample_at => ({sample_at, tiles: [{
      path: `habitat-history/${id}-${'a'.repeat(16)}.json`, sha256: 'a'.repeat(64), bytes: 1,
    }]})),
  };
}

const analysis = (...samples) => layer(sst, 'analysis', ['temperature_c', 'analysis_error_c'], samples);
const observation = (...samples) => layer(chl, 'observation', ['chlorophyll_mg_m3'], samples);

function manifest(...layers) {
  return {
    schema_version: 1, region_id: region,
    layers: Object.fromEntries(layers.map(l => [l.id, l])),
    sources: Object.fromEntries(layers.map(l => [l.id, {name: 'Synthetic product'}])),
  };
}

// Requiring both layers would suppress the days of regions with just one product.
test('C1: accepts either observed layer by itself', () => {
  for (const entry of [analysis(sunday), observation(sunday)]) {
    assert.deepEqual(regionPastDays(manifest(entry), region, now, zone), {
      days: [{day: '2026-03-08', weekday: 'Sun', layers: [entry.id]}],
    });
  }
});

// A current frame must not be mistaken for a past observation.
test('C1: listed layers without history contribute no days', () => {
  const feed = manifest(analysis(), observation());
  delete feed.layers[sst].history;
  feed.layers[sst].frames[0].time = Date.parse(sunday) / 1000;
  assert.deepEqual(regionPastDays(feed, region, now, zone), {days: []});
});

// A cache or caller mix-up must not expose a different region's history.
test('C1: refuses another region’s manifest and non-manifest input', () => {
  assert.deepEqual(regionPastDays(manifest(analysis(sunday), observation(sunday)), 'other-coast', now, zone), {days: []});
  assert.deepEqual(regionPastDays(null, region, now, zone), {days: []});
});

// Catching a layer error around the whole join would discard its valid sibling;
// bypassing layerOf would incorrectly offer history from the malformed entry.
test('C1: a malformed layer does not suppress a valid sibling', () => {
  const badSst = layer(sst, 'analysis', ['temperature_c'], [sunday]);
  const badChl = layer(chl, 'observation', ['temperature_c'], [sunday]);
  for (const [bad, good] of [[badSst, observation(sunday)], [badChl, analysis(sunday)]]) {
    assert.deepEqual(regionPastDays(manifest(bad, good), region, now, zone), {
      days: [{day: '2026-03-08', weekday: 'Sun', layers: [good.id]}],
    });
  }
});

// Reporting raw history timestamps would promise days with no valid tile reference.
test('C1: ignores unvalidated history references', () => {
  const entry = analysis(sunday);
  entry.history[0].tiles = [];
  assert.deepEqual(regionPastDays(manifest(entry), region, now, zone), {days: []});
});

// Intl throws on bad clock inputs; the region join must still return its result shape.
test('C1: invalid clock or zone fails closed', () => {
  const feed = manifest(analysis(sunday));
  assert.deepEqual(regionPastDays(feed, region, new Date(NaN), zone), {days: []});
  assert.deepEqual(regionPastDays(feed, region, now, 'Not/A_Zone'), {days: []});
});

// UTC grouping, a fixed offset, intersecting instead of joining, or carrying
// manifest insertion order into coverage would all give the wrong rows.
test('C2: joins and orders layers by Los Angeles local day across spring DST', () => {
  const feed = manifest(
    observation('2026-03-08T08:00:00Z', '2026-03-07T07:59:59Z'),
    analysis(sunday, '2026-03-08T07:59:59Z', '2026-03-09T07:00:00Z'),
  );
  assert.deepEqual(regionPastDays(feed, region, now, zone), {days: [
    {day: '2026-03-06', weekday: 'Fri', layers: [chl]},
    {day: '2026-03-07', weekday: 'Sat', layers: [sst]},
    {day: '2026-03-08', weekday: 'Sun', layers: [sst, chl]},
  ]});
});

// The cap is on observed local days in the joined result, not per layer or on
// elapsed calendar days: Feb 26 survives, while the eighth observation does not.
test('C2: keeps only the seven newest observed days, even across gaps older than a week', () => {
  const feed = manifest(
    analysis('2026-03-08T12:00:00Z', '2026-03-06T12:00:00Z', '2026-03-04T12:00:00Z', '2026-02-20T12:00:00Z'),
    observation('2026-03-07T12:00:00Z', '2026-03-05T12:00:00Z', '2026-03-03T12:00:00Z', '2026-02-26T12:00:00Z'),
  );
  assert.deepEqual(regionPastDays(feed, region, now, zone), {days: [
    {day: '2026-02-26', weekday: 'Thu', layers: [chl]},
    {day: '2026-03-03', weekday: 'Tue', layers: [chl]},
    {day: '2026-03-04', weekday: 'Wed', layers: [sst]},
    {day: '2026-03-05', weekday: 'Thu', layers: [chl]},
    {day: '2026-03-06', weekday: 'Fri', layers: [sst]},
    {day: '2026-03-07', weekday: 'Sat', layers: [chl]},
    {day: '2026-03-08', weekday: 'Sun', layers: [sst]},
  ]});
});
