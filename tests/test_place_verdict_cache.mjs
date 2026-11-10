// SC1407-02 (#1762 R1): a protected-area verdict is worked out once per place and boundary data, not again on every hour
// step (web/place-verdict-cache.ts). The callers are the real ones: web/ranking.ts `ranking` (atlas picks) over an assessed
// mark screen, and web/brief/run.ts `runRouteScreen` over the planner's own screen (dist/protected-areas.js
// `initProtectedAreas`), fed offline from the committed boundary snapshot. Each screen counts the distance screens it
// serves through its own interface (a mark screen's `boundaries.map`, the planner's `exportExclusions`): geo-screen.js
// `screenPlace` reads each exactly once per call, and nothing else in these paths does.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {screenPlace} from '../dist/geo-screen.js';
import {assetURL, getRegion, setRegion} from '../dist/region.js';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {assessScreen} from '../web/map/habitat.ts';
import {VERDICT_CACHE_CAP, placeVerdictCache, placeVerdicts} from '../web/place-verdict-cache.ts';
import {ranking} from '../web/ranking.ts';
import {runRouteScreen} from '../web/brief/run.ts';
import {region} from '../web/state.ts';

const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MORRO = read('regions/morro-bay/region.json'), ATLAS = read('data/atlas.json'), MPAS = read('data/protected-areas.geojson');
const DATA = {region: {...MORRO, id: 'morro-bay'}, atlas: ATLAS, survey: null, geology: null};
const HOUR = 3600000, NOW = Date.now(), WATER = () => ({state: 'water'});
const inputs = (patch = {}) => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, terrain: {state: 'unavailable'}, now: NOW, place: WATER, ...patch});
const same = (a, b, msg) => assert.ok(isDeepStrictEqual(a, b), msg);

/** An assessed mark screen whose distance screens are counted (screenPlace maps `boundaries` once per call; withheld() filters it). */
function countedMarks(now = NOW) {
  const s = assessScreen({areas: MPAS.features, checkedAt: new Date(now).toISOString(), live: true}, now), seen = {n: 0};
  Object.defineProperty(s.boundaries, 'map', {value(...a) { seen.n++; return Array.prototype.map.apply(this, a); }});
  return {s, seen};
}

// The planner's screen, offline: the snapshot through `readJSON`, its refresh through a stubbed fetch (live query refused,
// the daily feed's boundary record answered), a fixed clock, and every distance screen counted.
const buchon = MPAS.features.find(f => f.properties.NAME === 'Point Buchon SMR');
const RING = buchon.geometry.type === 'Polygon' ? buchon.geometry.coordinates[0] : buchon.geometry.coordinates[0][0];
const CENTRE = [RING.reduce((s, p) => s + p[0], 0) / RING.length, RING.reduce((s, p) => s + p[1], 0) / RING.length];
const HARBOR = {latitude: 35.3667, longitude: -120.868};
const straight = (at, id = 'a') => ({id, kind: 'spot', name: id, nm: 5, basis: 'straight', at});
const water = (at, routePoints, id = 'a') => ({...straight(at, id), basis: 'water', routePoints});
const INSIDE = {latitude: CENTRE[1], longitude: CENTRE[0]};
const T0 = Date.parse('2026-11-01T12:00:00Z');
const feed = (geojson, at) => ({schema_version: 1, part: 'mpa-boundaries', region_id: 'morro-bay', generated_at: at, catch_probability: null, bite_score: null,
  sources: {'mpa-boundaries': {status: 'ok', data_retrieved_at: at, data: {geojson}}}});
const withFeature = (i, patch) => ({...MPAS, features: MPAS.features.map((f, k) => k === i ? {...f, ...patch} : f)});

async function planner(t, checkedAt = new Date(T0).toISOString()) {
  const saved = {fetch: globalThis.fetch, document: Object.getOwnPropertyDescriptor(globalThis, 'document'), now: Date.now};
  const env = {clock: T0, answer: null};
  globalThis.fetch = async url => {
    if (String(url).includes('part=mpa-boundaries') && env.answer) return new Response(JSON.stringify(env.answer));
    throw new TypeError('offline');
  };
  Object.defineProperty(globalThis, 'document', {configurable: true, writable: true, value: {getElementById: () => null, dispatchEvent() {},
    createElement: () => ({classList: {toggle() {}}, textContent: ''})}});
  Date.now = () => env.clock;
  t.after(() => { globalThis.fetch = saved.fetch; Date.now = saved.now; if (saved.document) Object.defineProperty(globalThis, 'document', saved.document); else delete globalThis.document; placeVerdicts.clear(); });
  const screen = await initProtectedAreas(null, () => {}, async path => { assert.equal(path, assetURL('protected_areas')); return {...MPAS, checked_at: checkedAt}; });
  const seen = {n: 0}, own = screen.exportExclusions;
  screen.exportExclusions = () => { seen.n++; return own(); };
  /** Refresh in place from the daily feed's record (the live query is refused). */
  const refresh = async (geojson, at) => { env.answer = feed(geojson, at); await screen.refresh(); };
  return {screen, seen, env, refresh};
}

test('verdict_cache_hour_steps_reuse_real_atlas_and_run: an hour step reuses each verdict; cached equals uncached', async t => {
  placeVerdicts.clear();
  const {s, seen} = countedMarks();
  const first = ranking(inputs({screen: s}));
  assert.equal(first.source, 'atlas');
  assert.ok(first.picks.length > 0);
  assert.equal(seen.n, first.picks.length, 'one distance screen per listed atlas place');
  for (const h of [1, 2, 5]) {
    const later = ranking(inputs({screen: s, now: NOW + h * HOUR}));
    assert.equal(seen.n, first.picks.length, `hour +${h}: no place screened again`);
    same(later.picks, first.picks, 'same picks and verdicts');
  }
  // Cached verdicts equal the uncached ones (a copy of the screen carries no capability, so it is screened directly).
  for (const p of first.picks) {
    const t0 = ATLAS.targets.find(x => x.id === p.id);
    const areas = (t0.area_ids ?? []).flatMap(id => ATLAS.areas.filter(a => a.id === id).map(a => a.geometry));
    same(p.screen, screenPlace({...s}, {latitude: t0.latitude, longitude: t0.longitude, geometries: areas}), `${p.id}: cached equals uncached`);
  }
  // The run line: the planner's screen, the same line at every hour.
  const {screen, seen: runs} = await planner(t);
  const pick = straight(INSIDE);
  const v = runRouteScreen(HARBOR, pick, screen, 'morro-bay');
  for (let h = 0; h < 4; h++) same(runRouteScreen(HARBOR, pick, screen, 'morro-bay'), v);
  assert.equal(runs.n, 1, 'the run line is screened once');
  assert.equal(v.screened, true);
  assert.equal(v.inside, true);
  same(v, runRouteScreen(HARBOR, pick, screen), 'the legacy (uncached) call answers the same');
  runRouteScreen(HARBOR, pick, screen); runRouteScreen(HARBOR, pick, screen);
  assert.equal(runs.n, 4, 'a call without a region is screened every time and never invents one');
});

test('verdict_cache_in_place_refresh_recomputes: same screen object, same check time, new boundary data', async t => {
  const {screen, seen, refresh} = await planner(t);
  const pick = straight(INSIDE), at = new Date(T0).toISOString();
  const answer = () => runRouteScreen(HARBOR, pick, screen, 'morro-bay');
  const first = answer(), uncached = () => screenPlace({exportExclusions: () => screen.exportExclusions()}, {geometry: {type: 'LineString', coordinates: [[HARBOR.longitude, HARBOR.latitude], [INSIDE.longitude, INSIDE.latitude]]}});
  // The closure the verdict names (the first at the least distance, in boundary order).
  const NEAR = MPAS.features.findIndex(f => (f.properties.FULLNAME || f.properties.NAME) === first.name), near = MPAS.features[NEAR];
  assert.ok(NEAR >= 0, first.name);
  // Changed geometry at the same checked timestamp: the named closure moved far offshore.
  const far = {type: 'Polygon', coordinates: [[[-121.85, 35.8], [-121.84, 35.8], [-121.84, 35.81], [-121.85, 35.8]]]};
  await refresh(withFeature(NEAR, {geometry: far}), at);
  const moved = answer();
  assert.equal(seen.n, 2, 'recomputed after the boundary refresh');
  assert.notEqual(moved.name, first.name);
  same(moved, uncached(), 'equals uncached');
  answer();
  assert.equal(seen.n, 3, 'reused again (the uncached reference read once)');
  // Identical geometry, renamed nearest closure: a metadata-only refresh misses.
  await refresh(withFeature(NEAR, {properties: {...near.properties, NAME: 'Renamed SMR', FULLNAME: 'Renamed Reserve'}}), at);
  assert.equal(answer().name, 'Renamed Reserve');
  assert.equal(seen.n, 4);
  // Order: an equal-geometry alias before the original wins the tie, after it loses.
  const alias = {...near, properties: {...near.properties, NAME: 'Alias SMR', FULLNAME: 'Alias Reserve'}};
  await refresh({...MPAS, features: [alias, ...MPAS.features]}, at);
  assert.equal(answer().name, 'Alias Reserve');
  await refresh({...MPAS, features: [...MPAS.features, alias]}, at);
  same(answer(), first);
  assert.equal(seen.n, 6, 'each order recomputed');
  // Wrong-region binding: the screen is not current there, so nothing is reused and the line is not checked.
  const home = getRegion();
  try {
    setRegion({...home, id: 'elsewhere'});
    assert.equal(screen.verdictRevision(), null);
    assert.equal(runRouteScreen(HARBOR, pick, screen, 'morro-bay').screened, false);
  } finally { setRegion(home); }
  same(answer(), first);
  assert.equal(seen.n, 7, 'recomputed once the binding is back');
});

test('verdict_cache_status_and_clock_transitions: stale, future and recovered screens recompute; a false verdict is not stored', async t => {
  const {screen, seen, env, refresh} = await planner(t);
  const pick = straight(INSIDE), answer = () => runRouteScreen(HARBOR, pick, screen, 'morro-bay');
  // Inclusive freshness edges: 36 h old and 5 min ahead are current; one millisecond past either is not.
  for (const [clock, ok] of [[T0 + 36 * HOUR, true], [T0 + 36 * HOUR + 1, false], [T0 - 300000, true], [T0 - 300001, false]]) {
    env.clock = clock;
    assert.equal(typeof screen.verdictRevision() === 'string', ok, `clock ${clock - T0}`);
  }
  env.clock = T0;
  const clear = answer();
  assert.equal(clear.screened, true);
  env.clock = T0 + 37 * HOUR;
  for (let i = 0; i < 2; i++) assert.equal(answer().screened, false, 'expiry never returns the old cached verdict');
  env.clock = T0;
  same(answer(), clear);
  assert.equal(seen.n, 4, 'ready -> stale -> ready recomputed, and the stale answers were not stored');
  answer();
  assert.equal(seen.n, 4);
  // A newer check (stale-to-current through refresh) recomputes.
  env.clock = T0 + 40 * HOUR;
  assert.equal(answer().screened, false);
  await refresh(MPAS, new Date(env.clock).toISOString());
  same(answer(), clear);
  assert.equal(seen.n, 6);
  // Old, future and invalid check times are never current, so never cached.
  for (const at of [new Date(env.clock - 50 * HOUR).toISOString(), new Date(env.clock + HOUR).toISOString(), 'not a time']) {
    await refresh(MPAS, at);
    assert.equal(screen.verdictRevision(), null, at);
  }

  // A mark screen: status changed in place (stale, checking, unavailable) and back, and a new assessed snapshot.
  const cache = placeVerdictCache((s, p) => { calls++; return screenPlace(s, p); });
  let calls = 0;
  const {s} = countedMarks(), place = {latitude: INSIDE.latitude, longitude: INSIDE.longitude};
  const v = cache.verdict('morro-bay', s, place, 'atlas:x');
  cache.verdict('morro-bay', s, place, 'atlas:x');
  assert.equal(calls, 1);
  for (const status of ['stale', 'checking', 'unavailable']) {
    s.status = status;
    assert.equal(cache.verdict('morro-bay', s, place, 'atlas:x').screened, false, status);
    s.status = 'ready';
    same(cache.verdict('morro-bay', s, place, 'atlas:x'), v);
  }
  assert.equal(calls, 7, 'every status change recomputed');
  const next = countedMarks().s;
  same(cache.verdict('morro-bay', next, place, 'atlas:x'), v);
  assert.equal(calls, 8, 'a new assessed snapshot recomputes');
  s.until = s.until + 1;
  cache.verdict('morro-bay', s, place, 'atlas:x');
  assert.equal(calls, 9, 'a changed expiry recomputes');
  assert.equal(assessScreen(null, NOW).verdictRevision, undefined, 'CHECKING has no capability');
  const stale = assessScreen({areas: MPAS.features, checkedAt: new Date(NOW - 40 * HOUR).toISOString(), live: false}, NOW);
  assert.equal(stale.verdictRevision(), null);
  // A false verdict is never stored, and recovery really reevaluates.
  let flaky = true;
  const fc = placeVerdictCache(() => { calls++; return flaky ? {inside: false, name: null, distanceM: null, screened: false} : {inside: false, name: null, distanceM: 900, screened: true}; });
  const token = {verdictRevision: () => 'r1'};
  calls = 0;
  fc.verdict('a', token, place); fc.verdict('a', token, place);
  assert.equal(calls, 2);
  flaky = false;
  assert.equal(fc.verdict('a', token, place).distanceM, 900);
  fc.verdict('a', token, place);
  assert.equal(calls, 3);
});

test('verdict_cache_exact_place_mutation: a changed place misses, an identical copy hits, no rounding', async t => {
  let calls = 0;
  const cache = placeVerdictCache(() => { calls++; return {inside: false, name: null, distanceM: calls, screened: true}; });
  const s = {verdictRevision: () => 'r'}, area = {type: 'Polygon', coordinates: [[[-121, 35.2], [-120.99, 35.2], [-120.99, 35.21], [-121, 35.2]]]};
  const at = {latitude: 35.2, longitude: -121, geometries: [area]};
  cache.verdict('a', s, at, 'atlas:t1');
  cache.verdict('a', s, structuredClone(at), 'atlas:t1');
  assert.equal(calls, 1, 'an identical copy hits');
  cache.verdict('a', s, {...at, latitude: 35.2 + 1e-12}, 'atlas:t1');
  assert.equal(calls, 2, 'a moved point misses, however small');
  cache.verdict('a', s, {...at, geometries: []}, 'atlas:t1');
  assert.equal(calls, 3, 'changed area membership misses');
  area.coordinates[0][1][0] = -120.98;
  cache.verdict('a', s, at, 'atlas:t1');
  assert.equal(calls, 4, 'an in-place area coordinate edit misses');
  cache.verdict('a', s, {...at, latitude: 0}, 'x'); cache.verdict('a', s, {...at, latitude: -0}, 'x');
  assert.equal(calls, 6, 'negative zero is its own key');
  cache.verdict('a', s, {...at, latitude: NaN}); cache.verdict('a', s, {...at, latitude: NaN});
  cache.verdict('a', s, {geometry: {type: 'GeometryCollection', geometries: []}}); cache.verdict('a', s, {geometry: {type: 'GeometryCollection', geometries: []}});
  assert.equal(calls, 10, 'unkeyable places are not cached');

  // The run line through the real caller: bends, connectors, water versus fallback.
  const {screen, seen} = await planner(t);
  const a = {latitude: 35.3, longitude: -120.9}, b = {latitude: 35.25, longitude: -120.92};
  const lines = [straight(INSIDE), water(INSIDE, [a]), water(INSIDE, [b]), water(INSIDE, [HARBOR, a, INSIDE]), water(INSIDE, [a, INSIDE]), water(INSIDE, [HARBOR, a])];
  for (const p of lines) runRouteScreen(HARBOR, p, screen, 'morro-bay');
  assert.equal(seen.n, lines.length, 'each different line screened');
  for (const p of lines) runRouteScreen(HARBOR, structuredClone(p), screen, 'morro-bay');
  runRouteScreen(HARBOR, {...straight(INSIDE), id: 'other'}, screen, 'morro-bay');
  assert.equal(seen.n, lines.length, 'identical copied lines (whatever the pick id) hit');
  for (const bad of [water(INSIDE, undefined), water(INSIDE, [{latitude: NaN, longitude: 0}]), straight({latitude: 91, longitude: 0})]) {
    assert.equal(runRouteScreen(HARBOR, bad, screen, 'morro-bay').screened, false);
  }
  assert.equal(seen.n, lines.length, 'invalid lines are refused before any screen');
});

test('verdict_cache_region_reset_and_bound: a region change clears; 256 entries, least recently used first', () => {
  let calls = 0;
  const cache = placeVerdictCache(() => { calls++; return {inside: false, name: null, distanceM: 1, screened: true}; });
  const s = {verdictRevision: () => 'same'}, p = i => ({latitude: 35, longitude: -121 + i * 1e-6});
  for (const regions of [['A', 'B', 'A']]) for (const r of regions) cache.verdict(r, s, p(0));
  assert.equal(calls, 3, 'A -> B -> A recomputes even with the same screen, token and place');
  cache.verdict(null, s, p(0));
  cache.verdict('A', s, p(0));
  assert.equal(calls, 4, 'a call without a region is uncached and does not clear');
  assert.equal(VERDICT_CACHE_CAP, 256);
  cache.clear(); calls = 0;
  for (let i = 0; i < 256; i++) cache.verdict('A', s, p(i));
  cache.verdict('A', s, p(0));
  assert.equal(calls, 256, 'a hit promotes');
  cache.verdict('A', s, p(256));
  assert.equal(cache.size, 256, 'bounded');
  cache.verdict('A', s, p(0));
  assert.equal(calls, 257, 'the promoted entry survived');
  cache.verdict('A', s, p(1));
  assert.equal(calls, 258, 'the least recently used was evicted and is recomputed');

  // The app's cache follows the store's region signal itself, whoever reads it.
  placeVerdicts.clear();
  const {s: marks} = countedMarks();
  placeVerdicts.verdict('morro-bay', marks, p(0));
  assert.equal(placeVerdicts.size, 1);
  for (const next of ['other', null, 'morro-bay']) {
    placeVerdicts.verdict('morro-bay', marks, p(0));
    assert.equal(placeVerdicts.size, 1);
    region.value = next;
    assert.equal(placeVerdicts.size, 0, `cleared on region ${next}`);
  }
  region.value = null;
});

test('verdict_cache_uncapable_unchecked_and_mutation_safe: anything without a valid revision is screened uncached', async t => {
  let calls = 0, rev = 'r';
  const cache = placeVerdictCache((s, p) => { calls++; if (s.boom) throw new Error('coverage'); return {inside: false, name: 'X', distanceM: 5, screened: true}; });
  const place = {latitude: 35, longitude: -121};
  const screens = [{}, {verdictRevision: () => { throw new Error('no'); }}, {verdictRevision: () => ''}, {verdictRevision: () => 7}, {verdictRevision: 'r'}];
  for (const s of screens) { cache.verdict('A', s, place); cache.verdict('A', s, place); }
  assert.equal(calls, screens.length * 2);
  calls = 0;
  const shifting = {verdictRevision: () => rev};
  const midway = placeVerdictCache(() => { calls++; rev += '+'; return {inside: false, name: null, distanceM: null, screened: true}; });
  midway.verdict('A', shifting, place); midway.verdict('A', shifting, place);
  assert.equal(calls, 2, 'a revision that changes during evaluation is not stored');
  assert.throws(() => cache.verdict('A', {boom: true, verdictRevision: () => 'r'}, place), /coverage/);
  assert.equal(cache.size, 0, 'an exception is not stored');
  const ok = {verdictRevision: () => 'r'};
  const v = cache.verdict('A', ok, place);
  v.name = 'corrupted'; v.inside = true;
  const again = cache.verdict('A', ok, place);
  same(again, {inside: false, name: 'X', distanceM: 5, screened: true}, 'a consumer cannot corrupt a later answer');
  again.name = 'twice';
  assert.equal(cache.verdict('A', ok, place).name, 'X');

  // Through the real run caller: no screen, a hand-built copy, a throwing screen, an off-envelope line, a refused line.
  const {screen, seen} = await planner(t);
  const pick = straight(INSIDE), line = [[HARBOR.longitude, HARBOR.latitude], [INSIDE.longitude, INSIDE.latitude]];
  assert.equal(runRouteScreen(HARBOR, pick, null, 'morro-bay').screened, false);
  const copy = {...screen};
  same(runRouteScreen(HARBOR, pick, {...copy, verdictRevision: undefined}, 'morro-bay'), screenPlace(screen, {geometry: {type: 'LineString', coordinates: line}}));
  assert.equal(runRouteScreen(HARBOR, pick, {...screen, exportExclusions() { throw new Error('x'); }}, 'morro-bay').screened, false);
  const off = straight({latitude: 36.8, longitude: -123.5});
  for (let i = 0; i < 2; i++) assert.equal(runRouteScreen(HARBOR, off, screen, 'morro-bay').screened, false, 'not covered: unchecked');
  const n = seen.n;
  const refused = runRouteScreen(HARBOR, pick, screen, 'morro-bay');
  assert.equal(refused.inside, true, 'a refused line is a checked verdict');
  runRouteScreen(HARBOR, pick, screen, 'morro-bay');
  assert.equal(seen.n, n + 1, 'and is cached like a clear one');
});
