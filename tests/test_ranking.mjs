// "Where to look" ranking (FE-34, docs/plans/front-end/dev-plan.md; design § 8, § 10, § 12):
// one source at a time (reviewed terrain habitat where it binds and loads, else the survey
// reef atlas), nothing outside the profile's depth limit, the § 12 fit wording, a label per
// source, and a click that selects the mark or habitat as the map does. The atlas is the
// committed dist/data/atlas.json screened against the committed boundary snapshot; terrain
// features are synthetic, ranked by packages/coast's own `rankedHabitat`. Offline.
import assert from 'node:assert/strict';
import {mkdtemp, readFile} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rankedHabitat} from '../packages/coast/src/coast3d/regional.ts';
import {CHECKING, assessScreen, markFit} from '../web/map/habitat.ts';
import {TOP, atlasPicks, habitatPicks, harborOrigin, loadTerrainHabitat, ranking, terrainHabitat} from '../web/ranking.ts';

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
const inputs = (patch = {}) => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: CHECKED, terrain: {state: 'unavailable'}, now: NOW, ...patch});
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
  assert.deepEqual(habitatPicks(rankedHabitat(FEATURES, 'fit_lingcod', NOW), 'morro-bay', 'lingcod', 300, null).map(p => p.distance), ['—', '—', '—', '—']);
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

let view;
async function loadView() {
  if (view) return view;
  const out = join(await mkdtemp(join(tmpdir(), 'where-')), 'where.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {WhereToLook, choosePick} from './web/brief/WhereToLook.tsx';
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
