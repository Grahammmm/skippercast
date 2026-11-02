// RF2030-9: your own limits and cruise speed follow a change another tab of
// the same browser made (web/limits.ts followStoredLimits). A `storage` event
// for the limits or cruise key reloads through readStored, so the parse and
// clamp rules apply, and a later save here writes the newer map back.
import test from 'node:test';
import assert from 'node:assert/strict';

const {configureStore, STORAGE_KEYS} = await import('../web/state.ts');
const limits = await import('../web/limits.ts');

const memory = () => {const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), map: m};};

/** A fake window: holds listeners, `fire(key)` dispatches a storage event. */
function fakeTarget() {
  const listeners = new Set();
  return {
    listeners,
    addEventListener(type, fn) { if (type === 'storage') listeners.add(fn); },
    removeEventListener(type, fn) { if (type === 'storage') listeners.delete(fn); },
    fire(key, newValue = 'ignored') { for (const fn of listeners) fn({key, newValue}); },
  };
}

/** A fresh tab: empty signals, a Map-backed store, following `target`. */
function tab(store = memory()) {
  configureStore({storage: store});
  limits.savedLimits.value = {};
  limits.cruiseSpeed.value = null;
  const target = fakeTarget();
  const stop = limits.followStoredLimits(target);
  return {store, target, stop};
}

test('another tab tightens boat wind: the limits key reloads the clamped value, never the event value', t => {
  const {store, target, stop} = tab();
  t.after(() => { stop(); configureStore({storage: null}); });
  store.setItem(STORAGE_KEYS.limits, JSON.stringify({boat: {wind: 8, gust: 18, seas: 4}}));
  target.fire(STORAGE_KEYS.limits, JSON.stringify({boat: {wind: 3}}));
  assert.deepEqual(limits.savedLimits.value, {boat: {wind: 8, gust: 18, seas: 4}});
  store.setItem(STORAGE_KEYS.limits, JSON.stringify({boat: {wind: 99, gust: 18, seas: 4}}));
  target.fire(STORAGE_KEYS.limits);
  assert.equal(limits.savedLimits.value.boat.wind, 20, 'clamped to the bound as at start');
  assert.equal(limits.cruiseSpeed.value, null, 'the limits key leaves the cruise speed alone');
});

test('another tab sets a cruise speed: 22 follows; 99 is out of range and reads null, never a default', t => {
  const {store, target, stop} = tab();
  t.after(() => { stop(); configureStore({storage: null}); });
  store.setItem(STORAGE_KEYS.cruise, JSON.stringify({knots: 22}));
  target.fire(STORAGE_KEYS.cruise);
  assert.equal(limits.cruiseSpeed.value, 22);
  store.setItem(STORAGE_KEYS.cruise, JSON.stringify({knots: 99}));
  target.fire(STORAGE_KEYS.cruise);
  assert.equal(limits.cruiseSpeed.value, null);
  store.setItem(STORAGE_KEYS.cruise, '{broken');
  limits.cruiseSpeed.value = 30;
  assert.doesNotThrow(() => target.fire(STORAGE_KEYS.cruise));
  assert.equal(limits.cruiseSpeed.value, null, 'unreadable cruise reads null');
});

test('corrupt JSON under the limits key reads as defaults without throwing', t => {
  const {store, target, stop} = tab();
  t.after(() => { stop(); configureStore({storage: null}); });
  limits.savedLimits.value = {boat: {wind: 8, gust: 18, seas: 4}};
  store.setItem(STORAGE_KEYS.limits, '{not json');
  assert.doesNotThrow(() => target.fire(STORAGE_KEYS.limits));
  assert.deepEqual(limits.savedLimits.value, {});
});

test('a null key (another tab cleared storage) reloads both', t => {
  const {store, target, stop} = tab();
  t.after(() => { stop(); configureStore({storage: null}); });
  store.setItem(STORAGE_KEYS.limits, JSON.stringify({kayak: {wind: 6}}));
  store.setItem(STORAGE_KEYS.cruise, JSON.stringify({knots: 18}));
  target.fire(null);
  assert.equal(limits.savedLimits.value.kayak.wind, 6);
  assert.equal(limits.cruiseSpeed.value, 18);
  store.map.clear();
  target.fire(null);
  assert.deepEqual(limits.savedLimits.value, {}, 'cleared storage: defaults');
  assert.equal(limits.cruiseSpeed.value, null, 'cleared storage: no speed');
});

test('an event for an unrelated key changes neither signal object', t => {
  const {store, target, stop} = tab();
  t.after(() => { stop(); configureStore({storage: null}); });
  const saved = {boat: {wind: 8, gust: 18, seas: 4}};
  limits.savedLimits.value = saved;
  limits.cruiseSpeed.value = 22;
  store.setItem(STORAGE_KEYS.limits, JSON.stringify({}));
  store.setItem(STORAGE_KEYS.cruise, JSON.stringify({knots: 40}));
  for (const key of [STORAGE_KEYS.profile, 'skippercast-trip-v1', 'skippercast-limits-v1-x', '']) target.fire(key);
  assert.equal(limits.savedLimits.value, saved, 'same object identity');
  assert.equal(limits.cruiseSpeed.value, 22);
});

test('after the event, saves in this tab write the merged new map (the other tab is not overwritten)', t => {
  const {store, target, stop} = tab();
  t.after(() => { stop(); configureStore({storage: null}); });
  limits.saveLimits('boat', {wind: 15, gust: 18, seas: 4});
  // The other tab, which read the same map, tightens kayak and adds shore.
  store.setItem(STORAGE_KEYS.limits, JSON.stringify({boat: {wind: 15, gust: 18, seas: 4}, kayak: {wind: 6}}));
  target.fire(STORAGE_KEYS.limits);
  limits.saveLimits('boat', {wind: 12, gust: 18, seas: 4});
  let written = JSON.parse(store.map.get(STORAGE_KEYS.limits));
  assert.equal(written.kayak.wind, 6, 'first save keeps the other tab\'s kayak');
  assert.equal(written.boat.wind, 12);
  limits.resetLimits('boat');
  written = JSON.parse(store.map.get(STORAGE_KEYS.limits));
  assert.equal(written.boat, undefined);
  assert.equal(written.kayak.wind, 6, 'second save still keeps it');
});

test('the remover detaches the listener: a later event changes nothing', t => {
  const {store, target, stop} = tab();
  t.after(() => configureStore({storage: null}));
  stop();
  assert.equal(target.listeners.size, 0);
  store.setItem(STORAGE_KEYS.limits, JSON.stringify({boat: {wind: 8, gust: 18, seas: 4}}));
  store.setItem(STORAGE_KEYS.cruise, JSON.stringify({knots: 22}));
  target.fire(STORAGE_KEYS.limits);
  target.fire(STORAGE_KEYS.cruise);
  target.fire(null);
  assert.deepEqual(limits.savedLimits.value, {});
  assert.equal(limits.cruiseSpeed.value, null);
});

test('storage that throws on read: signals fall back as at start, nothing escapes the listener', t => {
  const {target, stop} = tab({getItem() { throw new Error('blocked'); }, setItem() { throw new Error('quota'); }});
  t.after(() => { stop(); configureStore({storage: null}); });
  limits.savedLimits.value = {boat: {wind: 8, gust: 18, seas: 4}};
  limits.cruiseSpeed.value = 22;
  assert.doesNotThrow(() => { target.fire(STORAGE_KEYS.limits); target.fire(STORAGE_KEYS.cruise); });
  assert.deepEqual(limits.savedLimits.value, {});
  assert.equal(limits.cruiseSpeed.value, null);
  limits.cruiseSpeed.value = 22;
  assert.doesNotThrow(() => target.fire(null));
  assert.equal(limits.cruiseSpeed.value, null);
});
