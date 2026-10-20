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
import {coastTargetsFor, loadPlans, optionText, reefRanked, regionAtlas, regionPlans, regionTargets, regionUnavailable, TARGET_STATE_TEXT, targetsFor, targetState, unavailableTargets} from '../web/species.ts';
import {hasCoastTerrain} from '../web/coast-context.ts';
import {habitatFamily, markFeatures} from '../web/map/habitat.ts';
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
      export {regionAtlas, regionPlans, regionUnavailable} from './web/species.ts';
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
    assert.match(html, /<option selected value="surfperch">Barred surfperch · not researched in this region<\/option>/, presentation);
  }
  m.regionPlans.value = null;
});

test('FE-54: the target menu groups plans by the profile\'s method, its own species and the coast targets, with search', async () => {
  const groups = html => [...html.matchAll(/<optgroup label="([^"]+)">(.*?)<\/optgroup>/g)].map(g => [g[1].replace(/&amp;/g, '&'), options(g[2])]);
  const m = await loadMenu();
  m.state.configureStore({v2: true, storage: null});
  m.regionPlans.value = {region: 'morro-bay', plans: PLANS};
  m.state.syncFromURL(`${ORIGIN}?region=morro-bay&profile=boat`);
  assert.deepEqual(groups(m.render(m.h(m.TargetSelect))), [
    ['Boat targets', ['lingcod']],
    ['Search plans · Boat', ['reef', 'halibut', 'salmon', 'albacore', 'bluefin', 'dungeness']],
    ['Coast habitat targets', ['rockfish-reef', 'gopher-rockfish', 'cabezon-shallow-reef']],
  ], 'boat: every plan whose method is boat, never merged with the coast targets');
  m.state.syncFromURL(`${ORIGIN}?region=morro-bay&profile=spear`);
  assert.deepEqual(groups(m.render(m.h(m.TargetSelect))).map(g => g[0]), ['Spear targets', 'Search plans · Spear', 'Coast habitat targets']);
  assert.deepEqual(groups(m.render(m.h(m.TargetSelect)))[1][1], ['reef'], 'spear lists only the dive-method plan');
  m.state.syncFromURL(`${ORIGIN}?region=morro-bay&profile=boat&target=vermilion`);
  assert.deepEqual(groups(m.render(m.h(m.TargetSelect)))[0], ['From the link', ['vermilion']], 'the link\'s own target heads the menu');
  assert.match(m.render(m.h(m.TargetSelect)), /<input type="search" class="app-target-search" aria-label="Find a target"/);
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
  // #617: the search-plan index first; the full plans only when the index fails.
  const index = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/search-plan-index.json', import.meta.url), 'utf8'));
  assert.deepEqual(index.profiles, PLANS, 'the committed index carries every plan profile');
  for (const failIndex of [false, true]) {
    const asked = [];
    await loadPlans('morro-bay', async url => {
      asked.push(String(url));
      return failIndex && String(url).endsWith('search-plan-index.json') ? {ok: false} : {ok: true, json: async () => ({region_id: 'morro-bay', profiles: PLANS})};
    });
    assert.deepEqual(asked, ['regions/morro-bay/search-plan-index.json', ...failIndex ? ['regions/morro-bay/search-plans.json'] : []]);
    assert.equal(regionPlans.value.region, 'morro-bay');
    regionPlans.value = null;
  }
});

// CI6-02: species honesty in the target picker. Every state comes from committed data: the region's
// search plans and `map.unavailable_targets`, whether it has coastal terrain or survey atlas marks, and
// the plan's kind. catalog/search-methods.json is read only, to check the reef rule against the catalog.
const committed = path => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const regionData = id => committed(`dist/regions/${id}/region.json`);
const plansOf = id => committed(`dist/regions/${id}/search-plans.json`).profiles;
const atlasMarks = id => (committed(`dist/${regionData(id).assets.atlas}`).targets ?? []).length;
/** The coverage the picker reads for region `id`, from its committed files. */
const coverageOf = id => ({unavailable: unavailableTargets(regionData(id)), plansLoaded: true, ranks: hasCoastTerrain(id) || atlasMarks(id) > 0});
const METHODS = committed('catalog/search-methods.json').species;

test('CI6-02: every Morro Bay species shows its state from committed data (Accept 1, 2)', () => {
  const region = regionData('morro-bay'), plans = plansOf('morro-bay'), coverage = coverageOf('morro-bay');
  assert.deepEqual(region.species, ['reef', 'halibut', 'salmon', 'albacore', 'bluefin', 'dungeness'], 'the region\'s researched target list');
  assert.equal(coverage.ranks, true, 'Morro Bay has coastal terrain and survey atlas marks to rank');
  const states = Object.fromEntries(region.species.map(id => [id, targetState(id, 'boat', plans, coverage)]));
  assert.deepEqual(states, {reef: 'ranked', halibut: 'plan', salmon: 'plan', albacore: 'plan', bluefin: 'plan', dungeness: 'plan'});
  // Not a per-species table: ranked exactly where the catalog's search method is a reef method.
  for (const id of region.species) assert.equal(states[id] === 'ranked', METHODS[id].kind === 'reef', id);
  // The menu lists every species with the same state, beside its own name.
  const listed = targetsFor('boat', 'morro-bay', plans, null, coverage);
  for (const id of region.species) {
    const t = listed.find(o => o.id === id);
    assert.ok(t, `${id} stays listed (Accept 4)`);
    assert.equal(t.state, states[id], id);
    assert.equal(optionText(t), `${plans[id].name} · ${TARGET_STATE_TEXT[states[id]]}`);
  }
  // The coast targets the terrain scores are ranked; the region's unavailable target is not researched.
  assert.deepEqual(listed.filter(t => t.group !== 'plan').map(t => [t.id, t.state]),
    [['lingcod', 'ranked'], ['rockfish-reef', 'ranked'], ['gopher-rockfish', 'ranked'], ['cabezon-shallow-reef', 'ranked']]);
  assert.deepEqual(Object.keys(coverage.unavailable), ['lobster']);
  assert.equal(targetState('lobster', 'boat', plans, coverage), 'unresearched', 'map.unavailable_targets');
  assert.equal(targetsFor('boat', 'morro-bay', plans, 'lobster', coverage)[0].state, 'unresearched', 'a link naming it says so');
  // Shore ranks no places (its runs show on the Chart): halibut has a plan only; surfperch is outside the researched list.
  assert.deepEqual(targetsFor('shore', 'morro-bay', plans, null, coverage).map(t => [t.id, t.state]), [['surfperch', 'unresearched'], ['halibut', 'plan']]);
  assert.deepEqual(targetsFor('spear', 'morro-bay', plans, null, coverage).map(t => t.state), ['ranked', 'ranked', 'ranked', 'ranked', 'ranked']);
});

test('CI6-02: "ranked" needs places to rank and the reef habitat family the ranking reads', () => {
  // Without terrain or atlas marks, the reef plan is a search plan only; atlas marks make it ranked.
  assert.equal(hasCoastTerrain('crescent-city'), false);
  assert.equal(atlasMarks('crescent-city'), 0);
  assert.equal(targetState('reef', 'boat', plansOf('crescent-city'), coverageOf('crescent-city')), 'plan');
  assert.ok(atlasMarks('southern-california') > 0);
  const socal = plansOf('southern-california'), cover = coverageOf('southern-california');
  assert.equal(targetState('reef', 'boat', socal, cover), 'ranked');
  assert.equal(targetState('kelp-bass', 'boat', socal, cover), 'plan', 'a habitat plan outside the reef family is not ranked');
  assert.deepEqual(['salmon', 'dungeness'].map(id => targetState(id, 'boat', socal, cover)), ['unresearched', 'unresearched'], 'southern-california names them unavailable');
  // reefRanked is the family web/map/habitat.ts ranks, for every target any profile lists in any region.
  for (const id of ['morro-bay', 'southern-california', 'crescent-city', 'cambria-san-simeon']) {
    const plans = plansOf(id);
    for (const p of ['boat', 'shore', 'spear', 'kayak']) for (const t of targetsFor(p, id, plans))
      assert.equal(reefRanked(t.id, plans), habitatFamily(t.id) === 'reef', `${id} ${p} ${t.id}`);
  }
});

test('CI6-02: states wait for the data that decides them, and use no catch, feeding, hotspot or bite wording (Accept 3)', () => {
  for (const text of Object.values(TARGET_STATE_TEXT)) assert.doesNotMatch(text, /catch|feed|hot ?spot|bite|fish (?:are|is) (?:here|present)/i, text);
  configureStore({v2: true, storage: null});
  syncFromURL(`${ORIGIN}?region=morro-bay&profile=shore`);
  // Before the plans load, a target nothing ranks has no state yet rather than a wrong one.
  assert.deepEqual(regionTargets('shore', 'morro-bay', null).map(t => [t.id, t.state]), [['surfperch', null], ['halibut', null]]);
  assert.equal(regionTargets('boat', 'morro-bay', null)[0].state, 'ranked', 'lingcod: the terrain ranks it with or without plans');
  regionPlans.value = {region: 'morro-bay', plans: PLANS};
  regionUnavailable.value = {region: 'morro-bay', targets: unavailableTargets(regionData('morro-bay'))};
  assert.deepEqual(regionTargets('shore', 'morro-bay', null).map(t => t.state), ['unresearched', 'plan']);
  assert.equal(regionTargets('boat', 'morro-bay', 'lobster')[0].state, 'unresearched');
  // Another region's facts never apply.
  regionUnavailable.value = {region: 'southern-california', targets: {halibut: 'x'}};
  assert.equal(regionTargets('shore', 'morro-bay', null)[1].state, 'plan');
  // An atlas-only region is ranked once its marks load, and only for itself.
  syncFromURL(`${ORIGIN}?region=southern-california&profile=boat`);
  regionPlans.value = {region: 'southern-california', plans: plansOf('southern-california')};
  assert.equal(regionTargets('boat', 'southern-california', 'reef').find(t => t.id === 'reef').state, 'plan', 'no marks loaded yet');
  regionAtlas.value = {region: 'southern-california', marks: atlasMarks('southern-california')};
  assert.equal(regionTargets('boat', 'southern-california', 'reef').find(t => t.id === 'reef').state, 'ranked');
  regionAtlas.value = {region: 'morro-bay', marks: 132};
  assert.equal(regionTargets('boat', 'southern-california', 'reef').find(t => t.id === 'reef').state, 'plan');
  regionPlans.value = null; regionUnavailable.value = null; regionAtlas.value = null;
});

test('CI6-02: the command bar shows each target\'s state and lists the region\'s unavailable targets, unselectable', async () => {
  const m = await loadMenu();
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(`${ORIGIN}?region=morro-bay&profile=boat`);
  m.regionPlans.value = {region: 'morro-bay', plans: PLANS};
  m.regionUnavailable.value = {region: 'morro-bay', targets: unavailableTargets(regionData('morro-bay'))};
  const html = m.render(m.h(m.TargetSelect)).replace(/&amp;/g, '&');
  const shown = Object.fromEntries([...html.matchAll(/<option(?: selected)? value="([^"]+)"(?: disabled)?>([^<]+)<\/option>/g)].map(o => [o[1], o[2]]));
  assert.deepEqual(shown, {
    lingcod: 'Lingcod · ranked by mapped habitat',
    reef: 'Lingcod & rockfish · ranked by mapped habitat',
    halibut: 'California halibut · search plan only',
    salmon: 'Chinook salmon · search plan only',
    albacore: 'Albacore tuna · search plan only',
    bluefin: 'Pacific bluefin tuna · search plan only',
    dungeness: 'Dungeness crab · search plan only',
    'rockfish-reef': 'Reef rockfish · ranked by mapped habitat',
    'gopher-rockfish': 'Gopher rockfish · ranked by mapped habitat',
    'cabezon-shallow-reef': 'Cabezon · ranked by mapped habitat',
    lobster: 'Lobster · not researched in this region',
  });
  assert.match(html, /<optgroup label="Other targets"><option value="lobster" disabled>/, 'listed, never selectable');
  // The search narrows by name, never by state words.
  assert.deepEqual(options(html), ['lingcod', 'reef', 'halibut', 'salmon', 'albacore', 'bluefin', 'dungeness', 'rockfish-reef', 'gopher-rockfish', 'cabezon-shallow-reef']);
  m.regionPlans.value = null; m.regionUnavailable.value = null;
});
