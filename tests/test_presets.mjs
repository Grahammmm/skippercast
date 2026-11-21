import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const out = join(await mkdtemp(join(tmpdir(), 'presets-')), 'test.mjs');
await build({stdin: {resolveDir: process.cwd(), loader: 'ts', contents: `
  export * from './web/app/presets.ts';
  export {Presets, helm, setHelm} from './web/app/Presets.tsx';
  export * as state from './web/state.ts';
  export {RAIL_IDS} from './web/profile.ts';
  export {depthLinesOn, spotsOn, FIELD_IDS, FLOW_IDS, LINES_OFF, SPOTS_OFF} from './web/map/layers.ts';
  export {render} from 'preact-render-to-string';
  export {h} from 'preact';`}, bundle: true, format: 'esm', platform: 'node', outfile: out,
  jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins, logLevel: 'silent'});
const m = await import(pathToFileURL(out).href);

test('presets have unique valid layer ids and stable target ordering', () => {
  assert.equal(m.PRESETS.length, 5);
  assert.equal(new Set(m.PRESETS.map(p => p.id)).size, 5);
  for (const p of m.PRESETS) {
    assert.equal(new Set(p.layers).size, p.layers.length);
    assert.ok(p.layers.every(id => m.RAIL_IDS.includes(id)));
  }
  assert.equal(m.presetsFor('halibut')[0].id, 'halibut');
  assert.equal(m.presetsFor('dungeness')[0].id, 'crab');
  assert.equal(m.presetsFor('rockfish')[0].id, 'reef-drift');
  assert.deepEqual(m.presetsFor('unknown'), m.PRESETS);
});

test('matching is exact, order-independent and checks source', () => {
  assert.equal(m.activePreset(['stations', 'swell'], 'off'), 'transit');
  assert.equal(m.activePreset(['stations', 'swell', 'clouds'], 'off'), null);
  assert.equal(m.activePreset([], 'off'), null);
  assert.equal(m.activePreset(['stations', 'swell'], 'wcofs'), null);
  assert.equal(m.activePreset(['swell', 'swell'], 'off'), null);
});

test('applying writes both values in a single replacement and makes one Back entry; repeat is a no-op', () => {
  let href = 'https://s.test/map?region=morro-bay&layers=none&current=off';
  const calls = [];
  globalThis.location = {get href() { return href; }};
  globalThis.history = {state: null, pushState(_s, _t, url) { calls.push('push'); href = new URL(url, href).href; },
    replaceState(_s, _t, url) { calls.push('replace'); href = new URL(url, href).href; }};
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(href);
  m.applyPreset('transit');
  assert.deepEqual(calls, ['push', 'replace']);
  assert.equal(new URL(href).searchParams.get('layers'), 'swell,stations');
  assert.equal(new URL(href).searchParams.get('current'), 'off');
  m.applyPreset('transit');
  m.applyPreset('missing');
  assert.deepEqual(calls, ['push', 'replace']);
  delete globalThis.location;
  delete globalThis.history;
});

// MB-13 (MAP-DESIGN-LOCK § 2.5, D5): the menu shows one field and one flow at a time, and Depth lines and
// Spots & charter activity are the menu's own switches. A preset sets the condition rows only.
const fields = (ids) => ids.filter(id => m.FIELD_IDS.includes(id));
// The Currents row is on while a source is chosen (rail.ts railOn), so the source counts as the currents flow.
const flows = (ids, source) => [...new Set([...ids.filter(id => m.FLOW_IDS.includes(id)), ...source === 'off' ? [] : ['currents']])];
const SWITCHES = ['fleet', 'lines-off', 'spots-off'];

test('every preset keeps the menu exclusivity: at most one field and one flow', () => {
  for (const p of m.PRESETS) {
    assert.ok(fields(p.layers).length <= 1, `${p.id}: one field at most, got ${fields(p.layers)}`);
    assert.ok(flows(p.layers, p.current).length <= 1, `${p.id}: one flow at most, got ${flows(p.layers, p.current)}`);
    assert.ok(!p.layers.some(id => SWITCHES.includes(id)), `${p.id}: a preset never sets the Depth lines or Spots switch`);
  }
});

test('applyPreset keeps lines-off and spots-off (and the charter areas) for every preset and every lines/spots state', () => {
  // Each Depth lines and Spots state a list can hold, over a list that also has other condition rows on.
  const LINES = {on: [], off: ['lines-off']};
  const SPOTS = {'on (D5 default)': ['fleet'], 'on (legacy list)': [], off: ['spots-off']};
  const OTHERS = [[], ['chlorophyll', 'clouds'], ['seafloor', 'water-temp', 'swell', 'sst-fronts']];
  let href;
  globalThis.location = {get href() { return href; }};
  globalThis.history = {state: null, pushState(_s, _t, url) { href = new URL(url, href).href; }, replaceState(_s, _t, url) { href = new URL(url, href).href; }};
  try {
    let cases = 0;
    for (const p of m.PRESETS) for (const [lines, lineIds] of Object.entries(LINES)) for (const [spots, spotIds] of Object.entries(SPOTS)) for (const others of OTHERS) for (const source of ['off', 'wcofs']) {
      const before = [...others, ...spotIds, ...lineIds];
      const where = `${p.id} from lines ${lines}, spots ${spots}, others [${others}], current ${source}`;
      href = `https://s.test/map?region=morro-bay&layers=${before.length ? before.join(',') : 'none'}&current=${source}`;
      m.state.configureStore({v2: true, storage: null});
      m.state.syncFromURL(href);
      m.applyPreset(p.id);
      const after = m.state.layers.value, current = m.state.current.value;
      assert.equal(m.depthLinesOn(after), lines === 'on', `${where}: Depth lines unchanged`);
      assert.equal(after.includes('lines-off'), lineIds.length > 0, `${where}: lines-off kept exactly`);
      assert.equal(m.spotsOn(after), !spotIds.includes('spots-off'), `${where}: Spots unchanged`);
      assert.equal(after.includes('spots-off'), spotIds.includes('spots-off'), `${where}: spots-off kept exactly`);
      assert.equal(after.includes('fleet'), spotIds.includes('fleet'), `${where}: the charter areas follow the Spots switch`);
      assert.deepEqual(after.filter(id => !SWITCHES.includes(id)).sort(), [...p.layers].sort(), `${where}: the preset sets every condition row`);
      assert.equal(current, p.current, `${where}: the preset sets the current source`);
      assert.ok(fields(after).length <= 1 && flows(after, current).length <= 1, `${where}: one field and one flow after applying`);
      assert.equal(m.activePreset(after, current), p.id, `${where}: the chip reads as active`);
      const settled = href;
      m.applyPreset(p.id);
      assert.equal(href, settled, `${where}: applying again is a no-op`);
      cases++;
    }
    assert.equal(cases, 5 * 2 * 3 * 3 * 2);
  } finally {
    delete globalThis.location;
    delete globalThis.history;
  }
});

test('matching ignores the Depth lines and Spots switches but nothing else', () => {
  assert.equal(m.activePreset(['swell', 'stations', 'fleet', 'lines-off'], 'off'), 'transit');
  assert.equal(m.activePreset(['swell', 'stations', 'spots-off'], 'off'), 'transit');
  assert.equal(m.activePreset(['swell', 'stations', 'fleet', 'clouds'], 'off'), null);
});

test('stored helm on initializes the document class', async () => {
  let applied = false;
  globalThis.localStorage = {getItem: key => key === 'skippercast-helm-v1' ? '1' : null};
  globalThis.document = {documentElement: {classList: {toggle: (_name, on) => { applied = on; }}}};
  try {
    const loaded = await import(`${pathToFileURL(out).href}?stored`);
    assert.equal(loaded.helm.value, true);
    assert.equal(applied, true);
  } finally {
    delete globalThis.localStorage;
    delete globalThis.document;
  }
});

test('SSR renders the accessible controls and storage failure leaves helm usable', () => {
  const html = m.render(m.h(m.Presets));
  assert.match(html, /role="group" aria-label="Layer presets"/);
  assert.equal((html.match(/aria-pressed=/g) ?? []).length, 5);
  assert.match(html, /role="switch" aria-checked="false"/);
  m.state.configureStore({storage: {getItem() { throw Error('private'); }, setItem() { throw Error('private'); }}});
  m.setHelm(true);
  assert.equal(m.helm.value, true);
  m.setHelm(false);
  assert.equal(m.helm.value, false);
});
