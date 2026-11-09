// RF0753-1 (audit F-23): the account dialog is usable from the keyboard. Focus moves into the card on open,
// Tab and Shift+Tab stay inside it, Escape and a click on the scrim itself close it (a click in the card does not).
// A tiny fake DOM stands in for the browser; no dependency.
import test from 'node:test';
import assert from 'node:assert/strict';

const FOCUS_TAGS = new Set(['BUTTON', 'INPUT', 'SUMMARY', 'A']);
class El {
  constructor(tag, id = '') {
    this.tagName = tag.toUpperCase(); this.id = id; this.children = []; this.parentElement = null;
    this.attrs = {}; this.listeners = {}; this.disabled = false; this.open = false; this.tabIndex = -1;
    this.classes = new Set(); this.classList = {add: c => this.classes.add(c), remove: c => this.classes.delete(c)};
    this.removed = false;
  }
  set className(v) { this.classes = new Set(v.split(' ')); }
  append(child) { child.parentElement = this; this.children.push(child); return child; }
  remove() { this.removed = true; if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(c => c !== this); }
  hasAttribute(name) { return name in this.attrs; }
  contains(el) { for (let n = el; n; n = n.parentElement) if (n === this) return true; return false; }
  all() { return this.children.flatMap(c => [c, ...c.all()]); }
  focusable() { return FOCUS_TAGS.has(this.tagName) || this.tabIndex >= 0; }
  querySelectorAll() { return this.all().filter(e => e.focusable()); }   // only ever asked for the focusable selector
  querySelector(sel) {
    return this.all().find(e => (sel[0] === '#' ? e.id === sel.slice(1) : sel[0] === '.' ? e.classes.has(sel.slice(1)) : false)) ?? null;
  }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  focus() { document.activeElement = this; }
  fire(type, event) { for (const fn of this.listeners[type] ?? []) fn(event); }
  // Only the shapes openAccount writes: h1#id, input#id, button#id.
  set innerHTML(html) {
    for (const gone of this.children) gone.parentElement = null;   // a removed node is no longer in the card, as in a browser
    if (this.contains(document.activeElement) && document.activeElement !== this) document.activeElement = document.body;   // and loses focus
    this.children = [];
    if (!this.classes.has("account-scrim")) for (const m of String(html).matchAll(/<(h1|input|button)\b[^>]*?id="([^"]+)"/g)) this.append(new El(m[1], m[2]));
    if (this.classes.has('account-scrim')) {
      const card = this.append(new El('section')); card.classes.add('account-card');
      const body = card.append(new El('div', 'account-body')); body.append(new El('h1', 'account-title'));
      card.append(new El('button')).classes.add('home-port-close');
    }
  }
}

const document = {body: new El('body'), activeElement: null, createElement: tag => new El(tag)};
document.activeElement = document.body;
globalThis.document = document;
globalThis.location = {hash: '', pathname: '/', search: ''};
globalThis.history = {replaceState() {}};
let sessionReply = () => new Promise(() => {});   // default: the session request never settles, so the dialog stays on "checking"
globalThis.fetch = (...args) => sessionReply(...args);

const {openAccount, dialogFocusables, keepFocusIn} = await import('../dist/account.js');

const tab = (shiftKey = false) => ({key: 'Tab', shiftKey, prevented: false, preventDefault() { this.prevented = true; }});
const key = k => ({key: k, prevented: false, preventDefault() { this.prevented = true; }});

async function opened(settled = false) {
  const trigger = document.body.append(new El('button', 'masthead-account')); trigger.focus();
  const pending = openAccount({});   // the default pending session request keeps it open
  if (settled) await pending;
  const scrim = document.body.children.find(c => c.classes.has('account-scrim'));
  return {trigger, scrim, card: scrim.querySelector('.account-card'), pending};
}

test('focus_moves_into_the_card_on_open', async () => {
  const {scrim, card} = await opened();
  assert.equal(document.activeElement.id, 'account-title');
  assert.ok(card.contains(document.activeElement));
  assert.equal(document.activeElement.tabIndex, -1);
  scrim.fire('keydown', key('Escape'));
});

test('escape_closes_and_restores_focus', async () => {
  const {trigger, scrim} = await opened();
  const event = key('Escape');
  scrim.fire('keydown', event);
  assert.ok(scrim.removed && event.prevented);
  assert.equal(document.activeElement, trigger);
});

test('scrim_click_closes_card_click_does_not', async () => {
  let {scrim, card} = await opened();
  scrim.fire('click', {target: card.querySelector('#account-title')});
  scrim.fire('click', {target: card});
  assert.equal(scrim.removed, false, 'a click inside the card must not close it');
  scrim.fire('click', {target: scrim});
  assert.equal(scrim.removed, true);
  ({scrim} = await opened());   // reopens after a close
  scrim.fire('keydown', key('Escape'));
});

test('tab_from_last_wraps_to_first_and_shift_tab_from_first_wraps_to_last', () => {
  const root = new El('section');
  const [a, b, c] = ['a', 'b', 'c'].map(id => root.append(new El('button', id)));
  c.focus(); let e = tab();
  assert.equal(keepFocusIn(root, e, c), true); assert.ok(e.prevented); assert.equal(document.activeElement, a);
  a.focus(); e = tab(true);
  assert.equal(keepFocusIn(root, e, a), true); assert.ok(e.prevented); assert.equal(document.activeElement, c);
  b.focus(); e = tab();
  assert.equal(keepFocusIn(root, e, b), false); assert.equal(e.prevented, false); assert.equal(document.activeElement, b);
  e = key('ArrowDown');
  assert.equal(keepFocusIn(root, e, c), false); assert.equal(e.prevented, false);
});

test('tab_with_focus_outside_the_card_comes_back_in', () => {
  const root = new El('section');
  const first = root.append(new El('button', 'first')), last = root.append(new El('button', 'last'));
  const outside = new El('button', 'masthead'); outside.focus();
  assert.equal(keepFocusIn(root, tab(), outside), true); assert.equal(document.activeElement, first);
  outside.focus();
  assert.equal(keepFocusIn(root, tab(true), outside), true); assert.equal(document.activeElement, last);
});

test('hidden_disabled_and_closed_details_are_skipped', () => {
  const root = new El('section');
  const off = root.append(new El('button', 'off')); off.disabled = true;
  const hid = root.append(new El('input', 'hid')); hid.attrs.hidden = '';
  const details = root.append(new El('details'));
  const summary = details.append(new El('summary', 'sum'));
  const inner = details.append(new El('input', 'inner'));
  const ok = root.append(new El('button', 'ok'));
  assert.deepEqual(dialogFocusables(root).map(e => e.id), ['sum', 'ok']);
  details.open = true;
  assert.deepEqual(dialogFocusables(root).map(e => e.id), ['sum', 'inner', 'ok']);
  assert.ok(summary && inner && ok);
});

test('no_focusables_is_safe', () => {
  const root = new El('section'); const title = root.append(new El('h1', 'account-title')); title.tabIndex = -1;
  const e = tab();
  assert.equal(keepFocusIn(root, e, document.body), true);
  assert.ok(e.prevented); assert.equal(document.activeElement, title);
});

// A resolved session response repaints the card and removes the focused title: focus must land on the new title
// (a connected element in the card), so Tab stays trapped and Escape still reaches the scrim.
const reply = body => () => Promise.resolve({ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body)});
for (const [name, fetchImpl, expected] of [
  ['sign_in_disabled', reply({signIn: false}), 'account-title'],
  ['offline', () => Promise.reject(new Error('offline')), 'account-title'],
]) {
  test(`resolved_session_${name}_keeps_focus_in_the_card_so_tab_and_escape_work`, async () => {
    sessionReply = fetchImpl;
    try {
      const {trigger, scrim, card} = await opened(true);
      const body = card.querySelector('#account-body');
      assert.ok(body.contains(document.activeElement), 'focus is inside the repainted body, not on document.body');
      assert.equal(document.activeElement.id, expected);
      assert.notEqual(document.activeElement, document.body);
      const e = tab();
      scrim.fire('keydown', e);   // no focusables in the card body other than close: Tab must wrap, not escape
      assert.ok(card.contains(document.activeElement), 'Tab keeps focus in the card');
      const esc = key('Escape');
      scrim.fire('keydown', esc);
      assert.ok(scrim.removed && esc.prevented);
      assert.equal(document.activeElement, trigger);
    } finally { sessionReply = () => new Promise(() => {}); }
  });
}
