// SC1537-05: '#alerts' (a trip-alert notification tap, dist/sw.js) opens the
// saved-trip alerts dialog, or the account panel with no port in view, once.
// DOM globals are stubbed per test, as tests/test_account_menu.mjs does.
import test from 'node:test';
import assert from 'node:assert/strict';

const {followAlertsHash} = await import('../web/account.ts');
const KEYS = ['location', 'history', 'addEventListener', 'removeEventListener'];

function page(hash, {pathname = '/map', search = '?region=morro-bay'} = {}) {
  const listeners = new Set(), replaced = [];
  const location = {hash, pathname, search};
  const history = {state: {v: 2}, replaceState: (state, title, url) => { replaced.push([state, url]); location.hash = ''; }};
  const previous = Object.fromEntries(KEYS.map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const values = {location, history,
    addEventListener: (type, fn) => { if (type === 'hashchange') listeners.add(fn); },
    removeEventListener: (type, fn) => { if (type === 'hashchange') listeners.delete(fn); }};
  for (const key of KEYS) Object.defineProperty(globalThis, key, {configurable: true, writable: true, value: values[key]});
  return {
    location, replaced, listeners,
    go(next) { location.hash = next; for (const fn of [...listeners]) fn({}); },
    restore() { for (const key of KEYS) if (previous[key]) Object.defineProperty(globalThis, key, previous[key]); else delete globalThis[key]; },
  };
}

function follow(p, hasRegion) {
  const calls = [];
  const stop = followAlertsHash(has => calls.push(has), () => hasRegion);
  return {calls, stop};
}

test('#alerts with a port in view opens the alerts dialog once and drops the hash, keeping the search', t => {
  const p = page('#alerts'); t.after(() => p.restore());
  const {calls, stop} = follow(p, true);
  assert.deepEqual(calls, [true]);
  assert.deepEqual(p.replaced, [[{v: 2}, '/map?region=morro-bay']]);
  stop();
});

test('#alerts with no port in view opens the account panel instead', t => {
  const p = page('#alerts', {search: ''}); t.after(() => p.restore());
  const {calls, stop} = follow(p, false);
  assert.deepEqual(calls, [false]);
  assert.deepEqual(p.replaced, [[{v: 2}, '/map']]);
  stop();
});

for (const hash of ['#account', '#trip', '', '#alerts-x', '#Alerts']) {
  test(`hash ${JSON.stringify(hash)} opens nothing and leaves the URL alone`, t => {
    const p = page(hash); t.after(() => p.restore());
    const {calls, stop} = follow(p, true);
    p.go(hash);
    assert.equal(calls.length, 0);
    assert.equal(p.replaced.length, 0);
    stop();
  });
}

test('a later hashchange to #alerts after closing opens again; a reload-style repeat does not', t => {
  const p = page(''); t.after(() => p.restore());
  const {calls, stop} = follow(p, true);
  assert.equal(calls.length, 0);
  p.go('#alerts');
  assert.deepEqual(calls, [true]);
  p.go('');
  p.go('#trip');
  assert.deepEqual(calls, [true]);
  p.go('#alerts');
  assert.deepEqual(calls, [true, true]);
  assert.equal(p.replaced.length, 2);
  stop();
});

test('cleanup removes the hashchange listener', t => {
  const p = page(''); t.after(() => p.restore());
  const {calls, stop} = follow(p, true);
  assert.equal(p.listeners.size, 1);
  stop();
  assert.equal(p.listeners.size, 0);
  p.go('#alerts');
  assert.equal(calls.length, 0);
});

test('the region is read when the hash is followed, not when the listener is set', t => {
  const p = page(''); t.after(() => p.restore());
  let hasRegion = false;
  const calls = [];
  const stop = followAlertsHash(has => calls.push(has), () => hasRegion);
  hasRegion = true;
  p.go('#alerts');
  assert.deepEqual(calls, [true]);
  stop();
});
