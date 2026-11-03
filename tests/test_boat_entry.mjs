// MYB-1: the optional boat length and comfort limits asked on first use
// (web/boat-entry.ts, web/app/FirstRun.tsx BoatEntry). SC-LANDING-ORDER: they
// come after "How do you fish?" and only for Boat, on the map's card and on
// arrival from the landing's profile step (web/landing/ProfileStep.tsx).
// Blank fields change nothing; a valid length writes the local boat; limits
// clamp through web/limits.ts; a storage failure is said, never thrown.
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
      export {saveFirstUse, ENTRY_COPY, ENTRY_FIELDS, carryAsk, takeAsk, withoutAsk, boatSaved, ASK_KEY} from './web/boat-entry.ts';
      export {ProfileStep} from './web/landing/ProfileStep.tsx';
      export {LandingApp} from './web/landing/Landing.tsx';
      export {FirstRun, BoatEntry, BOAT_ENTRY_COPY} from './web/app/FirstRun.tsx';
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

const tick = (ms = 0) => new Promise(resolve => setTimeout(resolve, ms));
const label = children => [].concat(children).filter(c => typeof c === 'string').join('');

/**
 * Mount `vnode` on a fake DOM with `storage` as localStorage and hand `run` a
 * view of what is rendered now: the boat inputs, the profile buttons, the other
 * buttons by label, the boat form and the text. Unmounts afterwards.
 */
async function mounted(m, vnode, storage, run) {
  const oldDocument = globalThis.document, oldStorage = globalThis.localStorage, oldHook = m.options.vnode;
  const root = new El('div');
  let seen = {inputs: {}, profiles: {}, buttons: {}, form: null};
  globalThis.document = {createElement: n => new El(n), createElementNS: (_, n) => new El(n), createTextNode: t => Object.assign(new El('text'), {nodeType: 3, data: String(t)})};
  globalThis.localStorage = storage;
  m.options.vnode = v => {
    oldHook?.(v);
    if (v.type === 'input' && v.props.name) seen.inputs[v.props.name] = v.props;
    if (v.type === 'form') seen.form = v.props;
    if (v.props?.['data-profile']) seen.profiles[v.props['data-profile']] = v.props;
    else if (v.type?.name === 'Button' && label(v.props.children)) seen.buttons[label(v.props.children)] = v.props;
  };
  const view = () => ({...seen, html: text(root)});
  const fresh = () => { seen = {inputs: {}, profiles: {}, buttons: {}, form: null}; };
  const type = async typed => { for (const [name, value] of Object.entries(typed)) { seen.inputs[name].onInput({currentTarget: {value}}); await tick(); } };
  const click = async props => { fresh(); props.onClick(); await tick(); };
  const submit = async () => { const form = seen.form; fresh(); form.onSubmit({preventDefault() {}}); await tick(); };
  try {
    m.renderDOM(vnode, root);
    await tick(50);   // mount effects run after the next frame (Preact's 35 ms fallback without requestAnimationFrame)
    return await run({view, type, click, submit});
  } finally {
    m.renderDOM(null, root); m.options.vnode = oldHook;
    if (oldDocument === undefined) delete globalThis.document; else globalThis.document = oldDocument;
    if (oldStorage === undefined) delete globalThis.localStorage; else globalThis.localStorage = oldStorage;
  }
}

function session(initial = {}) {
  const s = memory(initial);
  s.removeItem = k => { s.map.delete(k); };
  return s;
}
const refused = () => ({getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() { throw new Error('denied'); }});

async function withMap(href, s, run) {
  const oldLocation = globalThis.location, oldHistory = globalThis.history, oldSession = globalThis.sessionStorage;
  globalThis.location = {href};
  globalThis.history = {state: null, replaceState: (_s, _t, url) => { globalThis.location.href = new URL(url, globalThis.location.href).href; }, pushState() {}};
  globalThis.sessionStorage = s;
  try { return await run(); } finally {
    if (oldLocation === undefined) delete globalThis.location; else globalThis.location = oldLocation;
    if (oldHistory === undefined) delete globalThis.history; else globalThis.history = oldHistory;
    if (oldSession === undefined) delete globalThis.sessionStorage; else globalThis.sessionStorage = oldSession;
  }
}
const MAP = 'https://s.test/map?region=morro-bay';
const firstRun = (m, storage, href = MAP) => m.h(m.FirstRun, {href, storage, cookies: null});

test('SC-LANDING-ORDER: the profile is asked first; neither screen shows boat fields beside the four choices', async () => {
  const {m, storage} = await fresh();
  const step = m.render(m.h(m.ProfileStep, {place: 'Morro Bay', warm: null, onChoose: () => {}, onBack: () => {}}));
  const card = m.render(firstRun(m, storage));
  for (const html of [step, card]) {
    assert.ok(util.isDeepStrictEqual([...html.matchAll(/data-profile="([a-z]+)"/g)].map(x => x[1]), ['boat', 'shore', 'spear', 'kayak']));
    assert.doesNotMatch(html, /<input|<fieldset|Your boat/, 'no boat fields before the choice');
  }
});

test('the boat step shows MYB-1\'s optional fields in order, with Save and Not now, and no profile choice', async () => {
  const m = await load();
  const html = m.render(m.h(m.BoatEntry, {onDone: () => {}}));
  assert.ok(util.isDeepStrictEqual([...html.matchAll(/<input[^>]* name="([a-zA-Z]+)"/g)].map(x => x[1]), ['lengthFt', 'wind', 'seas']));
  assert.ok(html.includes('>Your boat (optional)</legend>'));
  assert.ok(html.includes('Boat length makes every rating yours; the rest can wait.'));
  assert.ok(html.includes('Boat length 8-70 ft'));
  assert.ok(html.includes(`>${m.BOAT_ENTRY_COPY.save}</button>`) && html.includes(`>${m.BOAT_ENTRY_COPY.skip}</button>`));
  assert.match(html, /<button[^>]* type="submit"[^>]*>Save boat</);
  assert.doesNotMatch(html, /data-profile=|role="dialog"|class="app-firstrun"/, 'not the card: the map\'s first-run checks keep meaning the card');
  assert.doesNotMatch(html, /reference boat/i);
  assert.doesNotMatch(html, /<input[^>]* required/, 'every field optional');
});

test('map first run: Boat closes the card and asks for the boat; Save writes it where MYB-1 did and re-rates the verdict', async () => {
  const {m, storage} = await fresh();
  await withMap(MAP, session(), () => mounted(m, firstRun(m, storage), storage, async ({view, type, click, submit}) => {
    assert.match(view().html, /How do you fish\?/);
    await click(view().profiles.boat);
    assert.equal(new URL(globalThis.location.href).searchParams.get('profile'), 'boat', 'the choice is made at once');
    assert.doesNotMatch(view().html, /How do you fish\?/, 'the card closed');
    assert.match(view().html, /Your boat \(optional\)/);
    assert.equal(storage.getItem(m.BOAT_KEY), null, 'nothing saved before Save');
    await type({lengthFt: '21', wind: '14'});
    const before = m.boatSaved.value;
    await submit();
    assert.equal(JSON.parse(storage.getItem(m.BOAT_KEY)).boat.loa_ft, 21, 'the boat under BOAT_KEY');
    assert.equal(JSON.parse(storage.getItem(m.STORAGE_KEYS.limits)).boat.wind, 14, 'the limits for Boat, through web/limits.ts');
    assert.equal(m.boatSaved.value, before + 1, 'the verdict on screen is told');
    assert.equal(view().html, '', 'the boat step closed');
  }));
});

test('map first run: Shore, Spear, Kayak and Keep Boat for now ask nothing more; Not now writes nothing', async () => {
  for (const p of ['shore', 'spear', 'kayak', 'keep', 'skip']) {
    const {m, storage} = await fresh();
    await withMap(MAP, session(), () => mounted(m, firstRun(m, storage), storage, async ({view, click}) => {
      if (p === 'keep') await click(view().buttons['Keep Boat for now']);
      else if (p === 'skip') { await click(view().profiles.boat); await click(view().buttons[m.BOAT_ENTRY_COPY.skip]); }
      else await click(view().profiles[p]);
      assert.equal(view().html, '', `${p}: nothing left on screen`);
      assert.equal(storage.getItem(m.BOAT_KEY), null, `${p}: no boat`);
      assert.equal(storage.getItem(m.STORAGE_KEYS.limits), null, `${p}: no limits`);
      assert.equal(new URL(globalThis.location.href).searchParams.get('profile'), p === 'keep' || p === 'skip' ? 'boat' : p);
    }));
  }
});

test('map first run: a failed save or an adjusted limit is said after the boat step closes', async () => {
  let {m, storage} = await fresh();
  let html = await withMap(MAP, session(), () => mounted(m, firstRun(m, storage), storage, async ({view, type, click, submit}) => {
    await click(view().profiles.boat); await type({wind: '99'}); await submit();
    return view().html;
  }));
  assert.ok(html.includes('Wind limit saved as 20 kt.'), html);
  assert.doesNotMatch(html, /How do you fish\?|Boat length \(ft\)/, 'the card and the fields closed');
  ({m} = await fresh());
  m.configureStore({storage: broken()});
  html = await withMap(MAP, session(), () => mounted(m, firstRun(m, broken()), broken(), async ({view, type, click, submit}) => {
    await click(view().profiles.boat); await type({lengthFt: '19'}); await submit();
    return view().html;
  }));
  assert.ok(html.includes(m.ENTRY_COPY.failed), html);
});

test('the landing\'s Boat choice is carried to the map in session storage, or as ?boat-entry=ask when that is refused', async () => {
  const m = await load();
  const url = 'https://s.test/map?region=morro-bay&port=morro-bay&profile=boat';
  const s = session();
  assert.equal(m.carryAsk(url, s), url, 'stored: the address is unchanged');
  assert.equal(m.takeAsk(url, s), true);
  assert.equal(m.takeAsk(url, s), false, 'read once');
  for (const none of [refused(), null]) {
    const next = m.carryAsk(url, none);
    assert.equal(new URL(next).searchParams.get('boat-entry'), 'ask');
    assert.equal(new URL(next).searchParams.get('port'), 'morro-bay', 'the rest of the address is kept');
    assert.equal(m.takeAsk(next, none), true);
    assert.equal(new URL(m.withoutAsk(next)).searchParams.has('boat-entry'), false);
  }
  assert.equal(m.takeAsk(`${url}&boat-entry=yes`, session()), false, 'only the one value asks');
});

test('map first run: arriving from the landing\'s Boat choice asks for the boat once and drops the marker', async () => {
  const {m, storage} = await fresh({'skippercast-profile': 'boat'});
  const s = session({[m.ASK_KEY]: 'ask'});
  const href = `${MAP}&profile=boat&boat-entry=ask`;
  await withMap(href, s, () => mounted(m, firstRun(m, storage, href), storage, async ({view, type, submit}) => {
    assert.match(view().html, /Your boat \(optional\)/);
    assert.doesNotMatch(view().html, /How do you fish\?/, 'the profile was answered on the landing');
    assert.equal(s.map.size, 0, 'read once');
    assert.equal(new URL(globalThis.location.href).searchParams.has('boat-entry'), false);
    assert.equal(new URL(globalThis.location.href).searchParams.get('region'), 'morro-bay');
    await type({lengthFt: '19'}); await submit();
    assert.equal(JSON.parse(storage.getItem(m.BOAT_KEY)).boat.loa_ft, 19);
  }));
  // A carried ask with another profile in the address asks nothing.
  const other = `${MAP}&profile=shore`;
  await withMap(other, session({[m.ASK_KEY]: 'ask'}), () => mounted(m, firstRun(m, storage, other), storage, async ({view}) => {
    assert.equal(view().html, '');
  }));
});

test('landing: choosing Boat navigates at once asking the map for the boat; other choices carry nothing', async () => {
  for (const p of ['boat', 'shore']) {
    const {m, storage} = await fresh();
    const s = session(), navigations = [];
    let portStep, profileStep;
    const oldHook = m.options.vnode;
    m.options.vnode = v => { oldHook?.(v); if (v.type?.name === 'PortInput') portStep = v.props; if (v.type?.name === 'ProfileStep') profileStep = v.props; };
    try {
      await withMap('https://s.test/', s, () => mounted(m, m.h(m.LandingApp, {href: 'https://s.test/', load: false, navigate: url => navigations.push(url)}), storage, async () => {
        portStep.onChoose({id: 'morro-bay', name: 'Morro Bay', region: 'morro-bay'});
        await tick();
        profileStep.onChoose(p);
      }));
    } finally { m.options.vnode = oldHook; }
    assert.equal(navigations.length, 1, p);
    assert.equal(new URL(navigations[0]).searchParams.get('profile'), p);
    assert.equal(new URL(navigations[0]).searchParams.has('boat-entry'), false, 'session storage carried it');
    assert.equal(s.getItem(m.ASK_KEY), p === 'boat' ? 'ask' : null, p);
    assert.equal(storage.getItem(m.BOAT_KEY), null, `${p}: the landing saves no boat`);
  }
});
