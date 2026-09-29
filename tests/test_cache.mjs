import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {cacheKey, overLimit} from '../server/edge-cache.ts';
import {useBucket, EDGE_CACHE_MAX_BYTES} from '../server/feeds.ts';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {};
globalThis.BUILD_ID = 'b1';
const {default: worker} = await import('../server/index.ts');

// A stand-in for caches.default with the Workers Cache API semantics the Worker
// relies on: put() refuses 206 and no-store; match() answers Range from a
// cached 200 (206 + Content-Range) and If-None-Match with 304.
class FakeCache {
  constructor() { this.entries = new Map(); this.puts = 0; }
  async put(request, response) {
    if (response.status === 206) throw new TypeError('Cannot cache a 206 response');
    if (/no-store|private/.test(response.headers.get('Cache-Control') || '')) { await response.arrayBuffer(); return; }
    this.puts++;
    this.entries.set(request.url, {status: response.status, headers: [...response.headers], body: new Uint8Array(await response.arrayBuffer())});
  }
  async match(request) {
    const entry = this.entries.get(request.url);
    if (!entry) return undefined;
    const headers = new Headers(entry.headers);
    if (request.headers.get('If-None-Match') && request.headers.get('If-None-Match') === headers.get('ETag')) return new Response(null, {status: 304, headers});
    const range = /^bytes=(\d*)-(\d*)$/.exec(request.headers.get('Range') || '');
    if (range && entry.status === 200) {
      const size = entry.body.length;
      const start = range[1] === '' ? size - Number(range[2]) : Number(range[1]);
      const end = range[1] === '' || range[2] === '' ? size - 1 : Math.min(Number(range[2]), size - 1);
      headers.set('Content-Range', `bytes ${start}-${end}/${size}`);headers.set('Content-Length', String(end - start + 1));
      return new Response(entry.body.slice(start, end + 1), {status: 206, headers});
    }
    return new Response(entry.body, {status: entry.status, headers});
  }
}
function fakeLimiter(limit) {
  const counts = new Map();
  return {counts, async limit({key}) { counts.set(key, (counts.get(key) || 0) + 1); return {success: counts.get(key) <= limit}; }};
}
async function withEdge(fn) {
  const cache = new FakeCache(), originalCaches = globalThis.caches, originalFetch = globalThis.fetch;
  // Named caches are unavailable, so every upstream read below is counted.
  globalThis.caches = {default: cache, async open() { throw Error('named caches unavailable'); }};
  try { return await fn(cache); } finally { globalThis.caches = originalCaches; globalThis.fetch = originalFetch; useBucket({}); }
}
const ctx = () => { const pending = []; return {pending, waitUntil: p => pending.push(p), settle: () => Promise.all(pending)}; };
const get = (path, headers = {}) => new Request('https://skippercast.com' + path, {headers: {'cf-connecting-ip': '203.0.113.9', ...headers}});

test('cache keys ignore parameter order and unknown parameters, and carry the build', () => {
  assert.equal(cacheKey('https://s/api/om/v1/forecast?longitude=1&latitude=2').url, cacheKey('https://s/api/om/v1/forecast?latitude=2&longitude=1').url);
  assert.equal(cacheKey('https://s/api/forecast?region=x&bust=1', {params: ['region']}).url, 'https://s/api/forecast?region=x&sc-build=dev');
  assert.notEqual(cacheKey('https://s/x', {build: 'a'}).url, cacheKey('https://s/x', {build: 'b'}).url);
});

test('/api/om answers repeat queries from the edge cache; errors are not cached', () => withEdge(async cache => {
  let reads = 0;
  globalThis.fetch = async url => { reads++; assert.match(url, /gfs_global\/manifest\.json$/);
    return Response.json({meta: {last_run_initialisation_time: 0}, provider: 'NOAA', cycle_iso: '2026-09-28T00:00Z'}); };
  const c = ctx();
  const first = await worker.fetch(get('/api/om/data/gfs_global/static/meta.json?b=2&a=1'), {}, c);await c.settle();
  assert.equal(first.status, 200);assert.equal(first.headers.get('X-SC-Cache'), 'miss');
  assert.match(first.headers.get('Cache-Control'), /s-maxage=300/);
  const second = await worker.fetch(get('/api/om/data/gfs_global/static/meta.json?a=1&b=2'), {}, ctx());
  assert.equal(second.headers.get('X-SC-Cache'), 'hit');assert.deepEqual(await second.json(), await first.json());
  assert.equal(reads, 1, 'the hit did not read the manifest again');
  assert.equal(second.headers.get('Content-Security-Policy') !== null, true, 'cached responses still get security headers');
  for (let i = 0; i < 2; i++) assert.equal((await worker.fetch(get('/api/om/data/nope/static/meta.json'), {}, ctx())).status, 400);
  assert.equal(cache.puts, 1, 'the 400 was not stored');
}));

test('/api/forecast and /api/intelligence share one feed read per TTL', () => withEdge(async () => {
  let reads = 0;
  globalThis.fetch = async () => { reads++; return Response.json({region_id: 'morro-bay', schema_version: 1, forecast: {points: {north: {}}},
    sources: {'model-x': {name: 'x', status: 'ok', issue: 'i', url: 'u', checked_at: 'c', raw: 'dropped'}, other: {kept: true}}}); };
  const c = ctx();
  const forecast = await worker.fetch(get('/api/forecast?region=morro-bay'), {}, c);await c.settle();
  assert.equal(forecast.headers.get('X-SC-Cache'), 'miss');assert.deepEqual(await forecast.json(), {points: {north: {}}});
  const intel = await worker.fetch(get('/api/intelligence?region=morro-bay&junk=1'), {}, ctx());
  assert.equal(intel.headers.get('X-SC-Cache'), 'hit');assert.equal(reads, 1);
  const body = await intel.json();assert.equal(body.forecast, undefined);assert.equal(body.sources['model-x'].raw, undefined);assert.equal(body.sources.other.kept, true);
  assert.equal(intel.headers.get('Cache-Control'), 'public, max-age=60, s-maxage=60');
  assert.equal((await worker.fetch(get('/api/forecast?region=morro-bay'), {}, ctx())).headers.get('X-SC-Cache'), 'hit');
}));

test('/api/habitat is cached per region', () => withEdge(async () => {
  let reads = 0;
  globalThis.fetch = async () => { reads++; return Response.json({schema_version: 1, region_id: 'morro-bay', layers: {}}); };
  const c = ctx();
  assert.equal((await worker.fetch(get('/api/habitat?region=morro-bay'), {}, c)).headers.get('X-SC-Cache'), 'miss');await c.settle();
  assert.equal((await worker.fetch(get('/api/habitat?region=morro-bay&x=1'), {}, ctx())).headers.get('X-SC-Cache'), 'hit');
  assert.equal(reads, 1);
}));

test('without caches.default the endpoints still answer', async () => {
  const originalCaches = globalThis.caches, originalFetch = globalThis.fetch;
  globalThis.caches = {get default() { throw Error('default cache forbidden'); }, async open() { throw Error('no'); }};
  globalThis.fetch = async () => Response.json({schema_version: 1, region_id: 'morro-bay', layers: {}});
  try {
    const r = await worker.fetch(get('/api/habitat?region=morro-bay'), {});
    assert.equal(r.status, 200);assert.equal(r.headers.get('X-SC-Cache'), 'miss');
  } finally { globalThis.caches = originalCaches; globalThis.fetch = originalFetch; }
});

function bucket(objects, log) {
  return {async get(key, options = {}) {
    const header = options.range?.get?.('Range');
    log.push(header ? 'range' : 'full');
    const text = objects[key];if (text === undefined) return null;
    const bytes = new TextEncoder().encode(text), size = bytes.length;
    const match = /^bytes=(\d+)-(\d+)$/.exec(header || '');
    if (match) {
      const offset = Number(match[1]), length = Math.min(Number(match[2]), size - 1) - offset + 1;
      return {size, httpEtag: '"v1"', range: {offset, length}, body: new Blob([bytes.slice(offset, offset + length)]).stream()};
    }
    return {size, httpEtag: '"v1"', body: new Blob([bytes]).stream(), json: async () => JSON.parse(text)};
  }};
}

test('R2 feeds: whole objects are cached once and Range reads are served from them', () => withEdge(async cache => {
  const log = [], archive = 'PMTiles-0123456789abcdef';
  const FEEDS = bucket({'conditions/latest.json': '{"ok":true}', 'tiles/reefs.pmtiles': archive}, log);
  const env = {FEEDS};
  let c = ctx();
  const miss = await worker.fetch(get('/feeds/conditions/latest.json'), env, c);
  assert.equal(miss.headers.get('X-SC-Cache'), 'miss');assert.deepEqual(await miss.json(), {ok: true});await c.settle();
  const hit = await worker.fetch(get('/feeds/conditions/latest.json?cachebust=1'), env, ctx());
  assert.equal(hit.headers.get('X-SC-Cache'), 'hit');assert.equal(hit.headers.get('X-Feed-Source'), 'r2');
  assert.deepEqual(await hit.json(), {ok: true});assert.deepEqual(log, ['full']);
  // A first Range read comes from R2 as a range and fills the cache with the whole object after the reply.
  c = ctx();
  const first = await worker.fetch(get('/feeds/tiles/reefs.pmtiles', {Range: 'bytes=0-6'}), env, c);
  assert.equal(first.status, 206);assert.equal(first.headers.get('Content-Range'), `bytes 0-6/${archive.length}`);
  assert.equal(await first.text(), 'PMTiles');await c.settle();
  assert.deepEqual(log.slice(1), ['range', 'full']);
  const stored = cache.entries.get('https://skippercast.com/feeds/tiles/reefs.pmtiles?sc-build=b1');
  assert.equal(stored.status, 200);assert.equal(new TextDecoder().decode(stored.body), archive);
  assert.equal(new Headers(stored.headers).get('Content-Range'), null, 'the stored whole object has no range headers');
  assert.equal(new Headers(stored.headers).get('ETag'), '"v1"');
  // Later ranges (and conditional requests) are answered by the cache, not R2.
  const later = await worker.fetch(get('/feeds/tiles/reefs.pmtiles', {Range: 'bytes=8-11'}), env, ctx());
  assert.equal(later.status, 206);assert.equal(later.headers.get('X-SC-Cache'), 'hit');assert.equal(await later.text(), '0123');
  assert.equal(later.headers.get('Content-Range'), `bytes 8-11/${archive.length}`);
  const unchanged = await worker.fetch(get('/feeds/tiles/reefs.pmtiles', {'If-None-Match': '"v1"'}), env, ctx());
  assert.equal(unchanged.status, 304);
  assert.equal(log.length, 3, 'no further R2 reads');
}));

test('R2 feeds larger than the cache limit, 404s and seafloor archives are not cached', () => withEdge(async cache => {
  const log = [];
  const big = 'x'.repeat(EDGE_CACHE_MAX_BYTES + 1);
  const env = {FEEDS: bucket({'data/big.json': big}, log)};
  globalThis.fetch = async () => new Response('missing', {status: 404});
  let c = ctx();
  assert.equal((await worker.fetch(get('/feeds/data/big.json'), env, c)).status, 200);await c.settle();
  c = ctx();
  assert.equal((await worker.fetch(get('/feeds/data/big.json', {Range: 'bytes=0-1'}), env, c)).status, 206);await c.settle();
  assert.equal((await worker.fetch(get('/feeds/data/missing.json'), env, ctx())).status, 404);
  assert.equal((await worker.fetch(get('/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles'), env, ctx())).status, 503);
  assert.equal(cache.puts, 0);
}));

test('per-IP rate limits: /api/om 60/min and feeds 300/min return 429 with Retry-After', () => withEdge(async () => {
  globalThis.fetch = async () => Response.json({meta: {}, provider: 'NOAA'});
  const env = {PUBLIC_LIMITER: fakeLimiter(60), FEED_LIMITER: fakeLimiter(300), FEEDS: bucket({'data/x.json': '{}'}, [])};
  for (let i = 0; i < 60; i++) assert.equal((await worker.fetch(get('/api/om/data/gfs_global/static/meta.json'), env, ctx())).status, 200);
  const limited = await worker.fetch(get('/api/om/data/gfs_global/static/meta.json'), env, ctx());
  assert.equal(limited.status, 429);assert.equal(limited.headers.get('Retry-After'), '60');
  assert.ok(limited.headers.get('Strict-Transport-Security'));
  assert.equal((await worker.fetch(get('/api/om/data/gfs_global/static/meta.json', {'cf-connecting-ip': '198.51.100.1'}), env, ctx())).status, 200, 'another IP is unaffected');
  assert.deepEqual([...env.PUBLIC_LIMITER.counts.keys()], ['om:203.0.113.9', 'om:198.51.100.1']);
  for (let i = 0; i < 300; i++) await worker.fetch(get('/feeds/data/x.json'), env, ctx());
  const feed = await worker.fetch(get('/feeds/data/x.json'), env, ctx());
  assert.equal(feed.status, 429);assert.equal(feed.headers.get('Retry-After'), '60');
  assert.equal((await worker.fetch(get('/api/forecast?region=nowhere'), env, ctx())).status, 404, 'other routes are not limited');
}));

test('rate limiting is a no-op without the binding and fails open if the binding errors', async () => {
  assert.equal(await overLimit(undefined, 'k'), false);
  assert.equal(await overLimit({}, 'k'), false);
  assert.equal(await overLimit({limit: async () => { throw Error('limiter down'); }}, 'k'), false);
  assert.equal(await overLimit({limit: async () => ({success: false})}, 'k'), true);
});

test('wrangler.jsonc binds both per-IP limiters', () => {
  const config = JSON.parse(readFileSync(new URL('../wrangler.jsonc', import.meta.url), 'utf8').replace(/^\s*\/\/.*$/mg, ''));
  const limits = Object.fromEntries(config.ratelimits.map(r => [r.name, r]));
  assert.deepEqual(limits.PUBLIC_LIMITER.simple, {limit: 60, period: 60});
  assert.deepEqual(limits.FEED_LIMITER.simple, {limit: 300, period: 60});
  assert.notEqual(limits.PUBLIC_LIMITER.namespace_id, limits.FEED_LIMITER.namespace_id);
});
