import assert from 'node:assert/strict';
import test from 'node:test';
import {feedKey, rangeResponse, readBucketJSON, serveFeed, useBucket} from '../server/feeds.ts';
import {feedAgeMinutes, watchdog} from '../server/watchdog.ts';
import {feedURL, withFeeds} from '../dist/feeds.js';

const RAW = 'https://raw.githubusercontent.com/Grahammmm/skippercast/';

test('only published feed branches map to keys; traversal is refused', () => {
  assert.equal(feedKey(RAW + 'conditions/regions/morro-bay/latest.json'), 'conditions/regions/morro-bay/latest.json');
  assert.equal(feedKey('/feeds/forecasts/gfs_global/manifest.json'), 'forecasts/gfs_global/manifest.json');
  assert.equal(feedKey('/feeds/main/README.md'), null);
  assert.equal(feedKey('/feeds/conditions/../main/x'), null);
  assert.equal(feedKey('https://example.com/conditions/x.json'), null);
});

test('browser feed URLs route through /feeds/ and leave everything else alone', () => {
  assert.equal(feedURL(RAW + 'data/latest.json'), '/feeds/data/latest.json');
  assert.equal(feedURL(RAW + 'main/README.md'), RAW + 'main/README.md');
  assert.equal(feedURL('regions/x.json'), 'regions/x.json');
  const region = withFeeds({id: 'x', daily_feed: RAW + 'data/regions/x/latest.json', name: 'X'});
  assert.equal(region.daily_feed, '/feeds/data/regions/x/latest.json');
  assert.equal(region.name, 'X');
});

test('range responses follow RFC 7233 for PMTiles reads', async () => {
  const bytes = new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  const req = range => new Request('https://x/y', {headers: range ? {Range: range} : {}});
  let r = rangeResponse(bytes, req('bytes=2-4'), new Headers());
  assert.equal(r.status, 206);
  assert.equal(r.headers.get('Content-Range'), 'bytes 2-4/10');
  assert.deepEqual([...new Uint8Array(await r.arrayBuffer())], [2, 3, 4]);
  r = rangeResponse(bytes, req('bytes=-3'), new Headers());
  assert.deepEqual([...new Uint8Array(await r.arrayBuffer())], [7, 8, 9]);
  assert.equal(rangeResponse(bytes, req('bytes=20-30'), new Headers()).status, 416);
  assert.equal(rangeResponse(bytes, req(null), new Headers()).status, 200);
});

function fakeBucket(objects) {
  return {async get(key) {
    if (!(key in objects)) return null;
    const text = objects[key];
    return {size: text.length, httpEtag: '"e"', body: new Blob([text]).stream(), json: async () => JSON.parse(text)};
  }};
}

test('feeds come from R2 when bound, GitHub otherwise', async () => {
  useBucket({FEEDS: fakeBucket({'conditions/latest.json': '{"completed_at":"2026-09-28T13:00:00Z"}'})});
  let r = await serveFeed(new Request('https://s/feeds/conditions/latest.json'), '/feeds/conditions/latest.json');
  assert.equal(r.headers.get('X-Feed-Source'), 'r2');
  assert.equal(r.headers.get('Cache-Control'), 'public, max-age=60');
  assert.deepEqual(await readBucketJSON(RAW + 'conditions/latest.json'), {completed_at: '2026-09-28T13:00:00Z'});
  assert.equal(await serveFeed(new Request('https://s/feeds/main/x'), '/feeds/main/x'), null);
  const realFetch = globalThis.fetch;
  globalThis.fetch = async url => (assert.equal(url, RAW + 'data/x.json'), new Response('{}', {status: 200}));
  try {
    useBucket({});
    r = await serveFeed(new Request('https://s/feeds/data/x.json'), '/feeds/data/x.json');
    assert.equal(r.headers.get('X-Feed-Source'), 'github');
    assert.equal(await readBucketJSON(RAW + 'data/x.json'), undefined);
  } finally { globalThis.fetch = realFetch; }
});

test('watchdog dispatches only for a stale feed with no refresh running', async () => {
  const now = Date.parse('2026-09-28T14:00:00Z');
  assert.equal(Math.round(feedAgeMinutes({completed_at: '2026-09-28T13:00:00Z'}, now)), 60);
  assert.equal(feedAgeMinutes({}, now), Infinity);
  const calls = [];
  const realFetch = globalThis.fetch;
  const run = async (completed, running) => {
    calls.length = 0;
    useBucket({FEEDS: fakeBucket({'conditions/latest.json': JSON.stringify({completed_at: completed})})});
    globalThis.fetch = async (url, init = {}) => {
      calls.push(`${init.method || 'GET'} ${url.replace('https://api.github.com/repos/Grahammmm/skippercast', '')}`);
      if (url.includes('status=in_progress')) return new Response(JSON.stringify({total_count: running ? 1 : 0}));
      if (url.includes('status=queued')) return new Response(JSON.stringify({total_count: 0}));
      return new Response(null, {status: 204});
    };
    try { return await watchdog({GITHUB_TOKEN: 't'}, now); } finally { globalThis.fetch = realFetch; }
  };
  assert.equal((await run('2026-09-28T13:40:00Z', false)).action, 'none');
  assert.equal(calls.length, 0);
  assert.equal((await run('2026-09-28T12:30:00Z', true)).action, 'already-in_progress');
  assert.equal((await run('2026-09-28T12:30:00Z', false)).action, 'dispatched');
  assert.ok(calls.includes('POST /actions/workflows/live-conditions.yml/dispatches'));
  useBucket({FEEDS: fakeBucket({'conditions/latest.json': JSON.stringify({completed_at: '2026-09-28T12:00:00Z'})})});
  assert.equal((await watchdog({}, now)).action, 'no-token');
  useBucket({});
});

test('seafloor archives require a fresh matching revision and never fall back to assets', async () => {
  const path = '/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles';
  const control = 'tiles/seafloor/manifest-morro-bay.json';
  const manifest = {region: 'morro-bay', status: 'ready', archive_sha256: 'a'.repeat(64),
    expires_at: new Date(Date.now() + 3600000).toISOString()};
  const make = (m, digest = 'a'.repeat(64), archive = true) => ({async get(key) {
    if (key === control) return m ? {json: async () => m} : null;
    return archive ? {body: new Blob(['PMTiles']).stream(), size: 7, httpEtag: '"a"', customMetadata: {sha256: digest}} : null;
  }});
  try {
    for (const m of [null, {...manifest, status: 'updating'}, {...manifest, region: 'other'},
      {...manifest, expires_at: '2000-01-01'}, {...manifest, archive_sha256: null}]) {
      useBucket({FEEDS: make(m)});
      const r = await serveFeed(new Request('https://s'+path), path);
      assert.equal(r.status, 503);
      assert.equal(r.headers.get('Cache-Control'), 'no-store');
    }
    useBucket({FEEDS: make(manifest, 'b'.repeat(64))});
    assert.equal((await serveFeed(new Request('https://s'+path), path)).status, 503);
    useBucket({FEEDS: make(manifest)});
    let r = await serveFeed(new Request('https://s'+path), path);
    assert.equal(r.status, 200);
    assert.ok(r.headers.get('Access-Control-Expose-Headers').includes('ETag'));
    assert.equal(r.headers.get('Cache-Control'), 'no-store');
    const internal = '/feeds/tiles/seafloor/regions/morro-bay/seafloor-morro-bay.pmtiles';
    assert.equal((await serveFeed(new Request('https://s'+internal), internal)).status, 404);
    useBucket({FEEDS: make(manifest, 'a'.repeat(64), false)});
    r = await serveFeed(new Request('https://s'+path), path, {fetch() {throw new Error('Must not use bundled stale tiles');}});
    assert.equal(r.status, 404);
    assert.equal(feedKey('/feeds/seafloor-cache/source.bag'), null);
    assert.equal(feedKey('/feeds/seafloor-review/run.json'), null);
  } finally { useBucket({}); }
});

test('canonical reef export shares the current manifest and revision gate',async()=>{
 const path='/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson',hash='c'.repeat(64);
 const m={region:'morro-bay',status:'ready',export_sha256:hash,expires_at:new Date(Date.now()+3600000).toISOString()};
 const make=(manifest,digest=hash)=>({async get(key){return key.endsWith('manifest-morro-bay.json')?{json:async()=>manifest}:{body:new Blob(['{}']).stream(),size:2,httpEtag:'"c"',customMetadata:{sha256:digest}};}});
 try{
  useBucket({FEEDS:make(m)});assert.equal((await serveFeed(new Request('https://s'+path),path)).status,200);
  for(const manifest of [{...m,status:'held'},{...m,expires_at:'2000-01-01'},{...m,export_sha256:null}]){
   useBucket({FEEDS:make(manifest)});assert.equal((await serveFeed(new Request('https://s'+path),path)).status,503);
  }
  useBucket({FEEDS:make(m,'d'.repeat(64))});assert.equal((await serveFeed(new Request('https://s'+path),path)).status,503);
  assert.equal((await serveFeed(new Request('https://s/feeds/tiles/seafloor/regions/morro-bay/candidates.geojson'),'/feeds/tiles/seafloor/regions/morro-bay/candidates.geojson')).status,404);
 }finally{useBucket({});}
});
