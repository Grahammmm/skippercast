// MYB-1: the optional boat length and comfort limits on the first-use
// "How do you fish?" step (web/boat-entry.ts, web/landing/ProfileStep.tsx,
// web/app/FirstRun.tsx). Blank fields change nothing; a valid length writes
// the local boat; limits clamp through web/limits.ts; a storage failure never
// blocks the profile choice.
import assert from 'node:assert/strict';
import test from 'node:test';
import util from 'node:util';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'boat-entry-')), 'boat-entry.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {saveFirstUse, ENTRY_COPY, ENTRY_FIELDS, carryNotices, takeNotices, withoutNotice} from './web/boat-entry.ts';
      export {ProfileStep} from './web/landing/ProfileStep.tsx';
      export {FirstRun} from './web/app/FirstRun.tsx';
      export {configureStore, STORAGE_KEYS} from './web/state.ts';
      export {loadLimits, savedLimits} from './web/limits.ts';
      export {defaultLimits} from './packages/coast/src/limits.ts';
      export {BOAT_KEY, savedBoat, boatFactors} from './dist/boat-handling.js';
      export {render} from 'preact-render-to-string';
      export {h, render as renderDOM, options} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

function memory(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {map, getItem: k => (map.has(k) ? map.get(k) : null), setItem: (k, v) => { map.set(k, String(v)); }};
}
const broken = () => ({getItem() { throw new Error('denied'); }, setItem() { throw new Error('QuotaExceededError'); }});
const snapshot = s => JSON.stringify([...s.map.entries()].sort());

async function fresh(initial) {
  const m = await load();
  const storage = memory(initial);
  m.configureStore({storage});
  m.savedLimits.value = {};
  return {m, storage};
}

test('blank fields leave storage untouched byte for byte', async () => {
  const boat = JSON.stringify({schema_version: 1, boat: {name: 'Ruby', loa_ft: 26}, query: 'x', preset: null, saved_at: 't', lookup: null});
  const {m, storage} = await fresh({'skippercast-boat-v1': boat, 'skippercast-limits-v1': '{"boat":{"wind":12,"gust":18,"seas":4}}'});
  const before = snapshot(storage);
  for (const entry of [{}, {lengthFt: '', wind: '', seas: ''}, {lengthFt: '  ', wind: ' ', seas: undefined}]) {
    const result = m.saveFirstUse({...entry, profile: 'boat'}, storage);
    assert.ok(util.isDeepStrictEqual(result, {boat: false, notices: []}), JSON.stringify(result));
  }
  assert.equal(snapshot(storage), before);
});

test('a valid length on empty storage writes a schema 1 boat that changes the rating factors', async () => {
  const {m, storage} = await fresh();
  const old = globalThis.localStorage;
  globalThis.localStorage = storage;
  try {
    assert.equal(m.saveFirstUse({lengthFt: '19', profile: 'boat'}, storage).boat, true);
    const saved = m.savedBoat();
    assert.equal(saved.schema_version, 1);
    assert.equal(saved.boat.loa_ft, 19);
    assert.equal(saved.boat.name, '19 ft boat');
    assert.equal(saved.query, ''); assert.equal(saved.preset, null); assert.equal(saved.lookup, null);
    assert.equal(typeof saved.saved_at, 'string');
    const ref = m.boatFactors(null), mine = m.boatFactors(saved.boat);
    assert.ok(mine.sea !== ref.sea && mine.wind !== ref.wind, 'a 19 ft boat is rated differently from the 23 ft reference');
    assert.equal(storage.map.has('skippercast-limits-v1'), false, 'no limits typed: none written');
  } finally {
    if (old === undefined) delete globalThis.localStorage; else globalThis.localStorage = old;
  }
});

test('only a length inside 8-70 ft is written; 19.5 is accepted', async () => {
  for (const bad of ['7', '71', 'abc', '', '-19', '0']) {
    const {m, storage} = await fresh();
    assert.equal(m.saveFirstUse({lengthFt: bad, profile: 'boat'}, storage).boat, false, bad);
    assert.equal(storage.map.size, 0, `${bad}: nothing written`);
  }
  const {m, storage} = await fresh();
  assert.equal(m.saveFirstUse({lengthFt: '19.5', profile: 'boat'}, storage).boat, true);
  assert.equal(JSON.parse(storage.getItem(m.BOAT_KEY)).boat.loa_ft, 19.5);
  assert.equal(m.ENTRY_COPY.lengthHint, 'Boat length 8-70 ft');
});

test('a saved boat keeps its other fields; only an auto-named boat is renamed', async () => {
  const full = {schema_version: 1, boat: {name: '23 ft boat', loa_ft: 23, beam_ft: 8.5, hull: 'modified-v', layout: 'center-console', displacement_lb: 4000},
    query: 'Parker 2320', preset: 'p', saved_at: '2026-01-01T00:00:00Z', lookup: {source: 'x'}};
  let {m, storage} = await fresh({'skippercast-boat-v1': JSON.stringify(full)});
  m.saveFirstUse({lengthFt: '25', profile: 'boat'}, storage);
  let saved = JSON.parse(storage.getItem(m.BOAT_KEY));
  assert.ok(util.isDeepStrictEqual(saved, {...full, boat: {...full.boat, loa_ft: 25, name: '25 ft boat'}}), JSON.stringify(saved));
  ({m, storage} = await fresh({'skippercast-boat-v1': JSON.stringify({...full, boat: {...full.boat, name: 'Ruby'}})}));
  m.saveFirstUse({lengthFt: '25', profile: 'boat'}, storage);
  saved = JSON.parse(storage.getItem(m.BOAT_KEY));
  assert.equal(saved.boat.name, 'Ruby'); assert.equal(saved.boat.loa_ft, 25); assert.equal(saved.boat.hull, 'modified-v');
  assert.equal(saved.query, 'Parker 2320'); assert.equal(saved.saved_at, full.saved_at);
  // An unreadable or other-schema record is replaced by a fresh one, never merged.
  ({m, storage} = await fresh({'skippercast-boat-v1': '{not json'}));
  m.saveFirstUse({lengthFt: '20', profile: 'boat'}, storage);
  assert.equal(JSON.parse(storage.getItem(m.BOAT_KEY)).boat.name, '20 ft boat');
});

test('limits clamp through clampLimits, the clamped value is said back, and defaults store no entry', async () => {
  let {m, storage} = await fresh();
  const result = m.saveFirstUse({wind: '99', seas: '0.2', profile: 'boat'}, storage);
  const saved = JSON.parse(storage.getItem(m.STORAGE_KEYS.limits));
  assert.equal(saved.boat.wind, 20); assert.equal(saved.boat.seas, 1);
  assert.ok(util.isDeepStrictEqual(result.notices, ['Wind limit saved as 20 kt.', 'Seas limit saved as 1 ft.']), JSON.stringify(result.notices));
  // Saved for the profile just chosen only, keeping other profiles' saved limits.
  ({m, storage} = await fresh({'skippercast-limits-v1': '{"boat":{"wind":12,"gust":18,"seas":4}}'}));
  assert.equal(m.saveFirstUse({wind: '10', profile: 'kayak'}, storage).notices.length, 0);
  const both = JSON.parse(storage.getItem(m.STORAGE_KEYS.limits));
  assert.equal(both.kayak.wind, 10); assert.equal(both.boat.wind, 12);
  // Each profile clamps to its own bounds (kayak wind tops out at 12 kt).
  ({m, storage} = await fresh());
  assert.ok(util.isDeepStrictEqual(m.saveFirstUse({wind: '1000', profile: 'kayak'}, storage).notices, ['Wind limit saved as 12 kt.']));
  // Wind at its default writes no entry for the profile.
  ({m, storage} = await fresh());
  assert.equal(m.saveFirstUse({wind: String(m.defaultLimits('boat').wind), profile: 'boat'}, storage).notices.length, 0);
  assert.ok(util.isDeepStrictEqual(JSON.parse(storage.getItem(m.STORAGE_KEYS.limits)), {}), 'default wind: no boat entry');
});

test('storage that throws: no exception, the notice is returned, nothing claims a save', async () => {
  const {m} = await fresh();
  m.configureStore({storage: broken()});
  const result = m.saveFirstUse({lengthFt: '19', wind: '12', seas: '3', profile: 'boat'}, broken());
  assert.equal(result.boat, false);
  assert.ok(result.notices.includes('Could not save the boat in this browser.'), JSON.stringify(result.notices));
  assert.ok(m.saveFirstUse({lengthFt: '19', profile: 'boat'}, null).notices.includes(m.ENTRY_COPY.failed), 'no storage at all');
});

class El {
  constructor(name) { Object.assign(this, {nodeType: 1, nodeName: name.toUpperCase(), localName: name, childNodes: [], parentNode: null, style: {}}); }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  remove() { this.parentNode?.removeChild(this); }
  removeChild(c) { this.childNodes.splice(this.childNodes.indexOf(c), 1); c.parentNode = null; return c; }
  insertBefore(c, ref) { c.parentNode?.removeChild(c); const i = ref ? this.childNodes.indexOf(ref) : -1; this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, c); c.parentNode = this; return c; }
  appendChild(c) { return this.insertBefore(c, null); }
  setAttribute() {} removeAttribute() {} addEventListener() {} removeEventListener() {} focus() {}
}
const text = el => el.nodeType === 3 ? el.data : el.childNodes.map(text).join('');

/** Mount `vnode` on a fake DOM, type `typed` into the boat fields, click profile `p`; returns what happened. */
async function typeAndClick(m, vnode, typed, p, storage) {
  const oldDocument = globalThis.document, oldStorage = globalThis.localStorage, oldHook = m.options.vnode;
  const root = new El('div'); let inputs = {}, buttons = {};
  globalThis.document = {createElement: n => new El(n), createElementNS: (_, n) => new El(n), createTextNode: t => Object.assign(new El('text'), {nodeType: 3, data: String(t)})};
  globalThis.localStorage = storage;
  m.options.vnode = v => { oldHook?.(v); if (v.type === 'input' && v.props.name) inputs[v.props.name] = v.props; if (v.props?.['data-profile']) buttons[v.props['data-profile']] = v.props; };
  try {
    m.renderDOM(vnode, root);
    for (const [name, value] of Object.entries(typed)) {
      inputs[name].onInput({currentTarget: {value}});
      await new Promise(resolve => setTimeout(resolve, 0));
    }
    buttons[p].onClick();
    await new Promise(resolve => setTimeout(resolve, 0));
    return {html: text(root)};
  } finally {
    m.renderDOM(null, root); m.options.vnode = oldHook;
    if (oldDocument === undefined) delete globalThis.document; else globalThis.document = oldDocument;
    if (oldStorage === undefined) delete globalThis.localStorage; else globalThis.localStorage = oldStorage;
  }
}

test('both screens show the same optional boat fields above the profile buttons, in order', async () => {
  const {m, storage} = await fresh();
  const step = m.render(m.h(m.ProfileStep, {place: 'Morro Bay', warm: null, onChoose: () => {}, onBack: () => {}}));
  const first = m.render(m.h(m.FirstRun, {href: 'https://s.test/map', storage, cookies: null}));
  for (const html of [step, first]) {
    assert.ok(util.isDeepStrictEqual([...html.matchAll(/<input[^>]* name="([a-zA-Z]+)"/g)].map(x => x[1]), ['lengthFt', 'wind', 'seas']), html.slice(0, 200));
    assert.ok(util.isDeepStrictEqual([...html.matchAll(/data-profile="([a-z]+)"/g)].map(x => x[1]), ['boat', 'shore', 'spear', 'kayak']));
    assert.ok(html.indexOf('<legend>Your boat (optional)</legend>') > 0 && html.indexOf('<legend>') < html.indexOf('data-profile='), 'fieldset above the buttons');
    assert.ok(html.includes('Boat length makes every rating yours; the rest can wait.'));
    assert.ok(html.includes('Boat length 8-70 ft'));
    assert.doesNotMatch(html, /reference boat/i);
    assert.doesNotMatch(html, /<input[^>]* required/, 'every field optional');
  }
});

test('landing step: a profile click saves the typed boat first and calls onChoose once', async () => {
  const {m, storage} = await fresh();
  const chosen = [];
  let seen = null;
  const onChoose = p => { chosen.push(p); seen = storage.getItem(m.BOAT_KEY); };
  await typeAndClick(m, m.h(m.ProfileStep, {place: 'Morro Bay', warm: null, onChoose, onBack: () => {}}), {lengthFt: '19', wind: '14'}, 'shore', storage);
  assert.ok(util.isDeepStrictEqual(chosen, ['shore']));
  assert.equal(JSON.parse(seen).boat.loa_ft, 19, 'the boat is in storage before onChoose runs');
  assert.equal(JSON.parse(storage.getItem(m.STORAGE_KEYS.limits)).shore.wind, 14, 'limits saved for the profile chosen');
});

test('landing step: blank fields, and storage that throws, still call onChoose once', async () => {
  let {m, storage} = await fresh();
  const before = snapshot(storage), chosen = [];
  await typeAndClick(m, m.h(m.ProfileStep, {place: 'Morro Bay', warm: null, onChoose: p => chosen.push(p), onBack: () => {}}), {}, 'boat', storage);
  assert.ok(util.isDeepStrictEqual(chosen, ['boat'])); assert.equal(snapshot(storage), before);
  ({m} = await fresh());
  m.configureStore({storage: broken()});
  const after = [];
  const {html} = await typeAndClick(m, m.h(m.ProfileStep, {place: 'Morro Bay', warm: null, onChoose: p => after.push(p), onBack: () => {}}), {lengthFt: '19'}, 'kayak', broken());
  assert.ok(util.isDeepStrictEqual(after, ['kayak']), 'the choice proceeds');
  assert.ok(html.includes('Could not save the boat in this browser.'));
});

test('map first run: a profile click saves the typed boat and still finishes the step', async () => {
  const {m, storage} = await fresh();
  const oldLocation = globalThis.location, oldHistory = globalThis.history;
  const replaced = [];
  globalThis.location = {href: 'https://s.test/map'};
  globalThis.history = {replaceState: (_s, _t, url) => { replaced.push(String(url)); globalThis.location.href = new URL(url, 'https://s.test/map').href; }, pushState() {}};
  try {
    const {html} = await typeAndClick(m, m.h(m.FirstRun, {href: 'https://s.test/map', storage, cookies: null}), {lengthFt: '21'}, 'boat', storage);
    assert.equal(JSON.parse(storage.getItem(m.BOAT_KEY)).boat.loa_ft, 21);
    assert.equal(new URL(globalThis.location.href).searchParams.get('profile'), 'boat');
    assert.equal(html, '', 'the card closes');
  } finally {
    if (oldLocation === undefined) delete globalThis.location; else globalThis.location = oldLocation;
    if (oldHistory === undefined) delete globalThis.history; else globalThis.history = oldHistory;
  }
});

// RETURN 1 (t_65797c35): the notices must outlive the card closing (map) and the page navigating (landing).
function session(initial = {}) {
  const s = memory(initial);
  s.removeItem = k => { s.map.delete(k); };
  return s;
}
const refused = () => ({getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() { throw new Error('denied'); }});

test('the landing carries notices to the map in session storage, or as ?boat-notice=failed when that is refused too', async () => {
  const m = await load();
  const url = 'https://s.test/map?region=morro-bay&port=morro-bay&profile=boat';
  const s = session();
  assert.equal(m.carryNotices(url, [], s), url, 'no notices: the address is unchanged');
  assert.equal(s.map.size, 0, 'no notices: nothing stored');
  assert.equal(m.carryNotices(url, ['Wind limit saved as 20 kt.'], s), url);
  assert.ok(util.isDeepStrictEqual(m.takeNotices(url, s), ['Wind limit saved as 20 kt.']));
  assert.ok(util.isDeepStrictEqual(m.takeNotices(url, s), []), 'read once');
  for (const none of [refused(), null]) {
    const next = m.carryNotices(url, ['Wind limit saved as 20 kt.', m.ENTRY_COPY.failed], none);
    assert.equal(new URL(next).searchParams.get('boat-notice'), 'failed');
    assert.equal(new URL(next).searchParams.get('port'), 'morro-bay', 'the rest of the address is kept');
    assert.ok(util.isDeepStrictEqual(m.takeNotices(next, none), [m.ENTRY_COPY.failed]));
    assert.equal(new URL(m.withoutNotice(next)).searchParams.has('boat-notice'), false);
  }
  // The address names only the fixed line; it never supplies notice text.
  assert.ok(util.isDeepStrictEqual(m.takeNotices(`${url}&boat-notice=${encodeURIComponent('<b>hi</b>')}`, session()), []));
});

test('landing step: the save notices go to onChoose, which navigates at once', async () => {
  const {m} = await fresh();
  m.configureStore({storage: broken()});
  const calls = [];
  await typeAndClick(m, m.h(m.ProfileStep, {place: 'Morro Bay', warm: null, onChoose: (p, notices) => calls.push([p, notices]), onBack: () => {}}), {lengthFt: '19'}, 'boat', broken());
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'boat');
  assert.ok(calls[0][1].includes(m.ENTRY_COPY.failed), JSON.stringify(calls));
});

async function withMap(href, s, run) {
  const oldLocation = globalThis.location, oldHistory = globalThis.history, oldSession = globalThis.sessionStorage;
  globalThis.location = {href};
  globalThis.history = {state: null, replaceState: (_s, _t, url) => { globalThis.location.href = new URL(url, href).href; }, pushState() {}};
  globalThis.sessionStorage = s;
  try { return await run(); } finally {
    if (oldLocation === undefined) delete globalThis.location; else globalThis.location = oldLocation;
    if (oldHistory === undefined) delete globalThis.history; else globalThis.history = oldHistory;
    if (oldSession === undefined) delete globalThis.sessionStorage; else globalThis.sessionStorage = oldSession;
  }
}

test('map first run: a failed save or an adjusted limit is still said after the card closes', async () => {
  let {m, storage} = await fresh();
  let html = await withMap('https://s.test/map', session(), async () =>
    (await typeAndClick(m, m.h(m.FirstRun, {href: 'https://s.test/map', storage, cookies: null}), {wind: '99'}, 'boat', storage)).html);
  assert.ok(html.includes('Wind limit saved as 20 kt.'), html);
  assert.doesNotMatch(html, /How do you fish\?/, 'the card itself closed');
  ({m} = await fresh());
  m.configureStore({storage: broken()});
  html = await withMap('https://s.test/map', session(), async () =>
    (await typeAndClick(m, m.h(m.FirstRun, {href: 'https://s.test/map', storage: broken(), cookies: null}), {lengthFt: '19'}, 'kayak', broken())).html);
  assert.ok(html.includes(m.ENTRY_COPY.failed), html);
  assert.doesNotMatch(html, /How do you fish\?/);
});

test('map first run: notices carried from the landing show on arrival, once, and the address loses the marker', async () => {
  const {m, storage} = await fresh({'skippercast-profile': 'boat'});
  const s = session({'skippercast-first-use-notice': JSON.stringify(['Seas limit saved as 1 ft.'])});
  const href = 'https://s.test/map?region=morro-bay&profile=boat&boat-notice=failed';
  const result = await withMap(href, s, async () => {
    const oldDocument = globalThis.document;
    const root = new El('div');
    globalThis.document = {createElement: n => new El(n), createElementNS: (_, n) => new El(n), createTextNode: t => Object.assign(new El('text'), {nodeType: 3, data: String(t)})};
    try {
      m.renderDOM(m.h(m.FirstRun, {href, storage, cookies: null}), root);
      // Wait for the arrival render instead of a fixed 20 ms, which a cold CI runner can miss.
      for (let waited = 0; waited < 2000 && !text(root).includes(m.ENTRY_COPY.failed); waited += 10) {
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      return {html: text(root), at: globalThis.location.href, left: s.map.size};
    } finally {
      m.renderDOM(null, root);
      if (oldDocument === undefined) delete globalThis.document; else globalThis.document = oldDocument;
    }
  });
  assert.ok(result.html.includes('Seas limit saved as 1 ft.') && result.html.includes(m.ENTRY_COPY.failed), result.html);
  assert.equal(result.left, 0, 'read once');
  assert.equal(new URL(result.at).searchParams.has('boat-notice'), false);
  assert.equal(new URL(result.at).searchParams.get('region'), 'morro-bay');
});
