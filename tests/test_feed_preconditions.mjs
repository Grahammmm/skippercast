// RF0824-6: an R2 object returned without a body because If-Match or
// If-Unmodified-Since failed is a 412, never a 304; ordinary validators and
// Range keep their behaviour. Offline: the real serveFeed with a conditional
// bucket stand-in and a cache spy (no R2, no network).
import assert from 'node:assert/strict';
import test from 'node:test';
import {serveFeed, useBucket} from '../server/feeds.ts';

const PATH = '/feeds/tiles/synthetic.pmtiles', KEY = 'tiles/synthetic.pmtiles', BUILD = 'b1';
const BODY = '0123456789', UPLOADED = new Date('2026-11-09T12:00:00.123Z');
const SAME_SECOND = 'Mon, 09 Nov 2026 12:00:00 GMT', EARLIER = 'Mon, 09 Nov 2026 11:59:59 GMT', LATER = 'Mon, 09 Nov 2026 12:00:01 GMT';

const tagsOf = header => (header.match(/(W\/)?"[^"]*"/g) || []).filter(t => !t.startsWith('W/'));
const seconds = date => Math.floor(date.getTime() / 1000);

/** A bucket whose conditional get answers like R2: metadata only when any supplied condition fails. */
function adapter({etag = '"current"', bodyOnFail = false} = {}) {
  const gets = [], cancelled = [];
  const bucket = {async get(key, options = {}) {
    gets.push({key, onlyIf: options.onlyIf instanceof Headers ? [...options.onlyIf].sort() : null});
    const c = options.onlyIf instanceof Headers ? options.onlyIf : new Headers();
    const bytes = new TextEncoder().encode(BODY);
    const meta = {key, size: bytes.length, httpEtag: etag, uploaded: UPLOADED};
    const fails = (c.has('If-Match') && !tagsOf(c.get('If-Match')).concat(c.get('If-Match').trim() === '*' ? [etag] : []).includes(etag))
      || (c.has('If-Unmodified-Since') && seconds(UPLOADED) > seconds(new Date(c.get('If-Unmodified-Since'))))
      || (c.has('If-None-Match') && tagsOf(c.get('If-None-Match')).includes(etag))
      || (c.has('If-Modified-Since') && seconds(UPLOADED) <= seconds(new Date(c.get('If-Modified-Since'))));
    const withBody = () => {
      const header = options.range instanceof Headers ? options.range.get('Range') : null, m = /^bytes=(\d+)-(\d+)$/.exec(header || '');
      const offset = m ? Number(m[1]) : 0, length = m ? Math.min(Number(m[2]), bytes.length - 1) - offset + 1 : bytes.length;
      const body = new ReadableStream({start(controller) { controller.enqueue(bytes.slice(offset, offset + length)); controller.close(); }, cancel() { cancelled.push(key); }});
      return {...meta, body, ...(m ? {range: {offset, length}} : {})};
    };
    return fails && !bodyOnFail ? meta : withBody();
  }};
  return {gets, cancelled, bucket};
}

/** caches.default spy seeded with a stale 200 for the feed. */
class SpyCache {
  constructor() { this.matches = 0; this.puts = 0; this.entry = null; this.fail = false; }
  seed(headers = {}) { this.entry = {body: 'STALE', headers: {ETag: '"old"', 'Cache-Control': 'public, max-age=300', 'Content-Length': '5', ...headers}}; }
  async match(request) {
    this.matches++;
    if (this.fail) throw Error('cache unavailable');
    if (!this.entry) return undefined;
    const headers = new Headers(this.entry.headers);
    if (request.headers.get('If-None-Match') === headers.get('ETag')) return new Response(null, {status: 304, headers});
    return new Response(this.entry.body, {status: 200, headers});
  }
  async put(request, response) {
    if (/no-store/.test(response.headers.get('Cache-Control') || '')) { await response.arrayBuffer(); return; }
    this.puts++;
    this.entry = {body: await response.text(), headers: [...response.headers]};
  }
}

async function withWorld(options, fn, caches) {
  const w = adapter(options), cache = new SpyCache(), original = globalThis.caches;
  globalThis.caches = caches === undefined ? {default: cache} : caches;
  useBucket({FEEDS: w.bucket});
  try { return await fn({...w, cache}); } finally { globalThis.caches = original; useBucket(null); }
}
const serve = (headers = {}) => serveFeed(new Request('https://skippercast.com' + PATH, {headers}), PATH, undefined, {build: BUILD});

async function assert412(response) {
  assert.equal(response.status, 412);
  assert.equal(await response.text(), '');
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(response.headers.get('ETag'), '"current"');
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), '*');
  assert.match(response.headers.get('Access-Control-Expose-Headers'), /ETag/);
  assert.equal(response.headers.get('Content-Type'), 'application/octet-stream');
}

test('feed_failed_if_match_is_412', () => withWorld({}, async ({cache, gets}) => {
  for (const value of ['"old"', 'W/"current"', '"old", W/"current"', 'current']) {
    await assert412(await serve({'If-Match': value}));
  }
  assert.equal(gets.length, 4, 'one object get per request, no re-fetch');
  assert.equal(cache.puts, 0);
  for (const value of ['"current"', '*', '"old", "current"', '"old" ,"current"']) {
    const r = await serve({'If-Match': value});
    assert.equal(r.status, 200, value); assert.equal(await r.text(), BODY);
  }
}));

test('feed_failed_if_match_quoted_tag_with_comma_is_not_split', () => withWorld({etag: '"a,b"'}, async () => {
  for (const value of ['"a,b"', '"x", "a,b"']) assert.equal((await serve({'If-Match': value})).status, 200, value);
  for (const value of ['"a"', '"b"', '"a", "b"']) {
    const r = await serve({'If-Match': value});
    assert.equal(r.status, 412, value); assert.equal(r.headers.get('ETag'), '"a,b"');
  }
}));

test('feed_unmodified_since_second_boundary', () => withWorld({}, async ({gets, cancelled}) => {
  await assert412(await serve({'If-Unmodified-Since': EARLIER}));
  for (const date of [SAME_SECOND, LATER]) {
    const r = await serve({'If-Unmodified-Since': date});
    assert.equal(r.status, 200, date); assert.equal(await r.text(), BODY);
  }
  const ignored = await serve({'If-Unmodified-Since': 'not a date'});
  assert.equal(ignored.status, 200); await ignored.text();
  assert.deepEqual(gets.at(-1).onlyIf, [], 'an invalid date is not forwarded');
  assert.equal(gets.length, 4); assert.deepEqual(cancelled, []);
}));

test('feed_if_unmodified_since_ignores_non_http_dates', () => withWorld({}, async ({gets, cancelled}) => {
  // Object uploaded 2026-11-09: each of these would be a (wrong) 412 if Date.parse's leniency were trusted.
  const invalid = ['2020-01-01', '2020-01-01T00:00:00Z', 'Jan 1 2020', '1/1/2020', '2020', 'Mon, 09 Nov 2020', 'Mon, 31 Feb 2020 10:00:00 GMT',
    'Mon, 09 Nov 2020 25:00:00 GMT', 'Mon, 09 Nov 2020 10:00:00 PST', 'Mon, 09 Nov 2020 10:00:00', '1577836800', ''];
  for (const value of invalid) {
    const r = await serve({'If-Unmodified-Since': value});
    assert.equal(r.status, 200, JSON.stringify(value)); assert.equal(await r.text(), BODY);
    assert.deepEqual(gets.at(-1).onlyIf, [], `${JSON.stringify(value)} is not forwarded`);
  }
  // The two obsolete HTTP-date forms are still dates (here far before the upload, so 412); a later date passes.
  for (const value of ['Sunday, 06-Nov-94 08:49:37 GMT', 'Sun Nov  6 08:49:37 1994']) await assert412(await serve({'If-Unmodified-Since': value}));
  for (const value of ['Tuesday, 09-Nov-49 12:00:01 GMT', 'Mon Nov  9 12:00:01 2026']) assert.equal((await serve({'If-Unmodified-Since': value})).status, 200, value);
  assert.deepEqual(cancelled.length, 0);
}));

test('feed_if_match_tag_with_illegal_characters_fails', () => withWorld({}, async ({gets}) => {
  for (const value of ['"current", "bad tag"', '"bad tag", "current"', '"current" "bad"', '"cur\trent"', '"current", "a"b"', '"current",, "x"', '"current"x', ' W/ "current"']) {
    await assert412(await serve({'If-Match': value}));
  }
  assert.equal(gets.length, 8, 'one object get per request');
  for (const value of ['"current", "tag-ok~!#"', ' "current" ', '"current",']) assert.equal((await serve({'If-Match': value})).status, 200, value);
}));

test('feed_failed_precondition_with_defensive_body_cancels_the_stream_without_refetch', () => withWorld({bodyOnFail: true}, async ({gets, cancelled}) => {
  await assert412(await serve({'If-Match': '"old"'}));
  await assert412(await serve({'If-Unmodified-Since': EARLIER}));
  assert.equal(gets.length, 2); assert.equal(cancelled.length, 2);
}));

test('feed_precondition_precedence', () => withWorld({}, async ({gets}) => {
  // Matching If-Match suppresses a stale If-Unmodified-Since.
  let r = await serve({'If-Match': '"current"', 'If-Unmodified-Since': EARLIER});
  assert.equal(r.status, 200); await r.text();
  assert.deepEqual(gets.at(-1).onlyIf, [['if-match', '"current"']]);
  // Matching If-Match + matching If-None-Match: 304.
  r = await serve({'If-Match': '"current"', 'If-None-Match': '"current"'});
  assert.equal(r.status, 304); assert.equal(await r.text(), ''); assert.equal(r.headers.get('ETag'), '"current"');
  // Failed If-Match beats a matching If-None-Match.
  await assert412(await serve({'If-Match': '"old"', 'If-None-Match': '"current"'}));
  // If-None-Match suppresses If-Modified-Since (even an invalid or unchanged one).
  r = await serve({'If-None-Match': '"old"', 'If-Modified-Since': SAME_SECOND});
  assert.equal(r.status, 200); await r.text();
  assert.deepEqual(gets.at(-1).onlyIf, [['if-none-match', '"old"']]);
  r = await serve({'If-None-Match': '"current"', 'If-Modified-Since': 'garbage'});
  assert.equal(r.status, 304);
  assert.deepEqual(gets.at(-1).onlyIf, [['if-none-match', '"current"']]);
}, null));

test('feed_positive_preconditions_bypass_warm_cache', async () => {
  for (const [headers, status] of [[{'If-Match': '"old"'}, 412], [{'If-Unmodified-Since': EARLIER}, 412], [{'If-Match': '"current"'}, 200]]) {
    await withWorld({}, async ({cache, gets}) => {
      cache.seed();
      const r = await serve(headers);
      assert.equal(r.status, status);
      if (status === 200) assert.equal(await r.text(), BODY, 'never the stale cached body'); else await assert412(r);
      assert.equal(gets.length, 1, 'exactly one object get');
      assert.equal(cache.matches, 0, 'no cache lookup'); assert.equal(cache.puts, 0, 'nothing stored');
    });
  }
  for (const caches of [{}, {get default() { throw Error('forbidden'); }}, null]) {
    await withWorld({}, async ({gets}) => {
      await assert412(await serve({'If-Match': '"old"'}));
      assert.equal(gets.length, 1);
    }, caches);
  }
  await withWorld({}, async ({cache}) => {
    cache.seed(); cache.fail = true;
    await assert412(await serve({'If-Match': '"old"'}));
  });
});

test('feed_ordinary_conditional_and_range_controls', async () => {
  await withWorld({}, async () => {
    let r = await serve(); assert.equal(r.status, 200); assert.equal(await r.text(), BODY);
    r = await serve({'If-None-Match': '"current"'}); assert.equal(r.status, 304); assert.equal(await r.text(), '');
    r = await serve({'If-Modified-Since': SAME_SECOND}); assert.equal(r.status, 304);
    r = await serve({'If-Modified-Since': EARLIER}); assert.equal(r.status, 200); await r.text();
    r = await serve({Range: 'bytes=2-5'}); assert.equal(r.status, 206); assert.equal(await r.text(), '2345');
    assert.equal(r.headers.get('Content-Range'), 'bytes 2-5/10');
    r = await serve({Range: 'bytes=2-5', 'If-Match': '"current"'}); assert.equal(r.status, 206); assert.equal(await r.text(), '2345');
    r = await serve({Range: 'bytes=2-5', 'If-Match': '"old"'}); assert.equal(r.status, 412); await r.text();
  }, null);
  await withWorld({}, async ({cache, gets}) => {
    await (await serve()).text();
    assert.equal(cache.puts, 1); assert.equal(gets.length, 1);
    const hit = await serve(); assert.equal(hit.headers.get('X-SC-Cache'), 'hit'); assert.equal(await hit.text(), BODY);
    const unchanged = await serve({'If-None-Match': '"current"'}); assert.equal(unchanged.status, 304);
    assert.equal(gets.length, 1, 'ordinary and conditional hits make no R2 read');
  });
});
