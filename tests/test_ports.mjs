// Port chooser and first run (FE-08, docs/plans/front-end/dev-plan.md):
// name matching and ranking, the featured list, the 75 nm rule, the
// addresses a choice leads to, the preference shared with v1's
// dist/home-port.js, the directory's schema, geolocation outcomes, and the
// components rendered to strings (the chooser's states, the first-run card
// shown once and never with ?profile= in the address). FE-83: one home
// memory with v1 and /coast, each side read by the other's own reader.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {FIRST_RUN_KEY as V1_FIRST_RUN_KEY, HOME_PORT_KEY as V1_KEY, forgetHome as v1Forget, resolveHome as v1Resolve} from '../dist/home-port.js';
import {
  browserPreferences, forgetPreferenceHeader, HOME_PLACE_KEY as COAST_PLACE_KEY, preferenceHeader, saveBrowserPreferences, syncPreferences,
} from '../packages/coast/src/coast3d/preferences.ts';
import {lintFile} from '../scripts/check_tokens.mjs';
import {
  COPY, FEATURED, FIRST_RUN_KEY, HOME_PLACE_KEY, HOME_PORT_KEY, closestPort, currentPort, exploreURL, forgetHome, hasSavedHome, homeURL, isDirectory,
  landingURL, listPorts, locatePort, loadPorts, matchPorts, portURL, resolveHome, savedHomeMode, savedHomeURL, savePort, savedPortId,
} from '../web/ports.ts';
import {fishLink} from '../web/fish-links.ts';
import {STORAGE_KEYS} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), map: m}; };
/** A cookie jar that applies Set-Cookie-style writes the way document.cookie does (Max-Age=0 deletes). */
const jar = (initial = '') => {
  const m = new Map(initial ? [initial.split(/=(.*)/s).slice(0, 2)] : []);
  return {
    map: m,
    get cookie() { return [...m].map(([k, v]) => `${k}=${v}`).join('; '); },
    set cookie(header) { const [pair, ...attrs] = header.split(';'); const [k, v] = pair.split(/=(.*)/s); if (attrs.some(a => a.trim() === 'Max-Age=0')) m.delete(k.trim()); else m.set(k.trim(), v); },
  };
};
const denied = {getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); }, removeItem() { throw Error('blocked'); }};
const deniedJar = {get cookie() { throw Error('blocked'); }, set cookie(_) { throw Error('blocked'); }};
/** /coast reads and writes the global localStorage; run `fn` with `storage` standing in for it. */
function asLocalStorage(storage, fn) {
  const before = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {value: storage, configurable: true, writable: true});
  try { return fn(); } finally { if (before) Object.defineProperty(globalThis, 'localStorage', before); else delete globalThis.localStorage; }
}
const port = (id, name, region, match, status = 'active') => ({id, name, region, status, forecast_point: id, forecast_name: name, match});
const morro = port('morro-bay', 'Morro Bay', 'morro-bay', [35.3667, -120.868]);
const sanDiego = port('san-diego', 'San Diego', 'southern-california', [32.72, -117.22]);
const santaCruz = port('santa-cruz', 'Santa Cruz', 'santa-cruz-monterey-bay', [36.959, -122.002]);
const sanPedro = port('san-pedro', 'San Pedro · Los Angeles', 'southern-california', [33.73, -118.27], 'preview');
const noyo = port('noyo-harbor', 'Noyo Harbor · Fort Bragg', 'fort-bragg-point-arena', [39.425, -123.805]);
const PORTS = [noyo, santaCruz, morro, sanPedro, sanDiego];
const HREF = 'https://skippercast.com/map?region=morro-bay&view=conditions&target=lingcod&profile=shore&ui=v2&utm_source=friend#x';

test('typing matches ports by name: a name start first, then a word start, then any match, ties in directory order', () => {
  assert.deepEqual(matchPorts(PORTS, 'san').map(p => p.id), ['santa-cruz', 'san-pedro', 'san-diego'], 'name starts win, then directory order');
  assert.deepEqual(matchPorts(PORTS, 'Bragg').map(p => p.id), ['noyo-harbor'], 'a later word matches, case folded');
  assert.deepEqual(matchPorts(PORTS, 'ro b').map(p => p.id), ['morro-bay'], 'any substring still matches (v1 rule)');
  assert.deepEqual(matchPorts(PORTS, 'diego').map(p => p.id), ['san-diego']);
  assert.deepEqual(matchPorts(PORTS, 'xyz'), []);
  assert.equal(matchPorts(PORTS, '  ').length, PORTS.length, 'an empty query matches every port');
});

test('the list shows the featured ports before a query and every port after "See all"', () => {
  assert.deepEqual(listPorts(PORTS, '').map(p => p.id), ['santa-cruz', 'morro-bay', 'san-diego']);
  assert.ok(listPorts(PORTS, '').every(p => FEATURED.includes(p.id)));
  assert.equal(listPorts(PORTS, '', true).length, PORTS.length);
  assert.deepEqual(listPorts(PORTS, 'noyo').map(p => p.id), ['noyo-harbor'], 'a query ignores the featured filter');
});

test('the nearest port stays within 75 nm and refuses a distant or invalid position', () => {
  assert.equal(closestPort(PORTS, 35.36, -120.88)?.id, 'morro-bay');
  assert.equal(closestPort(PORTS, 33.0, -117.5)?.id, 'san-diego', 'the nearer of two southern ports');
  assert.equal(closestPort(PORTS, 37, -119), null, 'the Sierra is more than 75 nm from any port');
  assert.equal(closestPort(PORTS, NaN, -120.9), null);
  assert.equal(closestPort([], 35.36, -120.88), null);
  assert.equal(closestPort(PORTS, 37, -119, 200)?.id, 'morro-bay', 'the limit is a parameter');
});

test('a choice opens /map at the port with the profile, dropping area keys and keeping the ui switch', () => {
  const url = new URL(portURL(HREF, sanDiego, 'shore'));
  assert.equal(url.pathname, '/map');
  assert.equal(url.hash, '');
  assert.deepEqual([...url.searchParams.keys()].sort(), ['profile', 'region', 'ui', 'utm_source']);
  assert.equal(url.searchParams.get('region'), 'southern-california');
  assert.equal(url.searchParams.get('profile'), 'shore');
  assert.equal(new URL(portURL('https://skippercast.com/', morro)).search, '?region=morro-bay', 'no profile parameter without a profile');
  assert.equal(new URL(portURL('https://skippercast.com/', morro, 'skiff')).searchParams.get('profile'), null, 'an unknown profile is not written');
  assert.equal(exploreURL(HREF), 'https://skippercast.com/map?profile=shore&ui=v2&utm_source=friend&coast=central', 'the coast keeps the profile');
  assert.equal(landingURL(HREF), 'https://skippercast.com/?ui=v2');
  assert.equal(landingURL('https://skippercast.com/map'), 'https://skippercast.com/');
});

test('the preference uses v1\'s key, so v1 reads the port v2 saved', () => {
  assert.equal(HOME_PORT_KEY, V1_KEY);
  const storage = memory();
  assert.equal(savedPortId(storage), null);
  assert.equal(savePort('san-diego', storage), true);
  assert.equal(storage.map.get(V1_KEY), 'san-diego', 'the bare id, as dist/home-port.js stores and reads it');
  assert.equal(savedPortId(storage), 'san-diego');
  assert.equal(savePort('x', null), false, 'no storage: the session still navigates');
  const throwing = {getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); }};
  assert.equal(savedPortId(throwing), null);
  assert.equal(savePort('x', throwing), false);
});

const BARE = 'https://skippercast.com/map?ui=v2';
const legacyCookie = (place, mode) => preferenceHeader({v: 1, place, mode}, true).split(';')[0];

test('a port saved in v2 is the home v1 and /coast read, replacing an older /coast home (FE-83)', () => {
  assert.equal(HOME_PLACE_KEY, COAST_PLACE_KEY);
  assert.equal(FIRST_RUN_KEY, V1_FIRST_RUN_KEY);
  const storage = memory(), cookies = jar();
  asLocalStorage(storage, () => assert.equal(saveBrowserPreferences(cookies, {v: 1, place: 'cambria', mode: 'spear'}, true), true));
  assert.ok(storage.map.has(HOME_PLACE_KEY) && cookies.map.has('skippercast_home'), 'an older home saved on /coast');
  assert.equal(savePort('morro-bay', storage, cookies, true), true);
  assert.equal(storage.map.get(V1_KEY), 'morro-bay');
  assert.equal(storage.map.has(HOME_PLACE_KEY), false, 'the /coast place no longer competes');
  assert.equal(cookies.map.has('skippercast_home'), false, 'nor its cookie');
  assert.deepEqual(v1Resolve(PORTS, storage, cookies.cookie), {port: morro}, 'v1 reads the port');
  assert.deepEqual(asLocalStorage(storage, () => browserPreferences(cookies)), {v: 1, place: 'morro', mode: 'spear'}, '/coast reads the port\'s place with the stored profile');
  savePort('san-diego', storage, cookies, true);
  assert.deepEqual(v1Resolve(PORTS, storage, cookies.cookie), {port: sanDiego});
  assert.equal(asLocalStorage(storage, () => browserPreferences(cookies)), null, 'a port /coast has no place for: no older home comes back');
});

test('a home saved in v1 or on /coast opens the same home in v2, migrating a legacy cookie as v1 does', () => {
  const states = {
    'v1 port': (s) => s.setItem(V1_KEY, 'santa-cruz'),
    '/coast at a port': (s, c) => asLocalStorage(s, () => saveBrowserPreferences(c, {v: 1, place: 'morro', mode: 'shore'}, true)),
    '/coast place': (s, c) => asLocalStorage(s, () => saveBrowserPreferences(c, {v: 1, place: 'cambria', mode: 'spear'}, true)),
    'profile changed since': (s, c) => { asLocalStorage(s, () => saveBrowserPreferences(c, {v: 1, place: 'carmel', mode: 'spear'}, true)); s.setItem(STORAGE_KEYS.profile, 'boat'); },
    'legacy cookie only': (_s, c) => { c.cookie = legacyCookie('avila', 'shore'); },
    'nothing saved': () => {},
  };
  const expected = {
    'v1 port': {port: santaCruz}, '/coast at a port': {port: morro}, '/coast place': {native: {v: 1, place: 'cambria', mode: 'spear'}},
    'profile changed since': {native: {v: 1, place: 'carmel', mode: 'boat'}}, 'legacy cookie only': {native: {v: 1, place: 'avila', mode: 'shore'}}, 'nothing saved': null,
  };
  for (const [name, setup] of Object.entries(states)) {
    const [s1, c1, s2, c2] = [memory(), jar(), memory(), jar()];
    setup(s1, c1); setup(s2, c2);
    assert.deepEqual(resolveHome(PORTS, s2, c2.cookie), expected[name], name);
    assert.deepEqual(v1Resolve(PORTS, s1, c1.cookie), expected[name], `${name}: v1 agrees`);
    assert.deepEqual([...s2.map], [...s1.map], `${name}: the same storage afterwards`);
  }
  const native = homeURL(BARE, {native: {v: 1, place: 'cambria', mode: 'spear'}});
  assert.equal(native, 'https://skippercast.com/map?ui=v2&place=cambria&profile=spear');
  assert.equal(fishLink(native).searchParams.get('region'), 'cambria-san-simeon', 'the v2 store opens the place\'s region');
  assert.equal(new URL(homeURL(BARE + '&profile=boat', {native: {v: 1, place: 'cambria', mode: 'spear'}})).searchParams.get('profile'), 'boat', 'the address\'s profile wins');
  assert.equal(homeURL(BARE, {port: morro}), portURL(BARE, morro));
  assert.equal(homeURL(BARE, null), 'https://skippercast.com/?ui=v2');
});

test('/map with no area loads the directory only for a saved port and reads the cookie only when no port won', async () => {
  let loads = 0, reads = 0;
  const load = async () => { loads++; return PORTS; };
  const counted = text => ({get cookie() { reads++; return text; }, set cookie(_) { /* unused */ }});
  assert.equal(await savedHomeURL(BARE, memory(), counted(''), load), 'https://skippercast.com/?ui=v2');
  assert.equal(loads, 0);
  const saved = memory(); savePort('san-diego', saved, null);
  reads = 0;
  assert.equal(await savedHomeURL(BARE, saved, counted(legacyCookie('avila', 'shore')), load), portURL(BARE, sanDiego));
  assert.deepEqual([loads, reads], [1, 0], 'a saved port wins without reading the cookie');
  assert.equal(await savedHomeURL(BARE, memory(), counted(legacyCookie('avila', 'shore')), load), 'https://skippercast.com/map?ui=v2&place=avila&profile=shore');
  assert.deepEqual([loads, reads], [1, 1]);
  assert.equal(await savedHomeURL(BARE, saved, null, async () => { throw Error('offline'); }), 'https://skippercast.com/?ui=v2', 'a failed directory opens the landing');
});

test('forget clears the home for v2, v1 and /coast; forgetting on either of them clears what v2 reads', () => {
  const storage = memory(), cookies = jar();
  asLocalStorage(storage, () => saveBrowserPreferences(cookies, {v: 1, place: 'morro', mode: 'shore'}, true));
  storage.setItem(V1_FIRST_RUN_KEY, 'boat');
  assert.equal(hasSavedHome(storage, cookies), true);
  forgetHome(storage, cookies, true);
  assert.deepEqual([storage.map.size, cookies.map.size], [0, 0], 'port, place, profile, v1 first run and cookie');
  assert.equal(hasSavedHome(storage, cookies), false);
  assert.equal(v1Resolve(PORTS, storage, cookies.cookie), null, 'v1');
  assert.equal(asLocalStorage(storage, () => browserPreferences(cookies)), null, '/coast');
  const elsewhere = {
    v1: (s, c) => v1Forget(s, c, true),
    '/coast': (s, c) => asLocalStorage(s, () => { c.cookie = forgetPreferenceHeader(true); syncPreferences(null); }),
  };
  for (const [name, forget] of Object.entries(elsewhere)) {
    const s = memory(), c = jar(legacyCookie('avila', 'boat'));
    savePort('santa-cruz', s, null);
    asLocalStorage(s, () => syncPreferences({v: 1, place: 'cambria', mode: 'spear'}));
    forget(s, c);
    assert.equal(hasSavedHome(s, c), false, name);
    assert.equal(resolveHome(PORTS, s, c.cookie), null, name);
  }
});

test('with storage and cookies denied nothing throws: the choice reports unsaved and the visit still navigates', async () => {
  assert.equal(savePort('morro-bay', denied, deniedJar), false);
  assert.equal(savePort('morro-bay', null, null), false);
  assert.doesNotThrow(() => forgetHome(denied, deniedJar));
  assert.equal(hasSavedHome(denied, deniedJar), false);
  assert.equal(savedHomeMode(denied, deniedJar), null);
  assert.equal(resolveHome(PORTS, denied, ''), null);
  assert.deepEqual(resolveHome(PORTS, denied, legacyCookie('avila', 'shore')), {native: {v: 1, place: 'avila', mode: 'shore'}}, 'the cookie still opens the home without storage');
  assert.equal(await savedHomeURL(BARE, denied, deniedJar), 'https://skippercast.com/?ui=v2');
  assert.equal(portURL(BARE, morro), 'https://skippercast.com/map?ui=v2&region=morro-bay', 'the address a choice navigates to needs no storage');
});

test('the current port is the saved one in the region, else the first listed there', () => {
  assert.equal(currentPort(PORTS, 'southern-california', 'san-diego')?.id, 'san-diego');
  assert.equal(currentPort(PORTS, 'southern-california', 'morro-bay')?.id, 'san-pedro');
  assert.equal(currentPort(PORTS, 'southern-california', null)?.id, 'san-pedro');
  assert.equal(currentPort(PORTS, null, 'morro-bay'), null);
  assert.equal(currentPort(PORTS, 'unknown', null), null);
});

test('the served directory passes the schema check and the chooser loads it once', async () => {
  const served = JSON.parse(await readFile(join(ROOT, 'dist/data/home-ports.json'), 'utf8'));
  assert.ok(isDirectory(served), 'dist/data/home-ports.json');
  assert.ok(served.ports.some(p => p.id === 'morro-bay'));
  assert.ok(FEATURED.every(id => served.ports.some(p => p.id === id)), 'every featured port is listed');
  assert.equal(isDirectory({schema_version: 1, ports: []}), false);
  assert.equal(isDirectory({schema_version: 2, ports: [morro]}), false);
  assert.equal(isDirectory({schema_version: 1, ports: [{...morro, match: [1]}]}), false);
  let calls = 0;
  const fetchFn = async () => { calls++; return {ok: true, json: async () => ({schema_version: 1, ports: [morro]})}; };
  assert.deepEqual(await loadPorts(fetchFn), [morro]);
  await loadPorts(fetchFn);
  assert.equal(calls, 1, 'one fetch per page');
});

test('locating resolves the nearest port, or why there is none, without throwing', async () => {
  const geo = (lat, lon) => ({getCurrentPosition: (ok) => ok({coords: {latitude: lat, longitude: lon}})});
  assert.deepEqual(await locatePort(PORTS, geo(35.36, -120.88)), {ok: true, port: morro});
  assert.deepEqual(await locatePort(PORTS, geo(37, -119)), {ok: false, reason: 'none'});
  assert.deepEqual(await locatePort(PORTS, {getCurrentPosition: (_ok, fail) => fail({code: 1})}), {ok: false, reason: 'unavailable'});
  assert.deepEqual(await locatePort(PORTS, null), {ok: false, reason: 'unsupported'});
  for (const reason of ['unsupported', 'unavailable', 'none']) assert.match(COPY[reason], /Search/, `${reason} points back to the search`);
  assert.match(COPY.privacy, /stays in this browser/);
});

let components;
async function load() {
  if (components) return components;
  const out = join(await mkdtemp(join(tmpdir(), 'ports-')), 'ports.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {PortInput, PortDialog} from './web/landing/PortInput.tsx';
      export {FirstRun, firstRunDue, savedFirstRun, PROFILE_NOTES} from './web/app/FirstRun.tsx';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  });
  components = await import(pathToFileURL(out).href);
  return components;
}
const count = (html, re) => (html.match(re) || []).length;

test('the chooser renders the question, the featured ports, both actions and the privacy line; a failed directory still offers the coast', async () => {
  const {PortInput, PortDialog, render, h} = await load();
  const noop = () => {};
  const html = render(h(PortInput, {ports: PORTS, onChoose: noop, onExplore: noop}));
  assert.match(html, /<form class="port-input">/);
  assert.match(html, /<label class="port-input-label" for="[^"]+">Where are you launching\?<\/label>/);
  assert.match(html, /<input [^>]*type="search"[^>]*placeholder="Try Morro Bay, Ventura, San Diego…"/);
  assert.deepEqual([...html.matchAll(/data-port="([a-z-]+)"/g)].map(m => m[1]), ['santa-cruz', 'morro-bay', 'san-diego']);
  assert.match(html, /<strong>San Diego<\/strong><span>Mapped area · San Diego<\/span>/);
  assert.match(html, /See all 5 ports/);
  assert.match(html, /Use my location<\/button>/);
  assert.match(html, /Explore the coast<\/button>/);
  assert.match(html, /<p class="port-input-feedback" role="status"><\/p>/);
  assert.match(html, /class="port-input-note">Your choice stays in this browser\./);
  assert.match(html, /<button [^>]*type="submit"[^>]*>.*?Go<\/button>/s, 'Enter submits the top match');
  assert.doesNotMatch(html, /Forget saved home/, 'nothing to forget without a saved home');
  const home = memory(); home.setItem(HOME_PORT_KEY, 'morro-bay');
  assert.match(render(h(PortInput, {ports: PORTS, onChoose: noop, onExplore: noop, storage: home, cookies: null})), /class="[^"]*port-input-forget[^"]*"[^>]*>Forget saved home<\/button>/);
  assert.match(render(h(PortInput, {ports: PORTS, onChoose: noop, onExplore: noop, storage: null, cookies: jar(legacyCookie('cambria', 'spear'))})), /Forget saved home/, 'a home kept only in the /coast cookie');
  const loading = render(h(PortInput, {ports: null, onChoose: noop, onExplore: noop}));
  assert.match(loading, /Loading ports…/);
  assert.match(loading, /Use my location<\/button>/);
  const failed = render(h(PortInput, {ports: [], onChoose: noop, onExplore: noop}));
  assert.match(failed, /Port choices are unavailable\. Explore the coast instead\./);
  assert.match(failed, /<button [^>]*disabled[^>]*>.*?Go<\/button>/s);
  const dialog = render(h(PortDialog, {open: false, onClose: noop}, 'inner'));
  assert.match(dialog, /<dialog class="port-dialog" aria-labelledby="([^"]+)">/);
  assert.match(dialog, /<h2 id="[^"]+">Change port<\/h2>/);
  assert.doesNotMatch(dialog, /inner/, 'a closed dialog renders no chooser');
  assert.match(render(h(PortDialog, {open: true, onClose: noop}, 'inner')), /inner<\/dialog>/);
});

test('first run shows once: due without a stored profile, never with ?profile= in the address, gone after the choice is stored', async () => {
  const {FirstRun, firstRunDue, PROFILE_NOTES, state, render, h} = await load();
  const storage = memory();
  const href = 'https://s.test/map?region=morro-bay';
  assert.equal(firstRunDue(href, storage), true);
  assert.equal(firstRunDue(href + '&profile=spear', storage), false, '?profile= in the address');
  assert.equal(firstRunDue(href + '&profile=skiff', storage), true, 'an unknown profile value does not count');
  const html = render(h(FirstRun, {href, storage}));
  assert.match(html, /<section class="app-firstrun" role="dialog" aria-labelledby="first-run-title"/);
  assert.match(html, /<h2 id="first-run-title">How do you fish\?<\/h2>/);
  assert.deepEqual([...html.matchAll(/data-profile="([a-z]+)"/g)].map(m => m[1]), ['boat', 'shore', 'spear']);
  for (const p of ['boat', 'shore', 'spear']) assert.ok(html.includes(PROFILE_NOTES[p]), `${p} note`);
  assert.doesNotMatch(html, /aria-modal/, 'never modal: the map is not blocked');
  assert.match(html, /Keep Boat for now<\/button>/);
  assert.doesNotMatch(html, /\b(?:best spot|productive|catch rate|bite|fish will)\b/i, 'promises no fish');
  // The store persists a profile the address names; after that the card is not due.
  state.configureStore({v2: true, storage});
  state.syncFromURL(href + '&profile=shore');
  assert.equal(storage.map.get(STORAGE_KEYS.profile), 'shore');
  assert.equal(firstRunDue(href, storage), false, 'a stored profile ends the first run');
  assert.equal(render(h(FirstRun, {href, storage})), '');
  assert.equal(count(render(h(FirstRun, {href, storage: null})), /app-firstrun/), 1, 'no storage: the card shows, and the choice still writes the address');
});

test('a home saved on /coast already answers the first run with its mode, unless the address or storage names a profile', async () => {
  const {FirstRun, firstRunDue, savedFirstRun, render, h} = await load();
  const href = 'https://s.test/map?region=morro-bay';
  const place = memory();
  asLocalStorage(place, () => syncPreferences({v: 1, place: 'cambria', mode: 'spear'}));
  place.removeItem(STORAGE_KEYS.profile);
  assert.equal(firstRunDue(href, place, null), false);
  assert.equal(savedFirstRun(href, place, null), 'spear', 'the stored /coast place');
  assert.equal(render(h(FirstRun, {href, storage: place, cookies: null})), '');
  const cookieOnly = jar(legacyCookie('avila', 'shore'));
  assert.equal(firstRunDue(href, memory(), cookieOnly), false);
  assert.equal(savedFirstRun(href, null, cookieOnly), 'shore', 'the /coast cookie, even without storage');
  assert.equal(savedFirstRun(href + '&profile=boat', place, cookieOnly), null, 'the address wins');
  place.setItem(STORAGE_KEYS.profile, 'boat');
  assert.equal(savedFirstRun(href, place, cookieOnly), null, 'a stored profile wins');
  assert.equal(firstRunDue(href, memory(), jar()), true, 'no home anywhere: ask');
});

test('the entry-flow files keep the token and copy rules', () => {
  for (const file of ['web/ports.ts', 'web/landing/PortInput.tsx', 'web/landing/port-input.css', 'web/app/FirstRun.tsx']) {
    const source = readFileSync(join(ROOT, file), 'utf8');
    assert.deepEqual(lintFile(file, source), [], file);
    assert.doesNotMatch(source, /innerHTML/, `${file} renders through Preact`);
    assert.doesNotMatch(source, /\b(?:best spot|productive|catch rate|bite)\b/i, `${file} promises no fish`);
  }
});
