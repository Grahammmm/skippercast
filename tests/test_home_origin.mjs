// SCJ-2c: one distance origin. The brief measures from the port the trip planner measures from (its choice this
// session, else the saved home port, else the region's first listed port), not region.json's harbor; a chosen Kayak
// launch still wins, and only a failed or empty port list leaves the harbor. Offline: the committed port directory.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises'; import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {bestSpots, distanceNm} from '../dist/spot-ranking.js';
import {homePortOrigin, loadRegionPorts, portChoice, regionPorts} from '../web/ports.ts';
import {ranking} from '../web/ranking.ts';

const ROOT = new URL('..', import.meta.url).pathname, NOW = Date.now();
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const PORTS = read('data/home-ports.json').ports, MORRO = PORTS.filter(p => p.region === 'morro-bay');
const [MB, PSL] = MORRO, READY = {region: 'morro-bay', state: 'ready', list: MORRO};
const HARBOR = {name: 'Region harbour', latitude: 35.40, longitude: -120.95};
const DATA = {region: {...read('regions/morro-bay/region.json'), id: 'morro-bay', harbor: HARBOR}, atlas: read('data/atlas.json'), survey: null, geology: null};
const box = (w, s, e, n) => ({type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]]});
const reef = (id, latitude, longitude) => ({target: {id, canonical_habitat: true, name: id, label: 'Reef', latitude, longitude, neighborhood_depth_ft: [40, 80], habitat_score: 50,
  species_fit: {lingcod: 3, 'rockfish-reef': 3}, resolution_m: 2, evidence_confidence: {percent: 90}, area_ids: [id]}, area: {id, geometry: box(longitude - 0.002, latitude - 0.002, longitude + 0.002, latitude + 0.002)}});
const REEFS = [reef('near-harbor', 35.39, -120.94), reef('near-port', 35.16, -120.78)];
const LOADED = {targets: REEFS.map(r => r.target), areas: REEFS.map(r => r.area),
  publication: {status: 'ready', region: 'morro-bay', archive_sha256: 'a'.repeat(64), export_sha256: 'b'.repeat(64), expires_at: new Date(NOW + 3600000).toISOString()}};
const SCREEN = {status: 'ready', note: '', source: 'test', boundaries: [], until: Infinity}, WATER = () => ({state: 'water'});
const inputs = patch => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: SCREEN, terrain: {state: 'idle'}, now: NOW, place: WATER,
  publication: {state: 'ready', region: 'morro-bay', loaded: LOADED}, ...patch});
const at = id => REEFS.find(r => r.target.id === id).target;

test('portChoice is the planner\'s old inline rule: chosen, else saved, else first, else empty', () => {
  const old = (list, chosen, savedPort) => list.some(p => p.id === chosen) ? chosen : list.some(p => p.id === savedPort) ? savedPort : list[0]?.id ?? '';
  const rows = [[MORRO, PSL.id, MB.id, PSL.id], [MORRO, 'ventura', PSL.id, PSL.id], [MORRO, 'gone', 'ventura', MB.id], [MORRO, null, null, MB.id],
    [MORRO, '', PSL.id, PSL.id], [MORRO, MB.id, PSL.id, MB.id], [[], PSL.id, MB.id, ''], [[], null, null, '']];
  for (const [list, chosen, saved, want] of rows) {
    assert.equal(portChoice(list, chosen, saved), want, `${chosen} / ${saved}`);
    assert.equal(portChoice(list, chosen, saved), old(list, chosen, saved), 'same answer as the old rule');
  }
});

test('homePortOrigin: saved port, the session choice over it, the first port without one; null until loaded or with no port', () => {
  assert.deepEqual(homePortOrigin('morro-bay', READY, null, PSL.id), {latitude: PSL.match[0], longitude: PSL.match[1], name: PSL.name});
  assert.equal(homePortOrigin('morro-bay', READY, MB.id, PSL.id).name, MB.name, 'the planner\'s choice wins over the saved port');
  assert.equal(homePortOrigin('morro-bay', READY, null, null).name, MB.name, 'no saved port: the first listed');
  assert.equal(homePortOrigin('morro-bay', READY, null, 'ventura').name, MB.name, 'a saved port elsewhere: the first listed');
  assert.equal(homePortOrigin('morro-bay', null, null, PSL.id), null);
  assert.equal(homePortOrigin('morro-bay', {...READY, state: 'loading'}, null, PSL.id), null);
  assert.equal(homePortOrigin('morro-bay', {...READY, region: 'southern-california'}, null, PSL.id), null, 'another region\'s list');
  assert.equal(homePortOrigin('morro-bay', {...READY, list: []}, null, PSL.id), null, 'a region without ports');
});

test('loadRegionPorts: once per region, filtered to it, a failure is `failed` and never throws, the latest load wins', async () => {
  let calls = 0; const count = async () => { calls++; return PORTS; };
  await loadRegionPorts('morro-bay', count); await loadRegionPorts('morro-bay', count);
  assert.equal(calls, 1);
  assert.deepEqual(regionPorts.value.list.map(p => p.id), MORRO.map(p => p.id));
  await loadRegionPorts('big-sur-coast', async () => { throw Error('offline'); });
  assert.deepEqual(regionPorts.value, {region: 'big-sur-coast', state: 'failed', list: []});
  let release; const slow = loadRegionPorts('monterey-point-sur', () => new Promise(r => { release = r; }));
  assert.equal(regionPorts.value.state, 'loading');
  await loadRegionPorts('morro-bay', async () => PORTS);
  release(PORTS); await slow;
  assert.equal(regionPorts.value.region, 'morro-bay', 'an older region\'s late answer does not land');
});

test('the brief and the planner give the same distance, and the range follows the port', () => {
  const origin = homePortOrigin('morro-bay', READY, null, PSL.id);
  const planner = bestSpots(LOADED, {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true},
    {species: 'lingcod', count: 50, maxDepth: 300, origin: {latitude: PSL.match[0], longitude: PSL.match[1]}, place: WATER});
  const r = ranking(inputs({origin}));
  assert.equal(r.harbor, PSL.name); assert.equal(r.picks.length, 2);
  for (const p of r.picks) {
    assert.equal(p.nm, planner.find(t => t.id === p.id).distance_nm, `${p.id}: the planner's distance`);
    assert.equal(p.nm, distanceNm(origin, at(p.id)));
    assert.notEqual(p.nm, distanceNm(HARBOR, at(p.id)), 'not from the harbour');
  }
  assert.deepEqual(ranking(inputs({reachNm: 5})).picks.map(p => p.id), ['near-harbor'], 'from the harbour');
  assert.deepEqual(ranking(inputs({origin, reachNm: 5})).picks.map(p => p.id), ['near-port'], 'from the port: the reverse');
});

test('originPending: the source label stays, no picks, no distance or range', () => {
  const r = ranking(inputs({originPending: true, reachNm: 5}));
  assert.equal(r.source, 'publication'); assert.equal(r.label, 'Seafloor reef publication');
  assert.deepEqual(r.picks, []); assert.equal(r.empty, 'Finding your home port…');
  assert.equal(r.harbor, undefined); assert.equal(r.reach, undefined);
  assert.doesNotMatch(r.basis, /Region harbour/);
  assert.equal(ranking(inputs({originPending: true, profile: 'shore'})).empty, 'Shore runs and their review status show on the Chart.');
});

test('the brief: pending while ports load, then the home port; Kayak\'s chosen launch wins; failed or no ports keep the harbour', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'home-origin-')), out = join(dir, 'brief.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {currentRanking} from './web/brief/WhereToLook.tsx';
      export {loadRegionPorts, plannerPort, regionPorts, HOME_PORT_KEY} from './web/ports.ts';
      export {markData, markScreen} from './web/map/marks.ts';
      export {reefPublication} from './web/ranking.ts';
      export {launchPoints} from './web/launches.ts';
      export {launchChoice} from './web/reach.ts';
      export {profile, region} from './web/state.ts';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  const m = await import(pathToFileURL(out).href), store = new Map();
  const saved = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k)}});
  try {
    m.region.value = 'morro-bay'; m.profile.value = 'boat'; m.markData.value = DATA; m.markScreen.value = SCREEN;
    m.reefPublication.value = {state: 'unavailable', region: 'morro-bay'};
    let r = m.currentRanking(NOW);
    assert.equal(r.empty, 'Finding your home port…'); assert.equal(r.label, 'Survey reef atlas'); assert.equal(r.harbor, undefined);
    await m.loadRegionPorts('morro-bay', async () => PORTS);
    assert.equal(m.currentRanking(NOW).harbor, MB.name, 'no saved port, no planner: the first listed');
    store.set(m.HOME_PORT_KEY, PSL.id);
    assert.equal(m.currentRanking(NOW).harbor, PSL.name, 'the saved home port');
    m.plannerPort.value = {region: 'morro-bay', id: MB.id};
    assert.equal(m.currentRanking(NOW).harbor, MB.name, 'the planner\'s choice this session');
    m.plannerPort.value = {region: 'southern-california', id: 'ventura'};
    assert.equal(m.currentRanking(NOW).harbor, PSL.name, 'another region\'s planner choice is ignored');
    m.profile.value = 'kayak';
    assert.equal(m.currentRanking(NOW).harbor, PSL.name, 'Kayak without a launch: the home port');
    m.launchPoints.value = {region: 'morro-bay', points: [{id: 'l1', name: 'Test launch', kind: 'ramp', latitude: 35.3, longitude: -120.85}]};
    m.launchChoice.value = {'morro-bay': 'l1'}; m.regionPorts.value = null;
    assert.equal(m.currentRanking(NOW).harbor, 'Test launch', 'a chosen launch wins and never waits on ports');
    m.profile.value = 'boat'; m.regionPorts.value = {region: 'morro-bay', state: 'failed', list: []};
    assert.equal(m.currentRanking(NOW).harbor, HARBOR.name, 'ports failed: the harbour');
    m.regionPorts.value = {region: 'morro-bay', state: 'ready', list: []};
    r = m.currentRanking(NOW);
    assert.equal(r.harbor, HARBOR.name, 'no ports in the region: the harbour'); assert.match(r.basis, /Region harbour/);
  } finally { if (saved) Object.defineProperty(globalThis, 'localStorage', saved); else delete globalThis.localStorage; }
});
