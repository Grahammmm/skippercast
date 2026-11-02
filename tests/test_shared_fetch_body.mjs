// RF2030-10: web/shared-fetch.ts keeps a shared static read only once its body
// has arrived whole, so a body that breaks mid-transfer costs one failed read
// and the next caller makes a fresh request. Runs by type stripping.
import assert from 'node:assert/strict';
import test from 'node:test';
import {shareStatic} from '../web/shared-fetch.ts';

const BASE = 'https://s.test/map?region=morro-bay';
const FILE = 'regions/morro-bay/region.json';
const enc = new TextEncoder();

/** A 200 whose body sends `{"id":` and then errors (a dropped stream). */
function broken(status = 200) {
  let sent = false;
  return new Response(new ReadableStream({
    pull(c) { if (!sent) { sent = true; c.enqueue(enc.encode('{"id":')); } else c.error(new TypeError('body stream dropped')); },
  }, {highWaterMark: 0}), {status, headers: {'content-type': 'application/json'}});
}
const whole = (status = 200) => new Response(JSON.stringify({id: 'morro-bay'}), {status, headers: {'content-type': 'application/json'}});

/** A fetch double answering each call with the next queued response maker. */
function queued(...makers) {
  const calls = [];
  const fetchFn = async (url, init = {}) => { calls.push([url, init]); return (makers[calls.length - 1] ?? makers.at(-1))(); };
  return {calls, fetchFn};
}

async function withPage(fn) {
  globalThis.location = {href: BASE};
  try { await fn(); } finally { delete globalThis.location; }
}

test('a 200 whose body fails after one chunk rejects and is asked again; the whole retry is read', () => withPage(async () => {
  const {calls, fetchFn} = queued(broken, whole);
  const shared = shareStatic(fetchFn);
  await assert.rejects(shared(FILE), /body stream dropped/);
  const again = await shared(FILE);
  assert.equal(calls.length, 2, 'a fresh request after the body failure');
  assert.deepEqual(await again.json(), {id: 'morro-bay'});
}));

test('concurrent callers during a body failure both reject; the next call makes one fresh request', () => withPage(async () => {
  const {calls, fetchFn} = queued(broken, whole);
  const shared = shareStatic(fetchFn);
  const results = await Promise.allSettled([shared(FILE), shared(FILE)]);
  assert.deepEqual(results.map(r => r.status), ['rejected', 'rejected']);
  assert.equal(calls.length, 1, 'the concurrent callers shared one request');
  const [a, b] = await Promise.all([shared(FILE), shared(FILE)]);
  assert.equal(calls.length, 2, 'one fresh request, not two');
  assert.deepEqual(await a.json(), {id: 'morro-bay'});
  assert.deepEqual(await b.json(), {id: 'morro-bay'});
}));

test('a whole 200 is one request for three sequential callers, each reading its own JSON', () => withPage(async () => {
  const {calls, fetchFn} = queued(whole, broken);
  const shared = shareStatic(fetchFn);
  for (let i = 0; i < 3; i++) assert.deepEqual(await (await shared(FILE)).json(), {id: 'morro-bay'});
  assert.equal(calls.length, 1);
}));

test('a 404 is returned without forcing its body and is forgotten', () => withPage(async () => {
  const {calls, fetchFn} = queued(() => broken(404), whole);
  const shared = shareStatic(fetchFn);
  const missing = await shared(FILE);
  assert.equal(missing.status, 404, 'returned to the caller, not rejected by a body read');
  assert.equal(missing.ok, false);
  assert.deepEqual(await (await shared(FILE)).json(), {id: 'morro-bay'});
  assert.equal(calls.length, 2, 'the 404 was forgotten');
}));

test('a test double without clone or body is shared as is, with no body check', () => withPage(async () => {
  const double = {ok: true, json: async () => ({id: 'double'})};
  const {calls, fetchFn} = queued(() => double);
  const shared = shareStatic(fetchFn);
  assert.equal(await shared(FILE), double);
  assert.equal(await shared(FILE), double);
  assert.equal(calls.length, 1);
}));

test('a caller aborting while the body arrives rejects alone; the read completes and is reused', () => withPage(async () => {
  let finish;
  const body = new ReadableStream({start(c) { c.enqueue(enc.encode('{"id":')); finish = () => { c.enqueue(enc.encode('"morro-bay"}')); c.close(); }; }});
  const {calls, fetchFn} = queued(() => new Response(body, {status: 200}), broken);
  const shared = shareStatic(fetchFn);
  const ctl = new AbortController();
  const early = shared(FILE, {signal: ctl.signal});
  await new Promise(r => setTimeout(r, 10));
  ctl.abort(new Error('caller gave up'));
  await assert.rejects(early, /caller gave up/);
  finish();
  assert.deepEqual(await (await shared(FILE)).json(), {id: 'morro-bay'});
  assert.equal(calls.length, 1, 'no second request');
  assert.equal(calls[0][1].signal, undefined, 'the shared request carries no caller signal');
}));

test('pass-through reads are never stored or body-checked', () => withPage(async () => {
  for (const [url, init] of [['/api/daily?region=morro-bay', {}], ['https://other.test/data/atlas.json', {}], [FILE, {cache: 'no-store'}]]) {
    const made = [];
    const shared = shareStatic(async () => { const r = broken(); made.push(r); return r; });
    const first = await shared(url, init);
    const second = await shared(url, init);
    assert.equal(made.length, 2, `${url} is not stored`);
    assert.equal(first, made[0], `${url} is the response itself, not a clone`);
    assert.equal(second.bodyUsed, false, `${url} body untouched by the wrapper`);
    await assert.rejects(first.text(), /body stream dropped/, `${url} body failure is the caller's to see`);
  }
}));
