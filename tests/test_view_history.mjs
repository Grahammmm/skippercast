// SC1722-09: a press that changes the app view pushes one browser-history entry, a press on the shown view
// pushes none, and query-only changes keep replacing. The real ViewNav, ReportsLink and PlanLink callbacks run
// against the real store, with a recording in-memory history and the popstate listener real startURLSync registers.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const BLANK = 'https://s.test/blank';
const MAP = 'https://s.test/map?region=morro-bay';

let mod;
async function load() {
  if (mod) return mod;
  const outfile = join(await mkdtemp(join(tmpdir(), 'view-history-')), 'bundle.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {ViewNav} from './web/app/Masthead.tsx';
    export {ReportsLink, viewDetent} from './web/app/Mobile.tsx';
    export {PlanLink} from './web/app/PlanView.tsx';
    export {appView, setParams, startURLSync, syncFromURL} from './web/state.ts';`},
  outfile, bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins, logLevel: 'silent'});
  mod = await import(pathToFileURL(outfile).href);
  return mod;
}

// The recording history: entries[], an index, and every write counted by kind. Back/Forward move the index,
// set the address and call the listener startURLSync registered, as the browser does.
const listeners = {};
const env = {entries: [], index: 0, pushes: 0, replaces: 0};
function reset(href = MAP) {
  env.entries = [BLANK, href]; env.index = 1; env.pushes = 0; env.replaces = 0;
  globalThis.location.href = href;
}
const go = delta => { env.index += delta; globalThis.location.href = env.entries[env.index]; listeners.popstate(); };
const url = () => new URL(location.href);

const saved = {};
const GLOBALS = ['window', 'location', 'history', 'addEventListener', 'dispatchEvent', 'HashChangeEvent'];
async function install() {
  const m = await load();
  if (!saved.done) { for (const k of GLOBALS) saved[k] = Object.getOwnPropertyDescriptor(globalThis, k); saved.done = true; }
  const set = (k, value) => Object.defineProperty(globalThis, k, {value, configurable: true, writable: true});
  set('window', globalThis);
  set('location', {href: MAP});
  set('history', {
    state: null,
    pushState(_s, _t, href) { env.pushes += 1; env.entries.splice(env.index + 1, Infinity, new URL(href, location.href).href); env.index += 1; location.href = env.entries[env.index]; },
    replaceState(_s, _t, href) { env.replaces += 1; env.entries[env.index] = new URL(href, location.href).href; location.href = env.entries[env.index]; },
  });
  set('addEventListener', (name, fn) => { listeners[name] = fn; });
  set('dispatchEvent', () => true);
  set('HashChangeEvent', class HashChangeEvent { constructor(type, init) { this.type = type; Object.assign(this, init); } });
  reset();
  m.startURLSync();
  m.syncFromURL();
  return m;
}
function restore() {
  for (const k of GLOBALS) { if (saved[k]) Object.defineProperty(globalThis, k, saved[k]); else delete globalThis[k]; }
  saved.done = false;
}

// Collect the element vnodes of a rendered component tree that carry an onClick (the anchors), without rendering to a DOM.
function anchors(vnode, out = []) {
  if (vnode == null || typeof vnode !== 'object') return out;
  if (Array.isArray(vnode)) { vnode.forEach(child => anchors(child, out)); return out; }
  if (typeof vnode.type === 'function') return out;
  if (vnode.type === 'a' && vnode.props.onClick) out.push(vnode.props);
  anchors(vnode.props?.children, out);
  return out;
}
const click = (props, extra = {}) => { const e = {button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...extra, prevented: false, preventDefault() { this.prevented = true; }}; props.onClick(e); return e; };
const tab = (m, view, icons) => anchors(m.ViewNav({icons})).find(p => p['data-view'] === view);
const counts = () => [env.pushes, env.replaces, env.entries.length];

test('desktop and phone tabs: Conditions, then History, then Back shows Conditions and Back again Coast, Forward returns', async () => {
  const m = await install();
  try {
    for (const icons of [false, true]) {
      reset(); m.syncFromURL();
      assert.equal(m.appView.value, 'coast');
      assert.ok(click(tab(m, 'conditions', icons)).prevented);
      assert.ok(click(tab(m, 'history', icons)).prevented);
      assert.deepEqual(counts(), [2, 0, 4], `icons ${icons}: exactly two pushes`);
      assert.equal(url().searchParams.get('view'), 'history');
      assert.equal(m.appView.value, 'history');
      go(-1);
      assert.equal(m.appView.value, 'conditions'); assert.equal(url().searchParams.get('view'), 'conditions');
      assert.equal(url().searchParams.get('region'), 'morro-bay');
      go(-1);
      assert.equal(m.appView.value, 'coast'); assert.equal(url().searchParams.get('view'), null);
      assert.equal(env.entries[env.index], MAP);
      go(1); assert.equal(m.appView.value, 'conditions');
      go(1); assert.equal(m.appView.value, 'history');
      assert.deepEqual(counts(), [2, 0, 4], `icons ${icons}: Back and Forward write nothing`);
    }
  } finally { restore(); }
});

test('a press on the shown view adds no entry: Coast by missing, explicit and invalid view, and a stale captured callback', async () => {
  const m = await install();
  try {
    for (const start of [MAP, `${MAP}&view=coast`, `${MAP}&view=nonsense`]) {
      reset(start); m.syncFromURL();
      assert.equal(m.appView.value, 'coast', start);
      click(tab(m, 'coast', false)); click(tab(m, 'coast', true));
      assert.deepEqual(counts(), [0, 0, 2], start);
      assert.equal(location.href, start, 'the address is not canonicalized by a same-view press');
    }
    reset(); m.syncFromURL();
    const staleCoast = tab(m, 'coast', false), conditions = tab(m, 'conditions', false);
    click(conditions); click(conditions);          // the same freshly changed tab, twice, from one render closure
    assert.deepEqual(counts(), [1, 0, 3], 'double activation of one changed tab pushes once');
    click(conditions);
    click(staleCoast);                              // rendered while Coast was shown: the live view decides
    assert.deepEqual(counts(), [2, 0, 4], 'a stale callback for the view no longer shown still changes the view once');
    assert.equal(m.appView.value, 'coast');
    click(staleCoast);
    assert.deepEqual(counts(), [2, 0, 4]);
  } finally { restore(); }
});

test('Reports footer link and Plan link push once from another view, restore on Back, and repeat as a no-op', async () => {
  const m = await install();
  try {
    for (const [view, Link] of [['reports', m.ReportsLink], ['plan', m.PlanLink]]) {
      reset(); m.syncFromURL();
      const props = anchors(Link())[0];
      assert.ok(click(props).prevented);
      assert.equal(m.appView.value, view); assert.equal(url().searchParams.get('view'), view);
      click(props); click(anchors(Link())[0]);
      assert.deepEqual(counts(), [1, 0, 3], `${view}: one push, repeats add none`);
      go(-1);
      assert.equal(m.appView.value, 'coast', view);
      assert.equal(env.entries[env.index], MAP);
    }
    // Reports from Conditions goes back to Conditions.
    reset(`${MAP}&view=conditions`); m.syncFromURL();
    click(anchors(m.ReportsLink())[0]); go(-1);
    assert.equal(m.appView.value, 'conditions');
  } finally { restore(); }
});

test('Plan link keeps native handling for modified and non-primary clicks', async () => {
  const m = await install();
  try {
    reset(); m.syncFromURL();
    const props = anchors(m.PlanLink())[0];
    for (const extra of [{ctrlKey: true}, {metaKey: true}, {shiftKey: true}, {altKey: true}, {button: 1}]) {
      const e = click(props, extra);
      assert.equal(e.prevented, false, JSON.stringify(extra));
    }
    assert.deepEqual(counts(), [0, 0, 2]); assert.equal(m.appView.value, 'coast');
  } finally { restore(); }
});

test('hour, area, layer, profile and target changes replace; Back restores the entry holding them; other query and hash are kept', async () => {
  const m = await install();
  try {
    reset(`${MAP}&keep=1#spot`); m.syncFromURL();
    click(tab(m, 'conditions', false));
    assert.deepEqual(counts(), [1, 0, 3]);
    const patches = [{hour: '2026-10-13T12:00Z'}, {area: 'morro-rock'}, {layers: 'wind'}, {profile: 'kayak'}, {target: 'halibut'}];
    patches.forEach((patch, i) => {
      m.setParams(patch);
      assert.deepEqual(counts(), [1, i + 1, 3], JSON.stringify(patch));
    });
    assert.equal(url().hash, '#spot'); assert.equal(url().searchParams.get('keep'), '1');
    assert.equal(url().searchParams.get('view'), 'conditions');
    click(tab(m, 'history', false));
    assert.deepEqual(counts(), [2, 5, 4]);
    assert.equal(url().searchParams.get('hour'), '2026-10-13T12:00Z'); assert.equal(url().hash, '#spot'); assert.equal(url().searchParams.get('keep'), '1');
    go(-1);
    assert.equal(m.appView.value, 'conditions');
    for (const [k, v] of [['hour', '2026-10-13T12:00Z'], ['area', 'morro-rock'], ['layers', 'wind'], ['profile', 'kayak'], ['target', 'halibut']]) assert.equal(url().searchParams.get(k), v, k);
    go(-1);
    assert.equal(m.appView.value, 'coast'); assert.equal(url().searchParams.get('hour'), null);
    assert.equal(url().hash, '#spot');
  } finally { restore(); }
});

test('Back to History from a peeked sheet opens it full through viewDetent; Back to other views leaves the detent', async () => {
  const m = await install();
  try {
    reset(); m.syncFromURL();
    click(tab(m, 'history', true)); click(tab(m, 'conditions', true));
    go(-1);
    assert.equal(m.appView.value, 'history');
    assert.equal(m.viewDetent(m.appView.value, 'peek'), 'full');
    assert.equal(m.viewDetent(m.appView.value, 'half'), 'half');
    go(1);
    assert.equal(m.appView.value, 'conditions');
    for (const d of ['peek', 'half', 'full']) assert.equal(m.viewDetent(m.appView.value, d), d);
  } finally { restore(); }
});
