// FE-50: the v2 account menu's wrapper over the v1 account modules
// (web/account.ts). The passkey flow itself is tests/test_accounts.mjs
// (unchanged) and e2e/v2-account.spec.ts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const {RETURN_KEY, accountLabel, dropEmptyHash, readSession, remember} = await import('../web/account.ts');

// Each scenario gets fresh module state, with no production reset API or network.
const freshAccount = name => import(`../web/account.ts?scenario=${name}`);
const signedOut = {signIn: '/#account', signedIn: false};
const signedIn = {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}};
function sessionFetch() {
  const requests = [];
  const fetchFn = (url, options) => new Promise((resolve, reject) => {
    assert.equal(url, '/api/session');
    assert.ok(options.signal instanceof AbortSignal);
    requests.push({resolve: (data, ok = true) => resolve({ok, json: async () => data}), reject});
  });
  return {requests, fetchFn};
}

for (const [state, answer] of [['signed-out', signedOut], ['signed-in', signedIn], ['disabled', {signIn: null}]]) {
  test(`mount ensures coalesce and settled ${state} remounts reuse the session`, async () => {
    const {ensureSession, session} = await freshAccount(state);
    const {requests, fetchFn} = sessionFetch();
    const first = ensureSession(fetchFn), second = ensureSession(fetchFn);
    assert.equal(first, second);
    assert.equal(requests.length, 1);
    requests[0].resolve(answer);
    await Promise.all([first, second]);
    assert.equal(session.value.state, state);
    const settled = session.value;
    assert.equal(await ensureSession(fetchFn), settled);
    assert.equal(await ensureSession(fetchFn), settled);
    assert.equal(requests.length, 1);
  });
}

test('explicit refresh force-fetches after a settled mount and updates sign-in state', async () => {
  const {ensureSession, refreshSession, session} = await freshAccount('force-refresh');
  const {requests, fetchFn} = sessionFetch();
  const initial = ensureSession(fetchFn);
  requests[0].resolve(signedOut);
  await initial;
  const refresh = refreshSession(fetchFn);
  assert.equal(requests.length, 2);
  assert.equal(ensureSession(fetchFn), refresh);
  requests[1].resolve(signedIn);
  await refresh;
  assert.deepEqual(session.value, {state: 'signed-in', name: 'Skipper'});
  await ensureSession(fetchFn);
  assert.equal(requests.length, 2);
});

test('an older mount response cannot overwrite a newer explicit refresh', async () => {
  const {ensureSession, refreshSession, session} = await freshAccount('stale-mount');
  const {requests, fetchFn} = sessionFetch();
  const initial = ensureSession(fetchFn);
  const refresh = refreshSession(fetchFn);
  assert.equal(requests.length, 2);
  assert.equal(ensureSession(fetchFn), refresh);
  requests[1].resolve(signedIn);
  await refresh;
  requests[0].resolve(signedOut);
  await initial;
  assert.deepEqual(session.value, {state: 'signed-in', name: 'Skipper'});
  await ensureSession(fetchFn);
  assert.equal(requests.length, 2);
});

test('stale request completion cannot clear the latest pending refresh', async () => {
  const {ensureSession, refreshSession, session} = await freshAccount('pending-refresh');
  const {requests, fetchFn} = sessionFetch();
  const initial = ensureSession(fetchFn);
  const refresh = refreshSession(fetchFn);
  requests[0].reject(new Error('offline'));
  await initial;
  assert.deepEqual(session.value, {state: 'loading'});
  assert.equal(ensureSession(fetchFn), refresh);
  assert.equal(requests.length, 2);
  requests[1].resolve(signedIn);
  await refresh;
  assert.equal(session.value.state, 'signed-in');
});

test('failed initial reads show offline and a later mount can recover', async () => {
  const {ensureSession, session} = await freshAccount('offline-recovery');
  const {requests, fetchFn} = sessionFetch();
  const initial = ensureSession(fetchFn);
  requests[0].reject(new Error('offline'));
  assert.deepEqual(await initial, {state: 'offline'});
  assert.deepEqual(session.value, {state: 'offline'});
  const retry = ensureSession(fetchFn);
  assert.equal(ensureSession(fetchFn), retry);
  assert.equal(requests.length, 2);
  requests[1].resolve(signedOut);
  await retry;
  assert.deepEqual(session.value, {state: 'signed-out'});
  await ensureSession(fetchFn);
  assert.equal(requests.length, 2);
});

test('AccountMenu uses the mount-only session initializer', () => {
  const source = readFileSync(new URL('../web/app/AccountMenu.tsx', import.meta.url), 'utf8');
  assert.match(source, /void ensureSession\(\);/);
  assert.doesNotMatch(source, /refreshSession/);
});

test('the session answer reads as signed in, signed out, disabled or offline', () => {
  assert.deepEqual(readSession({signIn: '/#account', signedIn: true, user: {display_name: ' Skipper '}}), {state: 'signed-in', name: 'Skipper'});
  assert.deepEqual(readSession({signIn: '/#account', signedIn: true, user: {display_name: ''}}), {state: 'signed-in', name: null});
  assert.deepEqual(readSession({signIn: '/#account', signedIn: false}), {state: 'signed-out'});
  assert.deepEqual(readSession({signIn: null, signedIn: false}), {state: 'disabled'});
  assert.deepEqual(readSession(null), {state: 'offline'});
  assert.deepEqual(readSession({signIn: '/#account', signedIn: true}, false), {state: 'offline'});
  assert.equal(accountLabel({state: 'signed-in', name: 'Skipper'}), 'Skipper');
  assert.equal(accountLabel({state: 'signed-in', name: null}), 'Account');
  assert.equal(accountLabel({state: 'signed-out'}), 'Sign in');
  assert.equal(accountLabel({state: 'loading'}), 'Sign in');
  assert.equal(accountLabel({state: 'disabled'}), 'Account');
});

test('account.js returns to the hash before #account, else a bare hash the app drops', () => {
  const stored = new Map();
  const storage = {setItem: (k, v) => stored.set(k, v)};
  assert.equal(RETURN_KEY, readFileSync(new URL('../dist/account.js', import.meta.url), 'utf8').match(/RETURN_KEY = '([^']+)'/)[1]);
  remember('', storage); assert.equal(stored.get(RETURN_KEY), '#');
  remember('#account', storage); assert.equal(stored.get(RETURN_KEY), '#');
  remember('#layers', storage); assert.equal(stored.get(RETURN_KEY), '#layers');
  assert.doesNotThrow(() => remember('#x', {setItem() { throw new Error('denied'); }}));
  const calls = [];
  const history = {state: {v: 2}, replaceState: (...args) => calls.push(args)};
  dropEmptyHash({href: 'https://skippercast.com/map?region=morro-bay#', hash: '', pathname: '/map', search: '?region=morro-bay'}, history);
  dropEmptyHash({href: 'https://skippercast.com/map?region=morro-bay#x', hash: '#x', pathname: '/map', search: '?region=morro-bay'}, history);
  assert.deepEqual(calls, [[{v: 2}, '', '/map?region=morro-bay']]);
});

test('the account menu opens the real boat sheet without the retired button and closing restores focus', async () => {
  const source = readFileSync(new URL('../dist/boat-profile.js', import.meta.url), 'utf8');
  assert.match(source, /export \{sheet as openBoatProfile\};/);
  const {openBoatSheet} = await import('../web/account.ts');
  const previous = Object.fromEntries(['document', 'localStorage'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const events = new Map(), classes = new Set(), mounted = [];
  let focused = 0, restored = 0, removed = false;
  const control = name => ({addEventListener(type, listener) { events.set(`${name}:${type}`, listener); }});
  const controls = new Map(['#boat-form', '#boat-lookup', '#boat-save', '.home-port-close'].map(name => [name, control(name)]));
  controls.set('#boat-query', {focus() { focused++; }});
  const scrim = {innerHTML: '', className: '', querySelector: name => controls.get(name) ?? null,
    addEventListener(type, listener) { events.set(`scrim:${type}`, listener); }, remove() { removed = true; }};
  try {
    Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: {getItem() { return null; }}});
    Object.defineProperty(globalThis, 'document', {configurable: true, value: {
      activeElement: {focus() { restored++; }},
      createElement(tag) { assert.equal(tag, 'div'); return scrim; },
      getElementById() { throw Error('The live sheet must not depend on the retired boat-button'); },
      body: {append(element) { mounted.push(element); }, classList: {add(name) { classes.add(name); }, remove(name) { classes.delete(name); }}},
    }});
    await openBoatSheet();
    assert.deepEqual(mounted, [scrim]);
    assert.equal(scrim.className, 'home-port-scrim boat-scrim');
    assert.match(scrim.innerHTML, /role="dialog" aria-modal="true" aria-labelledby="boat-title"/);
    assert.match(scrim.innerHTML, /Rate conditions for your boat/);
    assert.match(scrim.innerHTML, /id="boat-form"/);
    assert.match(scrim.innerHTML, /id="boat-save"/);
    assert.equal(focused, 1, 'the make/model field receives focus');
    assert.ok(classes.has('choosing-home-port'));
    assert.equal(typeof events.get('#boat-lookup:click'), 'function');
    assert.equal(typeof events.get('#boat-save:click'), 'function');
    events.get('.home-port-close:click')();
    assert.equal(removed, true);
    assert.equal(classes.has('choosing-home-port'), false);
    assert.equal(restored, 1);
  } finally {
    for (const [key, descriptor] of Object.entries(previous)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
  }
});
