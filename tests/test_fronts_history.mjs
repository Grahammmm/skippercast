import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {loadFrontsDay, readFrontsIndex} from '../web/map/fronts-history.ts';

const REGION = 'test-coast', DAY = '2024-02-29', PAGE = 'https://s.test/map?day=-1';
const INDEX_URL = 'https://s.test/feeds/conditions/regions/test-coast/sst-fronts/index.json';
const DAY_URL = 'https://s.test/feeds/conditions/regions/test-coast/sst-fronts/2024-02-29.json';
const entry = (date = DAY, sha256 = 'a'.repeat(64)) => ({date, path: `sst-fronts/${date}.json`, sha256});
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const observed = `${DAY}T08:00:00Z`;
const lines = [[-121, 35], [-120, 36]];
const wire = {schema_version: 1, region_id: REGION, layer_id: 'sst-fronts', product: 'Fixture SST', credit: ' Fixture credit ',
  max_age_hours: 48, observed_at: observed, fronts: [{id: 'f1', observed_at: observed, strength_c_per_km: 0.2,
    uncertainty_c: 0.3, band_half_width_km: 1.5, geometry: {type: 'LineString', coordinates: lines}}]};
const body = JSON.stringify(wire);
const ready = {state: 'ready', date: DAY, doc: {product: 'Fixture SST', credit: 'Fixture credit', maxAgeMs: 172_800_000, observedAt: observed,
  fronts: [{id: 'f1', observedAt: observed, strengthCPerKm: 0.2, uncertaintyC: 0.3, bandHalfWidthKm: 1.5, lines: [lines]}]}};
const error = {state: 'error'}, none = {state: 'none'};

function stub(responses, signal) {
  const calls = [];
  const options = {page: PAGE, signal, async fetchFn(url, init) {
    calls.push([url, init]);
    const response = responses[calls.length - 1];
    if (typeof response === 'function') return response(init);
    if (!response) throw new TypeError('unexpected fetch');
    return response;
  }};
  return {options, calls};
}
const indexFor = digest => Response.json([entry(DAY, digest)]);

// The index boundary owns pointer validation; live-front tests never see these rows.
test('C1: a non-array index is null, not an empty usable index', () => {
  assert.deepEqual(readFrontsIndex({entries: [entry()]}), null);
  assert.deepEqual(readFrontsIndex([]), []);
});

test('C1: project only wire fields; keep the first valid duplicate and sort before trimming to seven', () => {
  const days = ['2024-02-28', '2024-02-23', DAY, '2024-02-27', '2024-03-01', '2024-02-25', '2024-02-26', '2024-02-24'];
  const rows = days.map(date => Object.freeze({...entry(date), extra: true}));
  const duplicate = entry(DAY, 'b'.repeat(64));
  assert.deepEqual(readFrontsIndex(Object.freeze([...rows, duplicate])),
    ['2024-03-01', DAY, '2024-02-28', '2024-02-27', '2024-02-26', '2024-02-25', '2024-02-24'].map(date => entry(date)));
});

for (const [name, malformed] of [
  ['null and non-record rows', [null, false, [], 1]],
  ['noncanonical dates', [entry('2024-2-29'), entry('2024-02-29\n')]],
  ['impossible calendar dates', [entry('2023-02-29'), entry('2024-04-31'), entry('0000-01-01'), entry('2024-13-01')]],
  ['paths not bound to the date', [{...entry(), path: '../2024-02-29.json'}, {...entry(), path: 'sst-fronts/2024-02-28.json'}]],
  ['uppercase, short, non-hex and non-string digests', ['A'.repeat(64), 'a'.repeat(63), 'g'.repeat(64), null].map(hash => entry(DAY, hash))],
  ['an unreadable row', [{get date() { throw new TypeError('unreadable'); }}]],
]) {
  test(`C1: drop ${name} without losing a valid row`, () => {
    assert.deepEqual(readFrontsIndex(malformed), []);
    assert.deepEqual(readFrontsIndex([...malformed, entry()]), [entry()]);
  });
}

test('C1: an unreadable index does not throw', () => {
  const {proxy, revoke} = Proxy.revocable([], {});
  revoke();
  assert.deepEqual(readFrontsIndex(proxy), null);
});

// Catch invalid selections and distinguish absent history from a failed index read.
for (const [name, region, day] of [
  ['an invalid region ID', '../other', DAY],
  ['an invalid day', REGION, '2024-02-30'],
]) {
  test(`C2: reject ${name} before fetching`, async () => {
    const {options, calls} = stub([]);
    assert.deepEqual(await loadFrontsDay(region, day, options), error);
    assert.deepEqual(calls, []);
  });
}

for (const [name, response, expected] of [
  ['index 404 means none', () => new Response(null, {status: 404}), none],
  ['other non-OK index means error', () => new Response(JSON.stringify([entry()]), {status: 503}), error],
  ['a non-array index means error', () => Response.json({entries: []}), error],
  ['invalid index JSON means error', () => new Response('{'), error],
  ['a missing day is not replaced by a neighbouring file', () => Response.json([entry('2024-02-28')]), none],
  ['a path escape in the selected entry gives no usable day', () => Response.json([{...entry(), path: '../../other.json'}]), none],
]) {
  test(`C2: ${name}`, async () => {
    const {options, calls} = stub([response()]);
    assert.deepEqual(await loadFrontsDay(REGION, DAY, options), expected);
    assert.deepEqual(calls, [[INDEX_URL, {}]]);
  });
}

// With a valid hash, even padding and exact byte limits are checked against the original response, not reserialized JSON.
const padded = size => body.padEnd(size);
for (const [name, makeContent] of [['the chosen day', () => `\n${body}\n`], ['exactly 5,000,000 bytes', () => padded(5_000_000)]]) {
  test(`C3: load and parse ${name} as a whole FrontsDoc`, async () => {
    const content = makeContent();
    const index = Response.json([entry('2024-03-01'), entry(DAY, sha(content))]);
    const {options, calls} = stub([index, new Response(content)]);
    assert.deepEqual(await loadFrontsDay(REGION, DAY, options), ready);
    assert.deepEqual(calls, [[INDEX_URL, {}], [DAY_URL, {}]]);
  });
}

// Each failure changes one gate; signed-looking documents for another region or with malformed geometry still fail parsing.
for (const [name, fixture] of [
  ['a changed but still valid document', () => [indexFor(sha(body)), new Response(body.replace('Fixture SST', 'Changed SST'))]],
  ['a correctly hashed document for another region', () => matching(JSON.stringify({...wire, region_id: 'other-coast'}))],
  ['correctly hashed invalid JSON', () => matching('{')],
  ['correctly hashed invalid geometry for this region', () => matching(JSON.stringify({...wire, fronts: [{...wire.fronts[0], geometry: {type: 'Point', coordinates: lines[0]}}]}))],
  ['5,000,001 bytes even with a matching hash', () => matching(padded(5_000_001))],
  ['a dated-file 404 even when the index lists the day', () => [indexFor(sha(body)), new Response(null, {status: 404})]],
  ['a rejected dated-file request', () => [indexFor(sha(body)), () => { throw new TypeError('offline'); }]],
  ['a rejected dated-file body read', () => [indexFor(sha(body)), new Response(new ReadableStream({start(c) { c.error(new TypeError('body failed')); }}))]],
]) {
  test(`C3: refuse ${name}`, async () => {
    const {options, calls} = stub(fixture());
    assert.deepEqual(await loadFrontsDay(REGION, DAY, options), error);
    assert.deepEqual(calls, [[INDEX_URL, {}], [DAY_URL, {}]]);
  });
}
function matching(content) {
  return [indexFor(sha(content)), new Response(content)];
}

test('C3: a rejected index request is an error even when named AbortError but the signal is live', async () => {
  const {signal} = new AbortController();
  const {options, calls} = stub([() => { throw new DOMException('request failed', 'AbortError'); }], signal);
  assert.deepEqual(await loadFrontsDay(REGION, DAY, options), error);
  assert.deepEqual(calls, [[INDEX_URL, {signal}]]);
});

test('C3: pass the same signal to both requests and rethrow the original abort error', async () => {
  const controller = new AbortController();
  const {signal} = controller;
  const abort = new DOMException('superseded day', 'AbortError');
  const {options, calls} = stub([indexFor(sha(body)), init => {
    controller.abort(abort);
    init.signal.throwIfAborted();
  }], signal);
  await assert.rejects(loadFrontsDay(REGION, DAY, options), thrown => {
    assert.equal(thrown.constructor, DOMException);
    assert.equal(thrown, abort);
    return true;
  });
  assert.deepEqual(calls, [[INDEX_URL, {signal}], [DAY_URL, {signal}]]);
});

test('C3: a cancellation during verification cannot publish a ready day', async () => {
  const controller = new AbortController();
  const abort = new DOMException('superseded day', 'AbortError');
  const {options, calls} = stub([indexFor(sha(body)), {ok: true, arrayBuffer() {
    queueMicrotask(() => controller.abort(abort));
    return Promise.resolve(new TextEncoder().encode(body).buffer);
  }}], controller.signal);
  await assert.rejects(loadFrontsDay(REGION, DAY, options), thrown => {
    assert.equal(thrown.constructor, DOMException);
    assert.equal(thrown, abort);
    return true;
  });
  assert.deepEqual(calls, [[INDEX_URL, {signal: controller.signal}], [DAY_URL, {signal: controller.signal}]]);
});

test('C3: an already aborted request rejects without fetching', async () => {
  const {options, calls} = stub([], AbortSignal.abort());
  await assert.rejects(loadFrontsDay(REGION, DAY, options), {constructor: DOMException, name: 'AbortError'});
  assert.deepEqual(calls, []);
});
