// SC1407-06 (#1762 M4): dist/live-mpa.js shares one live ds582 read between concurrent callers of the exact same URL,
// and only while it is in flight: a settled read (answer or failure) is never handed to a later caller. Offline: a held
// synthetic fetch and a fake clock; no provider request.
import assert from 'node:assert/strict';
import test, {mock} from 'node:test';
import {createLiveMpaReader, readLiveMpa} from '../dist/live-mpa.js';

const URL_A = 'https://services2.arcgis.test/query?where=1%3D1&geometry=-121%2C35%2C-120%2C36&f=geojson';
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve)); };

/** A fetch whose answers the test releases: each call is recorded with a `respond(response)` / `fail(error)` handle. */
function heldFetch() {
  const calls = [];
  const fetchFn = (url, init) => new Promise((resolve, reject) => {
    const call = {url, init, respond: resolve, fail: reject};
    init?.signal?.addEventListener('abort', () => reject(init.signal.reason ?? new Error('aborted')), {once: true});
    calls.push(call);
  });
  return {calls, fetchFn};
}
/** A response whose body the test releases; `parses` counts json() calls. */
function heldBody({ok = true, status = 200} = {}) {
  const r = {ok, status, parses: 0, give: null, broken: null};
  r.json = () => { r.parses++; return new Promise((resolve, reject) => { r.give = resolve; r.broken = reject; }); };
  return r;
}

test('same URL while in flight: one request, one parse, one arrival time for every caller', async () => {
  let clock = Date.parse('2026-11-09T12:00:00Z');
  const {calls, fetchFn} = heldFetch(), read = createLiveMpaReader({fetchFn, now: () => clock});
  const first = read(URL_A), second = read(URL_A);
  assert.equal(calls.length, 1, 'one request');
  assert.equal(calls[0].url, URL_A);
  const response = heldBody(), body = {type: 'FeatureCollection', features: []};
  calls[0].respond(response);
  await settle();
  const arrived = clock;
  clock += 90_000;   // a slow body: the checked time stays when the response arrived
  response.give(body);
  const [a, b] = await Promise.all([first, second]);
  assert.equal(response.parses, 1, 'one parse');
  assert.equal(a, b, 'the same answer');
  assert.equal(a.data, body, 'the parsed body itself, not a copy');
  assert.equal(a.checkedAt, new Date(arrived).toISOString());
  assert.ok(Object.isFrozen(a));
});

test('a URL that differs in any way is its own read; equal URLs are never normalized', async () => {
  const {calls, fetchFn} = heldFetch(), read = createLiveMpaReader({fetchFn});
  const variants = [URL_A, URL_A.replace('-121', '-122'), URL_A.replace('f=geojson', 'f=json'), URL_A + '&outFields=NAME',
    'https://services2.arcgis.test/query?geometry=-121%2C35%2C-120%2C36&where=1%3D1&f=geojson'];
  const reads = variants.map(read);
  assert.equal(calls.length, variants.length, 'no two different URLs share');
  assert.deepEqual(calls.map(c => c.url), variants);
  for (const c of calls) c.respond({ok: true, status: 200, json: async () => ({url: c.url})});
  const answers = await Promise.all(reads);
  assert.deepEqual(answers.map(a => a.data.url), variants);
});

test('a read after the first answer asks again, with its own time', async () => {
  let clock = 1_000_000;
  const {calls, fetchFn} = heldFetch(), read = createLiveMpaReader({fetchFn, now: () => clock});
  const first = read(URL_A);
  calls[0].respond({ok: true, status: 200, json: async () => ({n: 1})});
  const a = await first;
  clock += 60_000;
  const later = read(URL_A);
  assert.equal(calls.length, 2, 'a refresh after the answer is a new request');
  calls[1].respond({ok: true, status: 200, json: async () => ({n: 2})});
  const b = await later;
  assert.notEqual(a, b);
  assert.deepEqual([a.data.n, b.data.n], [1, 2]);
  assert.equal(b.checkedAt, new Date(clock).toISOString());
  assert.ok(Date.parse(a.checkedAt) < Date.parse(b.checkedAt), 'the old answer keeps its own time');
});

test('a read started in the same turn the answer settles never receives that answer', async () => {
  const {calls, fetchFn} = heldFetch(), read = createLiveMpaReader({fetchFn});
  const first = read(URL_A);
  let again;
  // Reacting to the settled answer as early as possible: that reaction's read must still go to the network.
  first.then(() => { again = read(URL_A); });
  calls[0].respond({ok: true, status: 200, json: async () => ({n: 1})});
  await first; await settle();
  assert.equal(calls.length, 2);
  calls[1].respond({ok: true, status: 200, json: async () => ({n: 2})});
  assert.equal((await again).data.n, 2);
});

test('every failure rejects every caller, and the next read asks again', async t => {
  const cases = {
    'HTTP error': c => c.respond({ok: false, status: 503, json: async () => ({})}),
    'transport error': c => c.fail(new TypeError('network down')),
    'broken JSON': c => c.respond({ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected end of JSON input'); }}),
    'fetch throwing at once': null,
  };
  for (const [name, fail] of Object.entries(cases)) {
    await t.test(name, async () => {
      const held = heldFetch();
      let thrown = 0;
      const fetchFn = fail ? held.fetchFn : (url, init) => { if (thrown++ === 0) throw new TypeError('bad request'); return held.fetchFn(url, init); };
      const read = createLiveMpaReader({fetchFn});
      const first = read(URL_A), second = fail ? read(URL_A) : first;
      if (fail) { assert.equal(held.calls.length, 1); fail(held.calls[0]); }
      await assert.rejects(first);
      await assert.rejects(second);
      const retry = read(URL_A);
      assert.equal(held.calls.length, fail ? 2 : 1, 'a failed read is not kept');
      held.calls.at(-1).respond({ok: true, status: 200, json: async () => ({ok: 1})});
      assert.equal((await retry).data.ok, 1);
    });
  }
});

test('a read that never answers is abandoned after 20 seconds, its timer cleared on every settlement', async () => {
  mock.timers.enable({apis: ['setTimeout']});
  try {
    const {calls, fetchFn} = heldFetch(), read = createLiveMpaReader({fetchFn});
    const first = read(URL_A), second = read(URL_A);
    mock.timers.tick(19_999);
    assert.equal(calls[0].init.signal.aborted, false);
    mock.timers.tick(1);
    assert.equal(calls[0].init.signal.aborted, true, 'the shared read is aborted at 20 s');
    await assert.rejects(first); await assert.rejects(second);
    const retry = read(URL_A);
    assert.equal(calls.length, 2, 'a timed-out read is not kept');
    calls[1].respond({ok: true, status: 200, json: async () => ({})});
    await retry;
    mock.timers.tick(20_000);
    assert.equal(calls[1].init.signal.aborted, false, 'a settled read leaves no live timer');
  } finally { mock.timers.reset(); }
});

test('a caller cannot cancel the shared read for the others', async () => {
  const {calls, fetchFn} = heldFetch(), read = createLiveMpaReader({fetchFn});
  read(URL_A); read(URL_A);
  assert.ok(calls[0].init.signal instanceof AbortSignal, 'the reader owns the signal');
  assert.deepEqual(Object.keys(calls[0].init), ['signal'], 'no caller option reaches the request');
  calls[0].respond({ok: true, status: 200, json: async () => ({})});
  await settle();
});

test('the page reader forwards to the global fetch at call time', async () => {
  const saved = globalThis.fetch, seen = [];
  globalThis.fetch = async url => { seen.push(url); return {ok: true, status: 200, json: async () => ({page: true})}; };
  try {
    const [a, b] = await Promise.all([readLiveMpa(URL_A), readLiveMpa(URL_A)]);
    assert.equal(seen.length, 1);
    assert.equal(a, b);
    assert.equal((await readLiveMpa(URL_A)).data.page, true);
    assert.equal(seen.length, 2, 'nothing kept after the answer');
  } finally { globalThis.fetch = saved; }
});
