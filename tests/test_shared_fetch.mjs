// The v2 startup budget (scripts/startup-budget.json): web/shared-fetch.ts
// shares one request per committed static JSON file, and passes live feeds,
// other origins and fresh reads straight through. Runs by type stripping.
import assert from 'node:assert/strict';
import test from 'node:test';
import {shareStatic, sharedKey} from '../web/shared-fetch.ts';

const BASE = 'https://s.test/map?region=morro-bay';

test('only committed regions/ and data/ JSON on the page origin is shared', () => {
  assert.equal(sharedKey('regions/morro-bay/region.json', {}, BASE), 'https://s.test/regions/morro-bay/region.json');
  assert.equal(sharedKey('https://s.test/data/protected-areas.geojson', {signal: AbortSignal.timeout(1000)}, BASE), 'https://s.test/data/protected-areas.geojson');
  for (const [url, init] of [
    ['/api/daily?region=morro-bay&part=mpa-boundaries', {}],
    ['/feeds/data/regions/morro-bay/latest.json', {}],
    ['https://other.test/data/atlas.json', {}],
    ['regions/morro-bay/region.json', {cache: 'no-cache'}],
    ['regions/morro-bay/region.json', {cache: 'no-store'}],
    ['regions/morro-bay/region.json', {method: 'POST'}],
    ['regions/morro-bay/region.json?v=2', {}],
    ['regions/morro-bay/bottom/tile.pmtiles', {}],
  ]) assert.equal(sharedKey(url, init, BASE), null, `${url} ${JSON.stringify(init)}`);
});

function counting(respond = () => ({ok: true})) {
  const calls = [];
  const fetchFn = async (url, init = {}) => { calls.push([url, init]); return respond(url); };
  return {calls, fetchFn};
}

test('concurrent and later reads of one static file make one request; each caller gets its own clone', async () => {
  const calls = [];
  let clones = 0;
  const fetchFn = async url => { calls.push(url); return {ok: true, clone() { clones++; return {ok: true, json: async () => ({url})}; }}; };
  globalThis.location = {href: BASE};
  try {
    const shared = shareStatic(fetchFn);
    assert.equal(shareStatic(fetchFn), shared, 'one wrapper per fetch');
    assert.equal(shareStatic(shared), shared, 'wrapping twice shares the same reads');
    const [a, b] = await Promise.all([shared('regions/morro-bay/region.json'), shared('https://s.test/regions/morro-bay/region.json', {signal: AbortSignal.timeout(5000)})]);
    const c = await shared('regions/morro-bay/region.json');
    assert.equal(calls.length, 1, 'one request');
    assert.equal(clones, 3, 'each caller reads its own clone');
    assert.notEqual(a, b);
    assert.deepEqual(await c.json(), {url: 'regions/morro-bay/region.json'});
  } finally { delete globalThis.location; }
});

test('live feeds, fresh reads and failures are not shared', async () => {
  globalThis.location = {href: BASE};
  try {
    let fail = true;
    const {calls, fetchFn} = counting(url => /coverage/.test(url) && fail ? {ok: false, status: 503} : {ok: true});
    const shared = shareStatic(fetchFn);
    await shared('/api/forecast?region=morro-bay'); await shared('/api/forecast?region=morro-bay');
    await shared('regions/morro-bay/region.json', {cache: 'no-cache'}); await shared('regions/morro-bay/region.json', {cache: 'no-cache'});
    assert.equal((await shared('regions/morro-bay/coverage.json')).ok, false);
    fail = false;
    assert.equal((await shared('regions/morro-bay/coverage.json')).ok, true, 'a failed read is asked again');
    assert.equal(calls.length, 6);
    // The shared request carries no caller's signal: one caller timing out does not fail the others.
    const held = shareStatic(async (url, init = {}) => { calls.push([url, init]); await new Promise(r => setTimeout(r, 30)); return {ok: true}; });
    const quick = AbortSignal.timeout(1);
    const [early, late] = await Promise.allSettled([held('data/atlas.json', {signal: quick}), held('data/atlas.json')]);
    assert.equal(early.status, 'rejected', 'the caller whose signal aborted is rejected');
    assert.equal(late.status, 'fulfilled');
    assert.equal(calls.at(-1)[1].signal, undefined);
  } finally { delete globalThis.location; }
});
