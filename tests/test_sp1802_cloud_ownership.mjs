// Full-controller synthetic tests. ?guard is a pre-import network sentinel for
// this suite and the unchanged compatibility suite; no product module is sliced.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import dgram from 'node:dgram';

const key = Symbol.for('sp1802.offline');
if (!globalThis[key]) {
  const restores = [];
  const refuse = () => { throw new Error('SP1802_EXTERNAL_NETWORK_FORBIDDEN'); };
  for (const [object, name] of [[globalThis, 'fetch'], [globalThis, 'WebSocket'],
    [net, 'connect'], [net, 'createConnection'], [net.Socket.prototype, 'connect'],
    [tls, 'connect'], [http, 'request'], [http, 'get'], [https, 'request'], [https, 'get'], [dgram, 'createSocket']]) {
    const descriptor = Object.getOwnPropertyDescriptor(object, name);
    Object.defineProperty(object, name, {configurable: true, writable: true, value: refuse});
    restores.push(() => descriptor ? Object.defineProperty(object, name, descriptor) : delete object[name]);
  }
  syncBuiltinESMExports();
  globalThis[key] = () => { for (const restore of restores.reverse()) restore(); syncBuiltinESMExports(); delete globalThis[key]; };
}

if (!new URL(import.meta.url).searchParams.has('guard')) {
  const {default: test, after} = await import('node:test');
  after(() => globalThis[key]?.());
  const {signal} = await import('@preact/signals');
  const {createClouds, cloudLayerIds, cloudHeld, cloudStamp, frameId, CLOUD_OPACITY, HOLD_MS, FRAME_MS} = await import('../web/map/clouds.ts');
  const {configureStore, syncFromURL, setParams} = await import('../web/state.ts');
  const {railNotes} = await import('../web/map/layers.ts');
  const {unavailable} = await import('../web/map/chart.ts');
  const fixture = JSON.parse(readFileSync(new URL('./fixtures/sp1802_cloud_ownership/index.json', import.meta.url), 'utf8'));
  const expectedIds = fixture.availableTimes.map(frameId);
  const NOW = Date.parse('2026-10-02T03:00:00Z');
  const flush = () => new Promise(resolve => setImmediate(resolve));
  const unrelated = {sources: {other: {type: 'geojson', data: {type: 'FeatureCollection', features: []}}}, layers: []};

  function recording(name, log) {
    const overlays = new Map([['unrelated', unrelated]]), opacity = new Map();
    return {name, overlays, opacity,
      setOverlay(id, overlay, before) {
        assert.equal(id, 'clouds');
        log.push({engine: name, id, overlay, before});
        if (overlay) overlays.set(id, overlay); else overlays.delete(id);
        opacity.clear();
      },
      setRasterOpacity(id, value) {
        assert.ok(overlays.get('clouds')?.layers.some(layer => layer.id === id), 'opacity only on an owned layer');
        opacity.set(id, value);
      },
    };
  }
  function watched(state) {
    const listeners = new Set();
    return Object.assign(state, {listeners, addEventListener(_type, fn) { listeners.add(fn); },
      removeEventListener(_type, fn) { listeners.delete(fn); }, fire() { for (const fn of [...listeners]) fn(); }});
  }
  async function setup(t, {pending = false} = {}) {
    const saved = new Map(['location', 'history', 'dispatchEvent'].map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
    const page = 'https://fixture.invalid/map?region=morro-bay&layers=clouds';
    globalThis.location = {href: page};
    globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
    globalThis.dispatchEvent = () => true;
    configureStore({v2: true, storage: null}); syncFromURL(page);
    cloudHeld.value = false; unavailable.value = [];
    let serial = 0, time = NOW, resolveIndex;
    const timers = new Map(), fetched = [], log = [];
    const schedule = (fn, ms, interval) => { const id = ++serial; timers.set(id, {fn, ms, interval}); return id; };
    t.mock.method(globalThis, 'setTimeout', (fn, ms) => schedule(fn, ms, false));
    t.mock.method(globalThis, 'setInterval', (fn, ms) => schedule(fn, ms, true));
    t.mock.method(globalThis, 'clearTimeout', id => timers.delete(id));
    t.mock.method(globalThis, 'clearInterval', id => timers.delete(id));
    const a = recording('A', log), b = recording('B', log), live = signal(a);
    const doc = watched({hidden: false}), motion = watched({matches: false});
    const fetchFn = url => {
      assert.equal(url, 'https://fixture.invalid/feeds/conditions/goes-times.json');
      fetched.push(url);
      const answer = {ok: true, json: async () => structuredClone(fixture)};
      return pending ? new Promise(resolve => { resolveIndex = () => resolve(answer); }) : Promise.resolve(answer);
    };
    const c = createClouds({engine: live, zone: () => 'America/Los_Angeles', page: () => page,
      now: () => new Date(time), doc, motion, fetchFn, reported: () => null});
    t.after(() => {
      c.destroy();
      cloudHeld.value = false;
      for (const [name, descriptor] of saved) descriptor ? Object.defineProperty(globalThis, name, descriptor) : delete globalThis[name];
      t.mock.restoreAll();
    });
    await flush();
    return {a, b, live, log, c, doc, motion, timers, fetched, resolve: () => resolveIndex(),
      async step(ms) {
        const entry = [...timers].find(([, timer]) => !timer.interval);
        assert.ok(entry, 'loop timer is armed'); assert.equal(entry[1].ms, ms);
        timers.delete(entry[0]); time += ms; entry[1].fn(); await flush();
      }};
  }
  function healthy(run, engine = run.a) {
    assert.deepEqual(Object.keys(engine.overlays.get('clouds').sources), expectedIds);
    assert.deepEqual(engine.overlays.get('clouds').layers.map(layer => layer.id), expectedIds);
    assert.deepEqual(cloudLayerIds(), expectedIds);
    assert.equal(run.fetched.length, 1);
    assert.equal(cloudStamp.value.at, fixture.observedAt);
  }
  const active = engine => [...engine.opacity].filter(([, opacity]) => opacity === CLOUD_OPACITY).map(([id]) => id);
  const loops = run => [...run.timers.values()].filter(timer => !timer.interval).length;
  function cleared(engine) {
    assert.equal(engine.overlays.has('clouds'), false, `${engine.name} has no residual cloud sources/layers`);
    assert.equal(engine.overlays.get('unrelated'), unrelated);
  }

  test('primary regression A1: retire A before adopting B', async t => {
    const r = await setup(t); healthy(r);
    const before = r.log.length;
    r.live.value = r.b; await flush();
    assert.equal(r.log[before]?.engine, 'A', 'SP1802_A1_RETIRED_OWNER_NOT_CLEARED');
    assert.equal(r.log[before]?.overlay, null, 'SP1802_A1_RETIRED_OWNER_NOT_CLEARED');
    assert.equal(r.log[before + 1]?.engine, 'B');
    assert.equal(r.log.length, before + 2, 'one cleanup and exactly one new draw');
    cleared(r.a); healthy(r, r.b);
  });

  test('Healthy controller draws one cloud overlay and clears all timers on destroy', async t => {
    const r = await setup(t); healthy(r);
    assert.equal(r.log.filter(call => call.overlay).length, 1);
    assert.equal(r.timers.size, 2);
    assert.equal(r.doc.listeners.size, 1); assert.equal(r.motion.listeners.size, 1);
    r.c.destroy(); assert.equal(r.timers.size, 0);
    assert.equal(r.doc.listeners.size, 0); assert.equal(r.motion.listeners.size, 0);
  });

  test('A2: A to null to B and A to B to A preserve unrelated overlays', async t => {
    const r = await setup(t); healthy(r);
    r.live.value = null; await flush(); cleared(r.a);
    assert.deepEqual(cloudLayerIds(), []); assert.equal(cloudStamp.value, null); assert.equal(loops(r), 0);
    const retired = r.log.length;
    r.live.value = null; await flush(); assert.equal(r.log.length, retired);
    r.live.value = r.b; await flush(); healthy(r, r.b);
    r.live.value = r.a; await flush(); cleared(r.b); healthy(r);
    r.live.value = r.b; await flush(); cleared(r.a); healthy(r, r.b);
    r.live.value = r.a; await flush(); cleared(r.b); healthy(r);
    assert.equal(r.a.overlays.get('unrelated'), unrelated);
  });

  test('A3: double destroy clears owner, bookkeeping, listeners and pending work', async t => {
    const r = await setup(t); healthy(r);
    r.c.destroy(); cleared(r.a);
    assert.deepEqual(cloudLayerIds(), []); assert.equal(cloudStamp.value, null); assert.equal(railNotes.value.clouds, '');
    assert.equal(r.timers.size, 0); assert.equal(r.doc.listeners.size, 0); assert.equal(r.motion.listeners.size, 0);
    const calls = r.log.length;
    r.c.destroy(); r.live.value = r.b; r.doc.fire(); r.motion.fire(); await flush();
    assert.equal(r.log.length, calls); cleared(r.b);
  });

  test('A3 pending index resolution after destroy cannot repaint', async t => {
    const r = await setup(t, {pending: true});
    assert.equal(r.fetched.length, 1); assert.equal(r.a.overlays.has('clouds'), false);
    r.c.destroy(); const calls = r.log.length;
    r.resolve(); await flush(); r.live.value = r.b; await flush();
    assert.equal(r.log.length, calls); cleared(r.a); cleared(r.b);
    assert.deepEqual(cloudLayerIds(), []); assert.equal(cloudStamp.value, null);
    assert.equal(railNotes.value.clouds, ''); assert.equal(r.timers.size, 0);
    assert.equal(r.doc.listeners.size, 0); assert.equal(r.motion.listeners.size, 0);
  });

  test('A4: real signals preserve off/on, held loop, hidden page and reduced motion', async t => {
    const r = await setup(t); healthy(r);
    assert.deepEqual(active(r.a), [expectedIds.at(-1)]);
    await r.step(HOLD_MS); assert.deepEqual(active(r.a), [expectedIds[0]]);
    await r.step(FRAME_MS); assert.deepEqual(active(r.a), [expectedIds[1]]);
    cloudHeld.value = true; assert.equal(loops(r), 0);
    const held = active(r.a); r.live.value = r.b; await flush(); cleared(r.a);
    assert.deepEqual(active(r.b), held); assert.equal(loops(r), 0);
    cloudHeld.value = false; assert.equal(loops(r), 1);
    r.doc.hidden = true; r.doc.fire(); assert.equal(r.timers.size, 0);
    r.doc.hidden = false; r.doc.fire(); assert.equal(r.timers.size, 2);
    r.motion.matches = true; r.motion.fire();
    assert.equal(loops(r), 0); assert.deepEqual(active(r.b), [expectedIds.at(-1)]); assert.equal(cloudStamp.value.canLoop, false);
    r.motion.matches = false; r.motion.fire(); assert.equal(loops(r), 1);
    setParams({layers: 'none'}); await flush(); cleared(r.b);
    assert.deepEqual(cloudLayerIds(), []); assert.equal(cloudStamp.value, null); assert.equal(railNotes.value.clouds, ''); assert.equal(r.timers.size, 0);
    setParams({layers: 'clouds'}); await flush(); healthy(r, r.b);
    assert.deepEqual(active(r.b), [expectedIds.at(-1)]); assert.equal(r.timers.size, 2);
  });
}
