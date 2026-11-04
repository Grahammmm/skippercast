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
