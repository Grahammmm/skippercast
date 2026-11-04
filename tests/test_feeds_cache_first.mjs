// SC1322-05: a /feeds/ answer already in the edge cache costs no R2 read (not
// even the release pointer and snapshot); a miss resolves, reads and fills as
// before; cached copies live at most the feed's max-age, so a new release shows.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {serveFeed, useBucket} from '../server/feeds.ts';

const sha = text => createHash('sha256').update(text).digest('hex');
const BUILD = 'b1';

/** caches.default stand-in: Range/If-None-Match from a cached 200, entries expire after their max-age. */
class FakeCache {
  constructor(clock) { this.entries = new Map(); this.puts = 0; this.clock = clock; this.fail = false; }
  async put(request, response) {
    if (response.status === 206) throw new TypeError('Cannot cache a 206 response');
    const control = response.headers.get('Cache-Control') || '';
    if (/no-store|private/.test(control)) { await response.arrayBuffer(); return; }
    this.puts++;
    const maxAge = Number(/max-age=(\d+)/.exec(control)?.[1] || 0);
    this.entries.set(request.url, {expires: this.clock.now + maxAge * 1000, headers: [...response.headers], body: new Uint8Array(await response.arrayBuffer())});
  }
  async match(request) {
    if (this.fail) throw Error('cache unavailable');
    const entry = this.entries.get(request.url);
    if (!entry || this.clock.now >= entry.expires) return undefined;
    const headers = new Headers(entry.headers);
    if (request.headers.get('If-None-Match') && request.headers.get('If-None-Match') === headers.get('ETag')) return new Response(null, {status: 304, headers});
    const range = /^bytes=(\d+)-(\d+)$/.exec(request.headers.get('Range') || '');
    if (range) {
      const size = entry.body.length, start = Number(range[1]), end = Math.min(Number(range[2]), size - 1);
      headers.set('Content-Range', `bytes ${start}-${end}/${size}`); headers.set('Content-Length', String(end - start + 1));
      return new Response(entry.body.slice(start, end + 1), {status: 206, headers});
    }
    return new Response(entry.body, {status: 200, headers});
  }
}

/** A snapshot-layout bucket that records every get. */
function world() {
  const objects = new Map(), reads = [];
  function release(files) {
    const listed = {};
    for (const [path, body] of Object.entries(files)) { const h = sha(body); objects.set(`conditions/.r2-objects/${h}`, body); listed[path] = h; }
    const bytes = JSON.stringify({schema_version: 1, files: listed}), generation = sha(bytes);
    objects.set(`conditions/.r2-releases/${generation}.json`, bytes);
    objects.set('conditions/.r2-current.json', JSON.stringify({schema_version: 1, generation}));
    return generation;
  }
  const bucket = {async get(key, options = {}) {
    reads.push(key);
    const text = objects.get(key);
    if (text === undefined) return null;
    if (typeof text === 'function') return text();
    const bytes = new TextEncoder().encode(text), size = bytes.length;
    const header = options.range instanceof Headers ? options.range.get('Range') : null;
    const match = /^bytes=(\d+)-(\d+)$/.exec(header || '');
    if (match) {
      const offset = Number(match[1]), length = Math.min(Number(match[2]), size - 1) - offset + 1;
      return {size, httpEtag: `"${sha(text)}"`, range: {offset, length}, body: new Blob([bytes.slice(offset, offset + length)]).stream()};
    }
    return {size, httpEtag: `"${sha(text)}"`, body: new Blob([bytes]).stream(), json: async () => JSON.parse(text), arrayBuffer: async () => bytes.buffer};
  }};
  return {objects, reads, release, bucket};
}

async function withEdge(fn, caches) {
  const clock = {now: 0}, cache = new FakeCache(clock), original = globalThis.caches;
  globalThis.caches = caches === undefined ? {default: cache} : caches;
  try { return await fn({cache, clock}); } finally { globalThis.caches = original; useBucket(null); }
}
const path = '/feeds/conditions/latest.json';
const serve = (headers = {}, p = path) => serveFeed(new Request('https://skippercast.com' + p, {headers}), p, undefined, {build: BUILD});

test('a hit makes no R2 read and returns the filled body, ETag and X-Feed-Generation', () => withEdge(async ({cache}) => {
  const w = world(), generation = w.release({'latest.json': '{"cycle":"one"}'}); useBucket({FEEDS: w.bucket});
  const miss = await serve();
  assert.equal(miss.status, 200); assert.equal(miss.headers.get('X-SC-Cache'), 'miss');
  const missBody = await miss.text();
  // A miss: the release pointer and snapshot (2 resolver reads) then the object, as today, then one fill.
  assert.deepEqual(w.reads, ['conditions/.r2-current.json', `conditions/.r2-releases/${generation}.json`, `conditions/.r2-objects/${sha('{"cycle":"one"}')}`]);
  assert.equal(cache.puts, 1);
  assert.ok(cache.entries.has(`https://skippercast.com/feeds/conditions/latest.json?sc-build=${BUILD}`), 'stored under the logical key');
  w.reads.length = 0;
  const hit = await serve();
  assert.equal(hit.status, 200); assert.equal(hit.headers.get('X-SC-Cache'), 'hit');
  assert.equal(w.reads.length, 0, 'a hit makes no R2 read');
  assert.equal(await hit.text(), missBody);
  assert.equal(hit.headers.get('ETag'), miss.headers.get('ETag'));
  assert.equal(hit.headers.get('X-Feed-Generation'), generation);
  assert.equal(hit.headers.get('Cache-Control'), 'public, max-age=60');
}));

test('a Range request on a hit is a 206 from the cache entry with no R2 read', () => withEdge(async () => {
  const w = world(); w.release({'latest.json': '{"cycle":"0123456789"}'}); useBucket({FEEDS: w.bucket});
  await (await serve()).text();
  w.reads.length = 0;
  const part = await serve({Range: 'bytes=2-6'});
  assert.equal(part.status, 206); assert.equal(part.headers.get('X-SC-Cache'), 'hit');
  assert.equal(await part.text(), 'cycle'); assert.equal(part.headers.get('Content-Range'), 'bytes 2-6/22');
  const unchanged = await serve({'If-None-Match': `"${sha('{"cycle":"0123456789"}')}"`});
  assert.equal(unchanged.status, 304);
  assert.equal(w.reads.length, 0);
}));

test('an expired entry is not served: the new release shows within max-age', () => withEdge(async ({clock}) => {
  const w = world(), first = w.release({'latest.json': '{"cycle":"one"}'}); useBucket({FEEDS: w.bucket});
  await (await serve()).text();
  const second = w.release({'latest.json': '{"cycle":"two"}'});
  clock.now = 59_000;  // still within max-age=60: the cached copy, its own generation, no read
  w.reads.length = 0;
  let r = await serve();
  assert.equal(r.headers.get('X-SC-Cache'), 'hit'); assert.equal(r.headers.get('X-Feed-Generation'), first);
  assert.deepEqual(await r.json(), {cycle: 'one'}); assert.equal(w.reads.length, 0);
  clock.now = 60_000;  // max-age reached
  r = await serve();
  assert.equal(r.headers.get('X-SC-Cache'), 'miss'); assert.equal(r.headers.get('X-Feed-Generation'), second);
  assert.deepEqual(await r.json(), {cycle: 'two'});
  assert.equal(w.reads.length, 3);
  w.reads.length = 0;
  r = await serve();
  assert.equal(r.headers.get('X-SC-Cache'), 'hit'); assert.equal(r.headers.get('X-Feed-Generation'), second);
  assert.equal(w.reads.length, 0);
}));

test('a file missing from the release is a 404 no-store and is never cached', () => withEdge(async ({cache}) => {
  const w = world(); w.release({'other.json': '{}'}); useBucket({FEEDS: w.bucket});
  for (let i = 0; i < 2; i++) {
    const r = await serve();
    assert.equal(r.status, 404); assert.equal(r.headers.get('Cache-Control'), 'no-store');
  }
  assert.equal(cache.puts, 0); assert.equal(w.reads.filter(k => k.endsWith('.r2-current.json')).length, 2);
}));

test('without caches, or when match throws, the feed resolves and reads R2 as before', async () => {
  for (const caches of [{}, {get default() { throw Error('forbidden'); }}]) {
    await withEdge(async () => {
      const w = world(); w.release({'latest.json': '{"cycle":"one"}'}); useBucket({FEEDS: w.bucket});
      for (let i = 0; i < 2; i++) {
        const r = await serve();
        assert.equal(r.status, 200); assert.deepEqual(await r.json(), {cycle: 'one'}); assert.equal(r.headers.get('X-SC-Cache'), null);
      }
      assert.equal(w.reads.length, 6);
    }, caches);
  }
  await withEdge(async ({cache}) => {
    const w = world(); w.release({'latest.json': '{"cycle":"one"}'}); useBucket({FEEDS: w.bucket});
    await (await serve()).text();
    cache.fail = true; w.reads.length = 0;
    const r = await serve();
    assert.equal(r.status, 200); assert.equal(r.headers.get('X-SC-Cache'), 'miss'); assert.deepEqual(await r.json(), {cycle: 'one'});
    assert.equal(w.reads.length, 3, 'a failed lookup falls through to the resolver and object read');
  });
});

test('seafloor keys run the receipt gate even with a cached entry present and are never served from the cache', () => withEdge(async ({cache}) => {
  const seafloor = '/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles', hash = 'c'.repeat(64);
  const w = world(), manifest = {region: 'morro-bay', status: 'ready', archive_sha256: hash, expires_at: new Date(Date.now() + 3600_000).toISOString()};
  w.objects.set('tiles/seafloor/manifest-morro-bay.json', () => ({json: async () => manifest}));
  w.objects.set('tiles/seafloor/seafloor-morro-bay.pmtiles', () => ({size: 4, httpEtag: '"r2"', customMetadata: {sha256: hash}, body: new Blob(['live']).stream()}));
  useBucket({FEEDS: w.bucket});
  const stale = new Response('old!', {headers: {'Cache-Control': 'public, max-age=300', ETag: '"old"'}});
  await cache.put(new Request(`https://skippercast.com${seafloor}?sc-build=${BUILD}`), stale);
  let r = await serve({}, seafloor);
  assert.equal(r.status, 200); assert.equal(await r.text(), 'live'); assert.equal(r.headers.get('X-SC-Cache'), null);
  assert.equal(r.headers.get('Cache-Control'), 'no-store');
  assert.deepEqual(w.reads, ['tiles/seafloor/manifest-morro-bay.json', 'tiles/seafloor/seafloor-morro-bay.pmtiles']);
  manifest.status = 'held';
  r = await serve({Range: 'bytes=0-1'}, seafloor);
  assert.equal(r.status, 503, 'an expired/held receipt refuses even with a cached copy present');
  assert.equal(cache.puts, 1, 'nothing stored for seafloor');
}));
