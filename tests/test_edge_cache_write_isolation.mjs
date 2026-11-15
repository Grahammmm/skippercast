// A cache write is optional: a put() or waitUntil() that throws synchronously
// must not replace a response the producer already made. Producer and onMiss
// failures are application failures and keep their exact semantics.
import test from 'node:test';
import assert from 'node:assert/strict';
import {cacheKey, cached, store} from '../server/edge-cache.ts';

const key = (path = '/api/x') => cacheKey('https://skippercast.com' + path);
const ok = (body = 'kept') => new Response(body, {status: 200, headers: {'Content-Type': 'text/plain', 'X-App': 'app'}});

// Runs fn with a stand-in default cache; restores globals, blocks the network
// and records warnings and unhandled rejections.
async function withEnv(cache, fn) {
  const originalCaches = globalThis.caches, originalFetch = globalThis.fetch, originalWarn = console.warn;
  const warnings = [], unhandled = [];
  const onUnhandled = reason => unhandled.push(reason);
  process.on('unhandledRejection', onUnhandled);
  globalThis.caches = cache ? {default: cache} : undefined;
  globalThis.fetch = () => { throw new Error('network blocked'); };
  console.warn = (...args) => warnings.push(args);
  try {
    const result = await fn({warnings});
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(unhandled, [], 'no unhandled rejection');
    return result;
  } finally {
    process.off('unhandledRejection', onUnhandled);
    globalThis.caches = originalCaches; globalThis.fetch = originalFetch; console.warn = originalWarn;
  }
}
const miss = async () => null;
const producer = (log, response = () => ok()) => async () => { log.n++; return {response: response()}; };

function expectKept(res, body = 'kept') {
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('X-SC-Cache'), 'miss');
  assert.equal(res.headers.get('X-App'), 'app');
  assert.equal(res.headers.get('Content-Type'), 'text/plain');
  return res.text().then(text => assert.equal(text, body));
}

test('sync_put_keeps_produced_response', async () => {
  const cache = {puts: 0, async match() { return undefined; }, put() { this.puts++; throw new Error('synthetic put'); }};
  await withEnv(cache, async ({warnings}) => {
    const log = {n: 0};
    const res = await cached(key(), {waitUntil() { throw new Error('unused'); }}, producer(log));
    await expectKept(res);
    assert.equal(log.n, 1);
    assert.equal(cache.puts, 1, 'no retry put');
    assert.equal(warnings.length >= 1, true);
    assert.ok(!JSON.stringify(warnings).includes('synthetic'), 'warning is content-free');
    // Direct store resolution, with and without a context.
    await store(cache, key(), ok(), undefined);
    await store(cache, key(), ok(), {waitUntil() {}});
    assert.equal(cache.puts, 3);
  });
});

for (const outcome of ['resolve', 'reject']) {
  test(`wait_until_throw_awaits_existing_guarded_write (${outcome})`, async () => {
    let finish, started = 0, registrations = 0;
    const cache = {async match() { return undefined; }, put() { started++; return new Promise((res, rej) => { finish = outcome === 'resolve' ? res : rej; }); }};
    await withEnv(cache, async () => {
      const ctx = {waitUntil() { registrations++; throw new Error('synthetic registration'); }};
      let settled = false;
      const pending = cached(key(), ctx, producer({n: 0})).then(r => { settled = true; return r; });
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(settled, false, 'existing write is awaited');
      finish(outcome === 'reject' ? new Error('synthetic put') : undefined);
      await expectKept(await pending);
      assert.equal(started, 1);
      assert.equal(registrations, 1);
    });
  });
}

test('absent_or_throwing_registration_access', async () => {
  let puts = 0;
  const cache = {async match() { return undefined; }, async put() { puts++; }};
  await withEnv(cache, async () => {
    await expectKept(await cached(key(), undefined, producer({n: 0})));
    await expectKept(await cached(key(), {}, producer({n: 0})));
    const getterCtx = {get waitUntil() { throw new Error('synthetic getter'); }};
    await expectKept(await cached(key(), getterCtx, producer({n: 0})));
    assert.equal(puts, 3);
    // A healthy context receives one handled promise and keeps its receiver.
    const seen = [];
    const ctx = {waitUntil(p) { assert.equal(this, ctx); seen.push(p); }};
    await expectKept(await cached(key(), ctx, producer({n: 0})));
    assert.equal(seen.length, 1);
    assert.ok(seen[0] instanceof Promise);
    await seen[0];
    assert.equal(puts, 4);
  });
});

test('async_put_rejection_and_healthy_write', async () => {
  const failing = {async match() { return undefined; }, async put() { throw new Error('synthetic async'); }};
  await withEnv(failing, async () => {
    await expectKept(await cached(key(), undefined, producer({n: 0})));
  });
  const entries = new Map();
  const healthy = {
    async match(request) { const hit = entries.get(request.url); return hit ? new Response(hit.clone().body, hit) : undefined; },
    async put(request, response) { entries.set(request.url, new Response(await response.arrayBuffer(), response)); },
  };
  await withEnv(healthy, async () => {
    const log = {n: 0}; let gated = 0;
    const gate = async () => { gated++; return null; };
    const first = await cached(key(), undefined, producer(log), gate);
    await expectKept(first);
    assert.equal(entries.size, 1);
    const second = await cached(key(), undefined, producer(log), gate);
    assert.equal(second.headers.get('X-SC-Cache'), 'hit');
    assert.equal(await second.text(), 'kept');
    assert.equal(log.n, 1);
    assert.equal(gated, 1);
  });
});

test('extra_write_failure_does_not_erase_primary', async () => {
  const stored = [];
  const cache = {async match() { return undefined; }, put(request) {
    if (request.url.includes('/extra-bad')) throw new Error('synthetic sibling');
    stored.push(request.url); return Promise.resolve();
  }};
  await withEnv(cache, async () => {
    const log = {n: 0};
    const res = await cached(key('/api/primary'), undefined, async () => {
      log.n++;
      return {response: ok(), extra: [
        [key('/extra-bad'), ok('bad')],
        [key('/extra-teapot'), new Response('no', {status: 404})],
        [key('/extra-good'), ok('good')],
      ]};
    });
    await expectKept(res);
    assert.equal(log.n, 1);
    assert.deepEqual(stored.map(u => new URL(u).pathname), ['/api/primary', '/extra-good']);
  });
});

test('application_failures_are_not_cache_failures', async () => {
  let puts = 0;
  const cache = {async match() { return undefined; }, async put() { puts++; }};
  await withEnv(cache, async () => {
    const sentinel = new Error('producer sentinel');
    await assert.rejects(cached(key(), undefined, async () => { throw sentinel; }), e => e === sentinel);
    const refusal = new Response('slow down', {status: 429});
    const log = {n: 0};
    const refused = await cached(key(), undefined, producer(log), async () => refusal);
    assert.equal(refused, refusal);
    assert.equal(log.n, 0);
    const notFound = await cached(key(), undefined, async () => ({response: new Response('gone', {status: 404})}));
    assert.equal(notFound.status, 404);
    assert.equal(notFound.headers.get('X-SC-Cache'), 'miss');
    assert.equal(puts, 0);
  });
  await withEnv(null, async () => {
    const log = {n: 0};
    await expectKept(await cached(key(), undefined, producer(log)));
    assert.equal(log.n, 1);
  });
});
