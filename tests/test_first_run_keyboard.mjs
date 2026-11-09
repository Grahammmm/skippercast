// RF0753-2 (audit F-01): the map's first-run card ("How do you fish?") is reachable and
// dismissable from the keyboard and stays non-modal (FE-08, D11). On desktop it focuses its
// heading when it opens, so the next Tab reaches the profile buttons; on the phone it moves
// no focus (the sheet expands when a first-run element is focused). Escape inside the card
// does what "Keep Boat for now" does. No trap, no aria-modal.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'first-run-keyboard-')), 'first-run-keyboard.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {FirstRun, boatEntryOpen} from './web/app/FirstRun.tsx';
      export {configureStore} from './web/state.ts';
      export {h, render as renderDOM} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

function memory(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {map, getItem: k => (map.has(k) ? map.get(k) : null), setItem: (k, v) => { map.set(k, String(v)); }, removeItem: k => { map.delete(k); }};
}

// A fake element tree that records focus() calls and keeps real keydown listeners.
const doc = {activeElement: null, focusCalls: []};
class El {
  constructor(name) { Object.assign(this, {nodeType: 1, nodeName: name.toUpperCase(), localName: name, childNodes: [], parentNode: null, style: {}, attrs: {}, listeners: {}, tabIndex: null}); }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  remove() { this.parentNode?.removeChild(this); }
  removeChild(c) { this.childNodes.splice(this.childNodes.indexOf(c), 1); c.parentNode = null; return c; }
  insertBefore(c, ref) { c.parentNode?.removeChild(c); const i = ref ? this.childNodes.indexOf(ref) : -1; this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, c); c.parentNode = this; return c; }
  appendChild(c) { return this.insertBefore(c, null); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  // Preact keeps the case of an event it cannot find as an `on...` property (KeyDown) and looks its handler up under that case, so the event carries it back.
  addEventListener(type, fn) { const wrapped = ev => { ev.type = type; return fn.call(this, ev); }; wrapped.fn = fn; (this.listeners[type.toLowerCase()] ??= []).push(wrapped); }
  removeEventListener(type, fn) { const k = type.toLowerCase(); this.listeners[k] = (this.listeners[k] ?? []).filter(f => f.fn !== fn); }
  focus(options) { doc.focusCalls.push({el: this, options}); doc.activeElement = this; }
}
const walk = (el, out = []) => { out.push(el); el.childNodes.forEach(c => walk(c, out)); return out; };
const text = el => el.nodeType === 3 ? el.data : el.childNodes.map(text).join('');
const tick = (ms = 0) => new Promise(resolve => setTimeout(resolve, ms));

const MAP = 'https://s.test/map?region=morro-bay';

/** Mount `vnode`, hand `run` the root and a keydown dispatcher, and restore every global afterwards. */
async function mounted(m, vnode, storage, run) {
  const saved = Object.fromEntries(['document', 'localStorage', 'location', 'history', 'sessionStorage'].map(k => [k, globalThis[k]]));
  const root = new El('div');
  const body = new El('body');
  Object.assign(doc, {activeElement: body, focusCalls: []});
  globalThis.document = {...doc, createElement: n => new El(n), createElementNS: (_, n) => new El(n), createTextNode: t => Object.assign(new El('text'), {nodeType: 3, data: String(t)})};
  Object.defineProperty(globalThis.document, 'activeElement', {get: () => doc.activeElement, configurable: true});
  globalThis.localStorage = storage;
  globalThis.sessionStorage = memory();
  globalThis.location = {href: MAP};
  globalThis.history = {state: null, replaceState: (_s, _t, url) => { globalThis.location.href = new URL(url, globalThis.location.href).href; }, pushState() {}};
  const key = (el, init) => {
    const event = {type: 'keydown', key: '', shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}, ...init, target: el, currentTarget: el};
    (el.listeners.keydown ?? []).forEach(fn => fn.call(el, event));
    return event;
  };
  try {
    m.renderDOM(vnode, root);
    await tick(50);   // mount effects run after the next frame (Preact's 35 ms fallback without requestAnimationFrame)
    return await run({root, body, key, nodes: () => walk(root), section: walk(root).find(e => e.localName === 'section'), heading: () => walk(root).find(e => e.attrs.id === 'first-run-title' || e.id === 'first-run-title')});
  } finally {
    m.renderDOM(null, root);
    for (const [k, v] of Object.entries(saved)) { if (v === undefined) delete globalThis[k]; else globalThis[k] = v; }
  }
}

const profileOf = () => new URL(globalThis.location.href).searchParams.get('profile');
const card = (m, storage, focusOnOpen) => m.h(m.FirstRun, {href: MAP, storage, cookies: null, ...(focusOnOpen === undefined ? {} : {focusOnOpen})});

async function fresh(initial) {
  const m = await load();
  const storage = memory(initial);
  m.configureStore({storage});
  return {m, storage};
}

test('desktop_open_focuses_the_heading', async () => {
  const {m, storage} = await fresh();
  await mounted(m, card(m, storage, true), storage, async ({heading, section, body}) => {
    const h2 = heading();
    assert.ok(h2 && h2.localName === 'h2', 'the card has its heading');
    assert.ok(doc.activeElement === h2, 'focus is on the heading after open');
    assert.ok(doc.activeElement !== body, 'focus left the body');
    assert.equal(String(h2.tabIndex ?? h2.attrs.tabindex ?? h2.attrs.tabIndex), '-1', 'focusable by script, not a tab stop');
    assert.equal(doc.focusCalls.length, 1, 'focused once');
    assert.equal(doc.focusCalls[0].options?.preventScroll, true, 'the map does not scroll');
    // Never modal (D11): still a plain dialog section, no aria-modal, no trap handler for Tab.
    assert.equal(section.attrs.role, 'dialog');
    assert.equal(section.attrs['aria-modal'], undefined);
    assert.ok(!Object.keys(section.listeners).some(k => k === 'focusout' || k === 'focusin'), 'no focus trap');
  });
});

test('phone_open_moves_no_focus', async () => {
  const {m, storage} = await fresh();
  for (const prop of [undefined, false]) {
    await mounted(m, card(m, storage, prop), storage, async ({heading, body}) => {
      assert.ok(heading(), 'the card is shown');
      assert.equal(doc.focusCalls.length, 0, `focusOnOpen=${prop}: no focus call`);
      assert.ok(doc.activeElement === body, 'focus is unchanged');
    });
  }
});

test('escape_keeps_boat', async () => {
  const {m, storage} = await fresh();
  await mounted(m, card(m, storage, true), storage, async ({root, section, key}) => {
    assert.equal(profileOf(), null, 'nothing written before Escape');
    const event = key(section, {key: 'Escape'});
    await tick(50);
    assert.equal(event.defaultPrevented, true);
    assert.equal(profileOf(), 'boat', 'Escape writes ?profile=boat like Keep Boat for now');
    assert.equal(text(root), '', 'the card is gone');
    assert.equal(root.childNodes.length, 0);
    assert.equal(m.boatEntryOpen.value, false, 'keeping Boat asks nothing more: BoatEntry does not open');
  });
});

test('escape_with_modifier_or_other_key_does_nothing', async () => {
  const {m, storage} = await fresh();
  await mounted(m, card(m, storage, true), storage, async ({root, section, key}) => {
    for (const init of [{key: 'Escape', shiftKey: true}, {key: 'Escape', ctrlKey: true}, {key: 'Escape', altKey: true}, {key: 'Escape', metaKey: true}, {key: 'Enter'}, {key: 'a'}, {key: 'Tab'}]) {
      const event = key(section, init);
      await tick(20);
      assert.equal(event.defaultPrevented, false, JSON.stringify(init));
      assert.equal(profileOf(), null, `${JSON.stringify(init)}: no params written`);
      assert.match(text(root), /How do you fish\?/, `${JSON.stringify(init)}: the card is still due`);
    }
  });
});

test('not_due_renders_no_focus_and_no_handler', async () => {
  const {m, storage} = await fresh({'skippercast-profile-v1': 'shore'});
  await mounted(m, card(m, storage, true), storage, async ({root, nodes}) => {
    assert.equal(text(root), '');
    assert.equal(doc.focusCalls.length, 0, 'no focus call');
    assert.ok(nodes().every(e => !(e.listeners.keydown ?? []).length), 'no keydown handler');
    assert.equal(profileOf(), null);
  });
});

test('notice_section_unchanged', async () => {
  const {m, storage} = await fresh();
  await mounted(m, card(m, storage, true), storage, async ({root, nodes, section}) => {
    // Boat, then Save with a limit the store clamps: the card closes and a notice-only section stays.
    const boat = nodes().find(e => e.localName === 'button' && e.attrs['data-profile'] === 'boat');
    const clicks = boat.listeners.click ?? [];
    assert.ok(clicks.length, 'the Boat button is wired');
    clicks.forEach(fn => fn.call(boat, {type: 'click', preventDefault() {}, currentTarget: boat, target: boat}));
    await tick(50);
    const input = walk(root).find(e => e.localName === 'input' && e.attrs.name === 'wind');
    assert.ok(input, 'the boat step opened');
    (input.listeners.input ?? []).forEach(fn => fn.call(input, {type: 'input', currentTarget: {value: '99'}, target: {value: '99'}}));
    await tick(20);
    const form = walk(root).find(e => e.localName === 'form');
    (form.listeners.submit ?? []).forEach(fn => fn.call(form, {type: 'submit', preventDefault() {}, currentTarget: form, target: form}));
    await tick(50);
    const notice = walk(root).find(e => e.localName === 'section');
    assert.ok(notice && /Wind limit saved as 20 kt\./.test(text(notice)), text(root));
    assert.ok(notice !== section, 'the card was replaced');
    assert.equal(notice.attrs.role, undefined, 'the notice section is not a dialog');
    assert.ok(!(notice.listeners.keydown ?? []).length, 'no keydown handler on the notice');
    assert.ok(walk(root).every(e => !(e.listeners.keydown ?? []).length));
  });
});
