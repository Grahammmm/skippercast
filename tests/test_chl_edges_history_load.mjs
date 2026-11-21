import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {loadChlEdgesDay, readChlEdgesIndex} from '../web/map/chl-edges-history.ts';

const day = '2024-02-29';
const region = 'test-coast-2';
const page = 'https://fixture.invalid/nested/map?region=ignored';
const root = 'https://fixture.invalid/feeds/conditions/regions/test-coast-2/chl-edges';
const indexUrl = `${root}/index.json`;
const dayUrl = `${root}/2024-02-29.json`;
const entry = (date, sha256 = 'ab'.repeat(32)) => ({date, path: `chl-edges/${date}.json`, sha256});

// Only the dated index, not its surrounding metadata, is a list of pointers.
test('C1: distinguish non-arrays from an empty index', () => {
  for (const data of [null, undefined, '[]', {entries: []}]) assert.deepEqual(readChlEdgesIndex(data), null);
  assert.deepEqual(readChlEdgesIndex([]), []);
});

test('C1: project clean keys and keep the first valid pointer for a duplicate date', () => {
  const first = entry(day);
  const earlier = entry('2024-02-28');
  assert.deepEqual(readChlEdgesIndex([
    {...earlier, path: 'wrong.json'}, {...first, unchecked: 'ignore'}, earlier, entry(day, 'b'.repeat(64)),
  ]), [first, earlier]);
});

// Early truncation would keep the oldest item rather than the newest seven.
test('C1: sort before limiting the index to seven', () => {
  const entries = ['01', '02', '03', '04', '05', '06', '07', '08'].map(d => entry(`2024-03-${d}`));
  assert.deepEqual(readChlEdgesIndex(entries), [entries[7], entries[6], entries[5], entries[4], entries[3], entries[2], entries[1]]);
});

test('C1: refuse invalid entry shapes, dates, noncanonical paths and digests without losing a valid sibling', () => {
  const good = entry(day);
  const bad = entry('2024-02-28');
  for (const invalid of [
    null, 'pointer', [bad], {date: bad.date}, {...bad, date: 20240228},
    ...['2023-02-29', '1900-02-29', '2024-04-31', '2024-00-01', '2024-01-00', '0000-01-01', '2024-2-28'].map(d => entry(d)),
    ...['chl-edges/2024-02-27.json', `sst-fronts/${bad.date}.json`, `chl-edges/../chl-edges/${bad.date}.json`,
      `https://fixture.invalid/${bad.path}`, `${bad.path}?alt=1`].map(path => ({...bad, path})),
    ...[null, 'A'.repeat(64), 'a'.repeat(63), 'a'.repeat(65), 'g'.repeat(64)].map(sha256 => ({...bad, sha256})),
  ]) assert.deepEqual(readChlEdgesIndex([invalid, good]), [good], JSON.stringify(invalid));
});

test('C1: never throw on unreadable unknown inputs', () => {
  const {proxy, revoke} = Proxy.revocable([], {});
  revoke();
  assert.deepEqual(readChlEdgesIndex(proxy), []);
  const unreadable = {get date() { throw new TypeError('unreadable'); }};
  assert.deepEqual(readChlEdgesIndex([unreadable, entry(day)]), [entry(day)]);
});

const observedAt = `${day}T12:00:00Z`;
const wireDoc = {
  schema_version: 1, region_id: region, layer_id: 'chl-edges', product: 'Synthetic chlorophyll', credit: 'Fixture credit',
  max_age_hours: 48, observed_at: observedAt, observed_fraction: 0.5, withheld: null, edges: [],
};
const body = JSON.stringify(wireDoc);
const ready = {state: 'ready', date: day, doc: {
  product: 'Synthetic chlorophyll', credit: 'Fixture credit', maxAgeMs: 172_800_000,
  observedAt, observedFraction: 0.5, withheld: null, edges: [],
}};
const error = {state: 'error'};
const none = {state: 'none'};
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const indexFor = bytes => Response.json([entry(day, hash(bytes))]);

function stub(...steps) {
  const calls = [];
  const fetchFn = async (url, options) => {
    const step = steps[calls.length];
    calls.push({url, signal: options?.signal});
    if (typeof step === 'function') return step(options);
    if (!step) throw new Error('unexpected fetch');
    return step;
  };
  return {calls, fetchFn};
}

// Make assertions on the calls outside fetch: the loader catches adapter failures.
async function check(expected, urls, steps, request = {}) {
  const {calls, fetchFn} = stub(...steps);
  const {regionId = region, date = day, base = page} = request;
  assert.deepEqual(await loadChlEdgesDay(regionId, date, {fetchFn, page: base}), expected);
  assert.deepEqual(calls, urls.map(url => ({url, signal: undefined})));
}

test('C2: index 404 and unlisted days stop before the second fetch', async () => {
  await check(none, [indexUrl], [new Response(null, {status: 404})]);
  await check(none, [indexUrl], [Response.json([entry('2024-02-28')])]);
});

test('C2: an index cannot redirect the dated request by supplying an escaping path', async () => {
  await check(none, [indexUrl], [Response.json([{...entry(day), path: `../other-region/chl-edges/${day}.json`}])]);
});

test('C2: invalid region or day fails before fetching', async () => {
  for (const regionId of ['../test-coast-2', 'Test-coast-2', '', 'ok/../other']) await check(error, [], [], {regionId});
  for (const date of ['2026-02-29', '2024-02-30', '2024-2-29', `${day}T00:00:00Z`]) await check(error, [], [], {date});
  await check(error, [], [], {base: 'not an absolute URL'});
});

test('C2: distinguish invalid or failed index responses from absence', async () => {
  for (const response of [new Response(null, {status: 503}), Response.json({index: []}), new Response('[')]) {
    await check(error, [indexUrl], [response]);
  }
});

test('C3: verify the exact selected bytes and return the parsed document at the inclusive byte limit', async () => {
  const bytes = ' '.repeat(5_000_000 - Buffer.byteLength(body)) + body;
  const index = Response.json([entry('2024-03-01'), entry(day, hash(bytes))]);
  await check(ready, [indexUrl, dayUrl], [index, new Response(bytes)]);
});

test('C3: refuse an oversized document even with a matching digest and no Content-Length', async () => {
  // Multibyte text makes a character-count check accept this 5,000,001-byte body.
  const unicodeBody = JSON.stringify({...wireDoc, credit: 'Café'});
  const bytes = unicodeBody.padEnd(5_000_000);
  await check(error, [indexUrl, dayUrl], [indexFor(bytes), new Response(bytes)]);
});

test('C3: refuse tampered bytes even when decoded JSON is unchanged', async () => {
  await check(error, [indexUrl, dayUrl], [indexFor(body), new Response(`${body}\n`)]);
});

test('C3: matching hashes cannot admit another region, invalid schema or malformed JSON', async () => {
  for (const bytes of [JSON.stringify({...wireDoc, region_id: 'other-coast'}), JSON.stringify({...wireDoc, layer_id: 'sst-fronts'}), '{']) {
    await check(error, [indexUrl, dayUrl], [indexFor(bytes), new Response(bytes)]);
  }
});

test('C3: a dated-file 404 or other failure is not a missing index entry', async () => {
  for (const status of [404, 502]) await check(error, [indexUrl, dayUrl], [indexFor(body), new Response(null, {status})]);
});

test('C3: rejection at either fetch or while reading the body becomes error without abort', async () => {
  const reject = () => { throw new TypeError('unavailable'); };
  await check(error, [indexUrl], [reject]);
  await check(error, [indexUrl, dayUrl], [indexFor(body), reject]);
  const unreadable = new Response(body);
  await unreadable.arrayBuffer();
  await check(error, [indexUrl, dayUrl], [indexFor(body), unreadable]);
  await check(error, [indexUrl], [() => { throw new DOMException('not signal-driven', 'AbortError'); }]);
});

test('C3: propagate an abort from either request with the original error and forwarded signal', async () => {
  for (const urls of [[indexUrl], [indexUrl, dayUrl]]) {
    const controller = new AbortController();
    const reason = new DOMException('fixture cancelled', 'AbortError');
    const abort = () => { controller.abort(reason); throw reason; };
    const {calls, fetchFn} = stub(...(urls.length === 1 ? [abort] : [indexFor(body), abort]));
    await assert.rejects(loadChlEdgesDay(region, day, {fetchFn, page, signal: controller.signal}),
      err => err instanceof DOMException && err.name === 'AbortError' && err === reason);
    assert.deepEqual(calls, urls.map(url => ({url, signal: controller.signal})));
  }
});

test('C3: refuse an already-aborted load without fetching and detect abort even if fetch resolves', async () => {
  for (const preAborted of [true, false]) {
    const controller = new AbortController();
    const reason = new TypeError('fixture cancelled');
    if (preAborted) controller.abort(reason);
    const {calls, fetchFn} = stub(() => {
      controller.abort(reason);
      return new Response(null, {status: 404});
    });
    await assert.rejects(loadChlEdgesDay(region, day, {fetchFn, page, signal: controller.signal}),
      err => err instanceof TypeError && err === reason);
    assert.deepEqual(calls, preAborted ? [] : [{url: indexUrl, signal: controller.signal}]);
  }
});
