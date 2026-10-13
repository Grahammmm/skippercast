import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {createFeedReader, feedKey, readBucketJSON, serveFeed, useBucket} from '../server/feeds.ts';

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

test('legacy bucket remains compatible and a reader captures its bucket instead of global reassignment', async () => {
  const f = fixture(); f.objects.set('forecasts/m/manifest.json', '{"cycle":"legacy"}'); useBucket({FEEDS: f.bucket});
  const read = createFeedReader();
  const other = fixture(); other.release('unrelated'); useBucket({FEEDS: other.bucket});
  try { assert.equal((await read(RAW + 'forecasts/m/manifest.json')).cycle, 'legacy'); }
  finally { useBucket(null); }
});
