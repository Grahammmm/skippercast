// SC-LAUNCH-4 (docs/operations/cost-ceiling.md): the hard cost ceiling and the
// per-caller limits, through the real Worker (server/index.ts) with a counting
// R2 bucket, the Workers Cache API stand-in and fake Rate Limiting bindings.
// 1. Under the ceiling every R2 read is counted, and a normal public read
//    keeps a last-known copy.
// 2. Past the ceiling (a constructed day: ceiling 6 reads) no request reads
//    R2: a feed is answered from its last-known copy and says so; one with
//    no copy takes the free GitHub fallback and says so; one with neither
//    answers 503 {degraded: true} with Retry-After, still without R2.
// 3. A PMTiles byte range (an object too large for the whole-object edge
//    cache) is answered from its last-known copy as the same 206.
// 4. The count is global: a D1 total from other isolates past the ceiling
//    degrades this one; a failed D1 write keeps the reads pending and
//    blocks nothing.
// 5. Private routes: per-IP before the session lookup and per account on
//    reads answer the documented 429 with Retry-After: 60.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {};
globalThis.BUILD_ID = 'b1';
const {default: worker} = await import('../server/index.ts');
const {resetMeter, readsToday, recordReads, flush, ceilingOf, DEFAULT_R2_READS_PER_DAY, FLUSH_READS, DEGRADED_RETRY_SECONDS, LAST_KNOWN_CACHE} = await import('../server/cost-ceiling.ts');
const {useBucket} = await import('../server/feeds.ts');

/** caches.default with the semantics the Worker relies on (as tests/test_cache.mjs): no 206 or no-store puts; Range from a cached 200. */
class FakeCache {
  constructor() { this.entries = new Map(); }
  async put(request, response) {
    if (response.status === 206) throw new TypeError('Cannot cache a 206 response');
    if (/no-store|private/.test(response.headers.get('Cache-Control') || '')) { await response.arrayBuffer(); return; }
    this.entries.set(request.url, {status: response.status, headers: [...response.headers], body: new Uint8Array(await response.arrayBuffer())});
  }
  async match(request) {
    const entry = this.entries.get(request.url);
    if (!entry) return undefined;
    const headers = new Headers(entry.headers), range = /^bytes=(\d*)-(\d*)$/.exec(request.headers.get('Range') || '');
    if (range && entry.status === 200) {
      const start = Number(range[1]), end = Math.min(Number(range[2]), entry.body.length - 1);
      headers.set('Content-Range', `bytes ${start}-${end}/${entry.body.length}`); headers.set('Content-Length', String(end - start + 1));
      return new Response(entry.body.slice(start, end + 1), {status: 206, headers});
    }
    return new Response(entry.body, {status: entry.status, headers});
  }
}

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const BIG = 40 * 1024 * 1024;   // larger than the whole-object edge cache (EDGE_CACHE_MAX_BYTES, 32 MiB), like the basemap
const bigByte = i => (i * 7 + 3) % 251;

/** An R2 bucket in the published snapshot layout (scripts/publish_r2.py) that logs every read. */
function snapshotBucket() {
  const objects = new Map(), reads = [];
  const files = {'regions/morro-bay/latest.json': JSON.stringify({region_id: 'morro-bay', cycle: 'live'}), 'regions/morro-bay/other.json': JSON.stringify({x: 1})};
  for (const prefix of ['data', 'conditions']) {
    const listed = {};
    for (const [path, body] of Object.entries(files)) { const h = sha(prefix + body); objects.set(`${prefix}/.r2-objects/${h}`, prefix === 'data' ? body : JSON.stringify({prefix, path})); listed[path] = h; }
    delete listed['regions/morro-bay/other.json'];   // published on GitHub only
    const release = JSON.stringify({schema_version: 1, files: listed}), generation = sha(release);
    objects.set(`${prefix}/.r2-releases/${generation}.json`, release);
    objects.set(`${prefix}/.r2-current.json`, JSON.stringify({schema_version: 1, generation}));
  }
  const object = (key, bytes, size = bytes.length, range = null) => ({key, size, httpEtag: `"${sha(key)}"`, etag: sha(key), range,
    body: new Response(bytes).body, json: async () => JSON.parse(new TextDecoder().decode(bytes)), arrayBuffer: async () => bytes.buffer});
  return {reads, async get(key, options = {}) {
    reads.push(key);
    if (key === 'tiles/basemap/big.pmtiles') {
      const m = /^bytes=(\d+)-(\d+)$/.exec(options.range?.get?.('Range') || '');
      if (!m) return object(key, new Uint8Array(0), BIG);   // never read whole in these tests
      const start = Number(m[1]), end = Number(m[2]), bytes = Uint8Array.from({length: end - start + 1}, (_, i) => bigByte(start + i));
      return object(key, bytes, BIG, {offset: start, length: bytes.length});
    }
    const text = objects.get(key);
    return text === undefined ? null : object(key, new TextEncoder().encode(text));
  }, async head(key) { reads.push('head:' + key); return null; }};
}

function limiter(limit) {
  const counts = new Map();
  return {counts, async limit({key}) { counts.set(key, (counts.get(key) || 0) + 1); return {success: counts.get(key) <= limit}; }};
}
const ctx = () => { const pending = []; return {waitUntil: p => pending.push(p), settle: () => Promise.all(pending), passThroughOnException() {}}; };
const get = (path, headers = {}) => new Request('https://skippercast.com' + path, {headers: {'cf-connecting-ip': '203.0.113.9', ...headers}});
async function fetchSettled(request, env) { const c = ctx(), r = await worker.fetch(request, env, c); await c.settle(); return r; }

async function withWorld(fn) {
  const cache = new FakeCache(), lastKnownCopies = new FakeCache(), originalCaches = globalThis.caches, originalFetch = globalThis.fetch;
  // Last-known copies have their own named cache (server/cost-ceiling.ts); every other named cache is unavailable.
  globalThis.caches = {default: cache, async open(name) { if (name === LAST_KNOWN_CACHE) return lastKnownCopies; throw Error('named caches unavailable'); }};
  const upstream = [];
  globalThis.fetch = async url => { upstream.push(String(url)); return new Response('missing', {status: 404}); };
  resetMeter();
  try { return await fn({cache, upstream}); } finally { globalThis.caches = originalCaches; globalThis.fetch = originalFetch; resetMeter(); useBucket(null); }
}

test('the ceiling is COST_CEILING_R2_READS_PER_DAY, the default for anything that is not a positive integer, and "off" disables it', () => {
  assert.equal(DEFAULT_R2_READS_PER_DAY, 300_000);
  assert.equal(ceilingOf({COST_CEILING_R2_READS_PER_DAY: '1200'}), 1200);
  for (const raw of [undefined, '', '0', '-5', '1e6', 'lots']) assert.equal(ceilingOf({COST_CEILING_R2_READS_PER_DAY: raw}), DEFAULT_R2_READS_PER_DAY, String(raw));
  assert.equal(ceilingOf({COST_CEILING_R2_READS_PER_DAY: 'off'}), Infinity);
  const committed = readFileSync(new URL('../wrangler.jsonc', import.meta.url), 'utf8');
  assert.match(committed, /"COST_CEILING_R2_READS_PER_DAY": "300000"/, 'the deployed value is the documented default');
});

test('past the ceiling a feed is served from its last-known copy and says so, with no R2 read', () => withWorld(async ({upstream}) => {
  const FEEDS = snapshotBucket(), env = {FEEDS, COST_CEILING_R2_READS_PER_DAY: '6'};
  const first = await fetchSettled(get('/feeds/data/regions/morro-bay/latest.json'), env);
  assert.equal(first.status, 200); assert.equal(first.headers.get('X-Feed-Source'), 'r2');
  assert.equal(first.headers.get('X-SC-Degraded'), null);
  const body = await first.text();
  assert.equal(readsToday(), 3, 'release pointer, release manifest and the object are all counted');
  assert.equal(FEEDS.reads.length, 3);
  // Two more requests take the count past 6; each was under the ceiling when it started, so each is normal.
  assert.equal((await fetchSettled(get('/feeds/data/regions/morro-bay/latest.json'), env)).headers.get('X-SC-Cache'), 'hit');
  assert.equal((await fetchSettled(get('/feeds/conditions/regions/morro-bay/latest.json'), env)).status, 200);
  assert.ok(readsToday() >= 6, `count ${readsToday()}`);
  const before = FEEDS.reads.length;

  const degraded = await fetchSettled(get('/feeds/data/regions/morro-bay/latest.json'), env);
  assert.equal(degraded.status, 200);
  assert.equal(degraded.headers.get('X-SC-Degraded'), 'cost-ceiling');
  assert.match(degraded.headers.get('X-SC-Last-Known-At'), /^\d{4}-\d\d-\d\dT/);
  assert.match(degraded.headers.get('Access-Control-Expose-Headers'), /X-SC-Degraded/);
  assert.equal(degraded.headers.get('Cache-Control'), 'no-store', 'browsers ask again once the day resets');
  assert.ok(degraded.headers.get('Content-Security-Policy'), 'security headers still apply');
  assert.equal(await degraded.text(), body, 'the last-known bytes, unchanged');
  assert.equal(FEEDS.reads.length, before, 'no R2 read past the ceiling');
  assert.deepEqual(upstream, [], 'and no upstream fetch either: the copy answered');
}));

test('past the ceiling a feed with no copy takes the free GitHub fallback, and one with neither answers 503 degraded; R2 is never read', () => withWorld(async ({upstream}) => {
  const FEEDS = snapshotBucket(), env = {FEEDS, COST_CEILING_R2_READS_PER_DAY: '6'};
  recordReads(6);
  globalThis.fetch = async url => { upstream.push(String(url)); return /other\.json$/.test(url) ? Response.json({x: 'github'}) : new Response('missing', {status: 404}); };
  const github = await fetchSettled(get('/feeds/data/regions/morro-bay/other.json'), env);
  assert.equal(github.status, 200); assert.equal(github.headers.get('X-Feed-Source'), 'github');
  assert.equal(github.headers.get('X-SC-Degraded'), 'cost-ceiling');
  assert.deepEqual(await github.json(), {x: 'github'});
  const none = await fetchSettled(get('/feeds/data/regions/morro-bay/latest.json'), env);
  assert.equal(none.status, 503);
  assert.equal(none.headers.get('Retry-After'), String(DEGRADED_RETRY_SECONDS));
  assert.equal(none.headers.get('X-SC-Degraded'), 'cost-ceiling');
  assert.equal((await none.json()).degraded, true);
  assert.deepEqual(FEEDS.reads, [], 'R2 untouched past the ceiling');
  assert.equal(upstream.length, 2);
}));

test('a PMTiles byte range of an object too large for the edge cache is answered from its last-known copy as the same 206', () => withWorld(async ({cache}) => {
  const FEEDS = snapshotBucket(), env = {FEEDS, COST_CEILING_R2_READS_PER_DAY: '2'};
  const range = {Range: 'bytes=1000-17383'};
  const live = await fetchSettled(get('/feeds/tiles/basemap/big.pmtiles', range), env);
  assert.equal(live.status, 206); assert.equal(live.headers.get('X-SC-Cache'), 'miss');
  assert.equal(cache.entries.size, 0, 'the copy is kept in its own named cache, never the feed edge cache');
  const bytes = new Uint8Array(await live.arrayBuffer());
  assert.equal(bytes.length, 16384); assert.equal(bytes[0], bigByte(1000));
  recordReads(5);
  const before = FEEDS.reads.length;
  const copy = await fetchSettled(get('/feeds/tiles/basemap/big.pmtiles', range), env);
  assert.equal(copy.status, 206);
  assert.equal(copy.headers.get('Content-Range'), `bytes 1000-17383/${BIG}`);
  assert.equal(copy.headers.get('X-SC-Degraded'), 'cost-ceiling');
  assert.deepEqual(new Uint8Array(await copy.arrayBuffer()), bytes);
  assert.equal(FEEDS.reads.length, before, 'no R2 read');
  // A range never served before has no copy and no free source (tiles ship with the site only when small): 503, not R2.
  const other = await fetchSettled(get('/feeds/tiles/basemap/big.pmtiles', {Range: 'bytes=0-99'}), env);
  assert.equal(other.status, 503); assert.equal(FEEDS.reads.length, before);
}));

test('the count is global through D1: other isolates\' reads degrade this one, and a failed write blocks nothing', () => withWorld(async () => {
  const FEEDS = snapshotBucket(), writes = [];
  let total = 0, failing = false;
  const DB = {prepare(sql) { return {bind(...args) { return {async first() {
    if (failing) throw Error('D1 down');
    writes.push({sql, args}); total += args[1]; return {count: total + 1_000_000};   // a million reads already written by other isolates today
  }}; }}; }};
  const env = {FEEDS, DB, COST_CEILING_R2_READS_PER_DAY: '500000'};
  assert.equal((await fetchSettled(get('/feeds/data/regions/morro-bay/latest.json'), env)).headers.get('X-SC-Degraded'), null);
  assert.equal(writes.length, 0, 'three reads are not worth a D1 write yet');
  recordReads(FLUSH_READS);
  await fetchSettled(get('/feeds/data/regions/morro-bay/latest.json'), env);
  assert.equal(writes.length, 1, 'the batch is written once it reaches FLUSH_READS');
  assert.match(writes[0].sql, /INSERT INTO request_limits\(id,count,expires_at\).*ON CONFLICT\(id\) DO UPDATE SET count=count\+excluded\.count RETURNING count/);
  assert.match(writes[0].args[0], /^cost-ceiling:r2-reads:\d{4}-\d\d-\d\d$/);
  assert.ok(readsToday() >= 1_000_000);
  const degraded = await fetchSettled(get('/feeds/data/regions/morro-bay/latest.json'), env);
  assert.equal(degraded.headers.get('X-SC-Degraded'), 'cost-ceiling');

  resetMeter(); failing = true;
  recordReads(FLUSH_READS);
  const ok = await fetchSettled(get('/feeds/data/regions/morro-bay/latest.json'), env);
  assert.equal(ok.status, 200, 'a D1 failure never takes a feed down');
  assert.ok(readsToday() >= FLUSH_READS, 'the unwritten reads stay pending');
  failing = false; await flush(env);
  assert.equal(writes.length, 2);
}));

// ---- the documented 429 on private routes ---------------------------------

const SESSION = '__Host-sc_session=' + 'a'.repeat(43);   // the token shape server/auth.ts accepts
function sessionDb() {
  const queries = [];
  return {queries, prepare(sql) { queries.push(sql); return {bind() { return this; },
    async first() { return /FROM sessions/.test(sql) ? {user_id: 'user-1', expires_at: Math.floor(Date.now() / 1000) + 29 * 86400, display_name: null} : null; },
    async all() { return {results: []}; }, async run() { return {meta: {changes: 0}}; }}; }};
}

test('a signed-in account past 60 private reads a minute gets the documented 429 with Retry-After: 60', () => withWorld(async () => {
  const DB = sessionDb(), PUBLIC_LIMITER = limiter(60), env = {DB, PUBLIC_LIMITER, IDENTITY_PROVIDER: 'skippercast'};
  for (let i = 0; i < 60; i++) { const s = (await fetchSettled(get('/api/trips', {Cookie: SESSION}), env)).status; assert.ok(s !== 429 && s !== 401, `read ${i + 1}: ${s}`); }
  const limited = await fetchSettled(get('/api/trips', {Cookie: SESSION}), env);
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get('Retry-After'), '60');
  assert.equal(limited.headers.get('Cache-Control'), 'no-store');
  assert.match((await limited.json()).error, /Too many requests/);
  assert.equal(PUBLIC_LIMITER.counts.get('account:user-1'), 61, 'keyed on the account, not the address');
}));

test('the per-IP private gate answers 429 before any session lookup reaches D1', () => withWorld(async () => {
  const DB = sessionDb(), FEED_LIMITER = limiter(0), env = {DB, FEED_LIMITER, IDENTITY_PROVIDER: 'skippercast'};
  const limited = await fetchSettled(get('/api/trips', {Cookie: SESSION}), env);
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get('Retry-After'), '60');
  assert.deepEqual(DB.queries, [], 'no D1 read for a refused request');
  assert.equal(FEED_LIMITER.counts.get('private-ip:203.0.113.9'), 1);
}));
