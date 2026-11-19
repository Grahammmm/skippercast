import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {Hono} from 'hono';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: ['https://worker.test']};
const {costCeiling, readsToday} = await import('../server/cost-ceiling.ts');
const {coastData} = await import('../server/routes/coast.ts');

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const path = '/data/coast-wide/f03-05.bin';

// Contract: concurrent ranges share one metered verification only within a
// binding. Keying by each request proxy duplicates the whole read; keying by
// digest alone lets a different bucket borrow proof for bytes it never verified.
test('cold coast ranges share verification across requests, not across bindings', {timeout: 5000}, async t => {
  let bridgeCalls = 0;
  t.mock.method(globalThis, 'fetch', async () => { bridgeCalls++; throw Error('Unexpected bridge request'); });
  const app = new Hono();
  app.use('*', async (c, next) => { c.set('path', c.req.path); await next(); });
  app.use('*', costCeiling);
  app.route('/', coastData);
  const data = Uint8Array.of(21, 37, 49, 53, 61, 77);
  const digest = sha(data), key = 'coast/objects/' + digest;
  const manifest = JSON.stringify({schemaVersion: 1, kind: 'skippercast-coast-assets', groups: ['terrain'],
    objects: {[path]: {sha256: digest, bytes: data.length, contentType: 'application/octet-stream'}}});
  const releaseId = sha(manifest);
  const pointer = JSON.stringify({schemaVersion: 1, status: 'ready', releaseId});
  const entered = Promise.withResolvers(), hold = Promise.withResolvers();
  const calls = [], jobs = [], retained = [];
  function bucket(bytes, pause) {
    return {async get(name, options) {
      calls.push({bucket: this, name, options});
      if (name === 'coast/current.json') return {size: pointer.length, body: new Response(pointer).body};
      if (name === `coast/releases/${releaseId}.json`) return {size: manifest.length, body: new Response(manifest).body};
      assert.equal(name, key);
      if (pause) { entered.resolve(); await hold.promise; }
      const range = options?.range;
      return {size: bytes.length, etag: 'same-etag', body: new Response(range ? bytes.slice(range.offset, range.offset + range.length) : bytes).body};
    }};
  }
  const good = bucket(data, true), corrupt = bucket(data.map(v => v ^ 1), false);
  const send = (binding, start, signal, asset = path) => {
    const req = new Request('https://worker.test/coast-data' + asset, {headers: {Range: `bytes=${start}-${start + 1}`}, signal});
    const job = app.fetch(req, {FEEDS: binding}, {waitUntil: promise => retained.push(promise)});
    jobs.push(job);
    return job;
  };
  t.after(async () => { hold.resolve(); await Promise.allSettled([...jobs, ...retained]); });
  const before = readsToday();
  // Warm only the manifest. Pointer reads for the overlapping requests then
  // finish in microtasks while the first whole-object read is still held.
  assert.equal((await send(good, 0, undefined, '/data/coast-wide/f03-absent.bin')).status, 404);
  const abort = new AbortController();
  const leader = send(good, 0, abort.signal);
  await entered.promise;
  const parts = [send(good, 0), send(good, 2)];
  const denied = send(corrupt, 2);
  await new Promise(resolve => setImmediate(resolve));
  const fullReads = binding => calls.filter(c => c.bucket === binding && c.name === key && !c.options).length;
  assert.equal(fullReads(good), 1, 'separate request proxies must join the held whole-object read');
  assert.equal(fullReads(corrupt), 1, 'a different binding must verify its own bytes');
  assert.equal((await denied).status, 503, 'corruption in the other binding fails before the good read is released');
  assert.equal(retained.length, 2, 'only the two initiating requests retain cold work for joiners');
  abort.abort();
  assert.equal((await leader).status, 503, 'owner abort remains request-local');
  hold.resolve();
  for (const [i, response] of (await Promise.all(parts)).entries()) {
    assert.equal(response.status, 206);
    assert.equal(response.headers.get('Content-Range'), `bytes ${2 * i}-${2 * i + 1}/${data.length}`);
    assert.deepEqual(new Uint8Array(await response.arrayBuffer()), data.slice(2 * i, 2 * i + 2));
  }
  const warm = await send(good, 4);
  assert.equal(warm.status, 206);
  assert.deepEqual(new Uint8Array(await warm.arrayBuffer()), data.slice(4));
  assert.ok(calls.some(c => c.bucket === good && c.name === key && c.options?.onlyIf?.etagMatches === 'same-etag'));
  assert.equal(fullReads(good), 1, 'a warm range uses the verified etag, not another whole read');
  assert.equal((await send(corrupt, 4)).status, 503, 'a matching etag in a different binding is not proof');
  assert.equal(readsToday() - before, calls.length, 'every physical bucket read is metered');
  assert.equal(bridgeCalls, 0);
});
