// NB-SC-03 (#519): in Terrain 2D/3D the Seafloor entry's Terrain options show the renderer's habitat status
// verbatim, its ranked reefs selecting that reef, and "Explore a ranked reef" (exploreNext); stage and rail bundled together.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname, ORIGIN = 'https://s.test/map';
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const out = join(await mkdtemp(join(tmpdir(), 'habitat-rail-')), 'rail.mjs');
await build({
  stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {LayerRail, TerrainOptions} from './web/app/LayerRail.tsx';
    export {createStage, exploreRankedReef, selectRankedReef, terrainFailed, terrainHabitat} from './web/map/stage.ts';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  plugins: rendererPlugins,
});
const m = await import(pathToFileURL(out).href);

function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(href);
}
/** A mounted stage over a fake terrain handle that records selectHabitat and exploreNext. */
async function mounted() {
  browser(`${ORIGIN}?region=morro-bay&presentation=3d&layers=seafloor`);
  const fake = {calls: [], options: null, count: name => fake.calls.filter(([n]) => n === name).length};
  const handle = new Proxy({load: async () => true, destroy() {}}, {get: (t, name) => t[name] ?? (value => { fake.calls.push([name, value]); return true; })});
  const doc = {hidden: false, addEventListener() {}, removeEventListener() {}}, host = {dataset: {}, shadowRoot: {children: [], replaceChildren() {}}};
  m.terrainFailed.value = false;
  const stage = m.createStage({host, doc, viewDelay: 0, center: () => [35.37, -120.86], now: () => new Date('2026-10-05T20:17:00Z'),
    load: async () => ({styles: [], mountCoast: (_h, options) => { fake.options = options; return handle; }})});
  await tick(); await tick();
  assert.ok(fake.options, 'terrain mounted');
  return {stage, fake};
}
const rail = () => m.render(m.h(m.TerrainOptions, {on: true}));
const rank = i => ({id: `reef-${i}`, title: `${i}. Morro / Estero reef · grade A`, detail: `${i}0–${i}5 ft · screened · terrain 8${i}/100`});
/** Every button the Terrain options render (function components called), in order, with their props. */
function buttons(vnode, found = []) {
  if (Array.isArray(vnode)) { for (const v of vnode) buttons(v, found); return found; }
  if (!vnode || typeof vnode !== 'object') return found;
  if (typeof vnode.type === 'function') return buttons(vnode.type(vnode.props), found);
  if (vnode.type === 'button') found.push(vnode.props);
  return buttons(vnode.props?.children, found);
}
const terrainButtons = () => buttons(m.TerrainOptions({on: true})).filter(p => p.type === 'button');

test('unavailable, no ranks: the status sentence verbatim, no list, Explore disabled', async () => {
  const {stage, fake} = await mounted(), status = 'Habitat ranking is unavailable for this target.';
  fake.options.onHabitat({status, state: 'unavailable', ranks: [], canExplore: false});
  const html = rail();
  assert.ok(html.includes(`<p class="app-rail-hint" role="status" data-reason="habitat">${status}</p>`) && !html.includes('<ol>'));
  assert.match(html, /<button type="button" class="ui-button ui-button--sm" disabled>Explore a ranked reef<\/button>/);
  stage.destroy();
});

test('three ranks (or 14): buttons in order, at most 12; the 2nd selects its reef once and names it in the link', async () => {
  const {stage, fake} = await mounted();
  fake.options.onHabitat({status: '3 ranked reefs.', state: 'ok', ranks: [rank(1), rank(2), rank(3)], canExplore: true});
  const html = rail();
  assert.deepEqual([...html.matchAll(/<li><button[^>]*><b>([^<]+)<\/b> <small>([^<]+)<\/small>/g)].map(x => x[1]), [1, 2, 3].map(i => rank(i).title));
  const reefs = terrainButtons().slice(0, 3);
  reefs[1].onClick();
  assert.deepEqual(fake.calls.filter(([n]) => n === 'selectHabitat'), [['selectHabitat', 'reef-2']], 'told once');
  assert.equal(new URL(location.href).searchParams.get('habitat'), 'reef-2');
  reefs[1].onClick();
  assert.equal(fake.count('selectHabitat'), 2, 'the same reef again re-selects it without echoing the link back');
  fake.options.onHabitat({status: 'ok', state: 'ok', ranks: Array.from({length: 14}, (_, i) => rank(i + 1)), canExplore: true});
  assert.equal([...rail().matchAll(/<li><button/g)].length, 12, 'at most 12 listed');
  stage.destroy();
});

test('Explore is enabled only with canExplore, and a click calls exploreNext once', async () => {
  const {stage, fake} = await mounted();
  fake.options.onHabitat({status: 'Withheld.', state: 'withheld', ranks: [rank(1)], canExplore: false});
  assert.equal(terrainButtons().at(-1).disabled, true, 'ranks without canExplore stay disabled');
  fake.options.onHabitat({status: 'ok', state: 'ok', ranks: [rank(1)], canExplore: true});
  const explore = terrainButtons().at(-1);
  assert.equal(explore.disabled, false);
  assert.match(rail(), /<button type="button" class="ui-button ui-button--sm">Explore a ranked reef<\/button>/);
  explore.onClick();
  assert.equal(fake.count('exploreNext'), 1);
  stage.destroy();
});

test('no habitat (before load, after destroy): no status, list or Explore; a late event after destroy is ignored', async () => {
  m.terrainHabitat.value = null;
  browser(`${ORIGIN}?region=morro-bay&presentation=3d&layers=seafloor`);
  const none = html => !html.includes('data-reason="habitat"') && !html.includes('<ol>') && !html.includes('Explore a ranked reef');
  assert.ok(none(rail()), 'before load');
  const {stage, fake} = await mounted();
  assert.ok(none(rail()), 'mounted, no event yet');
  fake.options.onHabitat({status: 'ok', state: 'ok', ranks: [rank(1)], canExplore: true});
  assert.ok(!none(rail()));
  stage.destroy();
  assert.equal(m.terrainHabitat.value, null);
  assert.ok(none(rail()), 'after destroy');
  fake.options.onHabitat({status: 'late', state: 'ok', ranks: [rank(1)], canExplore: true});
  assert.equal(m.terrainHabitat.value, null, 'a destroyed stage writes nothing');
});

test('Chart: no Terrain options at all, even with a habitat event held', () => {
  browser(`${ORIGIN}?region=morro-bay&presentation=chart&layers=seafloor`);
  m.terrainHabitat.value = {status: 'Habitat status', state: 'ok', ranks: [rank(1)], canExplore: true};
  const html = m.render(m.h(m.LayerRail, {}));
  m.state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d&layers=seafloor`);
  const shown = m.render(m.h(m.LayerRail, {}));
  m.terrainHabitat.value = null;
  assert.ok(!html.includes('Terrain options') && !html.includes('data-reason="habitat"') && !html.includes('Explore a ranked reef'));
  assert.ok(shown.includes('data-reason="habitat">Habitat status<'), 'control: the same event shows in 3D');
});

test('a status or title holding <b> is text, not markup', async () => {
  const {stage, fake} = await mounted();
  fake.options.onHabitat({status: 'Reefs <b>withheld</b>', state: 'withheld', ranks: [{...rank(1), title: '<b>x</b>'}], canExplore: false});
  const html = rail();
  assert.ok(html.includes('data-reason="habitat">Reefs &lt;b>withheld&lt;/b></p>'), 'status escaped');
  assert.ok(html.includes('<b>&lt;b>x&lt;/b></b>'), 'title escaped');
  stage.destroy();
});

test('exploreRankedReef() and selectRankedReef() with no live handle: false and a no-op, no throw', async () => {
  const {stage, fake} = await mounted();
  stage.destroy();
  assert.equal(m.exploreRankedReef(), false);
  assert.doesNotThrow(() => m.selectRankedReef('reef-1'));
  assert.equal(fake.count('exploreNext') + fake.count('selectHabitat'), 0);
});
