import assert from 'node:assert/strict';
import test from 'node:test';
import {inspectLegalPack} from '../dist/legal-pack.js';

const origin = 'https://skippercast.test';
const now = Date.parse('2026-11-07T12:00:00Z');
const at = '2026-11-07T10:00:00Z';
function fixture() {
  const entries = new Map();
  const put = (path, data, saved = at) => entries.set(new URL(path, origin).href,
    new Response(JSON.stringify(data), {headers: {'X-SC-Saved-At': saved}}));
  put('/regions/test/region.json', {id: 'test', assets: {regulations: 'data/rules.json', protected_areas: 'data/areas.json'}});
  put('/data/rules.json', {schema_version: 1, valid_from: '2026-01-01', valid_through: '2026-12-31', reviewed_at: '2026-10-01', sources: {rules: {url: 'https://wildlife.ca.gov/Fishing/Ocean'}}});
  put('/data/areas.json', {type: 'FeatureCollection', features: []});
  for (const part of ['regulations', 'mpa-boundaries', 'additional-closures']) put(`/api/daily?region=test&part=${part}`,
    {schema_version: 1, region_id: 'test', part, generated_at: at, ...(part === 'regulations' ? {regulations: {checks: {rules: {status: 'ok', data_retrieved_at: at}}}} : {sources: {source: {status: 'ok', checked_at: at}}})});
  return {entries, put, cache: {match: async path => entries.get(new URL(path, origin).href)?.clone()}};
}

test('legal inventory reads actual cached parts, dates and official source links without fetching', async () => {
  const {cache} = fixture();
  const result = await inspectLegalPack(cache, 'test', origin, now);
  assert.equal(result.complete, true);
  assert.equal(result.items.length, 5);
  assert.ok(result.items.every(item => item.saved && item.saved_at === at));
  assert.equal(result.items[0].valid_from, '2026-01-01');
  assert.equal(result.items[0].reviewed_at, '2026-10-01');
  assert.deepEqual(result.items[0].sources, ['https://wildlife.ca.gov/Fishing/Ocean']);
  assert.equal(result.stale, false);
});

test('evicted, corrupt and wrong-region parts are missing even if pack metadata claimed success', async () => {
  for (const failure of ['evicted', 'corrupt', 'wrong-region']) {
    const {cache, entries, put} = fixture();
    const path = '/api/daily?region=test&part=additional-closures';
    if (failure === 'evicted') entries.delete(origin + path);
    if (failure === 'corrupt') entries.set(origin + path, new Response('invalid json'));
    if (failure === 'wrong-region') put(path, {schema_version: 1, region_id: 'elsewhere', part: 'additional-closures', generated_at: at, sources: {}});
    const result = await inspectLegalPack(cache, 'test', origin, now);
    assert.equal(result.complete, false, failure);
    assert.equal(result.items.at(-1).saved, false, failure);
  }
});

test('freshly saved old feeds, future/missing dates and expired rules warn rather than imply legal clearance', async () => {
  for (const generated_at of ['2026-11-05T12:00:00Z', '2026-11-08T12:00:00Z', null]) {
    const {cache, put} = fixture();
    put('/api/daily?region=test&part=regulations', {schema_version: 1, region_id: 'test', part: 'regulations', generated_at, regulations: {}});
    assert.equal((await inspectLegalPack(cache, 'test', origin, now)).stale, true);
  }
  const {cache, put} = fixture();
  put('/data/rules.json', {schema_version: 1, valid_from: '2026-01-01', valid_through: '2026-11-06'});
  assert.equal((await inspectLegalPack(cache, 'test', origin, now)).stale, true);
});

test('newly assembled feeds with stale, failed or absent source checks still warn', async () => {
  for (const checks of [{}, {rules: {status: 'error', data_retrieved_at: at}}, {rules: {status: 'ok', data_retrieved_at: '2026-11-05T12:00:00Z'}}]) {
    const {cache, put} = fixture();
    put('/api/daily?region=test&part=regulations', {schema_version: 1, region_id: 'test', part: 'regulations', generated_at: at, regulations: {checks}});
    assert.equal((await inspectLegalPack(cache, 'test', origin, now)).stale, true);
  }
});

test('old packs without a readable region config never report a complete legal inventory', async () => {
  const result = await inspectLegalPack({match: async () => undefined}, 'test', origin, now);
  assert.equal(result.complete, false);
  assert.equal(result.stale, true);
  assert.ok(result.items.every(item => !item.saved));
});
