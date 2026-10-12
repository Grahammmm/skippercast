// FE-50: the v2 account menu's wrapper over the v1 account modules
// (web/account.ts). The passkey flow itself is tests/test_accounts.mjs
// (unchanged) and e2e/v2-account.spec.ts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const {RETURN_KEY, accountLabel, dropEmptyHash, readSession, remember} = await import('../web/account.ts');

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

test('v1 boat-profile.js exposes its sheet to the menu without changing v1', () => {
  const source = readFileSync(new URL('../dist/boat-profile.js', import.meta.url), 'utf8');
  assert.match(source, /export \{sheet as openBoatProfile\};/);
  assert.match(source, /button\.addEventListener\('click', sheet\)/);
});
