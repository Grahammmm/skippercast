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

// RF1050-22: a request carrying any header may get a different representation (Range, conditional,
// Authorization…), so it neither seeds nor reuses the shared whole-file cache.
const FILE = 'regions/morro-bay/region.json';
const WHOLE = JSON.stringify({complete: true, marks: [1, 2, 3]});
const PART = JSON.stringify({subset: true});
const whole = () => new Response(WHOLE, {status: 200});
const partial = () => new Response(PART, {status: 206});
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };

test('shared_key_header_shapes', () => {
  const key = 'https://s.test/regions/morro-bay/region.json';
  for (const headers of [
    {Range: 'bytes=0-9'}, {range: 'bytes=0-9'}, {'RANGE': 'bytes=0-9'}, {'If-None-Match': '"abc"'},
    {Accept: 'application/json'}, {Authorization: 'Bearer x'}, {'X-Empty': ''},
    [['Range', 'bytes=0-9']], [['accept', 'text/plain']], [['X-Empty', '']],
    new Headers({Range: 'bytes=0-9'}), new Headers([['If-Modified-Since', 'Wed, 21 Oct 2026 07:28:00 GMT']]),
  ]) assert.equal(sharedKey(FILE, {headers}, BASE), null, JSON.stringify([...new Headers(headers)]));
  for (const headers of [undefined, {}, [], new Headers()]) assert.equal(sharedKey(FILE, {headers}, BASE), key);
  assert.equal(sharedKey(FILE, {}, BASE), key);
  // A header that cannot be inspected falls through to the network call itself; no wrapper error.
  for (const headers of [[['Range']], [['bad name', 'x']], {'Bad Name': 'x'}, 'Range: bytes=0-9', 42]) {
    assert.equal(sharedKey(FILE, {headers}, BASE), null, String(headers));
  }
  // The caller's headers are only read, never changed.
  const mine = {Range: 'bytes=0-9'};
  sharedKey(FILE, {headers: mine}, BASE);
  assert.equal(JSON.stringify(mine), '{"Range":"bytes=0-9"}');
  const list = [['Range', 'bytes=0-9']];
  sharedKey(FILE, {headers: list}, BASE);
  assert.equal(JSON.stringify(list), '[["Range","bytes=0-9"]]');
});

test('range_first_does_not_poison_whole_file', async () => {
  globalThis.location = {href: BASE};
  try {
    const calls = [];
    const shared = shareStatic(async (url, init = {}) => { calls.push(init.headers ? 'range' : 'whole'); return init.headers ? partial() : whole(); });
    const sub = await shared(FILE, {headers: {Range: 'bytes=0-9'}});
    assert.equal(sub.status, 206);
    assert.equal(await sub.text(), PART);
    const ordinary = await shared(FILE);
    assert.equal(ordinary.status, 200);
    assert.equal(await ordinary.text(), WHOLE);
    const again = await shared(FILE);
    assert.equal(await again.text(), WHOLE, 'a second ordinary read reuses only the complete one');
    assert.deepEqual(calls, ['range', 'whole']);
  } finally { delete globalThis.location; }
});

test('whole_file_first_does_not_swallow_range', async () => {
  globalThis.location = {href: BASE};
  try {
    const calls = [];
    const shared = shareStatic(async (url, init = {}) => { calls.push(init.headers ? 'range' : 'whole'); return init.headers ? partial() : whole(); });
    assert.equal(await (await shared(FILE)).text(), WHOLE);
    const sub = await shared(FILE, {headers: [['Range', 'bytes=0-9']]});
    assert.equal(sub.status, 206);
    assert.equal(await sub.text(), PART);
    assert.equal(await (await shared(FILE)).text(), WHOLE, 'the good ordinary response stays cached');
    assert.deepEqual(calls, ['whole', 'range']);
  } finally { delete globalThis.location; }
});

test('concurrent_header_variants_are_independent', async () => {
  globalThis.location = {href: BASE};
  try {
    const pending = [];
    const calls = [];
    const shared = shareStatic((url, init = {}) => {
      const d = deferred();
      pending.push(d);
      calls.push(init.headers ? 'variant' : 'whole');
      return d.promise;
    });
    const ordinary = shared(FILE);
    const conditional = shared(FILE, {headers: {'If-None-Match': '"v1"'}});
    const ranged = shared(FILE, {headers: new Headers({Range: 'bytes=0-9'})});
    const second = shared(FILE);
    assert.deepEqual(calls, ['whole', 'variant', 'variant'], 'the second ordinary read joins the first request');
    // Settle in reverse order.
    pending[2].resolve(partial());
    pending[1].resolve(new Response(WHOLE, {status: 200}));
    pending[0].resolve(whole());
    const [o, c, r, s] = await Promise.all([ordinary, conditional, ranged, second]);
    assert.equal(r.status, 206);
    assert.equal(await r.text(), PART);
    assert.equal(c.status, 200);
    assert.equal(await o.text(), WHOLE);
    assert.equal(await s.text(), WHOLE);
    assert.notEqual(o, c);
    // A header-specific 200 is not stored: the same header asks the network again.
    const next = shared(FILE, {headers: {'If-None-Match': '"v1"'}});
    assert.equal(calls.length, 4);
    pending[3].resolve(whole());
    assert.equal((await next).status, 200);
    assert.equal(calls.length, 4);
  } finally { delete globalThis.location; }
});

test('header_variant_preserves_fetch_arguments', async () => {
  globalThis.location = {href: BASE};
  try {
    const seen = [];
    let read = false;
    const response = whole();
    response.json = async () => { read = true; return {}; };
    const shared = shareStatic(async (input, init) => { seen.push([input, init]); return response; });
    const init = {headers: {Range: 'bytes=0-9'}, signal: new AbortController().signal};
    const got = await shared(FILE, init);
    assert.equal(got, response, 'the variant response is returned unchanged');
    assert.equal(read, false, 'its body is not read eagerly');
    assert.equal(response.bodyUsed, false);
    assert.equal(seen.length, 1);
    assert.equal(seen[0][0], FILE);
    assert.equal(seen[0][1], init, 'the original init object is passed on');
    assert.equal(seen[0][1].signal, init.signal);
    assert.equal(seen[0][1].headers, init.headers);
  } finally { delete globalThis.location; }
});

test('header_variant_errors_aborts_and_headerless_behaviour_are_unchanged', async () => {
  globalThis.location = {href: BASE};
  try {
    // A transport error from a header-bearing read is the fetch's own; nothing is shared or forgotten wrongly.
    let n = 0;
    const shared = shareStatic(async (url, init = {}) => {
      n++;
      if (init.headers && init.signal?.aborted) throw init.signal.reason;
      if (init.headers && n === 1) throw new TypeError('network down');
      return whole();
    });
    await assert.rejects(shared(FILE, {headers: {Range: 'bytes=0-9'}}), /network down/);
    const ac = new AbortController();
    ac.abort(new Error('stop'));
    await assert.rejects(shared(FILE, {headers: {Range: 'bytes=0-9'}, signal: ac.signal}), /stop/);
    // A malformed header value is the native fetch's problem, not a wrapper error.
    assert.doesNotThrow(() => { shared(FILE, {headers: [['Range']]}).catch(() => {}); });
    // Headerless reads still share one request, and an aborted caller does not cancel the share.
    const before = n;
    const gate = deferred();
    const slow = shareStatic(async () => { n++; await gate.promise; return whole(); });
    const quick = new AbortController();
    const a = slow(FILE, {signal: quick.signal});
    const b = slow(FILE);
    quick.abort(new Error('caller gone'));
    gate.resolve();
    await assert.rejects(a, /caller gone/);
    assert.equal(await (await b).text(), WHOLE);
    assert.equal(n - before, 1, 'headerless reads share one request');
    // A headerless body that fails to parse is still forgotten so the next read refetches.
    let bad = 0;
    const body = shareStatic(async () => { bad++; return new Response(bad === 1 ? '{not json' : WHOLE, {status: 200}); });
    await assert.rejects((await body(FILE)).json());
    assert.deepEqual(await (await body(FILE)).json(), JSON.parse(WHOLE));
    assert.equal(bad, 2);
  } finally { delete globalThis.location; }
});
