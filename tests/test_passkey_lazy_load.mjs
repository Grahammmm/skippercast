// SC0452-01: the passkey library (vendor/simplewebauthn-browser-14.0.0) loads when a ceremony starts, not with every map page.
// dist/account.js's loadPasskeyLibrary is run against a synthetic document and a hand-driven clock: no network, no browser.
// The real dialog handlers run in e2e/v2-account.spec.ts.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url));
const VENDOR = 'dist/vendor/simplewebauthn-browser-14.0.0/index.umd.min.js';
const ERROR_LINE = 'Passkeys are unavailable right now. Try again when you are online.';

/** A document whose head records every appended script; scripts are driven by hand with fire(). */
function harness() {
  const scripts = [], clock = {timers: [], cleared: new Set(), id: 0};
  const make = () => {
    const listeners = {};
    return {tag: 'script', removed: false, src: '', integrity: '', listeners,
      addEventListener(type, fn) { (listeners[type] ??= new Set()).add(fn); },
      removeEventListener(type, fn) { listeners[type]?.delete(fn); },
      remove() { this.removed = true; },
      fire(type) { for (const fn of [...(listeners[type] ?? [])]) fn({type}); }};
  };
  const document = {head: {appendThrows: false, append(el) { if (this.appendThrows) throw Error('blocked: CSP or detached'); scripts.push(el); }}, createElement: tag => { assert.equal(tag, 'script'); return make(); }};
  const saved = {document: globalThis.document, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout, lib: globalThis.SimpleWebAuthnBrowser};
  globalThis.document = document;
  globalThis.setTimeout = (fn, ms) => { const id = ++clock.id; clock.timers.push({id, fn, ms}); return id; };
  globalThis.clearTimeout = id => { clock.cleared.add(id); };
  delete globalThis.SimpleWebAuthnBrowser;
  const pending = () => clock.timers.filter(t => !clock.cleared.has(t.id));
  return {document, scripts, clock, pending,
    expire: () => { const t = pending().at(-1); clock.cleared.add(t.id); t.fn(); },
    install: (lib = complete()) => { globalThis.SimpleWebAuthnBrowser = lib; },
    restore() {
      Object.assign(globalThis, {document: saved.document, setTimeout: saved.setTimeout, clearTimeout: saved.clearTimeout});
      if (saved.document === undefined) delete globalThis.document;
      if (saved.lib === undefined) delete globalThis.SimpleWebAuthnBrowser; else globalThis.SimpleWebAuthnBrowser = saved.lib;
    }};
}
const complete = () => ({browserSupportsWebAuthn: () => true, startAuthentication: async () => ({}), startRegistration: async () => ({})});

let n = 0;
/** A fresh copy of the module (its load cache starts empty) inside a fresh harness. */
async function setup() {
  const h = harness();
  const account = await import(`../dist/account.js?lazy=${++n}`);
  return {h, account};
}
const settled = promise => promise.then(value => ({ok: true, value}), error => ({ok: false, error}));
const tick = () => new Promise(resolve => setImmediate(resolve));

test('lazy_loader_idle_and_exact_pin: nothing loads until asked; the script is pinned to the vendored bytes', async () => {
  const {h, account} = await setup();
  try {
    assert.equal(h.scripts.length, 0, 'importing the module adds no script');
    const first = account.loadPasskeyLibrary();
    assert.equal(h.scripts.length, 1);
    const [script] = h.scripts;
    assert.equal(script.src, '/vendor/simplewebauthn-browser-14.0.0/index.umd.min.js', 'same-origin absolute path');
    assert.equal(script.integrity, 'sha256-KbsGmbRbw5o1DZkqE7/BpNQNiVMTkFgeH1fxFCxuIh0=');
    assert.equal(script.crossOrigin, undefined, 'no crossorigin attribute: a same-origin request');
    assert.equal(script.crossorigin, undefined);
    assert.equal(h.pending()[0].ms, 20000, 'a 20 s allowance');
    h.install(); script.fire('load');
    assert.equal((await first), globalThis.SimpleWebAuthnBrowser);

    // The pinned integrity is the SRI form of the vendored file's digest, which is the digest the manifest pins.
    const digest = createHash('sha256').update(read(VENDOR)).digest();
    const manifest = JSON.parse(read('scripts/web-vendor-sha256.json'));
    assert.equal(manifest[VENDOR], digest.toString('hex'), 'the manifest pins the vendored bytes');
    assert.equal(account.PASSKEY_LIBRARY.integrity, 'sha256-' + digest.toString('base64'), 'the loader pins the same bytes');
  } finally { h.restore(); }
});

test('lazy_loader_idle_and_exact_pin: a complete global loads zero scripts; an incomplete one is not success', async () => {
  const {h, account} = await setup();
  try {
    h.install();
    assert.equal(await account.loadPasskeyLibrary(), globalThis.SimpleWebAuthnBrowser);
    assert.equal(h.scripts.length, 0);
  } finally { h.restore(); }
  for (const partial of [{}, {browserSupportsWebAuthn: () => true}, {browserSupportsWebAuthn: () => true, startAuthentication() {}, startRegistration: 'no'}]) {
    const {h: h2, account: account2} = await setup();
    try {
      h2.install(partial);
      const result = settled(account2.loadPasskeyLibrary());
      assert.equal(h2.scripts.length, 1, 'an incomplete global does not count as loaded');
      h2.scripts[0].fire('load');
      const out = await result;
      assert.equal(out.ok, false);
      assert.equal(out.error.message, ERROR_LINE);
    } finally { h2.restore(); }
  }
});

test('lazy_loader_concurrent_and_cached: overlapping callers share one script; success is reused for the page', async () => {
  const {h, account} = await setup();
  try {
    const calls = [account.loadPasskeyLibrary(), account.loadPasskeyLibrary(), account.loadPasskeyLibrary()];
    assert.equal(h.scripts.length, 1, 'one script for three callers');
    assert.equal(globalThis.SimpleWebAuthnBrowser, undefined, 'nothing is used before it loads');
    h.install(); h.scripts[0].fire('load');
    const libs = await Promise.all(calls);
    assert.ok(libs.every(lib => lib === globalThis.SimpleWebAuthnBrowser));
    assert.equal(h.pending().length, 0, 'the timer is cleared on success');
    // A later ceremony (reopen, create, sign in, add) finds it loaded.
    for (let i = 0; i < 3; i++) assert.equal(await account.loadPasskeyLibrary(), globalThis.SimpleWebAuthnBrowser);
    assert.equal(h.scripts.length, 1, 'no repeated script per ceremony');
    assert.equal(h.scripts[0].removed, false);
  } finally { h.restore(); }
});

test('lazy_loader_failure_retry: error, timeout, bad global and a refused insert each say passkeys are unavailable, then retry', async () => {
  const {h, account} = await setup();
  try {
    const outcomes = [];
    // 1. Script error (also what a browser reports for an SRI mismatch).
    let call = settled(account.loadPasskeyLibrary());
    h.scripts.at(-1).fire('error');
    outcomes.push(await call);
    assert.equal(h.scripts.at(-1).removed, true, 'the failed script is removed');
    assert.equal(h.pending().length, 0, 'the failed attempt leaves no timer');
    // 2. Timeout.
    call = settled(account.loadPasskeyLibrary());
    assert.equal(h.scripts.length, 2, 'the next deliberate attempt loads afresh');
    h.expire();
    outcomes.push(await call);
    // 3. Loaded, but no usable global.
    call = settled(account.loadPasskeyLibrary());
    h.scripts.at(-1).fire('load');
    outcomes.push(await call);
    // 4. The insert itself throws.
    h.document.head.appendThrows = true;
    call = settled(account.loadPasskeyLibrary());
    outcomes.push(await call);
    h.document.head.appendThrows = false;
    for (const out of outcomes) {
      assert.equal(out.ok, false);
      assert.equal(out.error.message, ERROR_LINE);
      assert.equal(account.passkeyMessage(out.error), ERROR_LINE, 'shown as is, with no doubled stop');
    }
    assert.equal(h.scripts.length, 3, 'one script per attempt: error, timeout, bad global (the refused insert never reached the head)');

    // 5. And now it works.
    call = settled(account.loadPasskeyLibrary());
    assert.equal(h.scripts.length, 4);
    h.install(); h.scripts.at(-1).fire('load');
    assert.equal((await call).ok, true);
  } finally { h.restore(); }
});

test('lazy_loader_failure_retry: a late event or timeout from an expired attempt cannot settle or reset a newer one', async () => {
  const {h, account} = await setup();
  try {
    const first = settled(account.loadPasskeyLibrary());
    const [old] = h.scripts;
    const oldTimer = h.pending()[0];
    h.expire();
    assert.equal((await first).ok, false);

    const second = account.loadPasskeyLibrary();
    assert.equal(h.scripts.length, 2);
    old.fire('error'); old.fire('load'); oldTimer.fn();   // everything the expired attempt might still deliver
    h.install(); h.scripts[1].fire('load');
    assert.equal(await second, globalThis.SimpleWebAuthnBrowser, 'the newer attempt still resolves');
    assert.equal(h.scripts.length, 2);

    // A second event for a settled attempt changes nothing either.
    h.scripts[1].fire('error');
    assert.equal(await account.loadPasskeyLibrary(), globalThis.SimpleWebAuthnBrowser);
  } finally { h.restore(); }
});

test('lazy_loader_failure_retry: callers sharing a failed attempt all see the one line, and no rejection goes unhandled', async () => {
  const {h, account} = await setup();
  const unhandled = [];
  const watch = reason => unhandled.push(reason);
  process.on('unhandledRejection', watch);
  try {
    const a = settled(account.loadPasskeyLibrary()), b = settled(account.loadPasskeyLibrary());
    assert.equal(h.scripts.length, 1);
    h.scripts[0].fire('error');
    assert.deepEqual((await Promise.all([a, b])).map(r => r.error?.message), [ERROR_LINE, ERROR_LINE]);
    await tick(); await tick();
    assert.deepEqual(unhandled, []);
  } finally { process.off('unhandledRejection', watch); h.restore(); }
});

test('lazy_handler_capability_and_ceremonies: the shell does not load it, and every vendor call in account.js follows an awaited load', () => {
  const html = read('dist/app.html').toString();
  assert.ok(!/simplewebauthn|\/vendor\//i.test(html), 'the map page requests no vendored library');
  const source = read('dist/account.js').toString();
  // Create, Sign in (and the autofill that shares its path) and Add reach the vendor object only through a loaded `lib`.
  assert.ok(!/webauthn\(\)\??\.(?:start|browsersupports)/i.test(source), 'no ceremony calls the global before the loader');
  assert.equal([...source.matchAll(/lib\.startRegistration\(/g)].length, 2, 'Create and Add register through the loaded library');
  assert.equal([...source.matchAll(/lib\.startAuthentication\(/g)].length, 1, 'Sign in and autofill authenticate through the loaded library');
  assert.equal([...source.matchAll(/await loadPasskeyLibrary\(\)/g)].length, 3, 'the three entry points (ready, add, autofill) await the loader');
  assert.ok(!/\.crossOrigin\b|setAttribute\(\s*['"]crossorigin|use-credentials/i.test(source), 'no crossorigin or credentials mode on the script');
});
