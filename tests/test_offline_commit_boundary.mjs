// SCP3-07: once savePack has written PACK_META, tidying older packs (enumeration, deletion) and analytics are best-effort and
// can never roll back the committed pack; a failure before the commit still removes only the partial candidate.
// The real dist/offline-pack.js savePack runs; Cache Storage, fetch and the page are in-memory stubs, restored after each run.
import assert from 'node:assert/strict';
import test from 'node:test';
import {getRegion} from '../dist/region.js';
import {savePack} from '../dist/offline-pack.js';
import {PACK_META} from '../dist/offline-core.js';

const ORIGIN = 'https://s.test', ID = getRegion().id, OLD = [`sc-pack-${ID}-1`, `sc-pack-${ID}-2`], OTHER = 'sc-pack-other-region-1';

class FakeCache {
  constructor() { this.map = new Map(); }
  async put(k, r) { this.map.set(String(k?.url ?? k), {bytes: Buffer.from(await r.arrayBuffer()), headers: [...r.headers]}); }
  async match(k) { const e = this.map.get(String(k?.url ?? k)); return e && new Response(e.bytes, {headers: e.headers}); }
  async keys() { return [...this.map.keys()].map(url => ({url})); }
}
class FakeCaches {
  constructor() { this.map = new Map(); this.failDelete = () => false; this.failKeys = false; }
  async open(name) { if (!this.map.has(name)) this.map.set(name, new FakeCache()); return this.map.get(name); }
  async keys() { if (this.failKeys) throw new Error('keys failed'); return [...this.map.keys()]; }
  async has(name) { return this.map.has(name); }
  async delete(name) { if (this.failDelete(name)) throw new Error(`delete failed: ${name}`); return this.map.delete(name); }
}

/** One savePack run over in-memory old packs. `setup(caches, ctl)` adjusts failures; `regionOk: false` makes the region config 404. */
async function run({setup, regionOk = true, abortOnFetch = false} = {}) {
  const names = ['caches', 'location', 'document', 'fetch', 'window', 'navigator', 'addEventListener'];
  const saved = Object.fromEntries(names.map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  const set = (k, value) => Object.defineProperty(globalThis, k, {value, configurable: true, writable: true});
  const caches = new FakeCaches(), controller = new AbortController(), ctl = {committed: false};
  for (const n of [...OLD, OTHER]) await (await caches.open(n)).put(PACK_META, new Response('{"old":true}'));
  const page = new URL(ORIGIN + '/map');
  set('caches', caches); set('location', page);
  set('document', {getElementById: () => null, querySelector: () => null, addEventListener() {}});
  set('fetch', async input => {
    const url = new URL(String(input?.url ?? input), ORIGIN + '/').href;
    if (abortOnFetch) controller.abort();
    if (url === ORIGIN + '/regions/index.json') return Response.json({regions: [{id: ID, config: `regions/${ID}/region.json`}]});
    if (url === `${ORIGIN}/regions/${ID}/region.json` && regionOk) return Response.json({id: ID});
    return new Response('no', {status: 404});
  });
  setup?.(caches, ctl, set);
  try {
    const outcome = await savePack({signal: controller.signal}).then(meta => ({meta}), error => ({error}));
    return {...outcome, caches, names: [...caches.map.keys()], fresh: [...caches.map.keys()].filter(n => ![...OLD, OTHER].includes(n))};
  } finally {
    for (const k of names) if (saved[k]) Object.defineProperty(globalThis, k, saved[k]); else Reflect.deleteProperty(globalThis, k);
  }
}
const committed = async (r, name) => (await (await r.caches.map.get(name).match(PACK_META)).json()).region_id;

test('an older pack that cannot be deleted after the commit leaves the new pack and its metadata; save resolves', async () => {
  const r = await run({setup: c => { c.failDelete = n => n === OLD[0]; }});
  assert.equal(r.error, undefined, String(r.error));
  assert.equal(r.fresh.length, 1, 'the new pack stays');
  assert.equal(await committed(r, r.fresh[0]), ID, 'its PACK_META was committed');
  assert.equal(r.meta.region_id, ID);
  assert.ok(r.names.includes(OLD[0]), 'the undeletable old pack is simply left');
  assert.ok(!r.names.includes(OLD[1]), 'the other old pack of the region is still tidied');
  assert.ok(r.names.includes(OTHER), 'another region is never touched');
});

test('one old pack deleted, then the second deletion rejects: the committed new pack survives', async () => {
  const r = await run({setup: c => { c.failDelete = n => n === OLD[1]; }});
  assert.equal(r.error, undefined, String(r.error));
  assert.equal(r.fresh.length, 1);
  assert.ok(!r.names.includes(OLD[0]), 'the first old pack was deleted');
  assert.ok(r.names.includes(OLD[1]) && r.names.includes(r.fresh[0]));
});

test('cache-key enumeration rejecting after the commit does not delete the new pack', async () => {
  const r = await run({setup: c => { c.failKeys = true; }});
  assert.equal(r.error, undefined, String(r.error));
  assert.equal(r.fresh.length, 1);
  assert.deepEqual(OLD.filter(n => !r.names.includes(n)), [], 'nothing was tidied');
});

test('analytics throwing after the commit does not delete the new pack', async () => {
  const {initTelemetry} = await import('../web/telemetry.ts');
  const r = await run({setup: (c, ctl, set) => {
    set('window', {}); set('navigator', {sendBeacon: () => true}); set('addEventListener', () => {});
    // track() reads location.href for the visit source: make that read throw once tracking starts.
    const page = globalThis.location;
    set('location', {origin: page.origin, get href() { if (ctl.committed) throw new Error('analytics failed'); return page.href; }});
    assert.ok(initTelemetry(), 'telemetry started');
    const keys = c.keys.bind(c);
    c.keys = async () => { ctl.committed = true; return keys(); };
  }});
  assert.equal(r.error, undefined, String(r.error));
  assert.equal(r.fresh.length, 1);
  assert.ok(r.names.includes(OTHER));
});

test('a failure before the commit removes only the partial candidate; previous packs stay', async () => {
  for (const options of [{regionOk: false}, {abortOnFetch: true}]) {
    const r = await run(options);
    assert.ok(r.error, 'save rejects');
    assert.deepEqual(r.names.sort(), [...OLD, OTHER].sort(), 'only the old packs remain');
  }
});
