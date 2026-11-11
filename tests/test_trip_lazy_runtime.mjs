// SC1407-10: web/trip.ts is the small module the first screen imports; the planner, pack and coastal implementation
// (web/trip-runtime.ts) arrives by its one dynamic import on first actual use. These cases drive the real facade, each in
// its own module instance (an import query), with a stand-in implementation whose arrival the test holds or fails, and
// entirely synthetic browser globals (no network, no cache, no worker).
import assert from 'node:assert/strict';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {region} from '../web/state.ts';

const win = new EventTarget(), doc = new EventTarget(), store = new Map();
const env = {reloads: 0, timers: [], hash: ''};
Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k)}});
Object.defineProperty(globalThis, 'location', {configurable: true, value: {
  get hash() { return env.hash; }, get href() { return `https://fixture.test/map${env.hash}`; }, origin: 'https://fixture.test', reload() { env.reloads++; }}});
Object.defineProperty(globalThis, 'document', {configurable: true, value: doc});
globalThis.addEventListener = win.addEventListener.bind(win);
globalThis.removeEventListener = win.removeEventListener.bind(win);

const deferred = () => { let ok, no; const p = new Promise((a, b) => { ok = a; no = b; }); return {p, ok, no}; };
const tick = () => new Promise(r => setImmediate(r));
let instance = 0;

/**
 * A fresh facade whose implementation is a stand-in: `arrive` resolves or fails the pending import, `log` records each
 * operation once, `ctxs` every context the facade made (one per instance). `startPlanner` reads the screen through the context.
 */
async function facade() {
  const trip = await import(`../web/trip.ts?lazy=${++instance}`);
  const s = {trip, loads: 0, ctxs: [], log: [], pending: null, screens: [], models: []};
  const runtimeModule = {createTripRuntime(ctx) {
    s.ctxs.push(ctx);
    return {
      async startPlanner(id) {
        const loaded = await ctx.loadProtectedScreen(id);
        if (loaded.state !== 'loaded') throw new Error('protected-area check unavailable');
        s.screens.push(loaded.screen); s.log.push(`start:${id}`);
        const ids = [];
        const model = {disposed: false, dispose() { model.disposed = true; },
          add(x) { ids.push(x); s.log.push(`add:${x}`); localStorage.setItem(trip.draftKey(id), JSON.stringify({ids})); },
          review(x) { s.log.push(`review:${x}`); }, open() {},
          addPlace(p) { const pid = trip.placeTripId(p.id); s.log.push(`place:${p.name}`); this.add(pid); return pid; }};
        s.models.push(model);
        return {model, View: () => null};
      },
      ranked(detail) { s.log.push(`ranked:${detail?.id ?? 'none'}`); },
      drawRanked() { s.log.push('draw'); },
      async recheckRanked() { s.log.push('recheck'); },
      async listPacks() { s.log.push('list'); if (s.listFails) throw new Error('cache locked'); return [{cache: 'sc-pack-x', meta: {region_id: 'morro-bay'}}]; },
      async savePack(id, signal) { s.log.push(`save:${id}:${ctx.sessionStart > 0}`); return {region_id: id}; },
      async readCoastal() { s.log.push('read'); return null; },
      async canSaveCoastal() { return true; },
      async saveCoastal() { s.log.push('coastal-save'); return {}; },
      async deleteCoastal() { return true; },
    };
  }};
  trip.runtimeSource.load = () => { s.loads++; s.pending = deferred(); return s.pending.p; };
  s.arrive = async () => { s.pending.ok(runtimeModule); await tick(); };
  s.fail = async () => { s.pending.no(new TypeError('Failed to fetch dynamically imported module')); await tick(); };
  /** The brief's screen: an injected init so nothing is fetched. */
  s.screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, refresh: async () => {}};
  s.inits = 0;
  s.brief = (id = 'morro-bay', init = async () => { s.inits++; return s.screen; }) => trip.loadProtectedScreen(id, init);
  /** startTrip with the timer captured; `stop` undoes it. */
  s.start = () => {
    const saved = globalThis.setInterval;
    globalThis.setInterval = f => { env.timers.push(f); return 0; };
    try { s.stop = trip.startTrip(); } finally { globalThis.setInterval = saved; }
  };
  return s;
}
const reset = (hash = '', id = 'morro-bay') => { env.hash = hash; env.timers.length = 0; env.reloads = 0; store.clear(); region.value = id; };

test('normal_map_stays_light_after_effects_and_timers', async () => {
  for (const id of ['morro-bay', null]) {
    reset('', id);
    const s = await facade();
    let keys = 0;
    globalThis.caches = {keys: async () => { keys++; return ['sc-pack-morro-bay']; }};
    try {
      s.start();
      await tick();
      doc.dispatchEvent(new Event('skippercast:boundaries'));
      for (const f of env.timers) f();
      region.value = id ? 'cambria-san-simeon' : 'morro-bay';
      region.value = id;
      win.dispatchEvent(new Event('storage'));
      await s.brief('morro-bay');
      await tick();
      assert.equal(keys, 1, 'saved-cache detection still runs');
      assert.equal(env.timers.length, 1, 'one recheck timer');
      assert.equal(s.loads, 0, `no implementation import on a plain /map (region ${id})`);
      assert.equal(s.trip.tripOpen.value, false);
      assert.ok(isDeepStrictEqual(s.log, []), 'no runtime work ran');
    } finally { s.stop(); delete globalThis.caches; }
  }
});

test('export_waits_for_region_and_opens_existing_dialog', async () => {
  // Startup #export with a region: the shell opens at once and the planner fills it when the implementation arrives.
  reset('#export');
  const s = await facade();
  s.brief();
  s.start();
  assert.equal(s.trip.tripOpen.value, true, 'the dialog opens before the implementation arrives');
  assert.equal(s.trip.tripReady.value, false);
  await tick();
  assert.equal(s.loads, 1);
  await s.arrive();
  assert.equal(s.trip.tripReady.value, true);
  assert.equal(s.trip.plannerView.value?.model, s.models[0]);
  assert.ok(isDeepStrictEqual(s.log, ['start:morro-bay']));
  s.stop();

  // Regionless /map#export (the app shortcut) waits without an empty dialog until home resolution sets the region.
  reset('#export', null);
  const r = await facade();
  r.start();
  await tick();
  assert.equal(r.trip.tripOpen.value, false);
  assert.equal(r.loads, 0, 'no import before a region');
  r.brief('morro-bay');
  region.value = 'morro-bay';
  assert.equal(r.trip.tripOpen.value, true, 'the region arriving opens the dialog');
  await tick();
  // Back while the implementation is still arriving: the dialog stays closed after it arrives.
  env.hash = '';
  win.dispatchEvent(new Event('hashchange'));
  assert.equal(r.trip.tripOpen.value, false);
  await r.arrive();
  assert.equal(r.trip.tripOpen.value, false, 'a late arrival never reopens a closed dialog');
  assert.equal(r.loads, 1);
  r.stop();
});

test('add_and_review_before_and_after_runtime', async () => {
  reset();
  const s = await facade();
  s.brief();
  // Two Add to trip clicks before the implementation arrives share one import and one planner; each adds once.
  const first = s.trip.addToTrip('SC26-001'), second = s.trip.addToTrip('reef-2');
  await tick();
  assert.equal(s.loads, 1);
  assert.equal(s.log.length, 0, 'nothing is added before the planner exists');
  await s.arrive();
  await Promise.all([first, second]);
  assert.ok(isDeepStrictEqual(s.log, ['start:morro-bay', 'add:SC26-001', 'add:reef-2']), s.log.join());
  assert.ok(isDeepStrictEqual(s.trip.tripIds.value, ['SC26-001', 'reef-2']), 'the mark card sees both ids');
  // After arrival: the same planner, no second import or start.
  await s.trip.reviewTrip('reef-2');
  const place = {id: 'habitat:reef:r1', name: 'Reef one', latitude: 35.3, longitude: -120.9};
  const pending = s.trip.reviewPlace(place);
  place.name = 'changed while pending';
  await pending;
  assert.ok(isDeepStrictEqual(s.log.slice(3), ['review:reef-2', 'place:Reef one', 'add:user:habitat-reef-r1', 'review:user:habitat-reef-r1']), s.log.join());
  assert.equal(s.loads, 1); assert.equal(s.ctxs.length, 1); assert.equal(s.models.length, 1);
});

test('add_fails_closed_on_region_change_and_import_failure_then_retries', async () => {
  // A region change while the implementation arrives adds nothing to either region and publishes no planner.
  reset();
  const s = await facade();
  s.brief();
  const add = s.trip.addToTrip('SC26-001');
  await tick();
  region.value = 'cambria-san-simeon';
  await s.arrive();
  await add;
  assert.ok(!s.log.some(l => l.startsWith('add:')), s.log.join());
  assert.equal(s.trip.plannerView.value, null);
  assert.equal(store.size, 0, 'no draft written for either region');

  // A failed import: no add, the dialog's error, and Retry imports again.
  reset();
  const f = await facade();
  f.brief();
  const failed = f.trip.addToTrip('SC26-001');
  await tick();
  await f.fail();
  await failed;
  assert.match(f.trip.tripError.value, /The trip planner could not load \(Failed to fetch dynamically imported module\)/);
  assert.equal(f.log.length, 0);
  const retry = f.trip.loadPlanner();
  assert.equal(f.trip.tripError.value, '');
  await tick();
  assert.equal(f.loads, 2, 'Retry imports again');
  await f.arrive();
  assert.equal(await retry, f.models[0]);
  await f.trip.addToTrip('SC26-001');
  assert.ok(isDeepStrictEqual(f.log, ['start:morro-bay', 'add:SC26-001']));
});

test('brief_and_planner_share_exact_screen', async () => {
  // Brief first, then the planner: one init, and the planner is handed the brief's very object.
  reset();
  const s = await facade();
  const briefed = await s.brief();
  const ready = s.trip.loadPlanner();
  await tick(); await s.arrive();
  await ready;
  assert.equal(s.inits, 1);
  assert.equal(s.screens[0], briefed.screen);
  assert.equal(s.trip.protectedScreen.value.screen, s.screens[0]);

  // Planner asked first (import pending), the brief's check starting meanwhile: still one init, one shared object.
  reset();
  const c = await facade();
  const both = c.trip.loadPlanner();
  await tick();
  const briefing = c.brief();
  await c.arrive();
  await both;
  assert.equal(c.inits, 1);
  assert.equal(c.screens[0], (await briefing).screen);

  // A failed screen is not kept: the planner asked next is handed the one screen built on the next try, no other.
  reset();
  const f = await facade();
  let tries = 0;
  const failing = await f.brief('morro-bay', async () => { tries++; throw new Error('ds582 down'); });
  assert.equal(failing.state, 'failed');
  const refused = f.trip.loadPlanner();
  await tick();
  // The runtime's own screen request goes through the same loader; inject a working init for the retry.
  f.brief('morro-bay');
  await f.arrive();
  assert.equal(await refused, f.models[0], 'the retry shares the brief\'s recovered screen');
  assert.equal(tries, 1); assert.equal(f.inits, 1);
});

test('pack_calls_wait_and_abort_before_writes', async () => {
  reset();
  globalThis.caches = {keys: async () => []};
  try {
    const s = await facade();
    let listed = null;
    const list = s.trip.listPacks().then(v => { listed = v; });
    await tick();
    assert.equal(listed, null, 'a listing before arrival waits, it is never an empty success');
    await s.arrive();
    await list;
    assert.equal(listed[0].cache, 'sc-pack-x');
    s.listFails = true;
    await assert.rejects(s.trip.listPacks(), /cache locked/, 'a listing error stays an error, never "no packs"');

    // An already-cancelled save rejects before importing anything.
    const a = await facade(), aborted = new AbortController();
    aborted.abort();
    await assert.rejects(a.trip.savePack('morro-bay', aborted.signal, () => {}), {name: 'AbortError'});
    await assert.rejects(a.trip.saveCoastal(aborted.signal), {name: 'AbortError'});
    assert.equal(a.loads, 0);
    // Cancelled while the implementation arrives: no save starts.
    const live = new AbortController(), save = assert.rejects(a.trip.savePack('morro-bay', live.signal, () => {}), {name: 'AbortError'});
    await tick();
    live.abort();
    await a.arrive();
    await save;
    assert.ok(!a.log.some(l => l.startsWith('save')), a.log.join());
    // An un-cancelled save runs once, with the facade's session start.
    assert.ok(isDeepStrictEqual(await a.trip.savePack('morro-bay', new AbortController().signal, () => {}), {region_id: 'morro-bay'}));
    assert.ok(isDeepStrictEqual(a.log, ['save:morro-bay:true']));
    // A failed import rejects the call, and the next call imports again.
    const f = await facade(), read = assert.rejects(f.trip.readCoastal(), /Failed to fetch/);
    await tick(); await f.fail();
    await read;
    const again = f.trip.readCoastal();
    await tick(); await f.arrive();
    assert.equal(await again, null);
    assert.equal(f.loads, 2);
  } finally { delete globalThis.caches; }
  // No Cache Storage: no packs, and no import.
  const n = await facade();
  assert.ok(isDeepStrictEqual(await n.trip.listPacks(), []));
  assert.equal(n.loads, 0);
});

test('runtime_installs_no_duplicate_ranked_work', async () => {
  reset();
  const s = await facade();
  s.start();
  // The planner's ranked event is actual use: one import, and each event forwarded once, in order.
  doc.dispatchEvent(new CustomEvent('skippercast:trip-ranked', {detail: {id: 'a', targets: []}}));
  doc.dispatchEvent(new CustomEvent('skippercast:trip-ranked', {detail: {id: 'b', targets: []}}));
  await tick();
  assert.equal(s.loads, 1);
  await s.arrive();
  assert.ok(isDeepStrictEqual(s.log, ['ranked:a', 'ranked:b']), s.log.join());
  // Later boundary, region and timer work reaches the same instance; no second listener or timer.
  doc.dispatchEvent(new Event('skippercast:boundaries'));
  for (const f of env.timers) f();
  doc.dispatchEvent(new CustomEvent('skippercast:trip-ranked', {detail: {id: 'c', targets: []}}));
  await tick();
  assert.ok(isDeepStrictEqual(s.log.slice(2), ['draw', 'recheck', 'ranked:c']), s.log.join());
  assert.equal(env.timers.length, 1); assert.equal(s.ctxs.length, 1); assert.equal(s.loads, 1);
  s.stop();

  // An event from the old region, still waiting for the import, never draws in the new one.
  reset();
  const o = await facade();
  o.start();
  doc.dispatchEvent(new CustomEvent('skippercast:trip-ranked', {detail: {id: 'old', targets: []}}));
  await tick();
  region.value = 'cambria-san-simeon';
  await o.arrive();
  assert.ok(!o.log.includes('ranked:old'), o.log.join());
  o.stop();
});
