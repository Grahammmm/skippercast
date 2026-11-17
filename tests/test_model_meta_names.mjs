// Model metadata admits only own MODELS names: inherited Object names are refused
// with the Unknown model QueryError before any manifest or bucket read (RF1751-5).
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';
import {meta, MODELS, QueryError} from '../server/model-api.js';

const INHERITED = ['constructor', '__proto__', 'toString', 'valueOf', 'hasOwnProperty'];
const published = model => ({model, provider: 'synthetic', documentation: 'https://example.invalid/docs', cycle_iso: '2026-01-01T00:00:00Z',
  meta: {last_run_initialisation_time: 0, data_end_time: 18000}});
const counting = (fn = async m => published(m)) => {
  const store = {calls: [], manifest: async m => { store.calls.push(m); return fn(m); }};
  return store;
};
const refusal = e => e instanceof QueryError && e.message === 'Unknown model';

test('meta_inherited_names_refuse_before_storage', async () => {
  for (const name of INHERITED) {
    const store = counting(async () => { throw new Error('storage must not be read'); });
    await assert.rejects(meta(name, store), refusal, name);
    assert.deepEqual(store.calls, [], name);
  }
});

test('meta_own_models_preserve_projection', async () => {
  for (const name of Object.keys(MODELS)) {
    const store = counting();
    const result = await meta(name, store);
    assert.deepEqual(store.calls, [name], name);
    assert.ok(isDeepStrictEqual(result, {last_run_initialisation_time: 0, data_end_time: 18000, provider: 'synthetic',
      source: 'https://example.invalid/docs', cycle_iso: '2026-01-01T00:00:00Z'}), name);
  }
});

test('meta_unpublished_and_unknown_remain_distinct', async () => {
  const store = counting(async () => ({model: 'gfs_global'}));
  await assert.rejects(meta('gfs_global', store), e => e instanceof QueryError && e.message === 'Model not yet published');
  assert.deepEqual(store.calls, ['gfs_global']);
  for (const bad of ['not_a_model', '', ' gfs_global', 'gfs_global ', 'GFS_GLOBAL']) {
    const unread = counting();
    await assert.rejects(meta(bad, unread), refusal, JSON.stringify(bad));
    assert.deepEqual(unread.calls, [], JSON.stringify(bad));
  }
});

test('metadata_route_inherited_names_are_400_without_bucket_reads', async () => {
  const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
  const saved = {};
  const names = ['REGIONS', 'DEPLOYMENT', 'SHELLS', 'BUILD_ID', 'fetch'];
  for (const n of names) saved[n] = Object.getOwnPropertyDescriptor(globalThis, n);
  let fetched = 0;
  try {
    globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
    globalThis.DEPLOYMENT = read('../deployments/production.json');
    globalThis.SHELLS = {'/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html', '/sources.html': '/sources.0123456789.html'};
    globalThis.BUILD_ID = 'build-test';
    const {default: worker} = await import('../server/index.ts');
    globalThis.fetch = async () => { fetched++; throw new Error('no upstream request expected'); };
    const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
    const reads = [];
    const FEEDS = {get: async key => {
      reads.push(key);
      if (key.endsWith('/manifest.json')) return {json: async () => published(key.split('/')[1])};
      return null; // no release pointer: legacy layout
    }};
    const get = path => worker.fetch(new Request('https://skippercast.com' + path), {ASSETS, FEEDS});
    for (const name of ['constructor', '__proto__']) {  // the route grammar is lowercase only
      const path = `/api/om/data/${name}/static/meta.json`;
      const response = await get(path);
      assert.equal(response.status, 400, path);
      const body = await response.json();
      assert.deepEqual([body.error, body.reason], [true, 'Unknown model'], path);
    }
    assert.deepEqual(reads, [], 'inherited names read no bucket keys');
    // Healthy control: an own model still reads its manifest and answers 200.
    const ok = await get('/api/om/data/gfs_global/static/meta.json');
    assert.equal(ok.status, 200);
    assert.equal((await ok.json()).provider, 'synthetic');
    assert.ok(reads.includes('forecasts/gfs_global/manifest.json'));
    assert.equal(fetched, 0);
  } finally {
    for (const n of names) { if (saved[n]) Object.defineProperty(globalThis, n, saved[n]); else delete globalThis[n]; }
  }
});
