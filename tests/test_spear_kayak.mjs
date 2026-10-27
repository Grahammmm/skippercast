// #644 (walkthrough slice 5, part 2): Spear's own deepest dive, where the diver
// dives from and the farthest swim from shore (web/reach.ts, web/profile.ts,
// web/shore-distance.ts), and Kayak's launch (web/launches.ts): kept on the
// device, applied to "Where to look" (web/ranking.ts), shown in Your limits and
// the brief (web/app/LimitsPanel.tsx, web/brief/WhereToLook.tsx). Offline: the
// atlas, launch list and shoreline are the committed snapshots.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {distanceNm} from '../dist/spot-ranking.js';
import {assessScreen} from '../web/map/habitat.ts';
import {reachFeatures} from '../web/map/reach.ts';
import {launchOrigin, launchPoints, loadLaunchPoints, parseLaunchPoints, resetLaunchPoints} from '../web/launches.ts';
import {depthLimitFt, ownSpearDepthFt, PROFILE_TABLE, terrainDepthLimitFt, withinDepth} from '../web/profile.ts';
import {harborOrigin, ranking} from '../web/ranking.ts';
import * as reach from '../web/reach.ts';
import {linesOf, loadShoreLines, resetShoreLines, shoreLines, yardsFromShore} from '../web/shore-distance.ts';
import {configureStore, STORAGE_KEYS} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MORRO = read('regions/morro-bay/region.json'), ATLAS = read('data/atlas.json');
const LAUNCHES = read('regions/morro-bay/launch-points.json'), SHORE = read('regions/morro-bay/shoreline-overview.geojson');
const DATA = {region: {...MORRO, id: 'morro-bay'}, atlas: ATLAS, survey: null, geology: null};
const NOW = Date.now();
const CHECKED = assessScreen({areas: read('data/protected-areas.geojson').features, checkedAt: new Date(NOW).toISOString(), live: true}, NOW);
// Every place is water here; the land/water check has its own tests (test_land_water.mjs).
const WATER = () => ({state: 'water'});
const inputs = (patch = {}) => ({region: 'morro-bay', profile: 'spear', target: 'lingcod', coast: 'lingcod', data: DATA, screen: CHECKED, terrain: {state: 'unavailable'}, now: NOW, place: WATER, ...patch});
const CLAIMS = /safe|passage|reachable|guarantee|hotspot|catch/i;
const LINES = linesOf(SHORE);

const memory = () => {
  const data = new Map();
  configureStore({storage: {getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v)}});
  return data;
};

test('Spear inputs are on the device: depth within 10–100 ft (60 is the table and saves as none), where from, and the swim', () => {
  const data = memory();
  reach.loadSpear();
  assert.equal(ownSpearDepthFt.value, null);
  assert.equal(depthLimitFt('spear'), PROFILE_TABLE.spear.maxDepthFt, 'nothing saved: the table');
  assert.deepEqual(reach.spearPlan.value, {from: null, shoreYd: null});
  assert.deepEqual(reach.saveSpear({depthFt: '42', from: 'shore', shoreYd: '310'}), {depthFt: 40, plan: {from: 'shore', shoreYd: 300}}, 'rounded to 5 ft and 25 yd');
  assert.deepEqual(JSON.parse(data.get(STORAGE_KEYS.spear)), {depthFt: 40, from: 'shore', shoreYd: 300});
  assert.equal(depthLimitFt('spear'), 40);
  assert.equal(terrainDepthLimitFt('spear'), 40, 'the list uses it');
  assert.equal(withinDepth('spear', 45), false);
  assert.equal(withinDepth('spear', 35), true);
  assert.equal(depthLimitFt('boat'), PROFILE_TABLE.boat.maxDepthFt, 'other profiles keep the table');
  assert.equal(reach.shoreSwimLimit(), 300);
  assert.equal(reach.shoreSwimLimit({from: 'boat', shoreYd: 300}), null, 'from a boat: no swim limit');
  assert.equal(reach.saveSpear({depthFt: 60, from: 'boat', shoreYd: ''}).depthFt, null, 'the default saves as none');
  for (const bad of ['', 'deep', 5, 105, NaN, null]) assert.equal(reach.parseSpearDepth(bad), null, `${JSON.stringify(bad)} is no depth`);
  for (const bad of ['', 10, 2500, 'far']) assert.equal(reach.parseShoreSwim(bad), null, `${JSON.stringify(bad)} is no swim`);
  data.set(STORAGE_KEYS.spear, JSON.stringify({depthFt: 400, from: 'kayak', shoreYd: 50}));
  reach.loadSpear();
  assert.equal(ownSpearDepthFt.value, null, 'stored values are re-checked');
  assert.deepEqual(reach.spearPlan.value, {from: null, shoreYd: 50});
  data.set(STORAGE_KEYS.spear, '{oops');
  reach.loadSpear();
  assert.deepEqual(reach.spearPlan.value, {from: null, shoreYd: null});
  configureStore({storage: null});
  ownSpearDepthFt.value = null;
});

test('the launch list parses only this region\'s valid points and loads once; the chosen launch is the origin', async () => {
  const points = parseLaunchPoints(LAUNCHES, 'morro-bay');
  assert.ok(points.length >= 1);
  assert.deepEqual(parseLaunchPoints(LAUNCHES, 'elsewhere'), [], 'another region\'s list is no list');
  assert.deepEqual(parseLaunchPoints({region_id: 'x', launch_points: [{id: 'a', name: 'A', latitude: 'n', longitude: 1}, {id: 'b', name: 'B', latitude: 95, longitude: 1}, {id: 'c', name: 'C', latitude: 35, longitude: -120}]}, 'x').map(p => p.id), ['c']);
  resetLaunchPoints();
  let calls = 0;
  const fetchFn = async url => { calls++; assert.match(String(url), /regions\/morro-bay\/launch-points\.json$/); return new Response(JSON.stringify(LAUNCHES)); };
  await loadLaunchPoints('morro-bay', 'https://example.test/', fetchFn);
  await loadLaunchPoints('morro-bay', 'https://example.test/', fetchFn);
  assert.equal(calls, 1);
  assert.equal(launchPoints.value.points.length, points.length);
  const data = memory();
  reach.loadLaunch();
  assert.equal(launchOrigin('morro-bay'), null, 'none chosen: the harbor');
  const pick = points.at(-1);
  reach.saveLaunch('morro-bay', pick.id);
  assert.deepEqual(JSON.parse(data.get(STORAGE_KEYS.launch)), {'morro-bay': pick.id});
  assert.deepEqual(launchOrigin('morro-bay'), {latitude: pick.latitude, longitude: pick.longitude, name: pick.name});
  assert.equal(launchOrigin('other'), null);
  assert.equal(launchOrigin('morro-bay', launchPoints.value, {'morro-bay': 'gone'}), null, 'a launch no longer listed: the harbor');
  reach.saveLaunch('morro-bay', '');
  assert.equal(launchOrigin('morro-bay'), null, 'back to the harbor');
  assert.deepEqual(reach.parseStoredLaunch(JSON.stringify({'morro-bay': 'ok-1', 'Bad Key': 'x', z: 5})), {'morro-bay': 'ok-1'});
  resetLaunchPoints();
  await loadLaunchPoints('morro-bay', 'https://example.test/', async () => { throw new Error('offline'); });
  assert.deepEqual(launchPoints.value, {region: 'morro-bay', points: []}, 'a failure leaves the harbor');
  resetLaunchPoints();
  configureStore({storage: null});
  reach.launchChoice.value = {};
});

test('Kayak distances, the range filter and the ring run from the chosen launch', () => {
  const points = parseLaunchPoints(LAUNCHES, 'morro-bay'), far = points.reduce((a, b) => distanceNm(harborOrigin(DATA), b) > distanceNm(harborOrigin(DATA), a) ? b : a);
  const origin = {latitude: far.latitude, longitude: far.longitude, name: far.name};
  const r = ranking(inputs({profile: 'kayak', origin, reachNm: 10}));
  assert.equal(r.harbor, far.name);
  assert.match(r.basis, new RegExp(far.name));
  for (const p of r.picks) assert.ok(p.nm <= 10 && Math.abs(p.nm - Number(distanceNm(origin, ATLAS.targets.find(t => t.id === p.id)).toFixed(1))) < 0.11, `${p.id} measured from the launch`);
  assert.equal(ranking(inputs({profile: 'kayak'})).harbor, harborOrigin(DATA).name, 'no launch: the harbor');
  const ring = reachFeatures(origin, 3);
  assert.match(ring.features[1].properties.label, new RegExp(`3 nm from ${far.name}`));
});

test('the shoreline distance is the nearest segment in yards; Spear from shore lists only places within the swim', () => {
  assert.ok(LINES.length > 0);
  assert.equal(yardsFromShore({latitude: 35, longitude: -120}, []), null);
  const line = [[[-120, 35], [-120, 35.01]]];
  assert.ok(Math.abs(yardsFromShore({latitude: 35.005, longitude: -120.001}, line) - 0.001 * 111_320 / 0.9144 * Math.cos(35 * Math.PI / 180)) < 1);
  assert.ok(Math.abs(yardsFromShore({latitude: 35.02, longitude: -120}, line) - 0.01 * 111_320 / 0.9144) < 1, 'past the end: to the end point');
  const all = ranking(inputs());
  assert.ok(all.picks.length > 0, 'Spear lists places within its depth');
  const yards = ATLAS.targets.map(t => yardsFromShore(t, LINES)).filter(y => y !== null).sort((a, b) => a - b);
  const maxYd = Math.ceil(yards[Math.floor(yards.length / 3)] / 25) * 25;
  const near = ranking(inputs({shore: {maxYd, lines: LINES}}));
  for (const p of near.picks) {
    const yd = yardsFromShore(ATLAS.targets.find(t => t.id === p.id), LINES);
    assert.ok(yd <= maxYd, `${p.id} at ${yd} yd`);
    assert.match(p.distance, /^~\d+ yd from shore$/);
  }
  assert.match(near.basis, new RegExp(`within ${maxYd} yd of the mapped shoreline.*approximate and not a swim route`));
  assert.doesNotMatch(near.basis + near.empty, CLAIMS);
  const none = ranking(inputs({shore: {maxYd: 25, lines: [[[0, 0], [0, 1]]]}}));
  assert.deepEqual(none.picks, []);
  assert.match(none.empty, /and 25 yd of shore/);
  const loading = ranking(inputs({shore: {maxYd: 25, lines: null}}));
  assert.deepEqual(loading.picks.map(p => p.id), all.picks.map(p => p.id), 'no shoreline: no filter');
  assert.match(loading.basis, /swim limit is not applied/);
  ownSpearDepthFt.value = 30;
  for (const p of ranking(inputs()).picks) assert.ok(Number(p.depth.match(/–(\d+)/)[1]) <= 30, `${p.id} within 30 ft`);
  ownSpearDepthFt.value = null;
});

test('the shoreline loads once per region; a failure claims no distance', async () => {
  resetShoreLines();
  let calls = 0;
  const fetchFn = async url => { calls++; assert.match(String(url), /shoreline-overview\.geojson$/); return new Response(JSON.stringify(SHORE)); };
  await loadShoreLines('morro-bay', 'https://example.test/', fetchFn);
  await loadShoreLines('morro-bay', 'https://example.test/', fetchFn);
  assert.equal(calls, 1);
  assert.equal(shoreLines.value.lines.length, LINES.length);
  resetShoreLines();
  await loadShoreLines('morro-bay', 'https://example.test/', async () => new Response('', {status: 404}));
  assert.deepEqual(shoreLines.value, {region: 'morro-bay', lines: null});
  resetShoreLines();
});

// Committed region files over a fake network: a missing file answers 404; `hold` delays one region's answer.
const committedFetch = (hold = {}) => async url => {
  const path = new URL(String(url)).pathname.replace(/^\//, ''), region = decodeURIComponent(path.split('/')[1] ?? '');
  if (hold[region]) await hold[region];
  try { return new Response(readFileSync(new URL(`../dist/${path}`, import.meta.url))); } catch { return new Response('', {status: 404}); }
};
const deferred = () => { let open; const promise = new Promise(r => { open = r; }); return {promise, open}; };

test('the shoreline comes back on a region revisit and a late answer never replaces the current region', async () => {
  resetShoreLines();
  const fetchFn = committedFetch();
  await loadShoreLines('morro-bay', 'https://example.test/', fetchFn);
  await loadShoreLines('big-sur-coast', 'https://example.test/', fetchFn);
  assert.equal(shoreLines.value.region, 'big-sur-coast');
  await loadShoreLines('morro-bay', 'https://example.test/', fetchFn);
  assert.equal(shoreLines.value.region, 'morro-bay', 'A -> B -> A restores A');
  assert.equal(shoreLines.value.lines.length, LINES.length);
  // The saved swim still filters with the restored lines.
  const yards = ATLAS.targets.map(t => yardsFromShore(t, LINES)).filter(y => y !== null).sort((a, b) => a - b);
  const maxYd = Math.ceil(yards[Math.floor(yards.length / 3)] / 25) * 25;
  const near = ranking(inputs({shore: {maxYd, lines: shoreLines.value.lines}}));
  assert.match(near.basis, /within \d+ yd of the mapped shoreline/);
  for (const p of near.picks) assert.ok(yardsFromShore(ATLAS.targets.find(t => t.id === p.id), LINES) <= maxYd, p.id);
  // Morro Bay answers late, after the visitor moved to Big Sur: Big Sur stays.
  resetShoreLines();
  const late = deferred(), slow = committedFetch({'morro-bay': late.promise});
  const first = loadShoreLines('morro-bay', 'https://example.test/', slow);
  await loadShoreLines('big-sur-coast', 'https://example.test/', slow);
  late.open(); await first;
  assert.equal(shoreLines.value.region, 'big-sur-coast', 'the obsolete answer is not published');
  resetShoreLines();
});

test('the saved Kayak launch comes back on a region revisit and a late list never replaces the current region', async () => {
  resetLaunchPoints();
  const data = memory();
  reach.loadLaunch();
  const fetchFn = committedFetch(), points = parseLaunchPoints(LAUNCHES, 'morro-bay'), pick = points.at(-1);
  reach.saveLaunch('morro-bay', pick.id);
  const origin = {latitude: pick.latitude, longitude: pick.longitude, name: pick.name};
  await loadLaunchPoints('morro-bay', 'https://example.test/', fetchFn);
  assert.deepEqual(launchOrigin('morro-bay'), origin);
  await loadLaunchPoints('big-sur-coast', 'https://example.test/', fetchFn);
  assert.equal(launchOrigin('morro-bay'), null, 'away from Morro Bay its launch is not the origin');
  await loadLaunchPoints('morro-bay', 'https://example.test/', fetchFn);
  assert.deepEqual(launchOrigin('morro-bay'), origin, 'A -> B -> A restores the saved launch');
  // Distances, the range filter and the ring all run from the restored launch.
  const r = ranking(inputs({profile: 'kayak', origin: launchOrigin('morro-bay'), reachNm: 10}));
  assert.equal(r.harbor, pick.name);
  for (const p of r.picks) assert.ok(p.nm <= 10, p.id);
  assert.match(reachFeatures(launchOrigin('morro-bay'), 3).features[1].properties.label, new RegExp(`3 nm from ${pick.name}`));
  // Morro Bay's list answers late, after the visitor moved to Big Sur: Big Sur stays.
  resetLaunchPoints();
  const late = deferred(), slow = committedFetch({'morro-bay': late.promise});
  const first = loadLaunchPoints('morro-bay', 'https://example.test/', slow);
  await loadLaunchPoints('big-sur-coast', 'https://example.test/', slow);
  late.open(); await first;
  assert.equal(launchPoints.value.region, 'big-sur-coast', 'the obsolete list is not published');
  assert.ok(data.has(STORAGE_KEYS.launch));
  resetLaunchPoints();
  configureStore({storage: null});
  reach.launchChoice.value = {};
});

test('the Chart\'s seafloor layer redraws when the diver\'s depth changes, as the marks and the list do', () => {
  const src = readFileSync(new URL('../web/map/seafloor.ts', import.meta.url), 'utf8');
  assert.match(src, /effect\(\(\) => \{[^}]*ownSpearDepthFt\.value;[^}]*untracked\(\(\) => void draw\(\)\)/, 'the redraw effect tracks the saved depth');
  assert.match(src, /limit = depthLimitFt\(p\)/, 'and its note quotes it');
});

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'spear-')), 'spear.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {LimitsForm} from './web/app/LimitsPanel.tsx';
      export {WhereToLook, diveText} from './web/brief/WhereToLook.tsx';
      export {launchPoints} from './web/launches.ts';
      export {ownSpearDepthFt} from './web/profile.ts';
      export {launchChoice, spearPlan} from './web/reach.ts';
      export {profile, region} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

test('Your limits: Spear sets its depth, where from and, from shore, the swim; Kayak picks a launch once the list loads', async () => {
  const {LimitsForm, render, h, ownSpearDepthFt: depth, spearPlan, launchPoints: list, launchChoice, region} = await load();
  let html = render(h(LimitsForm, {profile: 'spear'}));
  assert.match(html, /Deepest dive <span class="ui-mono">\(ft\)<\/span>/);
  assert.match(html, /name="depth"[^>]*value="60"/, 'the table\'s depth until one is set');
  assert.match(html, /Default 60 · 10–100/);
  assert.match(html, /Diving from/);
  assert.doesNotMatch(html, /name="swim"/, 'the swim asks only when diving from shore');
  depth.value = 35; spearPlan.value = {from: 'shore', shoreYd: 200};
  html = render(h(LimitsForm, {profile: 'spear', focusDepth: true}));
  assert.match(html, /name="depth"[^>]*value="35"/);
  assert.match(html, /Farthest swim from shore[\s\S]*name="swim"[^>]*value="200"/);
  assert.match(html, /approximate, from the mapped shoreline/);
  for (const p of ['boat', 'shore']) assert.doesNotMatch(render(h(LimitsForm, {profile: p})), /name="depth"|name="launch"/);
  region.value = 'morro-bay';
  assert.doesNotMatch(render(h(LimitsForm, {profile: 'kayak'})), /name="launch"/, 'no list loaded: the harbor, no choice');
  const points = parseLaunchPoints(LAUNCHES, 'morro-bay');
  list.value = {region: 'morro-bay', points};
  launchChoice.value = {'morro-bay': points[0].id};
  html = render(h(LimitsForm, {profile: 'kayak'}));
  assert.match(html, /Launch from/);
  assert.match(html, /<option value(?:="")?>The harbor<\/option>/);
  for (const p of points) assert.match(html, new RegExp(`value="${p.id}"`));
  assert.match(html, /straight line from the launch, not a route/);
  launchChoice.value = {};
  assert.match(render(h(LimitsForm, {profile: 'kayak'})), /straight line from the harbor, not a route/, 'the harbor chosen: the hint says so');
  depth.value = null; spearPlan.value = {from: null, shoreYd: null}; list.value = null; launchChoice.value = {};
});

test('"Where to look" shows Spear\'s dive limits in words that promise nothing', async () => {
  const {WhereToLook, diveText, render, h, profile, ownSpearDepthFt: depth, spearPlan} = await load();
  assert.equal(diveText(60, {from: null, shoreYd: null}), 'To 60 ft');
  assert.equal(diveText(40, {from: 'boat', shoreYd: 300}), 'To 40 ft · from a boat');
  assert.equal(diveText(40, {from: 'shore', shoreYd: null}), 'To 40 ft · from shore');
  assert.equal(diveText(40, {from: 'shore', shoreYd: 300}), 'To 40 ft · 300 yd from shore');
  const r = {source: 'atlas', label: 'Survey reef atlas', basis: 'b', picks: [], empty: 'None', harbor: 'Morro Bay'};
  profile.value = 'spear'; depth.value = 45; spearPlan.value = {from: 'shore', shoreYd: 150};
  const html = render(h(WhereToLook, {ranking: r}));
  assert.match(html, /data-dive="45"[^>]*>To 45 ft · 150 yd from shore</);
  assert.doesNotMatch(html, CLAIMS);
  profile.value = 'boat'; depth.value = null; spearPlan.value = {from: null, shoreYd: null};
});
