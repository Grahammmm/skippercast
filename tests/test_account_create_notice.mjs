// RF1925-4 (UX audit S4-40): after Create account verifies, the confirmation stays readable in the dialog until the person
// acknowledges it (Continue, Close, Escape or the scrim); only then does the existing return/reload handoff run, once.
// The real openAccount() runs against a small fake DOM, synthetic fetch and passkey library, and navigation stand-ins;
// every handler below is the registered one, not a copy of the state machine.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {accountOptions} from '../web/account-copy.ts';

const STRINGS = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url))).strings;
const FOCUS_TAGS = new Set(['BUTTON', 'INPUT', 'SUMMARY', 'A']);

class El {
  constructor(tag, id = '', attrs = {}) {
    this.tagName = tag.toUpperCase(); this.id = id; this.attrs = attrs; this.children = []; this.parentElement = null;
    this.listeners = {}; this.disabled = false; this.value = ''; this.tabIndex = -1; this.textContent = ''; this.removed = false;
    this.classes = new Set(); this.classList = {add: c => this.classes.add(c), remove: c => this.classes.delete(c)};
  }
  set className(v) { this.classes = new Set(v.split(' ')); }
  append(child) { child.parentElement = this; this.children.push(child); return child; }
  remove() { this.removed = true; if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(c => c !== this); }
  hasAttribute(name) { return name in this.attrs; }
  contains(el) { for (let n = el; n; n = n.parentElement) if (n === this) return true; return false; }
  all() { return this.children.flatMap(c => [c, ...c.all()]); }
  focusable() { return FOCUS_TAGS.has(this.tagName) || this.tabIndex >= 0; }
  querySelectorAll() { return this.all().filter(e => e.focusable()); }   // only ever asked for the focusable selector
  querySelector(sel) { return this.all().find(e => sel[0] === '#' ? e.id === sel.slice(1) : sel[0] === '.' ? e.classes.has(sel.slice(1)) : false) ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  focus() { document.activeElement = this; }
  fire(type, event = {}) { return Promise.all((this.listeners[type] ?? []).map(fn => fn({target: this, key: '', preventDefault() {}, ...event}))); }
  // Only the shapes openAccount writes: h1, input, button and p with an id, with their attributes.
  set innerHTML(html) {
    for (const gone of this.children) gone.parentElement = null;
    if (this.contains(document.activeElement) && document.activeElement !== this) document.activeElement = document.body;
    this.children = [];
    if (this.classes.has('account-scrim')) {
      const card = this.append(new El('section')); card.classes.add('account-card');
      const body = card.append(new El('div', 'account-body')); body.append(new El('h1', 'account-title'));
      card.append(new El('button')).classes.add('home-port-close');
      return;
    }
    for (const m of String(html).matchAll(/<(h1|input|button|p)\b([^>]*)>/g)) {
      const attrs = Object.fromEntries([...m[2].matchAll(/([\w-]+)="([^"]*)"/g)].map(a => [a[1], a[2]]));
      if (!attrs.id) continue;
      const el = this.append(new El(m[1], attrs.id, attrs));
      if (m[1] === 'button') el.textContent = (String(html).slice(m.index + m[0].length).match(/^([^<]*)</) ?? [])[1] ?? '';
    }
  }
}

const document = {body: new El('body'), activeElement: null, head: new El('head'), createElement: tag => new El(tag)};
document.activeElement = document.body;
class FakeHashChange { constructor(type) { this.type = type; } }
const nav = {reloads: 0, urls: [], hashchanges: 0, store: new Map()};
globalThis.document = document;
globalThis.HashChangeEvent = FakeHashChange;
globalThis.window = {dispatchEvent() { nav.hashchanges++; }};
globalThis.PublicKeyCredential = function PublicKeyCredential() {};
globalThis.location = {hash: '', pathname: '/map', search: '?region=morro-bay', reload() { nav.reloads++; }};
globalThis.history = {replaceState(_s, _t, url) { nav.urls.push(url); }};
globalThis.sessionStorage = {getItem: k => nav.store.get(k) ?? null, setItem: (k, v) => nav.store.set(k, String(v)), removeItem: k => nav.store.delete(k)};

const {openAccount, dialogFocusables} = await import('../dist/account.js');
const RETURN_KEY = 'skippercast-account-return';

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return {promise, resolve, reject}; };
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 0)); };
const reply = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const key = k => ({key: k});

let calls, routes, lib;
function reset({autofill = false} = {}) {
  calls = []; routes = {}; nav.reloads = 0; nav.urls = []; nav.hashchanges = 0; nav.store.clear();
  location.hash = ''; location.search = '?region=morro-bay'; document.body.children.length = 0; document.activeElement = document.body;
  globalThis.PublicKeyCredential = function PublicKeyCredential() {};
  lib = {
    browserSupportsWebAuthn: () => true, browserSupportsWebAuthnAutofill: async () => autofill,
    startRegistration: async () => ({id: 'new-credential'}), startAuthentication: async () => ({id: 'old-credential'}),
  };
  globalThis.SimpleWebAuthnBrowser = lib;
  routes.session = () => reply({signIn: true, signedIn: false});
  routes['auth/register/options'] = () => reply({challenge: 'c'});
  routes['auth/register/verify'] = () => reply({ok: true});
  routes['auth/login/options'] = () => reply({challenge: 'c'});
  routes['auth/login/verify'] = () => reply({ok: true});
  globalThis.fetch = async (url, init = {}) => {
    const path = String(url).replace('/api/', '');
    calls.push(path);
    const route = routes[path];
    assert.ok(route, `unexpected request ${path}`);
    return route(init);
  };
}
const count = path => calls.filter(c => c === path).length;

async function opened(lang = 'en') {
  const trigger = document.body.append(new El('button', 'masthead-account')); trigger.focus();
  await openAccount(accountOptions(lang));
  const scrim = document.body.children.find(c => c.classes.has('account-scrim'));
  const $ = sel => scrim.querySelector(sel);
  return {trigger, scrim, $, status: $('#account-status'), create: $('#account-create'), signin: $('#account-signin'), name: $('#account-name')};
}
/** Taps Create and lets the registration finish (or fail): the click handler's own promise. */
const create = dlg => dlg.create.fire('click');

test('create_verified_notice_persists_en_es', async () => {
  for (const lang of ['en', 'es']) {
    reset();
    const verify = deferred();
    routes['auth/register/verify'] = () => verify.promise;
    const dlg = await opened(lang);
    const text = id => STRINGS[id][lang];
    assert.equal(dlg.status.attrs.role, 'status'); assert.equal(dlg.status.attrs['aria-live'], 'polite'); assert.equal(dlg.status.attrs['aria-atomic'], 'true');
    const pending = create(dlg);
    await settle();
    assert.equal(dlg.status.textContent, text('account.status.createPrompt'), 'no success before the server verified');
    assert.equal(dlg.create.disabled, true);
    verify.resolve(reply({ok: true}));
    await pending; await settle(); await new Promise(r => setTimeout(r, 60));
    assert.equal(dlg.$('#account-status'), dlg.status, 'the same mounted status node');
    assert.equal(dlg.status.textContent, text('account.status.created'));
    assert.ok(text('account.status.created').length > 40 && text('account.status.created') !== STRINGS['account.create'][lang]);
    assert.equal(dlg.status.attrs.role, 'status'); assert.equal(dlg.status.attrs['aria-live'], 'polite'); assert.equal(dlg.status.attrs['aria-atomic'], 'true');
    assert.notEqual(document.activeElement, dlg.status, 'the status is never focused');
    assert.equal(dlg.create.textContent, text('account.continue'));
    assert.equal(dlg.create.disabled, false); assert.equal(dlg.signin.disabled, true); assert.equal(dlg.name.disabled, true);
    assert.ok(dialogFocusables(dlg.scrim.querySelector('.account-card')).includes(dlg.create), 'Continue is reachable by keyboard');
    assert.ok(dlg.scrim.querySelector('.home-port-close'), 'Close stays');
    assert.equal(nav.reloads, 0, 'no reload without an acknowledgment'); assert.equal(nav.urls.length, 0);
    assert.equal(dlg.scrim.removed, false);
    await dlg.create.fire('click');   // clean up
  }
  assert.equal(STRINGS['account.status.created'].en, 'Account created. You\u2019re signed in. Continue to return to your screen.');
  assert.equal(STRINGS['account.status.created'].es, 'Cuenta creada. Has iniciado sesi\u00f3n. Contin\u00faa para volver a tu pantalla.');
  assert.equal(STRINGS['account.continue'].en, 'Continue'); assert.equal(STRINGS['account.continue'].es, 'Continuar');
});

test('create_acknowledges_once_and_keeps_return', async () => {
  const acknowledgments = {
    continue: dlg => dlg.create.fire('click'),
    close: dlg => dlg.$('.home-port-close').fire('click'),
    escape: dlg => dlg.scrim.fire('keydown', key('Escape')),
    scrim: dlg => dlg.scrim.fire('click', {target: dlg.scrim}),
  };
  for (const [name, acknowledge] of Object.entries(acknowledgments)) {
    reset();
    nav.store.set(RETURN_KEY, '#trip');
    const dlg = await opened();
    await create(dlg);
    assert.equal(nav.reloads, 0, name);
    await acknowledge(dlg); await acknowledge(dlg);
    for (const again of Object.values(acknowledgments)) await again(dlg);   // a second press of anything never repeats it
    await settle();
    assert.equal(nav.reloads, 1, `${name}: one reload`);
    assert.equal(nav.urls.length, 1); assert.equal(nav.urls[0], '/map?region=morro-bay#trip', `${name}: query and remembered return survive`);
    assert.equal(nav.store.has(RETURN_KEY), false);
    assert.equal(count('auth/register/options'), 1, `${name}: no second registration`); assert.equal(count('auth/register/verify'), 1);
  }
  // Without a remembered address the existing default is used.
  reset();
  let dlg = await opened(); await create(dlg); await dlg.create.fire('click');
  assert.equal(nav.urls[0], '/map?region=morro-bay#guide');
  // Dismissing before success keeps the old behaviour: no reload, the opener is refocused, #account is cleared.
  reset(); location.hash = '#account';
  dlg = await opened();
  await dlg.scrim.fire('keydown', key('Escape'));
  assert.equal(dlg.scrim.removed, true); assert.equal(nav.reloads, 0); assert.equal(document.activeElement, dlg.trigger);
  assert.equal(nav.hashchanges, 1); assert.equal(nav.urls[0], '/map?region=morro-bay#guide');
  location.hash = '';
});

test('create_failure_or_cancel_is_not_success', async () => {
  const notSuccess = (dlg, label) => {
    assert.ok(dlg.status.textContent !== '' || label === 'options', label);
    assert.notEqual(dlg.status.textContent, STRINGS['account.status.created'].en, label);
    assert.equal(dlg.create.textContent, 'Create account', label); assert.equal(nav.reloads, 0, label);
    assert.equal(dlg.create.disabled, false, `${label}: retry allowed`); assert.equal(dlg.signin.disabled, false, label); assert.equal(dlg.name.disabled, false, label);
  };
  const failures = {
    options: () => { routes['auth/register/options'] = () => reply({error: 'No options today'}, 500); },
    cancelled: () => { lib.startRegistration = async () => { throw Object.assign(Error('x'), {name: 'NotAllowedError'}); }; },
    rejectedVerify: () => { routes['auth/register/verify'] = () => reply({error: 'Verification refused'}, 400); },
    libraryIncomplete: () => { lib.browserSupportsWebAuthn = () => false; },
  };
  for (const [label, arrange] of Object.entries(failures)) {
    reset(); arrange();
    const dlg = await opened();
    await create(dlg); await settle();
    if (label === 'libraryIncomplete') assert.equal(dlg.status.textContent, STRINGS['account.status.unsupported'].en);   // said, buttons stay off
    else { notSuccess(dlg, label); }
    assert.equal(nav.reloads, 0, label);
    await dlg.scrim.fire('keydown', key('Escape'));
    assert.equal(nav.reloads, 0, `${label}: closing after a failure does not reload`);
  }
  // No native passkey API: said at once, nothing to continue.
  reset(); delete globalThis.PublicKeyCredential;
  let dlg = await opened();
  assert.equal(dlg.status.textContent, STRINGS['account.status.unsupported'].en); assert.equal(dlg.create.disabled, true);
  assert.equal(dlg.create.textContent, 'Create account'); await dlg.scrim.fire('keydown', key('Escape')); assert.equal(nav.reloads, 0);
  // A failed verify can be retried and then confirms once.
  reset(); let first = true;
  routes['auth/register/verify'] = () => { if (first) { first = false; return reply({error: 'Verification refused'}, 400); } return reply({ok: true}); };
  dlg = await opened();
  await create(dlg); assert.equal(dlg.create.textContent, 'Create account');
  await create(dlg);
  assert.equal(dlg.status.textContent, STRINGS['account.status.created'].en); assert.equal(dlg.create.textContent, 'Continue'); assert.equal(nav.reloads, 0);
  await dlg.create.fire('click'); assert.equal(nav.reloads, 1);
});

test('create_late_verify_cannot_touch_new_dialog', async () => {
  for (const outcome of ['success', 'error']) {
    reset();
    const verify = deferred();
    routes['auth/register/verify'] = () => verify.promise;
    const a = await opened();
    const pending = create(a); await settle();
    await a.scrim.fire('keydown', key('Escape'));   // close A while the server is still verifying
    assert.equal(a.scrim.removed, true); assert.equal(nav.reloads, 0);
    const b = await opened();
    assert.notEqual(b.scrim, a.scrim);
    const before = {status: b.status.textContent, create: b.create.textContent, disabled: [b.create.disabled, b.signin.disabled, b.name.disabled]};
    if (outcome === 'success') verify.resolve(reply({ok: true})); else verify.resolve(reply({error: 'Late failure'}, 500));
    await pending; await settle();
    assert.equal(b.status.textContent, before.status, `${outcome}: B's status unchanged`);
    assert.equal(b.create.textContent, before.create); assert.equal(b.create.textContent, 'Create account');
    assert.ok([b.create.disabled, b.signin.disabled, b.name.disabled].every((v, i) => v === before.disabled[i]));
    assert.equal(a.status.textContent === STRINGS['account.status.created'].en, false, 'A never shows success after it closed');
    assert.equal(nav.reloads, 0, `${outcome}: no reload for the replacement dialog`);
    await b.scrim.fire('keydown', key('Escape')); assert.equal(nav.reloads, 0);
  }
});

test('create_late_autofill_stays_ignored_after_manual_create_and_signin_still_finishes', async () => {
  // A conditional (autofill) sign-in already waiting on its ceremony cannot finish a session after Create succeeded.
  reset({autofill: true});
  const ceremony = deferred();
  lib.startAuthentication = () => ceremony.promise;
  let dlg = await opened(); await settle();
  await create(dlg);
  assert.equal(dlg.status.textContent, STRINGS['account.status.created'].en);
  ceremony.resolve({id: 'late-autofill'}); await settle();
  assert.equal(count('auth/login/verify'), 0, 'the late autofill answer is never verified'); assert.equal(nav.reloads, 0);
  assert.equal(dlg.status.textContent, STRINGS['account.status.created'].en);
  await dlg.create.fire('click'); assert.equal(nav.reloads, 1);
  // Sign in with a passkey keeps its immediate finish and its own wording (no Continue step).
  reset();
  dlg = await opened();
  await dlg.signin.fire('click'); await settle();
  assert.equal(dlg.status.textContent, STRINGS['account.status.signedIn'].en);
  assert.equal(count('auth/login/verify'), 1); assert.equal(nav.reloads, 1); assert.equal(dlg.create.textContent, 'Create account');
  await dlg.scrim.fire('keydown', key('Escape'));   // sign-in leaves the dialog to the reload: close it for the next test
});

test('created_moves_lost_focus_onto_continue_never_onto_the_status', async () => {
  reset();
  let dlg = await opened();
  const verify = deferred();
  routes['auth/register/verify'] = () => verify.promise;
  const pending = create(dlg); await settle();
  document.activeElement = document.body;   // a disabled button loses focus to the page
  verify.resolve(reply({ok: true})); await pending;
  assert.equal(document.activeElement, dlg.create, 'Escape and Tab reach the dialog again');
  assert.notEqual(document.activeElement, dlg.status);
  await dlg.scrim.fire('keydown', key('Escape')); assert.equal(nav.reloads, 1);
  // Focus that is already inside the card is left alone.
  reset(); dlg = await opened();
  const slow = deferred(); routes['auth/register/verify'] = () => slow.promise;
  const again = create(dlg); await settle();
  dlg.name.focus();
  slow.resolve(reply({ok: true})); await again;
  assert.equal(document.activeElement, dlg.name);
  await dlg.create.fire('click');
});
