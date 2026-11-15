// SCP3-09: a resumed Range read is honored only when If-Range still names the current version (strong ETag, or an exact
// HTTP-date backed by trustworthy modification metadata); otherwise the whole file is sent, never bytes of two versions.
import assert from 'node:assert/strict';
import test from 'node:test';
import {rangeResponse, serveFeed, useBucket} from '../server/feeds.ts';

const PATH = '/feeds/tiles/synthetic.pmtiles', KEY = 'tiles/synthetic.pmtiles';
const OLD = '0123456789', NEW = 'abcdefghij', UPLOADED = new Date('2026-11-09T12:00:00.123Z');
const SAME_SECOND = 'Mon, 09 Nov 2026 12:00:00 GMT', EARLIER = 'Mon, 09 Nov 2026 11:59:59 GMT';

/** R2 stand-in: a body per version; If-Match against a different version answers metadata only; hook runs after each get. */
function world({uploaded = UPLOADED} = {}) {
  const w = {etag: '"A"', body: OLD, gets: [], afterGet: null};
  const bucket = {async get(key, options = {}) {
    const {etag, body} = w, ifMatch = options.onlyIf?.get('If-Match') ?? null, header = options.range?.get('Range') ?? null;
    w.gets.push({range: header, ifMatch});
    const meta = {key, size: body.length, httpEtag: etag, ...(uploaded ? {uploaded} : {})};
    w.afterGet?.();
    if ((ifMatch !== null && ifMatch !== etag) || options.onlyIf?.get('If-None-Match') === etag) return meta;
    const m = /^bytes=(\d+)-(\d+)$/.exec(header || ''), offset = m ? Number(m[1]) : 0, length = m ? Number(m[2]) - offset + 1 : body.length;
    return {...meta, body: new Response(body.slice(offset, offset + length)).body, ...(m ? {range: {offset, length}} : {})};
  }};
  return {w, run: async fn => { globalThis.caches = null; useBucket({FEEDS: bucket}); try { return await fn(); } finally { useBucket(null); } }};
}
const serve = headers => serveFeed(new Request('https://skippercast.com' + PATH, {headers}), PATH, undefined, {build: 'b1'});
const range = (ifRange, extra = {}) => ({Range: 'bytes=2-5', ...(ifRange === undefined ? {} : {'If-Range': ifRange}), ...extra});
async function assertWhole(response, body = OLD) {
  assert.equal(response.status, 200); assert.equal(response.headers.get('Content-Range'), null);
  assert.equal(response.headers.get('Content-Length'), String(body.length)); assert.equal(await response.text(), body);
}
async function assertSlice(response, body = OLD) {
  assert.equal(response.status, 206); assert.equal(response.headers.get('Content-Range'), `bytes 2-5/${body.length}`); assert.equal(await response.text(), body.slice(2, 6));
}

test('rangeResponse_if_range_etag', async () => {
  const bytes = new TextEncoder().encode(OLD), make = ifRange => rangeResponse(bytes, new Request('https://x.test/', {headers: range(ifRange)}), new Headers({ETag: '"cur"'}));
  await assertWhole(make('"old"'));
  await assertSlice(make('"cur"'));
  await assertSlice(make(undefined));
  for (const bad of ['W/"cur"', 'cur', '"cur", "old"', '', 'Mon, 09 Nov 2026 12:00:00 GMT']) await assertWhole(make(bad));
  await assertWhole(rangeResponse(bytes, new Request('https://x.test/', {headers: range('W/"cur"')}), new Headers({ETag: 'W/"cur"'})));
});

test('rangeResponse_if_range_date_needs_trustworthy_last_modified', async () => {
  const bytes = new TextEncoder().encode(OLD);
  const make = (ifRange, lastModified) => rangeResponse(bytes, new Request('https://x.test/', {headers: range(ifRange)}), new Headers(lastModified ? {'Last-Modified': lastModified} : {}));
  await assertSlice(make(SAME_SECOND, SAME_SECOND));
  await assertWhole(make(EARLIER, SAME_SECOND));
  await assertWhole(make(SAME_SECOND, undefined));           // no modification metadata
  await assertWhole(make(SAME_SECOND, 'not a date'));        // untrusted metadata
  await assertWhole(make('Mon, 31 Feb 2026 12:00:00 GMT', SAME_SECOND));
});

test('feed_cold_r2_if_range_etag', async () => {
  const {w, run} = world();
  await run(async () => {
    await assertWhole(await serve(range('"old"')));
    assert.deepEqual(w.gets.map(g => g.range), ['bytes=2-5', null], 'ignored Range is not sent on the whole read');
    assert.equal(w.gets[1].ifMatch, '"A"', 'whole read is bound to the version just checked');
    await assertSlice(await serve(range('"A"')));
    await assertSlice(await serve(range(undefined)));
    for (const bad of ['W/"A"', 'A', 'Mon, 09 Nov 2026 12:00:00 GMT x']) await assertWhole(await serve(range(bad)));
    await assertSlice(await serve(range('"A"', {'If-Match': '"A"'})));
    assert.equal((await serve(range('"old"', {'If-Match': '"old"'}))).status, 412, 'If-Match precedes If-Range');
    assert.equal((await serve(range('"old"', {'If-None-Match': '"A"'}))).status, 304, 'If-None-Match precedes If-Range');
  });
});

test('feed_cold_r2_if_range_never_mixes_versions', async () => {
  const {w, run} = world();
  await run(async () => {
    w.afterGet = () => { w.afterGet = null; w.etag = '"B"'; w.body = NEW; };   // the file is replaced after the checked read
    const r = await serve(range('"old"'));
    assert.equal(r.status, 503); assert.equal(r.headers.get('Cache-Control'), 'no-store'); assert.equal(r.headers.get('Content-Range'), null);
    assert.equal(await r.text(), 'Feed object changed; retry');
    await assertWhole(await serve(range('"old"')), NEW);   // a fresh request sees one whole new version
    await assertSlice(await serve(range('"B"')), NEW);
  });
});

test('feed_cold_r2_if_range_date', async () => {
  let {w, run} = world();
  await run(async () => {
    await assertSlice(await serve(range(SAME_SECOND)));
    await assertWhole(await serve(range(EARLIER)));
    await assertWhole(await serve(range('2026-11-09T12:00:00Z')));
    assert.equal(w.gets.at(-1).ifMatch, '"A"');
  });
  ({w, run} = world({uploaded: null}));
  await run(async () => { await assertWhole(await serve(range(SAME_SECOND))); });
});
