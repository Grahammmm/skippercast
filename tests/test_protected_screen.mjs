// SCJ-2b: the brief's publication list is admitted by the trip planner's own protected-area screen (web/trip.ts
// `loadProtectedScreen`, one instance per region), and shows no place until that screen has loaded and is current.
// Offline: an injected `init` stands in for initProtectedAreas; a small loadReefTrip-shaped fixture.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {bestSpots} from '../dist/spot-ranking.js';
import {geometryIntersects, pointInGeometry} from '../dist/geo-screen.js';
import {SCREEN_NOTES} from '../web/map/habitat.ts';
import {SCREEN_NOT_CURRENT, TOP, ranking} from '../web/ranking.ts';
import {loadProtectedScreen, protectedScreen} from '../web/trip.ts';

const NOW = Date.now(), read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const DATA = {region: {...read('regions/morro-bay/region.json'), id: 'morro-bay'}, atlas: read('data/atlas.json'), survey: null, geology: null};
const box = (w, s, e, n) => ({type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]]});
const BOUNDARY = box(-120.91, 35.23, -120.89, 35.25);
const reef = (id, latitude, longitude, percent, area = box(longitude - 0.002, latitude - 0.002, longitude + 0.002, latitude + 0.002)) => ({
  target: {id, canonical_habitat: true, name: id, label: 'Surveyed reef habitat', latitude, longitude, neighborhood_depth_ft: [40, 90], habitat_score: 50,
    species_fit: {lingcod: 3, 'rockfish-reef': 3}, resolution_m: 2, evidence_confidence: {percent}, area_ids: [id], terrain_interpretation: `${id} relief.`},
  area: {id, geometry: area}});
const REEFS = [reef('r-inside', 35.24, -120.90, 99), reef('r-touch', 35.24, -120.88, 98, box(-120.895, 35.235, -120.875, 35.245)),
  reef('r-a', 35.30, -120.95, 90), reef('r-b', 35.33, -120.95, 85), reef('r-c', 35.36, -120.95, 80)];
const LOADED = {targets: REEFS.map(r => r.target), areas: REEFS.map(r => r.area),
  publication: {status: 'ready', region: 'morro-bay', archive_sha256: 'a'.repeat(64), export_sha256: 'b'.repeat(64), expires_at: new Date(NOW + 3600000).toISOString()}};
const WATER = () => ({state: 'water'});
/** A planner-shaped screen over BOUNDARY; `fresh` is what `ready()` answers, `refreshed` counts refresh calls. */
const fake = (fresh = true) => { const s = {fresh, refreshed: 0, ready: () => s.fresh, pointAllowed: p => s.fresh && !pointInGeometry([p.longitude, p.latitude], BOUNDARY),
  geometryAllowed: g => s.fresh && !geometryIntersects(g, BOUNDARY), refresh: async () => { s.refreshed++; }}; return s; };
const brief = plannerScreen => ranking({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: {status: 'ready', note: '', source: 't', boundaries: [], until: Infinity},
  terrain: {state: 'idle'}, now: NOW, place: WATER, publication: {state: 'ready', region: 'morro-bay', loaded: LOADED}, ...(plannerScreen === undefined ? {} : {plannerScreen})});
const ids = r => r.picks.map(p => p.id);
const deferred = () => { let ok, no; const p = new Promise((a, b) => { ok = a; no = b; }); return {p, ok, no}; };

test('before the planner screen loads (absent, idle, loading, another region\'s), no place shows and the list says it is checking', () => {
  assert.ok(ids(brief({state: 'loaded', region: 'morro-bay', screen: fake()})).length > 1, 'places would rank once screened');
  for (const s of [undefined, {state: 'idle'}, {state: 'loading'}, {state: 'loaded', region: 'cambria-san-simeon', screen: fake()}]) {
    const r = brief(s);
    assert.deepEqual(r.picks, []); assert.equal(r.empty, SCREEN_NOTES.checking);
    assert.equal(r.source, 'publication'); assert.equal(r.label, 'Seafloor reef publication'); assert.match(r.basis, /planner's current protected-area check/);
  }
});

test('a loaded, current screen: the picks are the planner bestSpots answer through that same screen, boundary places withheld', () => {
  const screen = fake(), r = brief({state: 'loaded', region: 'morro-bay', screen});
  const direct = bestSpots(LOADED, screen, {species: 'lingcod', count: TOP, maxDepth: 300, place: WATER}).map(t => t.id);
  assert.ok(direct.length === 3 && isDeepStrictEqual(ids(r), direct), `ids ${ids(r)} vs ${direct}`);
  assert.ok(!ids(r).includes('r-inside') && !ids(r).includes('r-touch'), 'a point inside, and an area touching, a boundary are withheld');
  const all = brief({state: 'loaded', region: 'morro-bay', screen: {...screen, pointAllowed: () => false}});
  assert.match(all.empty, /^No ranked reef places pass the current protected-area check/, 'only a current screen that withheld everything says so');
});

test('failed, or loaded but not current: no place, the not-current line, never the checking line or "no place passes"', () => {
  for (const s of [{state: 'failed'}, {state: 'loaded', region: 'morro-bay', screen: fake(false)}, {state: 'loaded', screen: {...fake(), ready: () => false}}]) {
    const r = brief(s);
    assert.deepEqual(r.picks, []); assert.equal(r.empty, SCREEN_NOT_CURRENT); assert.notEqual(r.empty, SCREEN_NOTES.checking); assert.doesNotMatch(r.empty, /pass/);
  }
  const screen = fake(), loaded = {state: 'loaded', region: 'morro-bay', screen};
  assert.ok(brief(loaded).picks.length); screen.fresh = false;
  assert.equal(brief(loaded).empty, SCREEN_NOT_CURRENT, 'the same screen gone stale withholds on the next render, no reload');
});

test('one screen per region: the planner and the brief share one init, and it refreshes once', async () => {
  let calls = 0; const screen = fake();
  const init = async id => { calls++; assert.equal(id, 'r6'); return screen; };
  const first = loadProtectedScreen('r6', init);
  assert.deepEqual(protectedScreen.value, {state: 'loading'});
  const again = loadProtectedScreen('r6', init), planner = loadProtectedScreen('r6');
  assert.equal(again, first); assert.equal(planner, first, 'startPlanner\'s call shares the load');
  const got = await first;
  assert.equal(calls, 1); assert.equal(screen.refreshed, 1);
  assert.equal(got.state, 'loaded'); assert.equal(got.screen, screen); assert.equal(protectedScreen.value, got);
  assert.equal(await loadProtectedScreen('r6', init), got); assert.equal(calls, 1);
});

test('a failed load resolves as failed without throwing, and a later call for the region tries again', async () => {
  for (const init of [async () => { throw Error('offline'); }, () => { throw Error('import failed'); }]) {
    const r = await loadProtectedScreen('r4', init);
    assert.deepEqual(r, {state: 'failed'}); assert.deepEqual(protectedScreen.value, {state: 'failed'});
  }
  const screen = fake(), later = await loadProtectedScreen('r4', async () => screen);
  assert.equal(later.state, 'loaded'); assert.equal(later.screen, screen);
});

test('a region change resets to loading; the previous region\'s screen never stands for the new one', async () => {
  const a = deferred(), b = deferred(), sa = fake(), sb = fake();
  const first = loadProtectedScreen('ra', () => a.p), second = loadProtectedScreen('rb', () => b.p);
  assert.deepEqual(protectedScreen.value, {state: 'loading'});
  a.ok(sa); await first;
  assert.deepEqual(protectedScreen.value, {state: 'loading'}, 'region A\'s late screen is not published for B');
  b.ok(sb); const got = await second;
  assert.equal(protectedScreen.value, got); assert.equal(got.region, 'rb'); assert.equal(got.screen, sb);
  let calls = 0; await loadProtectedScreen('ra', async () => { calls++; return fake(); });
  assert.equal(calls, 1, 'back to A: a fresh load for A'); assert.equal(protectedScreen.value.region, 'ra');
});
