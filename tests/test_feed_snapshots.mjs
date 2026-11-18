import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {createFeedReader, feedKey, readBucketJSON, RELEASE_CACHE_BYTES, RELEASE_CACHE_ENTRIES, serveFeed, useBucket} from '../server/feeds.ts';
import {meter, readsToday, resetMeter} from '../server/cost-ceiling.ts';

const RAW = 'https://raw.githubusercontent.com/Grahammmm/skippercast/';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function fixture() {
  const objects = new Map(), reads = [];
  function release(cycle, includeTile = true) {
    const files = {};
    for (const [path, value] of Object.entries({'m/manifest.json': {cycle, tiles: ['x']}, ...(includeTile ? {'m/tiles/x.json': {cycle}} : {})})) {
      const bytes = JSON.stringify(value), sha = hash(bytes);
      objects.set(`forecasts/.r2-objects/${sha}`, bytes); files[path] = sha;
    }
    const bytes = JSON.stringify({schema_version: 1, files}), generation = hash(bytes);
    objects.set(`forecasts/.r2-releases/${generation}.json`, bytes);
    objects.set('forecasts/.r2-current.json', JSON.stringify({schema_version: 1, generation}));
    return {generation, files};
  }
  const bucket = {async get(key) {
    reads.push(key); const bytes = objects.get(key);
    if (bytes === undefined) return null;
    return {json: async () => JSON.parse(bytes), arrayBuffer: async () => new TextEncoder().encode(bytes).buffer,
      size: Buffer.byteLength(bytes), httpEtag: `"${hash(bytes)}"`, body: new Response(bytes).body};
  }};
  return {objects, reads, release, bucket};
}

test('one request pins manifest and tile even during a concurrent promotion or rollback', async () => {
  const f = fixture(), old = f.release('old'); useBucket({FEEDS: f.bucket});
  try {
    const read = createFeedReader();
    assert.equal((await read(RAW + 'forecasts/m/manifest.json')).cycle, 'old');
    f.release('new');
    assert.equal((await read(RAW + 'forecasts/m/tiles/x.json')).cycle, 'old');
    const next = createFeedReader();
    assert.equal((await next(RAW + 'forecasts/m/manifest.json')).cycle, 'new');
    f.objects.set('forecasts/.r2-current.json', JSON.stringify({schema_version: 1, generation: old.generation}));
    assert.equal((await next(RAW + 'forecasts/m/tiles/x.json')).cycle, 'new');
    assert.equal((await createFeedReader()(RAW + 'forecasts/m/tiles/x.json')).cycle, 'old');
    assert.equal(f.reads.filter(k => k.endsWith('.r2-current.json')).length, 3);
  } finally { useBucket(null); }
});

test('removed and missing snapshot objects fail closed instead of mixing legacy/GitHub data', async () => {
  const f = fixture(); f.release('new', false);
  f.objects.set('forecasts/m/tiles/x.json', '{"cycle":"legacy"}'); useBucket({FEEDS: f.bucket});
  const priorFetch = globalThis.fetch; globalThis.fetch = async () => { throw Error('must not fall back'); };
  try {
    await assert.rejects(createFeedReader()(RAW + 'forecasts/m/tiles/x.json'), /absent from current/);
    assert.equal((await serveFeed(new Request('https://x/feeds/forecasts/m/tiles/x.json'), '/feeds/forecasts/m/tiles/x.json')).status, 404);
    const current = f.release('new'); f.objects.delete(`forecasts/.r2-objects/${current.files['m/tiles/x.json']}`);
    await assert.rejects(readBucketJSON(RAW + 'forecasts/m/tiles/x.json'), /object unavailable/);
    assert.equal((await serveFeed(new Request('https://x/feeds/forecasts/m/tiles/x.json'), '/feeds/forecasts/m/tiles/x.json')).status, 503);
  } finally { globalThis.fetch = priorFetch; useBucket(null); }
});

test('snapshot corruption and invalid pointer cannot silently fall back to mutable stable keys', async () => {
  const f = fixture(), release = f.release('old'); useBucket({FEEDS: f.bucket});
  try {
    f.objects.set(`forecasts/.r2-releases/${release.generation}.json`, '{}');
    await assert.rejects(createFeedReader()(RAW + 'forecasts/m/manifest.json'), /hash mismatch/);
    f.objects.set('forecasts/.r2-current.json', '{"schema_version":1,"generation":"../other"}');
    await assert.rejects(readBucketJSON(RAW + 'forecasts/m/manifest.json'), /pointer/);
  } finally { useBucket(null); }
});

test('ordinary feed URLs retain JSON/type/ETag and indicate their coherent generation', async () => {
  const f = fixture(), release = f.release('new'); useBucket({FEEDS: f.bucket});
  try {
    const r = await serveFeed(new Request('https://x/feeds/forecasts/m/manifest.json'), '/feeds/forecasts/m/manifest.json');
    assert.equal(r.status, 200); assert.equal(r.headers.get('Content-Type'), 'application/json');
    assert.equal(r.headers.get('X-Feed-Generation'), release.generation);
    assert.equal(r.headers.get('Cache-Control'), 'public, max-age=60');
    assert.equal((await r.json()).cycle, 'new');
    assert.equal(feedKey('/feeds/forecasts/.r2-current.json'), null);
    assert.equal(feedKey('/feeds/forecasts/.r2-objects/' + 'a'.repeat(64)), null);
  } finally { useBucket(null); }
});

// SCA-032: validated release tables are shared across operations; pointers are not.
const MANIFEST = RAW + 'forecasts/m/manifest.json', TILE = RAW + 'forecasts/m/tiles/x.json';
const serveTile = () => serveFeed(new Request('https://x/feeds/forecasts/m/tiles/x.json'), '/feeds/forecasts/m/tiles/x.json');
const tableReads = f => f.reads.filter(k => k.includes('/.r2-releases/')).length;
const pointerReads = f => f.reads.filter(k => k.endsWith('/.r2-current.json')).length;
const point = (f, generation, prefix = 'forecasts') => f.objects.set(`${prefix}/.r2-current.json`, JSON.stringify({schema_version: 1, generation}));

test('two same-generation misses do one table GET/hash, through a fresh cost meter per request', async () => {
  const f = fixture(), release = f.release('one');
  resetMeter();
  try {
    useBucket({FEEDS: meter(f.bucket)});  // request 1: its own metered wrapper
    assert.equal((await createFeedReader()(MANIFEST)).cycle, 'one');
    useBucket({FEEDS: meter(f.bucket)});  // request 2: a new wrapper around the same bucket
    const r = await serveTile();
    assert.equal(r.status, 200); assert.equal(r.headers.get('X-Feed-Generation'), release.generation);
    useBucket({FEEDS: meter(f.bucket)});  // two concurrent misses share one in-flight check
    const [a, b] = await Promise.all([readBucketJSON(MANIFEST), readBucketJSON(TILE)]);
    assert.equal(a.cycle, 'one'); assert.equal(b.cycle, 'one');
    assert.equal(tableReads(f), 1, 'one release-table GET for four operations');
    assert.equal(pointerReads(f), 4, 'every operation still resolves the pointer');
    assert.equal(readsToday(), f.reads.length, 'every R2 read that does happen is still metered');
  } finally { useBucket(null); resetMeter(); }
});

test('rotation and rollback take effect on the next operation; one operation stays pinned', async () => {
  const f = fixture(), one = f.release('one'); useBucket({FEEDS: f.bucket});
  try {
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'one');
    const pinned = createFeedReader();
    assert.equal((await pinned(MANIFEST)).cycle, 'one');
    f.release('two');
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'two', 'rotation is immediate');
    assert.equal((await pinned(TILE)).cycle, 'one', 'an operation keeps its generation');
    point(f, one.generation);
    assert.equal((await readBucketJSON(TILE)).cycle, 'one', 'rollback is immediate');
    assert.equal(tableReads(f), 2, 'each verified generation was fetched once');
  } finally { useBucket(null); }
});

test('a bad table hash, bad pointer or missing table still fails closed and is never kept', async () => {
  const f = fixture(), one = f.release('one'); useBucket({FEEDS: f.bucket});
  const tableKey = `forecasts/.r2-releases/${one.generation}.json`, good = f.objects.get(tableKey);
  try {
    f.objects.set(tableKey, good.replace('"schema_version":1', '"schema_version":1 '));
    await assert.rejects(readBucketJSON(MANIFEST), /hash mismatch/);
    await assert.rejects(createFeedReader()(MANIFEST), /hash mismatch/);
    assert.equal(tableReads(f), 2, 'a failed check is retried, not remembered');
    f.objects.set(tableKey, good);
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'one');
    const two = f.release('two');  // a verified generation is cached; the next one is corrupt
    f.objects.set(`forecasts/.r2-releases/${two.generation}.json`, '{}');
    await assert.rejects(readBucketJSON(MANIFEST), /hash mismatch/, 'no fallback to the cached generation');
    f.objects.delete(`forecasts/.r2-releases/${two.generation}.json`);
    await assert.rejects(readBucketJSON(MANIFEST), /snapshot unavailable/);
    await assert.rejects(readBucketJSON(MANIFEST), /snapshot unavailable/);
    f.objects.set('forecasts/.r2-current.json', '{"schema_version":1,"generation":"../other"}');
    await assert.rejects(readBucketJSON(MANIFEST), /pointer/);
  } finally { useBucket(null); }
});

test('a cached table never hides a missing entry or a removed object', async () => {
  const f = fixture(), one = f.release('one', false); useBucket({FEEDS: f.bucket});
  f.objects.set('forecasts/m/tiles/x.json', '{"cycle":"legacy"}');
  try {
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'one');
    await assert.rejects(readBucketJSON(TILE), /absent from current/);
    assert.equal((await serveTile()).status, 404);
    assert.equal(tableReads(f), 1);
    f.objects.delete(`forecasts/.r2-objects/${one.files['m/manifest.json']}`);
    await assert.rejects(createFeedReader()(MANIFEST), /object unavailable/);
    assert.equal((await serveFeed(new Request('https://x/feeds/forecasts/m/manifest.json'), '/feeds/forecasts/m/manifest.json')).status, 503);
  } finally { useBucket(null); }
});

test('the cache is isolated by bucket and prefix, and an unbound bucket reads nothing', async () => {
  const a = fixture(), b = fixture(), one = a.release('one'); b.release('one');
  try {
    useBucket({FEEDS: a.bucket});
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'one');
    b.objects.delete(`forecasts/.r2-releases/${one.generation}.json`);  // same generation, but this bucket lacks it
    useBucket({FEEDS: b.bucket});
    await assert.rejects(readBucketJSON(MANIFEST), /snapshot unavailable/);
    useBucket({FEEDS: a.bucket});
    point(a, one.generation, 'data');  // same generation under another prefix, whose table is absent
    await assert.rejects(readBucketJSON(RAW + 'data/m/manifest.json'), /snapshot unavailable/);
    useBucket(null);  // past the cost ceiling or unbound: no read, no cached answer
    const before = a.reads.length;
    assert.equal(await readBucketJSON(MANIFEST), undefined);
    await assert.rejects(createFeedReader()(MANIFEST), /storage unavailable/);
    assert.equal((await serveTile()).status, 503);
    assert.equal(a.reads.length, before);
  } finally { useBucket(null); }
});

test('the cache is bounded by entries and bytes; a store that cannot be tagged reads uncached', async () => {
  const f = fixture(), first = f.release('g0'); useBucket({FEEDS: f.bucket});
  try {
    await readBucketJSON(MANIFEST);
    for (let i = 1; i <= RELEASE_CACHE_ENTRIES; i++) { f.release('g' + i); await readBucketJSON(MANIFEST); }
    assert.equal(tableReads(f), RELEASE_CACHE_ENTRIES + 1);
    await readBucketJSON(MANIFEST);
    assert.equal(tableReads(f), RELEASE_CACHE_ENTRIES + 1, 'the newest generation is held');
    point(f, first.generation);
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'g0');
    assert.equal(tableReads(f), RELEASE_CACHE_ENTRIES + 2, 'the oldest generation was evicted');
    // A table larger than the byte budget is checked and served but not kept, and does not evict the others.
    const files = {...first.files}, padding = Math.ceil((RELEASE_CACHE_BYTES + 1024 * 1024) / 80);
    for (let i = 0; i < padding; i++) files[`pad/${i}.json`] = hash(String(i));
    const bytes = JSON.stringify({schema_version: 1, files}), big = hash(bytes);
    assert.ok(Buffer.byteLength(bytes) > RELEASE_CACHE_BYTES);
    f.objects.set(`forecasts/.r2-releases/${big}.json`, bytes); point(f, big);
    const reads = tableReads(f);
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'g0');
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'g0');
    assert.equal(tableReads(f), reads + 2, 'the oversized table is fetched each time');
    point(f, first.generation); await readBucketJSON(MANIFEST);
    assert.equal(tableReads(f), reads + 2, 'held tables survive an oversized one');
    const frozen = fixture(); frozen.release('cold'); useBucket({FEEDS: Object.freeze(frozen.bucket)});
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'cold');
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'cold');
    assert.equal(tableReads(frozen), 2);
  } finally { useBucket(null); }
});

test('a legacy prefix is never remembered: its first release applies at once', async () => {
  const f = fixture(); f.objects.set('forecasts/m/manifest.json', '{"cycle":"legacy"}'); useBucket({FEEDS: f.bucket});
  try {
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'legacy');
    f.release('one');
    assert.equal((await readBucketJSON(MANIFEST)).cycle, 'one');
  } finally { useBucket(null); }
});

test('legacy bucket remains compatible and a reader captures its bucket instead of global reassignment', async () => {
  const f = fixture(); f.objects.set('forecasts/m/manifest.json', '{"cycle":"legacy"}'); useBucket({FEEDS: f.bucket});
  const read = createFeedReader();
  const other = fixture(); other.release('unrelated'); useBucket({FEEDS: other.bucket});
  try { assert.equal((await read(RAW + 'forecasts/m/manifest.json')).cycle, 'legacy'); }
  finally { useBucket(null); }
});
