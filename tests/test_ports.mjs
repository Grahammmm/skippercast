// Port chooser and first run (FE-08, docs/plans/front-end/dev-plan.md):
// name matching and ranking, the featured list, the 75 nm rule, the
// addresses a choice leads to, the preference shared with v1's
// dist/home-port.js, the directory's schema, geolocation outcomes, and the
// components rendered to strings (the chooser's states, the first-run card
// shown once and never with ?profile= in the address).
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {HOME_PORT_KEY as V1_KEY} from '../dist/home-port.js';
import {lintFile} from '../scripts/check_tokens.mjs';
import {
  COPY, FEATURED, HOME_PORT_KEY, closestPort, currentPort, exploreURL, isDirectory, landingURL, listPorts, locatePort, loadPorts, matchPorts,
  portURL, savePort, savedPortId,
} from '../web/ports.ts';
import {STORAGE_KEYS} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), map: m}; };
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
      export {FirstRun, firstRunDue, PROFILE_NOTES} from './web/app/FirstRun.tsx';
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

test('the entry-flow files keep the token and copy rules', () => {
  for (const file of ['web/ports.ts', 'web/landing/PortInput.tsx', 'web/landing/port-input.css', 'web/app/FirstRun.tsx']) {
    const source = readFileSync(join(ROOT, file), 'utf8');
    assert.deepEqual(lintFile(file, source), [], file);
    assert.doesNotMatch(source, /innerHTML/, `${file} renders through Preact`);
    assert.doesNotMatch(source, /\b(?:best spot|productive|catch rate|bite)\b/i, `${file} promises no fish`);
  }
});
