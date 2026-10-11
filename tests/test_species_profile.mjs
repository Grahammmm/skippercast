// Profiles applied across the app (FE-30, docs/plans/front-end/dev-plan.md; design § 8): the
// target list (the profile's species, the region's search plans by method, the coast targets
// through coastTarget), reef marks and the depth limit on the Chart and in the terrain handle's
// state, and which link keys win over storage. web/species.ts, web/map/habitat.ts, web/map/stage.ts
// and web/state.ts run by type stripping; the command bar's target menu is bundled with esbuild.
// The Morro Bay plans are the committed dist/regions file; the marks are synthetic.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {coastTargetsFor, loadPlans, regionPlans, targetsFor} from '../web/species.ts';
import {markFeatures} from '../web/map/habitat.ts';
import {terrainState} from '../web/map/stage.ts';
import {PROFILE_TABLE} from '../web/profile.ts';
import {configureStore, current, layers, profile, profilePatch, readURL, species, syncFromURL, withParams} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const ORIGIN = 'https://s.test/map';
const PLANS = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/search-plans.json', import.meta.url), 'utf8')).profiles;
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), map: m}; };
const READY = {status: 'ready', note: '', source: 'synthetic', boundaries: [], until: Number.POSITIVE_INFINITY};
/** Synthetic reef marks: one whose nearby depths reach 45 ft, one 90 ft, one 250 ft, all rugged enough for lingcod. */
const mark = (id, deepest) => ({id, label: id, latitude: 35.3, longitude: -120.9, neighborhood_depth_ft: [20, deepest],
  metrics: {relief_210m_m: 5, rugose_or_bedrock_fraction_210m: 0.8}});
const ATLAS = {targets: [mark('m45', 45), mark('m90', 90), mark('m250', 250)]};
const ids = collection => collection.features.map(f => f.properties.id);
const terrain = (p, target = null) => terrainState({profile: p, target, hour: null, camera: null, current: 'off', habitat: null,
  presentation: '3d', appView: 'coast', hidden: false, now: new Date('2026-10-09T20:00:00Z')});

let menu;
async function loadMenu() {
  if (menu) return menu;
  const out = join(await mkdtemp(join(tmpdir(), 'targets-')), 'menu.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {TargetSelect} from './web/app/CommandBar.tsx';
      export * as state from './web/state.ts';
      export {regionPlans} from './web/species.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  menu = await import(pathToFileURL(out).href);
  return menu;
}
const options = html => [...html.matchAll(/<option(?: selected)? value="([^"]+)">/g)].map(m => m[1]);

test('targets: the profile\'s species, the region\'s plans by method, then the coast targets coastTarget does not already name', () => {
  assert.deepEqual(targetsFor('boat', 'morro-bay', PLANS).map(t => t.id),
    ['lingcod', 'reef', 'halibut', 'salmon', 'albacore', 'bluefin', 'dungeness', 'rockfish-reef', 'gopher-rockfish', 'cabezon-shallow-reef']);
  assert.deepEqual(targetsFor('shore', 'morro-bay', PLANS).map(t => t.id), ['surfperch', 'halibut']);
  assert.deepEqual(targetsFor('spear', 'morro-bay', PLANS).map(t => t.id), ['cabezon-shallow-reef', 'reef', 'lingcod', 'rockfish-reef', 'gopher-rockfish']);
  assert.equal(targetsFor('boat', 'morro-bay', PLANS).find(t => t.id === 'reef').label, 'Lingcod & rockfish', 'plans keep their own names');
  assert.equal(targetsFor('shore', 'morro-bay', PLANS)[0].label, 'Barred surfperch', 'coast targets keep the renderer\'s names');
  // A region without coastal terrain lists no coast target.
  assert.deepEqual(targetsFor('spear', 'southern-california', {}).map(t => t.id), ['cabezon-shallow-reef']);
  assert.deepEqual(coastTargetsFor('shore').map(t => t.id), ['halibut', 'surfperch']);
});

test('Shore hides reef marks and lists surfperch first, on the Chart and in the terrain (Accept 1)', async () => {
  configureStore({v2: true, storage: memory()});
  let href = `${ORIGIN}?region=morro-bay&profile=boat&target=lingcod`;
  syncFromURL(href);
  assert.deepEqual(ids(markFeatures(ATLAS, species.value ?? PROFILE_TABLE[profile.value].defaultTarget, profile.value, READY)), ['m45', 'm90', 'm250']);
  href = withParams(href, profilePatch('shore'));
  syncFromURL(href);
  const target = species.value ?? PROFILE_TABLE[profile.value].defaultTarget;
  assert.equal(target, 'surfperch');
  assert.deepEqual(ids(markFeatures(ATLAS, target, 'shore', READY)), [], 'no reef mark on the Chart');
  assert.equal(terrain('shore').species, 'surfperch', 'the terrain draws the shore target, not reef pins');
  // The one target menu serves the Chart and the terrain: surfperch first in both.
  const m = await loadMenu();
  m.state.configureStore({v2: true, storage: null});
  m.regionPlans.value = {region: 'morro-bay', plans: PLANS};
  for (const presentation of ['chart', '3d']) {
    m.state.syncFromURL(`${ORIGIN}?region=morro-bay&profile=shore&presentation=${presentation}`);
    const html = m.render(m.h(m.TargetSelect));
    assert.deepEqual(options(html), ['surfperch', 'halibut'], presentation);
    assert.match(html, /<option selected value="surfperch">Barred surfperch<\/option>/, presentation);
  }
  m.regionPlans.value = null;
});

test('Spear limits marks to 60 ft on the Chart and in the terrain; Boat to 300 ft (Accept 2)', () => {
  assert.deepEqual(ids(markFeatures(ATLAS, 'cabezon-shallow-reef', 'spear', READY)), ['m45']);
  assert.deepEqual(ids(markFeatures(ATLAS, 'lingcod', 'boat', READY)), ['m45', 'm90', 'm250']);
  assert.deepEqual(ids(markFeatures({targets: [...ATLAS.targets, mark('m400', 400)]}, 'lingcod', 'boat', READY)), ['m45', 'm90', 'm250']);
  assert.deepEqual(['boat', 'shore', 'spear'].map(p => terrain(p).depthLimit), [300, 300, 60], 'the terrain handle gets the same limit (setDepthLimit)');
});

test('?profile= and Fish ?mode= win over storage; an unsupported target stays explicit (Accept 3)', async () => {
  const store = memory();
  configureStore({v2: true, storage: store});
  syncFromURL(`${ORIGIN}?profile=boat`);
  syncFromURL(`${ORIGIN}?region=morro-bay`);
  assert.equal(profile.value, 'boat', 'storage when the link names none');
  syncFromURL(`${ORIGIN}?region=morro-bay&mode=shore`);
  assert.equal(profile.value, 'shore', 'Fish ?mode= wins over storage');
  assert.deepEqual(layers.value, PROFILE_TABLE.shore.defaultLayers);
  assert.equal(current.value, 'off');
  syncFromURL(`${ORIGIN}?region=morro-bay&profile=spear&mode=shore`);
  assert.equal(profile.value, 'spear', 'an explicit ?profile= wins over ?mode=');
  syncFromURL(`${ORIGIN}?region=morro-bay&profile=boat`);
  assert.equal(profile.value, 'boat');
  // A target no list offers stays in the link, first in the menu and as given to the terrain.
  const href = `${ORIGIN}?region=morro-bay&profile=shore&target=yellowtail`;
  syncFromURL(href);
  assert.equal(species.value, 'yellowtail');
  assert.equal(readURL(withParams(href, {hour: '2026-10-09T20:00Z'})).target, 'yellowtail', 'other changes keep it');
  assert.deepEqual(targetsFor('shore', 'morro-bay', PLANS, 'yellowtail').map(t => t.id), ['yellowtail', 'surfperch', 'halibut']);
  assert.equal(terrain('shore', 'yellowtail').species, 'yellowtail', 'never swapped for the profile default');
  syncFromURL(`${ORIGIN}?region=morro-bay&mode=shore&species=yellowtail`);
  assert.equal(species.value, 'yellowtail', 'Fish ?species= is the target');
  configureStore({storage: null});
});

test('the region\'s plans load for that region only', async () => {
  const fetchFn = async url => ({ok: true, json: async () => ({region_id: String(url).includes('morro-bay') ? 'morro-bay' : 'other', profiles: PLANS})});
  regionPlans.value = null;
  await loadPlans('cambria-san-simeon', fetchFn);
  assert.equal(regionPlans.value, null, 'a file naming another region is refused');
  await loadPlans('morro-bay', fetchFn);
  assert.equal(regionPlans.value.region, 'morro-bay');
  await loadPlans('morro-bay', async () => ({ok: false}));
  assert.equal(regionPlans.value.region, 'morro-bay', 'a failed load keeps what was listed');
  regionPlans.value = null;
});
