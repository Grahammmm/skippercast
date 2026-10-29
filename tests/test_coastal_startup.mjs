import test from 'node:test';
import assert from 'node:assert/strict';
import {warmRegion} from '../web/landing/region-warm.ts';

const page = 'https://startup.test/';
const never = () => new Promise(() => {});
const ok = () => new Response('{}', {headers: {'Content-Type': 'application/json'}});

test('warmup bounds a stalled region JSON body, even when fetch ignores abort', {timeout: 1000}, async () => {
  let signal, cancelled = false;
  const fetcher = async (_url, init) => {
    signal = init.signal;
    return new Response(new ReadableStream({cancel() { cancelled = true; }}));
  };
  const result = await warmRegion('morro-bay', page, fetcher, {}, {timeoutMs: 20});
  assert.equal(result.state, 'failed');
  assert.equal(signal.aborted, true);
  assert.equal(cancelled, true);
});

test('admission shares same-key work, refuses saturation and retains abort-ignoring slots', async () => {
  const {startupAdmission} = await import('../web/landing/region-warm.ts');
  const pool = startupAdmission(2, 20);
  const a = Promise.withResolvers(), b = Promise.withResolvers();
  let reads = 0;
  const first = pool.read('a', async () => { reads++; return a.promise; });
  const shared = pool.read('a', never);
  assert.equal(first, shared);
  const other = pool.read('b', () => b.promise);
  await assert.rejects(pool.read('c', never), /saturated/);
  const failed = await Promise.allSettled([first, other]);
  assert.ok(failed.every(r => r.status === 'rejected'));
  assert.equal(reads, 1);
  await assert.rejects(pool.read('c', never), /saturated/, 'a non-cooperative task still owns its slot');
  a.resolve('late'); b.resolve('late');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(await pool.read('c', async () => 'recovered'), 'recovered');
});

test('source age is derived from its original timestamp and injected clock, never cache access', async () => {
  const {sourceFreshness} = await import('../web/landing/region-warm.ts');
  const sourceAt = '2026-10-29T12:00:00Z', start = Date.parse(sourceAt);
  let now = start + 60_000;
  const cached = {sourceAt};
  assert.deepEqual(sourceFreshness(cached.sourceAt, 120_000, () => now), {state: 'current', ageMs: 60_000});
  now += 60_000;
  assert.deepEqual(sourceFreshness(cached.sourceAt, 120_000, () => now), {state: 'stale', ageMs: 120_000});
  assert.equal(sourceFreshness('bad', 120_000, () => now).state, 'unknown');
  assert.equal(sourceFreshness(null, 120_000, () => now).state, 'unknown');
  assert.equal(sourceFreshness(new Date(now + 300_001).toISOString(), 120_000, () => now).state, 'unknown');
  assert.equal(cached.sourceAt, sourceAt);
});

test('coast bridge and R2 metadata deadlines include stalled bodies and reads', {timeout: 1000}, async () => {
  globalThis.REGIONS = {};
  globalThis.DEPLOYMENT = {allowed_origins: ['https://skippercast.com']};
  const {serveCoastData} = await import('../server/coast-data.ts');
  const req = path => new Request('https://skippercast.com' + path);
  let cancelled = false;
  const fetcher = async () => new Response(new ReadableStream({cancel() { cancelled = true; }}));
  const result = await serveCoastData(req('/coast-data/data/coast-wide/stalled.bin'), fetcher, null, new Set(), {timeoutMs: 20});
  assert.equal(result.status, 503);
  assert.equal(cancelled, true);
  const store = {get: never, head: never};
  const r2 = await serveCoastData(req('/coast-data/data/coast-wide/stalled.bin'), never, store, new Set(), {timeoutMs: 20});
  assert.equal(r2.status, 503);
});

test('region selection admits only the latest result, including A to B to A switches', async () => {
  const {createRegionWarmup} = await import('../web/landing/region-warm.ts');
  const gates = [], seen = [];
  const fetcher = async url => {
    if (!url.endsWith('/region.json')) return ok();
    const gate = Promise.withResolvers(); gates.push(gate); return gate.promise;
  };
  const warm = createRegionWarmup(fetcher, {});
  const a = warm.select('a', page, result => seen.push(['old-a', result.state]));
  await new Promise(resolve => setImmediate(resolve));
  const b = warm.select('b', page, result => seen.push(['b', result.state]));
  await new Promise(resolve => setImmediate(resolve));
  const latest = warm.select('a', page, result => seen.push(['latest-a', result.state]));
  await new Promise(resolve => setImmediate(resolve));
  gates[2].resolve(ok()); await latest;
  gates[0].resolve(ok()); gates[1].resolve(ok());
  await Promise.all([a, b]);
  assert.deepEqual(seen, [['latest-a', 'ready']]);
  const disposed = warm.select('b', page, result => seen.push(['disposed', result.state]));
  warm.cancel(); await disposed;
  assert.equal(seen.length, 1);
});

test('warmup bounds stalled asset bodies and abort-ignoring headers, and respects prior cancellation', async () => {
  let cancelled = false;
  const fetcher = async url => url.endsWith('/region.json') ? ok() :
    new Response(new ReadableStream({cancel() { cancelled = true; }}));
  assert.equal((await warmRegion('a', page, fetcher, {}, {timeoutMs: 20})).state, 'failed');
  assert.equal(cancelled, true);
  assert.equal((await warmRegion('a', page, never, {}, {timeoutMs: 20})).state, 'failed');
  let reads = 0;
  const controller = new AbortController(); controller.abort();
  assert.equal((await warmRegion('a', page, async () => { reads++; return ok(); }, {}, {signal: controller.signal})).state, 'failed');
  assert.equal(reads, 0);
});

test('warmup refuses an oversized region body before requesting other assets', async () => {
  let reads = 0, cancelled = false;
  const fetcher = async () => {
    reads++;
    return new Response(new ReadableStream({
      start(controller) { controller.enqueue(new Uint8Array(512 * 1024 + 1)); },
      cancel() { cancelled = true; },
    }));
  };
  assert.equal((await warmRegion('a', page, fetcher, {})).state, 'failed');
  assert.equal(reads, 1); assert.equal(cancelled, true);
});

test('local startup fixture baseline: cold then browser-cache warm; no speed claim', async t => {
  const cache = new Map(); let downloads = 0;
  const fetcher = async url => {
    if (!cache.has(url)) { downloads++; cache.set(url, '{}'); }
    return new Response(cache.get(url));
  };
  const start = performance.now();
  assert.equal((await warmRegion('fixture', page, fetcher, {})).state, 'ready');
  const coldMs = performance.now() - start, coldDownloads = downloads;
  const warmStart = performance.now();
  assert.equal((await warmRegion('fixture', page, fetcher, {})).state, 'ready');
  t.diagnostic(JSON.stringify({fixture: 'six synthetic startup responses', coldMs, warmMs: performance.now() - warmStart,
    coldDownloads, additionalWarmDownloads: downloads - coldDownloads}));
  assert.equal(coldDownloads, 6); assert.equal(downloads, coldDownloads);
});
