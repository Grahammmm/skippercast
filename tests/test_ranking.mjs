// "Where to look" ranking (FE-34, docs/plans/front-end/dev-plan.md; design § 8, § 10, § 12):
// one source at a time (reviewed terrain habitat where it binds and loads, else the survey
// reef atlas), nothing outside the profile's depth limit, the § 12 fit wording, a label per
// source, and a click that selects the mark or habitat as the map does. The atlas is the
// committed dist/data/atlas.json screened against the committed boundary snapshot; terrain
// features are synthetic, ranked by packages/coast's own `rankedHabitat`. Offline.
import assert from 'node:assert/strict';
import {mkdtemp, readFile} from 'node:fs/promises';
import {readFileSync, readdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rankedHabitat} from '../packages/coast/src/coast3d/regional.ts';
import {CHECKING, SCREEN_MAX_AGE_MS, assessScreen, markFit} from '../web/map/habitat.ts';
import {TOP, atlasPicks as checkedAtlasPicks, habitatPicks as checkedHabitatPicks, harborOrigin, loadTerrainHabitat, ranking, terrainHabitat} from '../web/ranking.ts';
import {distanceNm} from '../dist/spot-ranking.js';
import {locatePort} from '../web/ports.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MORRO = read('regions/morro-bay/region.json'), ATLAS = read('data/atlas.json');
const DATA = {region: {...MORRO, id: 'morro-bay'}, atlas: ATLAS, survey: null, geology: null};
const NOW = Date.now();
const CHECKED = assessScreen({areas: read('data/protected-areas.geojson').features, checkedAt: new Date(NOW).toISOString(), live: true}, NOW);
const CLAIMS = /hotspot|chance|probab|productive|best spot|catch rate|bite|guarantee/i;
const LATER = new Date(NOW + 86400000).toISOString(), EARLIER = new Date(NOW - 1000).toISOString();

/** A synthetic reviewed reef polygon (the properties rankedHabitat and the brief read). */
const reef = (id, props = {}) => ({type: 'Feature', id, geometry: {type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, properties: {
  id, region: 'morro-bay', exportable: true, screen_status: 'pass', screen_expires_at: LATER, waypoint_latitude: 35.3, waypoint_longitude: -120.95,
  depth_min_ft: 40, depth_max_ft: 80, terrain_score: 70, terrain_grade: 'B', fit_lingcod: 2, fit_cabezon_shallow_reef: 2, ...props}});
const FEATURES = [
  reef('m-deep', {depth_min_ft: 250, depth_max_ft: 320, fit_lingcod: 3, terrain_score: 99}),
  reef('m-a', {fit_lingcod: 3, terrain_score: 80}), reef('m-b', {terrain_score: 90}), reef('m-c', {depth_max_ft: 55, terrain_score: 60}),
  reef('m-d', {terrain_score: 50}), reef('m-e', {terrain_score: 40}), reef('m-weak', {fit_lingcod: 1, terrain_score: 100}),
  reef('m-expired', {screen_expires_at: EARLIER, fit_lingcod: 3}), reef('c-1', {region: 'cambria-san-simeon', fit_lingcod: 3}),
];
const READY = {state: 'ready', features: FEATURES, expiresAt: NOW + 3600000, rank: rankedHabitat};
// These tests cover the other filters: every place is water here. The land/water check has its own (test_land_water.mjs).
const WATER = () => ({state: 'water'});
const atlasPicks = (data, screen, target, limit, origin = harborOrigin(data), keep = undefined) => checkedAtlasPicks(data, screen, target, limit, origin, keep, WATER);
const habitatPicks = (ranked, screen, region, coast, limit, origin, keep = undefined) => checkedHabitatPicks(ranked, screen, region, coast, limit, origin, keep, WATER);
const inputs = (patch = {}) => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: CHECKED, terrain: {state: 'unavailable'}, now: NOW, place: WATER, ...patch});
const upper = depth => Number(/–(\d+) ft$/.exec(depth)[1]);

test('atlas picks: the top four admitted marks inside the limit, best fit first, labelled by source', () => {
  for (const [profile, limit] of [['boat', 300], ['spear', 60]]) {
    const r = ranking(inputs({profile}));
    assert.equal(r.source, 'atlas');
    assert.equal(r.label, 'Survey reef atlas');
    assert.ok(r.picks.length <= TOP);
    for (const p of r.picks) assert.ok(upper(p.depth) <= limit, `${p.id} ${p.depth} inside ${limit} ft`);
    if (!r.picks.length) assert.equal(r.empty, `No surveyed reef marks within ${limit} ft for this target.`);
  }
  const picks = atlasPicks(DATA, CHECKED, 'lingcod', 300);
  assert.equal(picks.length, TOP);
  const fits = picks.map(p => markFit(ATLAS.targets.find(t => t.id === p.id), 'lingcod').n);
  assert.deepEqual(fits, [...fits].sort((a, b) => b - a), 'ordered by fit');
  for (const p of picks) {
    assert.match(p.fit, /^Fits lingcod habitat [1-3] of 3$/);
    assert.match(p.distance, /^\d+\.\d nm$/);
    assert.equal(p.kind, 'spot');
  }
  assert.equal(harborOrigin(DATA).name, 'Morro Bay');
});

test('atlas reasons use only the selected target screen, otherwise neutral terrain', () => {
  const mark = {id: 'synthetic-reef', label: 'Synthetic reef', latitude: 0, longitude: 0,
    neighborhood_depth_ft: [40, 80], terrain_interpretation: 'Synthetic surveyed reef terrain.',
    metrics: {relief_210m_m: 8, rugose_or_bedrock_fraction_210m: 0.8,
      rough_habitat_within_250m_ha: 6, plane_residual_rms_250m_m: 1}};
  const data = {...DATA, atlas: {targets: [mark]}};
  const screen = {...CHECKED, boundaries: []};
  for (const target of ['lingcod', 'rockfish', 'rockfish-reef', 'gopher-rockfish', 'cabezon', 'cabezon-shallow-reef', 'reef', 'all']) {
    const [pick] = atlasPicks(data, screen, target, 100);
    assert.ok(pick, target);
    const expected = target === 'lingcod' ? '8.0 m local relief; 80% mapped rough cover.'
      : ['rockfish', 'rockfish-reef', 'gopher-rockfish'].includes(target) ? '6.0 ha nearby rough habitat; 80% mapped rough cover.'
      : mark.terrain_interpretation;
    assert.equal(pick.reason, expected, target);
    assert.equal(pick.fit, markFit(mark, target)?.line ?? 'Habitat fit unrated for this target');
    assert.deepEqual(atlasPicks(data, screen, target, 79), [], 'depth gate');
    const range = {maxNm: 1, shore: null};
    assert.deepEqual(atlasPicks(data, screen, target, 100, {latitude: 1, longitude: 1, name: 'Synthetic harbor'}, range), [], 'range gate');
    assert.deepEqual(atlasPicks(data, screen, target, 100, {latitude: 0, longitude: 0, name: 'Synthetic harbor'}, range).map(p => p.id), [pick.id], 'range gate keeps a mark at the origin');
    assert.deepEqual(atlasPicks(data, CHECKING, target, 100), [], 'screen gate');
  }
  const noText = {...data, atlas: {targets: [{...mark, terrain_interpretation: undefined}]}};
  assert.equal(atlasPicks(noText, screen, 'cabezon', 100)[0].reason, 'Surveyed reef terrain.');
  assert.deepEqual(atlasPicks(data, screen, 'unknown-target', 100), [], 'unknown target remains ineligible');
});

test('items outside the limit, without a depth band, or withheld by the screen never appear', () => {
  const best = ATLAS.targets.find(t => t.id === atlasPicks(DATA, CHECKED, 'lingcod', 300)[0].id);
  const deep = {...best, id: 'ZZ-deep', neighborhood_depth_ft: [200, 301]}, unknown = {...best, id: 'ZZ-unknown', neighborhood_depth_ft: undefined};
  const data = {...DATA, atlas: {...ATLAS, targets: [deep, unknown, ...ATLAS.targets]}};
  const ids = atlasPicks(data, CHECKED, 'lingcod', 300).map(p => p.id);
  assert.ok(!ids.includes('ZZ-deep') && !ids.includes('ZZ-unknown'));
  assert.deepEqual(atlasPicks(DATA, CHECKED, 'lingcod', 100).filter(p => upper(p.depth) > 100), []);
  const checking = ranking(inputs({screen: CHECKING}));
  assert.deepEqual(checking.picks, [], 'every mark is withheld until the protected-area check answers');
  assert.equal(checking.empty, CHECKING.note);
  assert.deepEqual(ranking(inputs({data: null})).picks, []);
});

test('terrain picks: packages/coast order, this region, inside the limit, one source and never mixed', () => {
  const r = ranking(inputs({terrain: READY}));
  assert.equal(r.source, 'terrain');
  assert.equal(r.label, 'Reviewed terrain habitat');
  assert.deepEqual(r.picks.map(p => p.id), ['m-a', 'm-b', 'm-c', 'm-d'], 'fit, then terrain score; deep, weak, expired and other-region habitat left out');
  assert.ok(r.picks.every(p => p.kind === 'habitat'));
  assert.equal(r.picks[0].fit, 'Fits lingcod habitat 3 of 3');
  assert.equal(r.picks[0].depth, '~40–80 ft');
  assert.equal(r.picks[0].reason, 'Terrain score 80/100 · grade B.');
  const spear = ranking(inputs({profile: 'spear', coast: 'cabezon-shallow-reef', target: 'cabezon-shallow-reef', terrain: READY}));
  assert.deepEqual(spear.picks.map(p => p.id), ['m-c'], 'spear keeps only habitat inside 60 ft');
  assert.equal(spear.picks[0].fit, 'Fits cabezon habitat 2 of 3');
  assert.equal(ranking(inputs({coast: 'all', target: 'reef', terrain: READY})).picks[0].fit, 'Screened reef habitat');
  // Elsewhere, or with the release unavailable or expired, the atlas ranks alone.
  assert.equal(ranking(inputs({region: 'southern-california', terrain: READY})).source, 'atlas');
  assert.equal(ranking(inputs({terrain: {...READY, expiresAt: NOW - 1}})).source, 'atlas');
  assert.deepEqual(habitatPicks(rankedHabitat(FEATURES, 'fit_lingcod', NOW), CHECKED, 'morro-bay', 'lingcod', 300, null).map(p => p.distance), ['—', '—', '—', '—']);
});

test('shore lists no ranked place here; the runs rank on the Chart', () => {
  const r = ranking(inputs({profile: 'shore', target: 'surfperch', coast: 'surfperch', terrain: READY}));
  assert.equal(r.source, null);
  assert.deepEqual(r.picks, []);
});

test('the release loads once and a failure leaves the atlas', async () => {
  let calls = 0;
  terrainHabitat.value = {state: 'idle'};
  await loadTerrainHabitat(async () => { calls++; throw new Error('offline'); });
  await loadTerrainHabitat(async () => { calls++; return {}; });
  assert.equal(calls, 1);
  assert.equal(terrainHabitat.value.state, 'unavailable');
  terrainHabitat.value = {state: 'idle'};
  await loadTerrainHabitat(async () => ({rankedHabitat, loadReviewedHabitat: async () => ({features: FEATURES, expiresAt: NOW + 1000})}));
  assert.equal(terrainHabitat.value.state, 'ready');
  terrainHabitat.value = {state: 'idle'};
});

test('wording per § 12: labels, fits, reasons and the basis promise nothing about fish', () => {
  for (const r of [ranking(inputs()), ranking(inputs({terrain: READY})), ranking(inputs({profile: 'spear'}))]) {
    for (const text of [r.label, r.basis, r.empty, ...r.picks.flatMap(p => [p.name, p.fit, p.reason])]) assert.doesNotMatch(text, CLAIMS, text);
    if (r.source) assert.match(r.basis, /fish presence is unverified/);
  }
});

// Synthetic current boundaries, independent of the reviewed release's own screen.
// The reef polygon is deliberately unrelated to its waypoint: admission checks the latter.
const area = (name, west, east, Type) => ({type: 'Feature', properties: {NAME: name, Type}, geometry: {
  type: 'Polygon', coordinates: [[[west, 35], [east, 35], [east, 35.2], [west, 35.2], [west, 35]]],
}});
const AREAS = [area('Synthetic protected area', -121, -120.9)];
const CLOSURES = [area('Synthetic groundfish closure', -120.8, -120.7, 'GEA')];
const SCREEN_INPUT = {areas: AREAS, checkedAt: new Date(NOW).toISOString(), live: false,
  closures: {areas: CLOSURES, checkedAt: new Date(NOW).toISOString()}};
const SCREENED = assessScreen(SCREEN_INPUT, NOW);
const currentTerrain = (features, patch = {}) => ranking(inputs({terrain: {...READY, features}, screen: SCREENED, ...patch}));
const pickIds = r => r.picks.map(p => p.id);
const atlasMark = (id, latitude, longitude) => ({id, label: id, latitude, longitude, neighborhood_depth_ft: [40, 80],
  metrics: {relief_210m_m: 8, rugose_or_bedrock_fraction_210m: 0.8, rough_habitat_within_250m_ha: 6, plane_residual_rms_250m_m: 1.5}});
const SCREEN_DATA = {...DATA, atlas: {targets: [atlasMark('atlas-allowed', 35.3, -120.95),
  atlasMark('atlas-closed', 35.1, -120.95), atlasMark('atlas-edge', 35, -120.95)]}};

test('terrain current screen: allows the waypoint outside mapped areas and describes the current check', () => {
  const r = currentTerrain([reef('allowed')]);
  assert.equal(SCREENED.status, 'ready');
  assert.equal(r.source, 'terrain');
  assert.deepEqual(pickIds(r), ['allowed']);
  assert.equal(r.picks[0].fit, 'Fits lingcod habitat 2 of 3');
  assert.match(r.basis, /passes the current protected-area and closure check/);
  assert.match(r.basis, /fish presence is unverified/);
  assert.doesNotMatch(r.basis, CLAIMS);
});

test('terrain current screen: withholds protected-area interiors and boundary contact using waypoint fields', () => {
  for (const latitude of [35.1, 35]) {
    const r = currentTerrain([reef('withheld', {waypoint_latitude: latitude, waypoint_longitude: -120.95})]);
    assert.equal(r.source, 'terrain');
    assert.deepEqual(r.picks, [], `waypoint latitude ${latitude} is withheld despite its reviewed-release pass`);
    assert.equal(r.empty, 'No reviewed terrain habitat passes the current protected-area and closure check within 300 ft for this target.');
  }
});

test('terrain current screen: withholds closure interiors and boundary contact', () => {
  for (const latitude of [35.1, 35]) {
    assert.deepEqual(currentTerrain([reef('closure', {waypoint_latitude: latitude, waypoint_longitude: -120.75})]).picks, []);
  }
});

test('terrain current screen: missing, checking, unavailable and stale checks withhold every terrain pick', () => {
  const old = new Date(NOW - SCREEN_MAX_AGE_MS - 1).toISOString();
  const unavailable = assessScreen({...SCREEN_INPUT, areas: null}, NOW);
  const stale = assessScreen({...SCREEN_INPUT, checkedAt: old}, NOW);
  const staleClosure = assessScreen({...SCREEN_INPUT, closures: {...SCREEN_INPUT.closures, checkedAt: old}}, NOW);
  const missingClosure = assessScreen({...SCREEN_INPUT, closures: null}, NOW);
  assert.equal(unavailable.status, 'unavailable');
  assert.equal(stale.status, 'stale');
  assert.equal(staleClosure.status, 'stale');
  assert.equal(missingClosure.status, 'stale');
  for (const screen of [undefined, null, CHECKING, unavailable, stale, staleClosure, missingClosure]) {
    const r = currentTerrain([reef('otherwise-allowed')], {screen});
    assert.equal(r.source, 'terrain', 'no fallback to atlas while terrain is withheld');
    assert.deepEqual(r.picks, []);
    assert.equal(r.empty, (screen ?? CHECKING).note);
  }
});

test('terrain current screen: rejects high-ranked waypoints before top-N and keeps admitted order', () => {
  const admitted = [reef('a', {fit_lingcod: 3, terrain_score: 90}), reef('b', {terrain_score: 90}),
    reef('c', {terrain_score: 80}), reef('d', {terrain_score: 70}), reef('e', {terrain_score: 60})];
  const closed = reef('closed-first', {fit_lingcod: 3, terrain_score: 100, waypoint_latitude: 35.1});
  const features = [...admitted].reverse().concat(closed);
  assert.equal(rankedHabitat(features, 'fit_lingcod', NOW)[0].id, 'closed-first');
  const r = currentTerrain(features);
  assert.equal(r.picks.length, TOP);
  assert.deepEqual(pickIds(r), ['a', 'b', 'c', 'd'], 'the next allowed waypoint fills the rejected high-rank slot');
});

test('terrain current screen: retains region, species, depth, reach and waypoint validity filters', () => {
  const origin = {name: 'Synthetic harbor', latitude: 35.3, longitude: -120.95};
  const data = {...DATA, region: {...DATA.region, harbor: origin}};
  const invalid = {terrain_score: 100, fit_lingcod: 3};
  const features = [reef('allowed', {waypoint_latitude: 35.3001}),
    reef('other-region', {...invalid, region: 'cambria-san-simeon'}), reef('wrong-species', {...invalid, fit_lingcod: 1}),
    reef('deep', {...invalid, depth_max_ft: 301}), reef('unknown-depth', {...invalid, depth_max_ft: null}),
    reef('far', {...invalid, waypoint_latitude: 35.5}), reef('no-waypoint', {...invalid, waypoint_longitude: null})];
  const r = currentTerrain(features, {data, reachNm: 1});
  assert.deepEqual(pickIds(r), ['allowed']);
  assert.equal(r.reach, 1);
  assert.equal(r.harbor, 'Synthetic harbor');
  assert.ok(r.picks[0].nm > 0 && r.picks[0].nm <= 1);
  assert.match(r.empty, /within 300 ft and 1 nm of Synthetic harbor/);
  assert.deepEqual(currentTerrain([reef('too-deep-for-spear')], {profile: 'spear'}).picks, []);
});

test('terrain current screen: retains reviewed-release feature gates independently of the current check', () => {
  const invalid = {fit_lingcod: 3, terrain_score: 100};
  const r = currentTerrain([reef('allowed'), reef('not-exportable', {...invalid, exportable: false}),
    reef('release-rejected', {...invalid, screen_status: 'fail'}), reef('feature-expired', {...invalid, screen_expires_at: EARLIER})]);
  assert.deepEqual(pickIds(r), ['allowed']);
});

test('terrain current screen: expired whole release still falls back to the independently screened atlas', () => {
  for (const expiresAt of [NOW, NOW - 1]) {
    const r = currentTerrain([reef('expired-release')], {data: SCREEN_DATA, terrain: {...READY, expiresAt}});
    assert.equal(r.source, 'atlas');
    assert.deepEqual(pickIds(r), ['atlas-allowed']);
    assert.deepEqual(r.picks, atlasPicks(SCREEN_DATA, SCREENED, 'lingcod', 300));
  }
});

test('terrain current screen: atlas screening and its withholding copy remain unchanged', () => {
  const r = ranking(inputs({data: SCREEN_DATA, screen: SCREENED}));
  assert.equal(r.source, 'atlas');
  assert.deepEqual(pickIds(r), ['atlas-allowed']);
  assert.equal(r.empty, 'No surveyed reef marks within 300 ft for this target.');
  assert.match(r.basis, /^Survey reef atlas marks that pass the current protected-area check/);
  const pending = ranking(inputs({data: SCREEN_DATA, screen: CHECKING}));
  assert.deepEqual(pending.picks, []);
  assert.equal(pending.empty, CHECKING.note);
});

let view;
async function loadView() {
  if (view) return view;
  const out = join(await mkdtemp(join(tmpdir(), 'where-')), 'where.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {WhereToLook, choosePick, pickRun} from './web/brief/WhereToLook.tsx';
      export {picked} from './web/map/marks.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}],
  });
  view = await import(pathToFileURL(out).href);
  return view;
}
function browser(state, href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  state.configureStore({v2: true, storage: null});
  state.syncFromURL(href);
}

test('clicking selects the mark or the habitat (one at a time) and opens the card; the selected row is pressed', async () => {
  const {WhereToLook, choosePick, picked, state, render, h} = await loadView();
  browser(state, 'https://s.test/map?region=morro-bay&habitat=m-a&focus=x');
  const before = picked.value;
  choosePick({id: 'SC26-001', kind: 'spot'});
  let url = new URL(location.href);
  assert.equal(url.searchParams.get('spot'), 'SC26-001');
  assert.ok(!url.searchParams.has('habitat') && !url.searchParams.has('focus'));
  assert.equal(picked.value, before + 1, 'a pick, so the mark card takes focus');
  assert.equal(state.selection.value, 'SC26-001');
  choosePick({id: 'm-b', kind: 'habitat'});
  url = new URL(location.href);
  assert.equal(url.searchParams.get('habitat'), 'm-b');
  assert.ok(!url.searchParams.has('spot'));
  const picks = [{id: 'm-a', kind: 'habitat', name: 'Reef habitat m-a', distance: '4.0 nm', depth: '~40–80 ft', fit: 'Fits lingcod habitat 3 of 3', reason: 'Terrain score 80/100.'},
    {id: 'm-b', kind: 'habitat', name: 'Reef habitat m-b', distance: '4.1 nm', depth: '~40–80 ft', fit: 'Fits lingcod habitat 2 of 3', reason: 'Terrain score 90/100.'}];
  const html = render(h(WhereToLook, {ranking: {source: 'terrain', label: 'Reviewed terrain habitat', basis: 'Basis sentence.', picks, empty: ''}}));
  assert.match(html, /<li data-mark="m-a"><button type="button" class="app-pick" aria-pressed="false">/);
  assert.match(html, /<li data-mark="m-b"><button type="button" class="app-pick" aria-pressed="true">/);
  assert.match(html, /class="app-where-source ui-mono">Reviewed terrain habitat</);
  assert.match(html, /<details class="ui-popover ui-popover--icon"[^>]*><summary[^>]*aria-label="About the reviewed terrain habitat ranking"/);
  const source = await readFile(join(ROOT, 'web/brief/WhereToLook.tsx'), 'utf8');
  assert.doesNotMatch(source, CLAIMS);
});

test('terrain current screen and Spear limits both apply: a pick must pass the check and sit within the depth and swim', () => {
  // A north-south shore line at -120.96: allowed (35.3, -120.95) and withheld (35.1, -120.95) are both ~1,000 yd off it.
  const lines = [[[-120.96, 34.9], [-120.96, 35.5]]];
  const spear = patch => currentTerrain([reef('near-allowed', {depth_max_ft: 55}), reef('near-withheld', {depth_max_ft: 55, waypoint_latitude: 35.1}),
    reef('too-deep', {depth_max_ft: 80})], {profile: 'spear', coast: 'cabezon-shallow-reef', target: 'cabezon-shallow-reef', ...patch});
  assert.deepEqual(pickIds(spear({})), ['near-allowed'], 'the check withholds one, the 60 ft limit the other');
  assert.deepEqual(pickIds(spear({shore: {maxYd: 1200, lines}})), ['near-allowed'], 'within the swim, and still never the withheld one');
  assert.match(spear({shore: {maxYd: 1200, lines}}).picks[0].distance, /^~\d+ yd from shore$/);
  const far = spear({shore: {maxYd: 500, lines}});
  assert.deepEqual(far.picks, [], 'outside the swim');
  assert.equal(far.empty, 'No reviewed terrain habitat passes the current protected-area and closure check within 60 ft and 500 yd of shore for this target.');
});

// CI6-01A: a run distance is measured from the chosen harbor or launch, never from the device.
// A decoy device fix stands in for the browser's location; nothing on these paths may read it.
const DEVICE = {latitude: 35.62, longitude: -121.18};
function trapGeolocation() {
  const calls = [];
  const fix = ok => ok({coords: {...DEVICE, accuracy: 10}, timestamp: NOW});
  const geolocation = {getCurrentPosition(ok) { calls.push('getCurrentPosition'); fix(ok); }, watchPosition(ok) { calls.push('watchPosition'); fix(ok); return 1; }, clearWatch() {}};
  const saved = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {value: {...globalThis.navigator, geolocation}, configurable: true, writable: true});
  return {calls, restore() { if (saved) Object.defineProperty(globalThis, 'navigator', saved); else delete globalThis.navigator; }};
}
const withHarbor = harbor => ({...DATA, region: {...DATA.region, harbor}});
const {harbor: _harbor, ...NO_HARBOR_REGION} = DATA.region;
const NO_HARBOR = {...DATA, region: {...NO_HARBOR_REGION, position: DEVICE, location: DEVICE}};
const SPREAD = ['n-1', 'n-2', 'n-3', 'n-4'].map((id, i) => reef(id, {waypoint_latitude: 35.28 + 0.02 * i, waypoint_longitude: -120.95 - 0.02 * i, terrain_score: 90 - i}));
const placeOf = {
  atlas: id => ATLAS.targets.find(t => t.id === id),
  terrain: id => { const p = SPREAD.find(f => f.id === id).properties; return {latitude: p.waypoint_latitude, longitude: p.waypoint_longitude}; },
};

test('run distance: both sources measure from the chosen harbor or launch, and never read the device position', () => {
  const geo = trapGeolocation();
  try {
    const origins = [{name: 'Synthetic harbor', latitude: 35.37, longitude: -120.86}, {name: 'Synthetic launch', latitude: 35.1, longitude: -120.7}];
    const seen = {atlas: new Set(), terrain: new Set()};
    for (const origin of origins) {
      const data = withHarbor(origin);
      for (const r of [ranking(inputs({data})), ranking(inputs({data, terrain: {...READY, features: SPREAD}}))]) {
        assert.equal(r.harbor, origin.name, `${r.source} names the run origin`);
        assert.ok(r.basis.includes(`straight-line from ${origin.name}.`), r.basis);
        assert.equal(r.picks.length, TOP, `${r.source}: ${r.picks.map(p => p.id)} ${r.empty}`);
        for (const p of r.picks) {
          const at = placeOf[r.source](p.id), nm = distanceNm(origin, at);
          assert.equal(p.nm, nm, `${r.source} ${p.id} from ${origin.name}`);
          assert.equal(p.distance, `${nm.toFixed(1)} nm`);
          assert.notEqual(p.nm, distanceNm(DEVICE, at), 'not from the device');
          seen[r.source].add(p.distance);
        }
      }
    }
    assert.ok(seen.atlas.size > TOP && seen.terrain.size > TOP, 'moving the origin moves every source\'s distances');
    // An explicit origin argument is the one used, for both sources.
    const launch = origins[1];
    for (const p of atlasPicks(withHarbor(origins[0]), CHECKED, 'lingcod', 300, launch)) assert.equal(p.nm, distanceNm(launch, placeOf.atlas(p.id)));
    for (const p of habitatPicks(SPREAD, CHECKED, 'morro-bay', 'lingcod', 300, launch)) assert.equal(p.nm, distanceNm(launch, placeOf.terrain(p.id)));
    // Only a published harbor with a finite position is an origin; device-like fields on the region are ignored.
    assert.equal(harborOrigin(NO_HARBOR), null);
    assert.equal(harborOrigin({...NO_HARBOR, region: {...NO_HARBOR.region, harbor: {name: 'No position'}}}), null);
    assert.equal(harborOrigin({...NO_HARBOR, region: {...NO_HARBOR.region, harbor: {name: 'Bad', latitude: NaN, longitude: -120}}}), null);
    assert.deepEqual(geo.calls, [], 'ranking never asks for the device position');
  } finally { geo.restore(); }
});

test('run origin: only the port chooser reads the device position, and it hands back a listed port', async () => {
  const files = [];
  const walk = dir => { for (const e of readdirSync(dir, {withFileTypes: true})) {
    const path = join(dir, e.name);
    if (e.isDirectory()) walk(path); else if (/\.(?:ts|tsx|js|mjs)$/.test(e.name)) files.push(path);
  } };
  walk(join(ROOT, 'web'));
  // The hand-written v1 scripts at the top of dist/ (dist/client and dist/server are the built bundle).
  for (const name of readdirSync(join(ROOT, 'dist'))) if (/\.m?js$/.test(name)) files.push(join(ROOT, 'dist', name));
  const DEVICE_READ = /\bgeolocation\b|getCurrentPosition|watchPosition|\.coords\b/;
  const readers = files.filter(f => DEVICE_READ.test(readFileSync(f, 'utf8'))).map(f => f.slice(ROOT.length)).sort();
  assert.deepEqual(readers, ['dist/home-port.js', 'web/landing/PortInput.tsx', 'web/ports.ts'],
    'a new reader of the device position must not feed a run distance; review it and extend this list only if it suggests a listed port');
  // Each reader turns the fix straight into the nearest listed port; PortInput only passes geolocation to locatePort.
  for (const f of ['dist/home-port.js', 'web/ports.ts']) {
    const text = readFileSync(join(ROOT, f), 'utf8');
    const used = text.match(/position\.coords\.\w+/g) ?? [];
    assert.deepEqual(used, ['position.coords.latitude', 'position.coords.longitude'], f);
    assert.match(text, /closestPort\(ports, position\.coords\.latitude, position\.coords\.longitude\)/, f);
  }
  const input = readFileSync(join(ROOT, 'web/landing/PortInput.tsx'), 'utf8');
  assert.doesNotMatch(input, /getCurrentPosition|watchPosition|\.coords\b/);
  // locatePort answers with the directory's own port object, not the fix.
  const port = (id, match) => ({id, name: id, region: 'morro-bay', status: 'active', forecast_point: id, forecast_name: id, match});
  const ports = [port('near', [35.6, -121.15]), port('far', [34.4, -119.7])];
  const geo = trapGeolocation();
  try {
    const found = await locatePort(ports, globalThis.navigator.geolocation);
    assert.equal(found.ok, true);
    assert.equal(found.port, ports[0], 'the listed port itself');
    assert.doesNotMatch(JSON.stringify(found), new RegExp(String(DEVICE.latitude)), 'the device fix is not carried along');
    assert.deepEqual(geo.calls, ['getCurrentPosition']);
  } finally { geo.restore(); }
});

test('run distance: without a harbor position every pick shows the no-distance dash, never a device figure', async () => {
  const geo = trapGeolocation();
  try {
    for (const terrain of [{state: 'unavailable'}, {...READY, features: SPREAD}]) {
      const r = ranking(inputs({data: NO_HARBOR, terrain, reachNm: 5}));
      assert.ok(r.picks.length > 0, `${r.source} still ranks`);
      for (const p of r.picks) {
        assert.equal(p.distance, '—', `${r.source} ${p.id}`);
        assert.equal(p.nm, null);
      }
      assert.equal(r.harbor, undefined);
      assert.equal(r.reach, undefined, 'a range cannot be measured without a harbor, so none is applied');
      assert.ok(r.basis.includes('straight-line from the region\'s harbor, which has no published position here, so no distance is shown.'), r.basis);
      assert.doesNotMatch(r.basis, /\d nm/);
    }
    assert.ok(atlasPicks(NO_HARBOR, CHECKED, 'lingcod', 300).every(p => p.distance === '—' && p.nm === null), 'the default origin is the harbor, and there is none');
    assert.ok(habitatPicks(SPREAD, CHECKED, 'morro-bay', 'lingcod', 300, null).every(p => p.distance === '—' && p.nm === null));
    // The row shows the dash; without a distance no run time is added, whatever the cruise speed.
    const {WhereToLook, pickRun, state, render, h} = await loadView();
    assert.equal(pickRun(null, 18), '');
    browser(state, 'https://s.test/map?region=morro-bay');
    const r = ranking(inputs({data: NO_HARBOR}));
    const html = render(h(WhereToLook, {ranking: r}));
    assert.equal((html.match(/<span class="ui-mono">— · ~\d+–\d+ ft<\/span>/g) ?? []).length, r.picks.length, html);
    assert.doesNotMatch(html, /\d nm\b/);
    assert.deepEqual(geo.calls, [], 'no device fix fills the gap');
  } finally { geo.restore(); }
});
