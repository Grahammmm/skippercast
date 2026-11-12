// SC2252-02: the account panel lists where the owner is signed in and signs out the other devices.
// A tiny fake DOM and a fetch stub stand in for the browser and the server; nothing leaves the process.
import test from 'node:test';
import assert from 'node:assert/strict';

class El {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.listeners = {}; this.parentElement = null;
    this.hidden = false; this.disabled = false; this.textContent = ''; this.innerHTML = ''; this.className = ''; this.tabIndex = 0;
  }
  append(child) { child.parentElement = this; this.children.push(child); return child; }
  after(node) { const kids = this.parentElement.children; node.parentElement = this.parentElement; kids.splice(kids.indexOf(this) + 1, 0, node); }
  remove() {
    const kids = this.parentElement.children; kids.splice(kids.indexOf(this), 1);
    // A browser drops focus to the page when the focused element, or one inside it, leaves the document.
    if (document.activeElement === this || (this.box && Object.values(this.box).includes(document.activeElement))) document.activeElement = document.body;
  }
  querySelector(sel) {
    if (sel === ':scope > .account-confirm') return this.children.find(c => c.className === 'account-confirm') ?? null;
    if (this.box) return sel === 'p' ? this.box.p : sel.includes('"no"') ? this.box.no : this.box.yes;
    return null;
  }
  setAttribute() {}
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  fire(type, event = {}) { for (const fn of this.listeners[type] ?? []) fn(event); }
  focus() { document.activeElement = this; }
  get isConnected() { return true; }
}
const document = {body: {}, activeElement: null, createElement: () => { const el = new El(); el.box = {p: new El(), no: new El('button'), yes: new El('button')}; return el; }};
globalThis.document = document;

let calls = [], script = [];   // script: queued replies {ok, body} or a function returning a promise
globalThis.fetch = async (url, init = {}) => {
  calls.push({url, method: init.method ?? 'GET', body: init.body});
  const next = script.shift();
  const reply = typeof next === 'function' ? await next() : next;
  if (reply === 'network') throw Error('offline');
  return {ok: reply.ok ?? true, status: reply.status ?? 200, json: async () => { if (reply.bad) throw Error('bad json'); return reply.body ?? {}; }};
};

const {createSessionControl, sessionListHTML, createCopy} = await import('../dist/account.js');

const row = (device, current = false, created_at = '2026-11-01T12:00:00.000Z') => ({current, created_at, expires_at: 1900000000, device});
const two = [row('Chrome on Mac', true), row('Safari on iPhone')];
const one = [row('Chrome on Mac', true)];
const listing = sessions => ({body: {sessions}});

function section() {
  const wrap = new El(), nodes = {'#account-sessions': new El('ul'), '#account-sessions-status': new El('p'), '#account-end-others': new El('button')};
  nodes['#account-end-others'].hidden = true;
  wrap.append(nodes['#account-end-others']);
  return {nodes, $: sel => nodes[sel], button: nodes['#account-end-others'], list: nodes['#account-sessions'], note: nodes['#account-sessions-status'], wrap};
}
const confirmBox = s => s.wrap.children.find(c => c.className === 'account-confirm');
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
const reset = replies => { calls = []; script = [...replies]; };

test('sessions list marks this device once, escapes labels and dates the sign-in', () => {
  const html = sessionListHTML([row('<img src=x onerror=1>', false), row('Chrome on Mac', true)], createCopy());
  assert.equal(html.match(/<li>/g).length, 2);
  assert.equal(html.match(/this device/g).length, 1);
  assert.ok(!html.includes('<img'), 'label escaped');
  assert.match(html, /signed in /);
  const es = sessionListHTML(one, createCopy({lang: 'es', strings: {'account.sessions.since': 'sesión iniciada el {date}', 'account.sessions.current': 'este dispositivo'}}));
  assert.match(es, /este dispositivo/); assert.match(es, /sesión iniciada el /);
});

test('the other-devices button is hidden with one session and shown with two', async () => {
  const s = section(); reset([listing(one), listing(two)]);
  const control = createSessionControl({$: s.$, alive: () => true});
  await control.refresh();
  assert.equal(s.button.hidden, true); assert.match(s.list.innerHTML, /Chrome on Mac/);
  await control.refresh();
  assert.equal(s.button.hidden, false); assert.match(s.list.innerHTML, /Safari on iPhone/);
});

test('a failed or malformed read says the list could not be loaded and shows no action', async () => {
  for (const reply of ['network', {ok: false, status: 500, body: {error: 'x'}}, {bad: true}, listing([]), listing([row('A'), row('B')]), listing([{...row('A', true), expires_at: 'soon'}])]) {
    const s = section(); reset([reply]);
    await createSessionControl({$: s.$, alive: () => true}).refresh();
    assert.equal(s.note.textContent, 'The list could not be loaded.');
    assert.equal(s.button.hidden, true); assert.equal(s.list.innerHTML, '');
  }
});

test('confirming signs out the others once, says how many and redraws', async () => {
  const s = section(); reset([listing(two)]);
  const control = createSessionControl({$: s.$, alive: () => true});
  await control.refresh();
  script.push({body: {ended: 1}}, listing(one));
  s.button.fire('click'); s.button.fire('click');   // a second press while asking sends nothing more
  const box = confirmBox(s);
  assert.equal(s.wrap.children.filter(c => c.className === 'account-confirm').length, 1);
  box.box.yes.dataset = {confirm: 'yes'};
  box.fire('click', {target: {closest: () => box.box.yes}});
  await settle(); await settle();
  const posts = calls.filter(c => c.method === 'POST');
  assert.equal(posts.length, 1); assert.ok(posts[0].url.endsWith('/api/auth/sessions/end-others')); assert.equal(posts[0].body, '{}');
  assert.equal(s.note.textContent, 'Signed out 1 other device.');
  assert.equal(s.button.hidden, true); assert.ok(!s.list.innerHTML.includes('iPhone'));
  assert.equal(document.activeElement, s.note);
});

test('focus stays on another field when the sign-out hides the action, whether the refresh works or fails', async () => {
  for (const refresh of [listing(one), 'network']) {
    const s = section(), field = new El('input'); reset([listing(two)]);
    await createSessionControl({$: s.$, alive: () => true}).refresh();
    // The owner tabs into a field while the sign-out request is in flight.
    script.push(async () => { field.focus(); return {body: {ended: 1}}; }, refresh);
    s.button.fire('click'); const box = confirmBox(s);
    box.fire('click', {target: {closest: () => ({dataset: {confirm: 'yes'}})}});
    await settle(); await settle();
    assert.equal(s.button.hidden, true);
    assert.equal(document.activeElement, field, 'focus elsewhere is preserved');
    assert.notEqual(document.activeElement, s.note);
  }
});

test('focus moves to the status line when the action held it and a failed refresh hides it', async () => {
  const s = section(); reset([listing(two)]);
  await createSessionControl({$: s.$, alive: () => true}).refresh();
  script.push({body: {ended: 1}}, 'network');
  s.button.fire('click'); const box = confirmBox(s);
  box.fire('click', {target: {closest: () => ({dataset: {confirm: 'yes'}})}});
  await settle(); await settle();
  assert.equal(s.button.hidden, true); assert.equal(document.activeElement, s.note);
});

test('cancel and Escape send nothing and keep the list', async () => {
  for (const how of ['cancel', 'escape']) {
    const s = section(); reset([listing(two)]);
    await createSessionControl({$: s.$, alive: () => true}).refresh();
    s.button.fire('click');
    const box = confirmBox(s);
    if (how === 'cancel') { box.box.no.dataset = {confirm: 'no'}; box.fire('click', {target: {closest: () => box.box.no}}); }
    else box.fire('keydown', {key: 'Escape', preventDefault() {}, stopPropagation() {}});
    await settle();
    assert.equal(calls.filter(c => c.method === 'POST').length, 0);
    assert.equal(s.button.hidden, false); assert.match(s.list.innerHTML, /iPhone/); assert.equal(document.activeElement, s.button);
  }
});

test('the count is the answer, plural for none or many, and a failed refresh keeps it with a warning', async () => {
  for (const [ended, text] of [[0, 'Signed out 0 other devices.'], [3, 'Signed out 3 other devices.']]) {
    const s = section(); reset([listing(two)]);
    const control = createSessionControl({$: s.$, alive: () => true}); await control.refresh();
    script.push({body: {ended}}, 'network');
    s.button.fire('click'); const box = confirmBox(s);
    box.fire('click', {target: {closest: () => ({dataset: {confirm: 'yes'}})}});
    await settle(); await settle();
    assert.equal(s.note.textContent, text + ' The list could not be loaded.');
    assert.equal(s.button.hidden, true); assert.equal(s.list.innerHTML, '');
  }
});

test('a failed or malformed sign-out claims no success and leaves the action to retry', async () => {
  for (const reply of ['network', {ok: false, status: 500, body: {error: 'x'}}, {body: {ended: -1}}, {body: {}}]) {
    const s = section(); reset([listing(two)]);
    await createSessionControl({$: s.$, alive: () => true}).refresh();
    script.push(reply);
    s.button.fire('click'); const box = confirmBox(s);
    box.fire('click', {target: {closest: () => ({dataset: {confirm: 'yes'}})}});
    await settle(); await settle();
    assert.equal(s.note.textContent, 'Other devices could not be signed out.');
    assert.equal(s.button.hidden, false); assert.match(s.list.innerHTML, /iPhone/);
    assert.equal(calls.length, 2, 'no refresh after a failed write');
  }
});

test('a read or confirmation that outlives the dialog changes and sends nothing', async () => {
  let open = true, release;
  const s = section(); reset([() => new Promise(resolve => { release = () => resolve(listing(two)); })]);
  const pending = createSessionControl({$: s.$, alive: () => open}).refresh();
  open = false; release(); await pending;
  assert.equal(s.list.innerHTML, ''); assert.equal(s.note.textContent, '');
  open = true; const t = section(); reset([listing(two)]);
  await createSessionControl({$: t.$, alive: () => open}).refresh();
  t.button.fire('click'); open = false;
  const box = confirmBox(t);
  box.fire('click', {target: {closest: () => ({dataset: {confirm: 'yes'}})}});
  await settle();
  assert.equal(calls.filter(c => c.method === 'POST').length, 0);
});

test('the passkey-removal caveat is catalogue copy in English and Spanish', () => {
  assert.match(createCopy()('account.sessions.passkeyNote'), /stay signed in until you sign them out here/);
  assert.equal(typeof createCopy({lang: 'es'})('account.sessions.endOthers'), 'string');
});
