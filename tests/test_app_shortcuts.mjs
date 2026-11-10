// SC2252-15: the installed app's "Trip planner" shortcut opens /map#export. The real startTrip (web/trip.ts) opens the
// trip dialog only once the address names a region: a regionless shortcut waits for main.tsx's home resolution without
// an empty dialog, and the trip planner never switches the view to the species Plan view. Each case starts a fresh
// trip module with a fake page (location, listeners, timers) and a blocked network; nothing leaves this process.
import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.REGIONS = undefined;
const {region, coast, appView} = await import('../web/state.ts');

let fresh = 0;
/** A fresh web/trip.ts started on a fake page at `path`; `run` gets the page and module, and everything is undone after. */
async function onPage(path, run) {
  const listeners = new Map(), docListeners = new Map(), timers = new Set(), requests = [], rejections = [];
  const on = map => (name, fn) => { if (!map.has(name)) map.set(name, new Set()); map.get(name).add(fn); };
  const off = map => (name, fn) => map.get(name)?.delete(fn);
  const page = {
    location: {href: '', hash: '', origin: 'https://fixture.test', reload() { throw new Error('unexpected reload'); }},
    go(next) { const url = new URL(next, 'https://fixture.test'); Object.assign(page.location, {href: url.href, hash: url.hash}); },
    fire(name) { for (const fn of [...listeners.get(name) ?? []]) fn(new Event(name)); },
    listening: name => listeners.get(name)?.size ?? 0, requests, timers,
  };
  page.go(path);
  const saved = Object.fromEntries(['location', 'document', 'addEventListener', 'removeEventListener', 'setInterval', 'clearInterval', 'fetch']
    .map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  const set = (k, value) => Object.defineProperty(globalThis, k, {configurable: true, writable: true, value});
  set('location', page.location);
  set('document', {addEventListener: on(docListeners), removeEventListener: off(docListeners), querySelector: () => null});
  set('addEventListener', on(listeners)); set('removeEventListener', off(listeners));
  set('setInterval', fn => { const id = {fn}; timers.add(id); return id; }); set('clearInterval', id => timers.delete(id));
  set('fetch', async input => { requests.push(String(input)); throw new TypeError('network blocked in tests'); });
  const unhandled = error => rejections.push(error);
  process.on('unhandledRejection', unhandled);
  const trip = await import(`../web/trip.ts?case=${++fresh}`);
  let stop = () => {};
  try {
    stop = trip.startTrip();
    await run(page, trip);
    await settle(() => false, 5);
    assert.deepEqual(rejections, [], 'no unhandled rejection');
  } finally {
    stop();
    process.off('unhandledRejection', unhandled);
    for (const [k, d] of Object.entries(saved)) { if (d) Object.defineProperty(globalThis, k, d); else Reflect.deleteProperty(globalThis, k); }
    region.value = null; coast.value = null; appView.value = 'coast';
  }
}
/** Let pending promises run until `done()` or `turns` macrotasks have passed. */
async function settle(done, turns = 200) {
  for (let i = 0; i < turns && !done(); i++) await new Promise(resolve => setImmediate(resolve));
}
const plannerRequested = (page, id) => page.requests.some(url => url.includes(`regions/${id}/region.json`));

test('start_trip_bound_export_requests_planner_without_switching_view', async () => {
  for (const view of ['conditions', 'coast']) {
    region.value = 'test-coast'; appView.value = view;
    await onPage('/map?region=test-coast&view=conditions#export', async (page, trip) => {
      assert.equal(trip.tripOpen.value, true, 'the trip dialog opens');
      await settle(() => trip.tripError.value !== '');
      assert.ok(plannerRequested(page, 'test-coast'), 'the planner asked for the region');
      assert.match(trip.tripError.value, /could not load/, 'a failed load is reported in the dialog, never thrown');
      assert.equal(appView.value, view, 'the view is unchanged, never plan');
    });
  }
});

test('non-export fragments never open the dialog or request the planner', async () => {
  for (const hash of ['', '#Export', '#export/extra', '#%65xport', '#account']) {
    region.value = 'test-coast';
    await onPage(`/map?region=test-coast${hash}`, async (page, trip) => {
      await settle(() => false, 20);
      assert.equal(trip.tripOpen.value, false, hash);
      assert.equal(plannerRequested(page, 'test-coast'), false, hash);
    });
  }
});

test('regionless_export_waits_without_empty_dialog', async () => {
  await onPage('/map#export', async (page, trip) => {
    assert.equal(trip.tripOpen.value, false, 'no empty dialog before home resolution');
    page.fire('hashchange');
    coast.value = 'central';
    page.fire('hashchange');
    await settle(() => false, 20);
    assert.equal(trip.tripOpen.value, false, 'a coast without a region has no planner region');
    assert.equal(page.requests.length, 0, 'nothing is requested while unresolved');
    coast.value = null; region.value = 'test-coast';
    assert.equal(trip.tripOpen.value, true, 'the region arriving opens the dialog');
    await settle(() => trip.tripError.value !== '');
    assert.ok(plannerRequested(page, 'test-coast'));
    page.go('/map?region=test-coast'); page.fire('hashchange');
    assert.equal(trip.tripOpen.value, false, 'closed');
    page.go('/map?region=test-coast#export'); page.fire('hashchange');
    assert.equal(trip.tripOpen.value, true, 'reopened');
  });
});

test('the start can be undone: no listener, subscription or timer is left behind', async () => {
  let after;
  await onPage('/map#export', async (page, trip) => { after = {page, trip}; assert.equal(page.timers.size, 1); assert.equal(page.listening('hashchange'), 1); });
  const {page, trip} = after;
  assert.equal(page.timers.size, 0, 'the recheck timer is cleared');
  assert.equal(page.listening('hashchange'), 0);
  region.value = 'test-coast';
  assert.equal(trip.tripOpen.value, false, 'a stopped start no longer follows the region');
  region.value = null;
});
