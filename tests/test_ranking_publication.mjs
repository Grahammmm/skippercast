// SCJ-2a: the brief's reef list is the planner's own answer (bestSpots over loadReefTrip's seafloor publication): same ids,
// order, names and depth bands for equal filters. Offline: a 9-target fixture in the loadReefTrip shape, a hand-built screen.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
import {build} from 'esbuild';
import {bestSpots} from '../dist/spot-ranking.js';
import {geometryIntersects, pointInGeometry} from '../dist/geo-screen.js';
import {CHECKING} from '../web/map/habitat.ts';
import {TOP, loadReefPublication, ranking, reefPublication} from '../web/ranking.ts';

const ROOT = new URL('..', import.meta.url).pathname, NOW = Date.now();
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const DATA = {region: {...read('regions/morro-bay/region.json'), id: 'morro-bay'}, atlas: read('data/atlas.json'), survey: null, geology: null};
const box = (w, s, e, n) => ({type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]]});
const BOUNDARY = box(-120.91, 35.23, -120.89, 35.25);
const SCREEN = {status: 'ready', note: '', source: 'test', boundaries: [{name: 'Test MPA', federal: false, geometry: BOUNDARY}], until: Infinity};
const reef = (id, latitude, longitude, depth, lc, rf, percent, area = box(longitude - 0.002, latitude - 0.002, longitude + 0.002, latitude + 0.002)) => ({
  target: {id, canonical_habitat: true, name: id, label: 'Surveyed reef habitat', latitude, longitude, neighborhood_depth_ft: depth, habitat_score: 50,
    species_fit: {lingcod: lc, 'rockfish-reef': rf}, resolution_m: 2, evidence_confidence: {percent}, area_ids: [id], terrain_interpretation: `${id} relief.`},
  area: {id, geometry: area}});
const REEFS = [reef('r-target', 35.20, -121.00, [200, 278], 3, 3, 90), reef('r-a', 35.30, -120.95, [40, 80], 3, 2, 85), reef('r-b', 35.32, -120.95, [60, 110], 2, 3, 80),
  reef('r-c', 35.34, -120.92, [30, 55], 2, 2, 75), reef('r-d', 35.28, -120.95, [100, 150], 3, 1, 70), reef('r-deep', 35.26, -120.95, [280, 320], 3, 3, 99),
  reef('r-inside', 35.24, -120.90, [50, 90], 3, 3, 95), reef('r-touch', 35.24, -120.88, [50, 90], 3, 3, 94, box(-120.895, 35.235, -120.875, 35.245)),
  reef('r-far', 35.60, -121.30, [50, 90], 3, 3, 60)];
const manifest = (expires = NOW + 3600000) => ({status: 'ready', region: 'morro-bay', archive_sha256: 'a'.repeat(64), export_sha256: 'b'.repeat(64), expires_at: new Date(expires).toISOString()});
const LOADED = {targets: REEFS.map(r => r.target), areas: REEFS.map(r => r.area), publication: manifest()};
const READY = {state: 'ready', region: 'morro-bay', loaded: LOADED}, WATER = () => ({state: 'water'});
const inputs = patch => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: SCREEN, terrain: {state: 'idle'}, now: NOW, place: WATER, publication: READY, ...patch});
const ids = r => r.picks.map(p => p.id);
/** The planner's kind of screen (dist/protected-areas.js), over the same boundary. */
const PLANNER_SCREEN = {ready: () => true, pointAllowed: p => !pointInGeometry([p.longitude, p.latitude], BOUNDARY), geometryAllowed: g => !geometryIntersects(g, BOUNDARY)};

test('equal filters, equal answer: ids, order, names and depth bands are the planner bestSpots answer', () => {
  for (const [coast, species] of [['lingcod', 'lingcod'], ['rockfish-reef', 'rockfish'], ['all', 'reef']]) {
    const r = ranking(inputs({coast})), direct = bestSpots(LOADED, PLANNER_SCREEN, {species, count: TOP, maxDepth: 300, place: WATER});
    assert.equal(r.source, 'publication'); assert.equal(r.label, 'Seafloor reef publication');
    assert.ok(direct.length > 1 && isDeepStrictEqual(ids(r), direct.map(t => t.id)), `${coast}: ids ${ids(r)} vs ${direct.map(t => t.id)}`);
    assert.ok(isDeepStrictEqual(r.picks.map(p => p.depth), direct.map(t => `~${t.neighborhood_depth_ft[0]}–${t.neighborhood_depth_ft[1]} ft`)), `${coast}: depths`);
    assert.ok(isDeepStrictEqual(r.picks.map(p => p.name), direct.map(t => t.name)), `${coast}: the planner's waypoint names`);
    assert.ok(r.picks.every(p => p.kind === 'reef' && p.at && Number.isFinite(p.nm)));
  }
  assert.deepEqual(ids(ranking(inputs({}))), ['r-target', 'r-a', 'r-d', 'r-far']);
  assert.equal(ranking(inputs({})).picks[1].fit, 'Fits lingcod habitat 3 of 3');
  assert.equal(ranking(inputs({coast: 'all'})).picks[0].fit, 'Screened reef habitat');
  assert.doesNotMatch(ranking(inputs({})).basis, /hotspot|chance|probab|productive|best spot|catch rate|bite|guarantee/i);
});

test('a reef the terrain release bands differently is ranked once with the publication band, never the release band', () => {
  const feature = {type: 'Feature', id: 'h-target', geometry: box(-121.01, 35.19, -120.99, 35.21), properties: {id: 'h-target', region: 'morro-bay',
    depth_min_ft: 179, depth_max_ft: 195, waypoint_latitude: 35.20, waypoint_longitude: -121.00, terrain_score: 80, fit_lingcod: 3}};
  const terrain = {state: 'ready', features: [feature], expiresAt: NOW + 3600000, rank: f => [...f]};
  const old = ranking(inputs({terrain, publication: {state: 'unavailable', region: 'morro-bay'}}));
  assert.equal(old.source, 'terrain'); assert.deepEqual(old.picks.map(p => p.depth), ['~179–195 ft'], 'the retained branch still bands it from the release');
  const r = ranking(inputs({terrain}));
  assert.equal(r.source, 'publication');
  assert.deepEqual(r.picks.filter(p => p.depth === '~200–278 ft').map(p => p.id), ['r-target']);
  assert.ok(!r.picks.some(p => p.depth === '~179–195 ft' || p.id === 'h-target'));
});

test('species the planner cannot rank, and an expired or unavailable publication, use the labelled atlas list', () => {
  for (const coast of ['gopher-rockfish', 'halibut']) assert.equal(ranking(inputs({coast, target: coast === 'halibut' ? 'halibut' : 'gopher-rockfish'})).label, 'Survey reef atlas');
  for (const publication of [{state: 'unavailable', region: 'morro-bay'}, {...READY, loaded: {...LOADED, publication: manifest(NOW - 1000)}}, undefined]) {
    const r = ranking(inputs({publication}));
    assert.equal(r.source, 'atlas'); assert.ok(r.picks.length && r.picks.every(p => p.kind === 'spot'));
  }
});

test('idle, loading or another region\'s publication: no picks, the loading line, never the atlas list', () => {
  for (const publication of [{state: 'idle'}, {state: 'loading', region: 'morro-bay'}, {...READY, region: 'cambria-san-simeon'}, {state: 'unavailable', region: 'cambria-san-simeon'}]) {
    const r = ranking(inputs({publication}));
    assert.equal(r.source, null); assert.deepEqual(r.picks, []); assert.equal(r.empty, 'Loading ranked reef places…');
  }
});

test('land/water: land and unknown places are withheld and counted; a pending place shows the check line and no picks', () => {
  const place = p => p.id === 'r-target' ? {state: 'land'} : p.id === 'r-a' ? {state: 'unknown', reason: 'edge'} : {state: 'water'};
  const r = ranking(inputs({place}));
  assert.equal(r.withheld, 2); assert.ok(!ids(r).includes('r-target') && !ids(r).includes('r-a')); assert.match(r.basis, /withheld/);
  const pending = ranking(inputs({place: p => p.id === 'r-b' ? {state: 'unknown', reason: 'pending'} : {state: 'water'}}));
  assert.equal(pending.pending, true); assert.deepEqual(pending.picks, []); assert.equal(pending.empty, 'Checking land and water for these places…');
  assert.deepEqual(ranking(inputs({place: undefined})).picks, [], 'no land/water check: nothing ranked');
});

test('screen bridge: a point inside a boundary, or an area touching one, is withheld; an unready screen ranks nothing', () => {
  assert.deepEqual(ids(ranking(inputs({screen: {...SCREEN, boundaries: []}}))).slice(0, 2), ['r-inside', 'r-touch'], 'they lead without the boundary');
  const r = ranking(inputs({})); assert.ok(!ids(r).includes('r-inside') && !ids(r).includes('r-touch'));
  for (const screen of [CHECKING, {...SCREEN, status: 'stale', note: 'Boundary check stale; fishing targets withheld'}]) {
    const held = ranking(inputs({screen}));
    assert.equal(held.source, 'publication'); assert.deepEqual(held.picks, []); assert.equal(held.empty, screen.note);
  }
});

test('depth limit, range and Spear\'s shore swim: nothing deeper or farther, and the swim applies after ranking', () => {
  assert.ok(ranking(inputs({})).picks.every(p => !p.id.includes('deep')));
  const kayak = ranking(inputs({profile: 'kayak'}));
  assert.ok(kayak.picks.length && !ids(kayak).includes('r-target'), 'nothing past 120 ft');
  const near = ranking(inputs({reachNm: 6}));
  assert.equal(near.reach, 6); assert.ok(near.picks.length && near.picks.every(p => p.nm <= 6) && !ids(near).includes('r-far') && !ids(near).includes('r-target'));
  assert.deepEqual(ids(ranking(inputs({profile: 'spear'}))), ['r-c'], 'Spear 60 ft');
  const lines = [[[-120.93, 34.9], [-120.93, 35.5]]];
  const swim = ranking(inputs({profile: 'spear', shore: {maxYd: 1200, lines}}));
  assert.deepEqual(ids(swim), ['r-c']); assert.match(swim.picks[0].distance, /^~\d+ yd from shore$/);
  const far = ranking(inputs({profile: 'spear', shore: {maxYd: 500, lines}}));
  assert.deepEqual(far.picks, []); assert.match(far.empty, /^No ranked reef places pass the current protected-area check within 60 ft and 500 yd of shore/);
});

test('the publication loads once per region; a failure or malformed answer is unavailable; a replaced region\'s late answer is dropped', async () => {
  reefPublication.value = {state: 'idle'}; let calls = 0;
  await loadReefPublication('morro-bay', async () => { calls++; return LOADED; });
  await loadReefPublication('morro-bay', async () => { calls++; return LOADED; });
  assert.equal(calls, 1); assert.equal(reefPublication.value.state, 'ready'); assert.equal(reefPublication.value.region, 'morro-bay');
  await loadReefPublication('cambria-san-simeon', async () => { throw Error('Seafloor layer unavailable'); });
  assert.deepEqual(reefPublication.value, {state: 'unavailable', region: 'cambria-san-simeon'});
  reefPublication.value = {state: 'idle'};
  await loadReefPublication('morro-bay', async () => ({targets: 'x', areas: [], publication: {}}));
  assert.equal(reefPublication.value.state, 'unavailable');
  let release;
  const slow = loadReefPublication('cambria-san-simeon', () => new Promise(ok => { release = ok; }));
  assert.deepEqual(reefPublication.value, {state: 'loading', region: 'cambria-san-simeon'});
  await loadReefPublication('morro-bay', async () => LOADED);
  release(LOADED); await slow;
  assert.equal(reefPublication.value.region, 'morro-bay', 'the late answer never replaces the current region');
});

test('a reef pick moves the Chart to the place (view only) and is never pressed', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'where-pub-')), 'where.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `export {WhereToLook, choosePick} from './web/brief/WhereToLook.tsx';
    export {picked} from './web/map/marks.ts'; export * as state from './web/state.ts'; export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}]});
  const {WhereToLook, choosePick, picked, state, render, h} = await import(pathToFileURL(out).href);
  const href = 'https://s.test/map?region=morro-bay&habitat=r-a&spot=r-a';
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }}; globalThis.dispatchEvent = () => true;
  state.configureStore({v2: true, storage: null}); state.syncFromURL(href);
  const before = picked.value, pick = ranking(inputs({})).picks[1];
  choosePick({...pick, at: undefined});
  assert.equal(location.href, href, 'a reef pick without a position changes nothing');
  choosePick(pick);
  const url = new URL(location.href); assert.ok(url.searchParams.get('view'), 'the Chart moves');
  assert.equal(url.searchParams.get('habitat'), 'r-a'); assert.equal(url.searchParams.get('spot'), 'r-a'); assert.equal(picked.value, before, 'no mark card');
  const html = render(h(WhereToLook, {ranking: {source: 'publication', label: 'Seafloor reef publication', basis: 'B.', picks: [{...pick, id: 'r-a'}], empty: ''}}));
  assert.match(html, /<li data-mark="r-a"><button type="button" class="app-pick" aria-pressed="false">/);
});
