// FSC-05: the Boat brief's run time, turn-back and fishing time take the water route (web/route.ts, FSC-04);
// the straight line stays only as a labelled fallback. Synthetic land-water products reuse the fixture of
// tests/test_route.mjs (zoom-12 tile 671/1616, 32×32 cells), so every case is offline.
// SC2207-02: the run line reads the routed list Where to look paints (boatPicks' memoised routes, WhereToLook's
// listedBoatPicks); it never searches a route itself. A test therefore prepares the list's routes the way the list
// does (boatPicks / routeAfterPaint) before it renders the line. The route search is counted by wrapping waterRoute.
import assert from 'node:assert/strict';
import {mkdtemp, readFile} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {distanceNm} from '../dist/spot-ranking.js';
import {assessScreen} from '../web/map/habitat.ts';
import {rankedHabitat} from '../packages/coast/src/coast3d/regional.ts';
import {ranking} from '../web/ranking.ts';
import {durationText, planRun, runRouteNote, runRouteScreen} from '../web/brief/run.ts';
import {PLANNING_MARGIN_M, screenPlace} from '../dist/geo-screen.js';
import {decodeCells, landWaterModel} from '../web/land-water.ts';

const ROOT = new URL('..', import.meta.url).pathname, TZ = 'America/Los_Angeles';
const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/land-water/${name}`, import.meta.url), 'utf8'));
const dist = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const coast = fixture('coast.json'), COAST = '12/671/1616', N = 4096, G = 32;
const cell = (col, row) => ({latitude: Math.atan(Math.sinh(Math.PI * (1 - 2 * (1616 + (row + 0.5) / G) / N))) * 180 / Math.PI, longitude: (671 + (col + 0.5) / G) / N * 360 - 180});
const paint = (rects, base = 'w'.repeat(G * G)) => {
  const a = [...base];
  for (const [c, c0, r0, c1, r1] of rects) for (let r = r0; r <= r1; r++) for (let k = c0; k <= c1; k++) a[r * G + k] = c;
  return a.join('').replace(/(.)\1*/g, m => m[0] + m.length);
};
const product = (rects, base, bounds = [-12110000, 3530000, -12075000, 3555000]) => landWaterModel({...coast, bounds, tiles: {[COAST]: paint(rects, base)}}, 'fixture');
const coastGrid = rects => product(rects, decodeCells(coast.tiles[COAST], G * G), coast.bounds);
const state = (model, lines = null, region = 'fixture') => ({region, state: 'ready', model, lines, linesLoading: false});
const IDLE = {region: null, state: 'idle', model: null, lines: null, linesLoading: false};
const WINDOW = {start: '2026-10-12T14:00:00.000Z', end: '2026-10-12T19:00:00.000Z', label: 'Lower wind & offshore seas', confidence: 'Low', reasons: [], wind: 8, gust: 12, wave: 3, period: 10};
const brief = {profile: 'boat', windows: [WINDOW], alerts: [], missing: [], tiles: [{id: 'wind', state: 'fresh'}], limits: {custom: false}};
const NOW = new Date('2026-10-12T12:00:00Z');
const pick = (at, nm = distanceNm(HARBOR, at), id = 'a') => ({id, kind: 'spot', name: `Reef ${id}`, distance: `${nm} nm`, nm, at, depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.', screen: {inside: false, name: null, distanceM: null, screened: true}});
const HARBOR = cell(4, 8), AWAY = cell(28, 8);
const rank = (at = AWAY, extra = {}) => ({source: 'atlas', label: 'Survey reef atlas', basis: '', picks: [pick(at)], empty: '', harbor: 'Fixture Harbor', origin: HARBOR, ...extra});
const HEADLAND = product([['l', 10, 0, 21, 23]]);

/** Counts every call of web/route.ts waterRoute, the one route search: it is the only way a route can be computed. */
const counting = {name: 'count-routes', setup: b => b.onLoad({filter: /web[\\/]route\.ts$/}, async args => {
  const src = await readFile(args.path, 'utf8'), head = 'export function waterRoute(';
  assert.ok(src.includes(head), 'waterRoute is still exported as a function');
  return {loader: 'ts', contents: src.replace(head, 'export let routeCalls = 0;\nexport function waterRoute(model: any, lines: any, from: any, to: any, maxNodes?: number): Route { routeCalls++; return waterRouteSearch(model, lines, from, to, maxNodes); }\nfunction waterRouteSearch(')};
})};

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'run-route-')), 'run.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {RunLine, runPlace, runText, runBasis, runScreenFor, watchBoundaries} from './web/brief/Run.tsx';
      export {protectedScreen} from './web/trip.ts';
      export {WhereToLook, boatPicks, listedBoatPicks, routeAfterPaint} from './web/brief/WhereToLook.tsx';
      export {routeCalls} from './web/route.ts';
      export {effect} from '@preact/signals';
      export {landWater, loadLandWaterLines} from './web/land-water.ts';
      export {cruiseSpeed} from './web/limits.ts';
      export {regionInfo} from './web/app/App.tsx';
      export {profile, region, selection, habitat} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  plugins: [...(await import('./helpers/esbuild-url.mjs')).rendererPlugins, counting]});
  mod = await import(pathToFileURL(out).href);
  return mod;
}
/** The rendered run line for a land-water state; the region is 'fixture'. */
async function line(lw, ranking = rank(), speed = 20, selected = null, habitat = null, b = brief) {
  const m = await load();
  m.regionInfo.value = {id: 'fixture', name: 'Fixture', center: [35.3, -120.9], timezone: TZ};
  m.profile.value = 'boat'; m.region.value = 'fixture'; m.selection.value = selected; m.habitat.value = habitat; m.cruiseSpeed.value = speed; m.landWater.value = lw;
  return m.render(m.h(m.RunLine, {brief: b, ranking, now: NOW}));
}
/** What Where to look does for a Boat list: compute every missing route (all at once here; it does one per task after the paint). */
const prepare = async (r, lw) => (await load()).boatPicks(r, lw, 'fixture');
/** The picks the list paints now, and the run's place from them. */
const listed = async (r, lw) => (await load()).listedBoatPicks(r, lw, 'fixture');
const placeOf = async (r, lw, spot = null, hab = null) => (await load()).runPlace(await listed(r, lw), spot, hab);
const fresh = () => state(product([['l', 10, 0, 21, 23]]));

test('a computed route: "by water" with the route nm, run time from it, less fishing time than the straight line', async () => {
  const straight = distanceNm(HARBOR, AWAY);
  await prepare(rank(), state(HEADLAND));
  const place = await placeOf(rank(), state(HEADLAND));
  assert.equal(place.basis, 'water');
  assert.ok(place.nm > straight * 1.5, `${place.nm} goes round the headland, the line is ${straight}`);
  const water = planRun(brief, place, 20, NOW), line0 = planRun(brief, {name: 'Reef a', nm: straight, basis: 'straight', why: 'no-product'}, 20, NOW);
  assert.equal(water.runMin, Math.ceil(place.nm / 20 * 60 / 5) * 5, 'run time from the route nm');
  assert.ok(water.runMin > line0.runMin && water.fishMin < line0.fishMin, `${water.fishMin} min fishing by water, ${line0.fishMin} on the line`);
  assert.equal(water.fishMin, 300 - 2 * water.runMin);
  const html = await line(state(HEADLAND));
  assert.match(html, new RegExp(`${place.nm.toFixed(1)} nm by water · at least ${water.runMin} min each way at 20 kt`));
  assert.match(html, /Up to 4 h 20 min fishing at Reef a\./);
  assert.doesNotMatch(html, /nm straight line/);
});

test('each failure keeps the straight-line nm and says why; times equal the straight-line times', async () => {
  const {runText} = await load(), straight = distanceNm(HARBOR, AWAY), walled = coastGrid([['l', 0, 22, 31, 22], ['m', 17, 22, 18, 22]]);
  const sea = product([['l', 0, 0, 15, 31]]), west = cell(4, 16), east = cell(24, 16);
  const cases = [
    ['no-product', IDLE, rank()],
    ['lines-needed', state(walled), rank(cell(14, 25), {origin: cell(14, 12)})],
    ['no-route', state(walled, false), rank(cell(14, 25), {origin: cell(14, 12)})],
    ['start-not-water', state(sea), rank(east, {origin: west})],
    ['end-not-water', state(sea), rank(west, {origin: east})],
  ];
  const words = {'no-product': 'no land/water data', 'lines-needed': 'shoreline still loading', 'start-not-water': 'the harbor or place is not on confirmed water', 'end-not-water': 'the harbor or place is not on confirmed water', 'no-route': 'no water path found'};
  for (const [why, lw, r] of cases) {
    await prepare(r, lw);
    const place = await placeOf(r, lw);
    assert.equal(place.basis, 'straight', why);
    assert.equal(place.why, why);
    assert.equal(place.nm, r.picks[0].nm, `${why}: the pick's straight-line nm`);
    const html = await line(lw, r);
    assert.ok(html.includes(`${r.picks[0].nm.toFixed(1)} nm straight line (no water route: ${words[why]})`), `${why}: ${html.match(/app-run-detail[^<]*/)}`);
    assert.doesNotMatch(html, /nm by water/);
  }
  await prepare(rank(), IDLE);
  const base = planRun(brief, {name: 'Reef a', nm: straight}, 20, NOW), fall = planRun(brief, await placeOf(rank(), IDLE), 20, NOW);
  assert.deepEqual([fall.runMin, fall.depart, fall.turnBack, fall.fishMin], [base.runMin, base.depart, base.turnBack, base.fishMin], 'same nm, same times as before');
  const text = why => runText({...fall, kind: 'no-time', place: {name: 'Reef a', nm: 2, basis: 'straight', why}}, TZ).run;
  assert.match(text('too-far'), /2\.0 nm straight line \(no water route: too far to route\) · at least/);
  assert.match(text(undefined), /\(water route not computed yet\)/, 'a place with no reason is a route not computed yet, not a failed one');
});

test('lines-needed, then the lines load: the list prepares the route, the run line follows it and asks for nothing', async () => {
  const m = await load(), walled = coastGrid([['l', 0, 22, 31, 22], ['m', 17, 22, 18, 22]]), r = rank(cell(14, 25), {origin: cell(14, 12)});
  await prepare(r, state(walled));
  assert.equal((await placeOf(r, state(walled))).why, 'lines-needed');
  assert.match(await line(state(walled), r), /straight line \(no water route: shoreline still loading\)/);
  const text = await readFile(new URL('./fixtures/land-water/coast.lines.json', import.meta.url), 'utf8');
  let asked = 0;
  const fetchFn = async () => { asked++; return {ok: true, text: async () => text}; };
  m.landWater.value = state(walled);
  await m.loadLandWaterLines('fixture', fetchFn);
  assert.equal(asked, 1);
  assert.equal(m.landWater.value.lines && typeof m.landWater.value.lines, 'object', 'the lines loaded');
  const calls = m.routeCalls;
  const pending = await line(m.landWater.value, r);
  assert.match(pending, /straight line \(water route not computed yet\)/, 'the lines landed but the list has not routed yet: never "shoreline still loading", never a route of its own');
  assert.doesNotMatch(pending, /shoreline still loading|nm by water/);
  assert.equal(m.routeCalls, calls, 'the run line searched no route');
  await new Promise(done => m.routeAfterPaint(r, m.landWater.value, 'fixture', undefined, done));
  const html = await line(m.landWater.value, r);
  assert.match(html, /nm by water/);
  assert.doesNotMatch(html, /shoreline still loading/);
  await line(m.landWater.value, r);
  assert.equal(m.routeCalls, calls + 1, 'one route search for the pick, made by the list; repeated run renders made none');
  assert.equal(asked, 1, 'the run line asked for no shoreline lines');
  assert.equal((await placeOf(r, state(walled, false))).why, undefined, 'no routes memoised for failed lines: not computed yet, not shown as a failure');
  await prepare(r, state(walled, false));
  assert.equal((await placeOf(r, state(walled, false))).why, 'no-route', 'failed lines do not read as still loading');
  await prepare(r, state(walled, null, 'other-region'));
  assert.equal((await placeOf(r, state(walled, null, 'other-region'))).why, 'no-product', "another region's product is never used");
});

test('no harbor position: the lead is unchanged, no place and so no route; an unpositioned pick takes no route', async () => {
  const none = rank(AWAY, {origin: undefined, harbor: undefined, picks: [{...pick(AWAY), nm: null}]});
  assert.equal(await placeOf(none, state(HEADLAND)), null);
  assert.match(await line(state(HEADLAND), none), /No harbor position to measure from, so no run time\./);
  const bare = await placeOf(rank(AWAY, {origin: undefined}), state(HEADLAND));
  assert.deepEqual([bare.basis, bare.why], ['straight', undefined], 'a distance without an origin is the labelled straight line, with no failure claimed');
});

test('spot and habitat picks carry their coordinates as at; the origin is the one the distances run from', () => {
  const NOWMS = Date.now(), data = {region: {...dist('regions/morro-bay/region.json'), id: 'morro-bay'}, atlas: dist('data/atlas.json'), survey: null, geology: null};
  const screen = assessScreen({areas: dist('data/protected-areas.geojson').features, checkedAt: new Date(NOWMS).toISOString(), live: true}, NOWMS);
  const base = {region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data, screen, terrain: {state: 'unavailable'}, now: NOWMS, place: () => ({state: 'water'})};
  const atlas = ranking(base);
  assert.ok(atlas.picks.length && atlas.origin, 'atlas picks and an origin');
  for (const p of atlas.picks) {
    const t = data.atlas.targets.find(x => x.id === p.id);
    assert.deepEqual(p.at, {latitude: t.latitude, longitude: t.longitude});
    assert.equal(p.nm, distanceNm(atlas.origin, p.at));
  }
  const reef = {type: 'Feature', id: 'h1', geometry: {type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, properties: {id: 'h1', region: 'morro-bay', exportable: true, screen_status: 'pass',
    screen_expires_at: new Date(NOWMS + 86400000).toISOString(), waypoint_latitude: 35.3, waypoint_longitude: -120.95, depth_min_ft: 40, depth_max_ft: 80, terrain_score: 70, fit_lingcod: 2}};
  const terrain = ranking({...base, terrain: {state: 'ready', features: [reef], expiresAt: NOWMS + 3600000, rank: rankedHabitat}});
  assert.equal(terrain.source, 'terrain');
  assert.deepEqual(terrain.picks.map(p => p.at), [{latitude: 35.3, longitude: -120.95}]);
  assert.deepEqual(terrain.origin, {latitude: data.region.harbor.latitude, longitude: data.region.harbor.longitude});
  assert.equal(ranking({...base, data: {...data, region: {...data.region, harbor: undefined}}}).origin, undefined, 'no harbor, no origin');
});

test('the basis names the water route, the labelled fallback and that it is not a navigation route', async () => {
  const basis = (await load()).runBasis('Morro Bay');
  assert.match(basis, /by water/);
  assert.match(basis, /not a navigation route/);
  assert.match(basis, /falls back to the straight line, labelled/);
  assert.doesNotMatch(basis, /until a charted route is available|the real route is longer/);
});

// SC2207-02. The headland product sends a route to AWAY round the headland, far past the straight line.
const WEST = [cell(7, 8), cell(6, 6), cell(6, 10), cell(7, 12)];
const ranked = (range, extra = {}) => rank(AWAY, {reach: range, picks: [pick(AWAY, undefined, 'a'), ...WEST.map((at, i) => pick(at, undefined, 'bcde'[i]))], ...extra});
const between = async () => {
  const straight = distanceNm(HARBOR, AWAY), [around] = await prepare(rank(), fresh());
  assert.ok(around.nm > straight * 1.5);
  return {straight, water: around.nm, range: (straight + around.nm) / 2};
};
const fishing = (place, b = brief) => { const plan = planRun(b, {name: place.name, nm: place.nm, basis: place.basis}, 20, NOW); return {plan, text: `Up to ${durationText(plan.fishMin)} fishing at ${place.name}.`, run: `${place.nm.toFixed(1)} nm by water · at least ${plan.runMin} min each way at 20 kt`}; };

test('run_uses_first_listed_after_range_drop: the run names and times the first place the list still shows, never the one range dropped', async () => {
  const m = await load(), {straight, water, range} = await between(), lw = fresh(), r = ranked(range);
  // Before the list's routes are in, both show the same provisional order (the straight line, labelled).
  const early = await line(lw, r);
  assert.deepEqual((await listed(r, lw)).map(p => p.id), ['a', 'b', 'c', 'd']);
  assert.match(early, /Up to [^<]* fishing at Reef a\./);
  assert.match(early, /straight line \(water route not computed yet\)/);
  await new Promise(done => m.routeAfterPaint(r, lw, 'fixture', undefined, done));
  const picks = await listed(r, lw);
  assert.deepEqual(picks.map(p => p.id), ['b', 'c', 'd', 'e'], `A: straight ${straight}, water ${water}, range ${range}: dropped; E fills the list`);
  const html = await line(lw, r), want = fishing(picks[0]);
  assert.match(html, new RegExp(want.text.replace('.', '\\.')));
  assert.ok(html.includes(want.run), `${want.run} in ${html.match(/app-run-detail[^<]*/)}`);
  assert.doesNotMatch(html, /Reef a|outside the ranked list/);
  const planned = m.runPlace(picks, null, null);
  assert.deepEqual([planned.name, planned.nm, planned.basis, planned.chosen, planned.unranked], ['Reef b', picks[0].nm, 'water', false, false]);
  // A selected place the list dropped falls back to the first listed one and says so; a visible one wins.
  assert.match(await line(lw, r, 20, 'a'), /Your selected place is outside the ranked list, so times are for the top pick\. Up to [^<]* fishing at Reef b\./);
  const chosen = picks[2], got = await line(lw, r, 20, 'd');
  assert.match(got, new RegExp(`${fishing(chosen).text.replace('.', '\\.')}`));
  assert.ok(got.includes(`${chosen.nm.toFixed(1)} nm by water`) && !got.includes('top pick') && !got.includes('outside the ranked list'), got.match(/app-run-detail[^<]*/));
  // A route exactly at the range is kept: the first pick stays A.
  const edge = ranked(water), lwEdge = fresh();
  await prepare(edge, lwEdge);
  assert.deepEqual((await listed(edge, lwEdge)).map(p => p.id), ['a', 'b', 'c', 'd']);
});

test('a habitat selection matches a listed habitat only; a reef with the same id is not it', async () => {
  const m = await load(), listedPicks = [{...pick(cell(7, 8), 1, 'r1'), kind: 'reef', basis: 'straight'}, {...pick(cell(6, 6), 2, 'h1'), kind: 'habitat', basis: 'water'}];
  assert.equal(m.runPlace(listedPicks, null, 'h1').name, 'Reef h1');
  const reefOnly = m.runPlace(listedPicks, null, 'r1');
  assert.deepEqual([reefOnly.name, reefOnly.chosen, reefOnly.unranked], ['Reef r1', false, true], 'a reef id never selects as a habitat: the first listed pick, said so');
});

test('run_empty_routed_range_has_no_times: range removed every listed place; exact copy, no arrival, turn-back or fishing', async () => {
  const m = await load(), {water, range} = await between(), lw = fresh(), r = ranked(range, {picks: [pick(AWAY, undefined, 'a'), pick(cell(27, 8), undefined, 'f')]});
  const pending = await line(lw, r);
  assert.match(pending, /fishing at Reef a\./, 'still on the straight line until the list routes');
  await new Promise(done => m.routeAfterPaint(r, lw, 'fixture', undefined, done));
  assert.deepEqual(await listed(r, lw), []);
  const html = await line(lw, r);
  assert.match(html, /data-state="no-place"/);
  assert.match(html, /No listed place is within your range, so no run time\./);
  assert.doesNotMatch(html, /Leave |turn back|in by|fishing at|each way|No harbor position|nm /);
  assert.doesNotMatch(html, /app-run-detail|app-run-times/);
  // A route exactly at the range stays listed.
  const edge = ranked(water, {picks: [pick(AWAY, undefined, 'a')]}), lwEdge = fresh();
  await prepare(edge, lwEdge);
  assert.match(await line(lwEdge, edge), /fishing at Reef a\./);
  // The other empty states keep their own copy and precedence.
  assert.match(await line(lw, {...r, picks: []}), /Run time shows once a place to look is listed\./);
  assert.match(await line(lw, {...r, picks: [{...pick(AWAY, undefined, 'a'), nm: null}], reach: undefined}), /No harbor position to measure from, so no run time\./);
  assert.match(await line(lw, r, null), /Set your cruise speed to see run time/, 'no speed outranks the empty list');
  assert.match(await line(lw, r, 20, null, null, {...brief, windows: []}), /No lower-exposure window for this day, so no return time\./, 'no window outranks the empty list');
  assert.doesNotMatch(await line(lw, r, 20, null, null, {...brief, windows: []}), /within your range/);
});

test('run_and_list_share_deferred_routes: one memo, one search per route, from the list; both update when the deferred routes land', async () => {
  const m = await load(), {range} = await between(), lw = fresh(), r = ranked(range), seen = [];
  const calls = () => m.routeCalls, start = calls();
  // Mounted subscriptions: each re-runs when a completed deferred route bumps the tick the shared helper reads.
  const stops = [
    m.effect(() => { seen.push(['run', m.runPlace(m.listedBoatPicks(r, lw, 'fixture'), null, null)?.name]); }),
    m.effect(() => { seen.push(['list', m.listedBoatPicks(r, lw, 'fixture').map(p => p.id).join('')]); }),
  ];
  assert.deepEqual(seen, [['run', 'Reef a'], ['list', 'abcd']]);
  await line(lw, r); m.render(m.h(m.WhereToLook, {ranking: r})); await line(lw, r);
  assert.equal(calls(), start, 'the first paint of the run line and of the list searched no route');
  await new Promise(res => { const was = seen.length; const poll = () => seen.length >= was + 2 ? res() : setTimeout(poll, 1); m.routeAfterPaint(r, lw, 'fixture'); poll(); });
  assert.deepEqual(seen.slice(2), [['run', 'Reef b'], ['list', 'bcde']], 'both subscribers followed the deferred routes: A dropped, E filled');
  const done = calls();
  assert.equal(done - start, 5, 'one search for each of the five candidates, none repeated');
  for (let i = 0; i < 3; i++) { await line(lw, r); m.render(m.h(m.WhereToLook, {ranking: r})); }
  assert.equal(calls(), done, 'repeated renders of both made no further search');
  // A cancelled task updates neither subscriber and searches nothing.
  const other = fresh(), size = seen.length, cancel = m.routeAfterPaint(ranked(range), other, 'fixture');
  cancel();
  await new Promise(res => setTimeout(res, 10));
  assert.ok(seen.length === size && calls() === done, 'a cancelled task changed nothing');
  // A new product, lines answer or region starts afresh: no other region's route is used.
  const stale = await listed(r, {...lw, region: 'elsewhere'});
  assert.ok(stale.every(p => p.basis === 'straight' && p.why === undefined), "another region's product reuses no route");
  assert.equal(calls(), done);
  stops.forEach(stop => stop());
});

test('run_invalid_distance_and_unused_feature: a distance that is not a usable number gives no place; names stay text; Shore and Kayak print nothing', async () => {
  const m = await load();
  for (const nm of [null, NaN, Infinity, -Infinity, -1, undefined]) {
    const r = rank(AWAY, {picks: [{...pick(AWAY, undefined, 'a'), nm}]});
    assert.equal(await placeOf(r, fresh()), null, String(nm));
    const html = await line(fresh(), r);
    assert.match(html, /data-state="no-place"/, String(nm));
    assert.doesNotMatch(html, /Leave |turn back|fishing at|each way/, String(nm));
  }
  const named = rank(AWAY, {picks: [{...pick(AWAY, undefined, 'a'), name: '<b>Reef &</b>'}]});
  const html = await line(fresh(), named);
  assert.ok(html.includes('&lt;b>Reef &amp;&lt;/b>') && !html.includes('<b>Reef'), 'the place name is text, never markup');
  for (const other of ['kayak', 'shore', 'spear']) {
    m.profile.value = other;
    assert.equal(m.render(m.h(m.RunLine, {brief: {...brief, profile: other}, ranking: ranked(1), now: NOW})), '', other);
  }
  m.profile.value = 'boat';
});

// SC0452-07: the run line names a protected area the line it times crosses or passes within the planning margin of.
// Synthetic screens only (the shape protected-areas.js hands out: ready, coversGeometry, exportExclusions); no fetch.
const M_LAT = 111320, mLon = lat => M_LAT * Math.cos(lat * Math.PI / 180);
/** A square area `halfM` metres either side of `at`, as a GeoJSON polygon. */
const box = (at, halfM) => { const dy = halfM / M_LAT, dx = halfM / mLon(at.latitude), {latitude: y, longitude: x} = at;
  return {type: 'Polygon', coordinates: [[[x - dx, y - dy], [x + dx, y - dy], [x + dx, y + dy], [x - dx, y + dy], [x - dx, y - dy]]]}; };
const mid = (a, b) => ({latitude: (a.latitude + b.latitude) / 2, longitude: (a.longitude + b.longitude) / 2});
/** A ready screen over `areas` ([name, geometry]); `patch` overrides any method. */
const screenOf = (areas, patch = {}) => ({ready: () => true, coversGeometry: () => true,
  exportExclusions: () => ({features: areas.map(([name, geometry]) => ({properties: {NAME: name}, geometry}))}), ...patch});
const loaded = (screen, region = 'fixture') => ({state: 'loaded', region, screen});
const verdict = (v, ...area) => runRouteScreen(...v, screenOf(area));
const waterPick = (at, routePoints, id = 'a') => ({...pick(at, undefined, id), basis: 'water', routePoints});
const straightPick = (at, id = 'a', why) => ({...pick(at, undefined, id), basis: 'straight', ...(why ? {why} : {})});
const A = {latitude: 35.30, longitude: -120.90}, B = {latitude: 35.30, longitude: -120.80}, UP = {latitude: 35.36, longitude: -120.85};
/** Screened, not inside, and nothing within the margin: the verdict that earns no note. (A farther area may still be the nearest one named.) */
const isClear = v => v.screened === true && v.inside === false && (v.distanceM === null || v.distanceM > PLANNING_MARGIN_M);

/** Runs `fn` with every network call refused and the protected-area signal put back after. */
async function guarded(fn) {
  const m = await load(), was = globalThis.fetch, signal = m.protectedScreen.value;
  globalThis.fetch = () => { throw new Error('unexpected network call'); };
  try { return await fn(m); } finally { globalThis.fetch = was; m.protectedScreen.value = signal; }
}
/** The run line with the protected-area signal set; the note paragraph, or null. */
async function noted(value, lw, r = rank(), ...rest) {
  const m = await load(); m.protectedScreen.value = value;
  const html = await line(lw, r, ...rest);
  return {html, note: html.match(/<p class="app-run-protected">([^<]*)<\/p>/)?.[1] ?? null};
}
/** The route a headland Boat list paints and the area on its water detour (clear of both ends and of the straight line) or on the chord. */
async function headland() {
  const lw = state(HEADLAND), r = rank();
  await prepare(r, lw);
  const [p] = await listed(r, lw), path = [HARBOR, ...p.routePoints, AWAY];
  assert.equal(p.basis, 'water');
  let best = 0;
  for (let i = 1; i < path.length; i++) if (Math.abs(mid(path[i - 1], path[i]).latitude - HARBOR.latitude) > Math.abs(mid(path[best], path[best + 1]).latitude - HARBOR.latitude)) best = i - 1;
  const detour = ['Detour Sound', box(mid(path[best], path[best + 1]), 60)], chord = ['Chord Banks', box(mid(HARBOR, AWAY), 100)];
  return {lw, r, p, detour, chord};
}

test('run_line_uses_water_bends_and_endpoint_connectors: a bent route crosses what the chord and both ends miss, and the converse', () => {
  const bends = [{latitude: 35.31, longitude: -120.88}, {latitude: 35.31, longitude: -120.82}], at = {latitude: 35.30, longitude: -120.80};
  const top = ['Top Reef', box(mid(bends[0], bends[1]), 80)], onChord = ['Chord Banks', box(mid(A, B), 80)];
  const water = waterPick(at, bends), chord = straightPick(at);
  const screen = screenOf([top]);
  assert.equal(runRouteScreen(A, water, screen).inside, true, 'the middle of the bent route crosses the area');
  assert.deepEqual(runRouteScreen(A, water, screen).name, 'Top Reef');
  assert.ok(isClear(runRouteScreen(A, chord, screen)), 'the straight chord misses it');
  for (const end of [A, at]) assert.ok(isClear(screenPlace(screen, end)), 'both ends and every bend are clear on their own');
  for (const bend of bends) assert.ok(isClear(screenPlace(screen, bend)), 'each bend is clear on its own');
  // The converse: the chord crosses, the water path goes round.
  const round = screenOf([onChord]);
  assert.equal(runRouteScreen(A, chord, round).inside, true);
  assert.ok(isClear(runRouteScreen(A, water, round)), 'the water path avoids what the chord crosses');
  // The connectors: harbor to the first snapped end, and the last snapped end to the place, are part of the line.
  const first = ['Start Cove', box(mid(A, bends[0]), 50)], last = ['End Cove', box(mid(bends[1], at), 50)];
  assert.equal(runRouteScreen(A, water, screenOf([first])).name, 'Start Cove');
  assert.equal(runRouteScreen(A, water, screenOf([last])).name, 'End Cove');
  assert.ok(isClear(runRouteScreen(A, water, screenOf([['Elsewhere', box({latitude: 35.5, longitude: -120.5}, 80)]]))), 'an area far from the line');
  // The route's bends decide it: the same place and screen, other bends, other verdict.
  assert.ok(isClear(runRouteScreen(A, waterPick(at, [{latitude: 35.29, longitude: -120.85}]), screen)));
});

test('run_line_uses_water_bends_and_endpoint_connectors (rendered): the line follows the list\'s route; times, list and pick are untouched', async () => guarded(async m => {
  const {lw, r, p, detour, chord} = await headland(), before = JSON.stringify(await listed(r, lw)), calls = m.routeCalls;
  const none = await noted({state: 'idle'}, lw, r);
  const hit = await noted(loaded(screenOf([detour])), lw, r), onChord = await noted(loaded(screenOf([chord])), lw, r);
  assert.equal(hit.note, 'Route crosses or touches Detour Sound.');
  assert.equal(onChord.note, null, 'the chord crosses Chord Banks, but the line goes by water round it');
  assert.equal(none.note, 'Route: protected areas not checked.');
  const strip = html => html.replace(/<p class="app-run-protected">[^<]*<\/p>/, '');
  assert.equal(strip(hit.html), strip(none.html), 'the lead, the times and the distance are the same with or without the screen');
  assert.equal(strip(onChord.html), strip(none.html));
  assert.equal(JSON.stringify(await listed(r, lw)), before, 'the list, its order and every pick verdict are unchanged');
  assert.ok(hit.html.includes(`${p.nm.toFixed(1)} nm by water`));
  assert.equal(m.routeCalls, calls, 'no route searched for the screen');
  // No water route (the lines of another region): the labelled straight line is screened the same way.
  const fallback = await noted(loaded(screenOf([chord])), IDLE, r), elsewhere = await noted(loaded(screenOf([detour])), IDLE, r);
  assert.match(fallback.html, /nm straight line/);
  assert.equal(fallback.note, 'Route crosses or touches Chord Banks.');
  assert.equal(elsewhere.note, null, 'the detour is not on the straight line');
}));

test('run_line_margin_inside_unknown_and_clear: the note at the margin, for a crossing, with no name, with markup, and for a clear line', async () => guarded(async () => {
  // The helper at the exact threshold, apart from any geometry.
  assert.equal(PLANNING_MARGIN_M, 70);
  assert.equal(runRouteNote({inside: false, name: 'Cove', distanceM: 69, screened: true}), 'Route passes within 70 m of Cove.');
  assert.equal(runRouteNote({inside: false, name: 'Cove', distanceM: 70, screened: true}), 'Route passes within 70 m of Cove.', 'exactly 70 m is within the margin');
  assert.equal(runRouteNote({inside: false, name: 'Cove', distanceM: 70.1, screened: true}), null);
  assert.equal(runRouteNote({inside: false, name: 'Cove', distanceM: 5000, screened: true}), null);
  assert.equal(runRouteNote({inside: false, name: null, distanceM: null, screened: true}), null, 'nothing within reach is no note, and no clearance claim');
  assert.equal(runRouteNote({inside: true, name: 'Cove', distanceM: 0, screened: true}), 'Route crosses or touches Cove.');
  assert.equal(runRouteNote({inside: true, name: null, distanceM: 0, screened: true}), 'Route crosses or touches a protected area.');
  assert.equal(runRouteNote({inside: false, name: null, distanceM: 40, screened: true}), 'Route passes within 70 m of a protected area.');
  assert.equal(runRouteNote({inside: false, name: 'Cove', distanceM: 10, screened: false}), 'Route: protected areas not checked.', 'not screened wins over any field');
  // Real geometry: a line along the harbor's parallel, an area 40 m or 500 m north of it, one on it, one touching its end.
  const water = waterPick(B, [mid(A, B)]), west = {latitude: A.latitude, longitude: A.longitude};
  const off = (m, name = 'Off Reef') => [name, box({latitude: A.latitude + (m + 30) / M_LAT, longitude: mid(A, B).longitude}, 30)];
  assert.match(runRouteNote(runRouteScreen(west, water, screenOf([off(40)]))), /^Route passes within 70 m of Off Reef\.$/);
  assert.equal(runRouteScreen(west, water, screenOf([off(500)])).screened, true);
  assert.equal(runRouteNote(runRouteScreen(west, water, screenOf([off(500)]))), null);
  assert.equal(runRouteNote(runRouteScreen(west, water, screenOf([['Over Reef', box(mid(A, B), 30)]]))), 'Route crosses or touches Over Reef.');
  assert.equal(runRouteNote(runRouteScreen(west, water, screenOf([['Edge Reef', box({latitude: B.latitude, longitude: B.longitude + 30 / mLon(B.latitude)}, 30)]]))), 'Route crosses or touches Edge Reef.', 'an area that only touches the place');
  // Several areas: the shared verdict names the nearest, a crossing over a near one.
  assert.equal(runRouteScreen(west, water, screenOf([off(60, 'Far Reef'), off(20, 'Near Reef')])).name, 'Near Reef');
  assert.equal(runRouteScreen(west, water, screenOf([off(20, 'Near Reef'), ['Over Reef', box(mid(A, B), 30)]])).name, 'Over Reef');
  // Rendered: an area with no name, markup in a name, and a clear line (no note, nothing said about being allowed).
  const {lw, r, detour} = await headland(), area = detour[1];
  assert.equal((await noted(loaded(screenOf([[null, area]])), lw, r)).note, 'Route crosses or touches a protected area.');
  const markup = await noted(loaded(screenOf([['<b>Cove &</b>', area]])), lw, r);
  assert.ok(markup.html.includes('Route crosses or touches &lt;b>Cove &amp;&lt;/b>.') && !markup.html.includes('<b>Cove'), 'the name is text, never markup');
  const clear = await noted(loaded(screenOf([['Far Reef', box({latitude: 35.9, longitude: -120.2}, 80)]])), lw, r);
  assert.equal(clear.note, null);
  assert.doesNotMatch(clear.html.replace(/<details.*<\/details>/s, ''), /app-run-protected|clear of|safe|allowed|permitted|legal/i, 'outside the method popover the line says nothing about being clear or allowed');
}));

test('run_line_fallback_and_bad_geometry: every route failure screens its straight line; a line that cannot be drawn is not checked, never clear', async () => {
  const bends = [{latitude: 35.31, longitude: -120.88}, {latitude: 35.31, longitude: -120.82}], at = B;
  const onChord = screenOf([['Chord Banks', box(mid(A, B), 80)]]), onBends = screenOf([['Top Reef', box(mid(bends[0], bends[1]), 80)]]);
  for (const why of [undefined, 'no-product', 'lines-needed', 'start-not-water', 'end-not-water', 'no-route', 'too-far']) {
    assert.equal(runRouteScreen(A, straightPick(at, 'a', why), onChord).name, 'Chord Banks', `${why}: the labelled straight line is screened`);
    assert.ok(isClear(runRouteScreen(A, {...straightPick(at, 'a', why), routePoints: bends}, onBends)), `${why}: a fallback line ignores bends it was never routed along`);
  }
  const UNCHECKED = {inside: false, name: null, distanceM: null, screened: false};
  const water = (points) => waterPick(at, points);
  const bad = [['missing', undefined], ['null', null], ['not an array', {length: 2}], ['NaN', [{latitude: NaN, longitude: -120.85}]], ['Infinity', [{latitude: 35.31, longitude: Infinity}]],
    ['latitude 91', [{latitude: 91, longitude: -120.85}]], ['longitude -181', [{latitude: 35.31, longitude: -181}]], ['null point', [bends[0], null, bends[1]]],
    ['text coordinate', [{latitude: '35.31', longitude: -120.85}]], ['missing field', [{latitude: 35.31}]]];
  for (const [label, points] of bad) assert.deepEqual(runRouteScreen(A, water(points), onChord), UNCHECKED, `${label}: the chord must not stand in for a detour it cannot see`);
  for (const origin of [null, undefined, {latitude: NaN, longitude: -120.9}, {latitude: 35.3, longitude: 181}, {latitude: 35.3}]) assert.deepEqual(runRouteScreen(origin, water(bends), onChord), UNCHECKED, JSON.stringify(origin));
  assert.deepEqual(runRouteScreen(A, null, onChord), UNCHECKED, 'no pick');
  assert.deepEqual(runRouteScreen(A, {...water(bends), at: undefined}, onChord), UNCHECKED, 'no place');
  assert.deepEqual(runRouteScreen(A, {...water(bends), at: {latitude: 95, longitude: 0}}, onChord), UNCHECKED, 'a place off the globe');
  assert.deepEqual(runRouteScreen(A, straightPick({latitude: NaN, longitude: 0}), onChord), UNCHECKED);
  // A route with no bends is still a line: harbor to place.
  assert.equal(runRouteScreen(A, water([]), onChord).name, 'Chord Banks', 'an explicitly empty bend list screens its end-to-end line');
  assert.equal(runRouteScreen(A, water(undefined), onChord).screened, false, 'no property is not an empty list');
});

test('run_line_screen_lifecycle_and_coverage: a screen that is not loaded, current, for this region and covering the line is "not checked"; a refresh updates the note', async () => guarded(async m => {
  const {lw, r, detour} = await headland(), ok = screenOf([detour]), NOTE = 'Route: protected areas not checked.', HIT = 'Route crosses or touches Detour Sound.';
  // What the run reads from the shared signal.
  for (const value of [{state: 'idle'}, {state: 'loading'}, {state: 'failed'}]) assert.equal(m.runScreenFor(value, 'fixture'), null, value.state);
  assert.equal(m.runScreenFor(loaded(ok, 'elsewhere'), 'fixture'), null, 'another region\'s screen');
  assert.equal(m.runScreenFor(loaded(ok), null), null, 'no region');
  assert.equal(m.runScreenFor(loaded(screenOf([], {ready: () => false})), 'fixture'), null, 'a screen that is not current (stale or expired)');
  assert.equal(m.runScreenFor(loaded(screenOf([], {ready: () => { throw new Error('boom'); }})), 'fixture'), null, 'a screen that throws');
  assert.equal(m.runScreenFor(loaded(ok), 'fixture'), ok);
  // What the screen itself cannot say.
  const bends = [{latitude: 35.31, longitude: -120.88}, {latitude: 35.31, longitude: -120.82}], water = waterPick(B, bends);
  for (const [label, patch] of [['partial coverage', {coversGeometry: () => false}], ['coverage that throws', {coversGeometry: () => { throw new Error('boom'); }}],
    ['closures that throw', {exportExclusions: () => { throw new Error('boom'); }}], ['no closures', {exportExclusions: () => null}]]) {
    assert.equal(runRouteScreen(A, water, screenOf([detour], patch)).screened, false, label);
    assert.equal(runRouteScreen(A, straightPick(B), screenOf([detour], patch)).screened, false, `${label}, straight line`);
  }
  assert.equal(runRouteScreen(A, water, null).screened, false);
  assert.equal(runRouteScreen(A, water, {}).screened, false);
  assert.equal(runRouteScreen(A, water, 'screen').screened, false);
  // Rendered, one signal after another.
  for (const [label, value] of [['idle', {state: 'idle'}], ['loading', {state: 'loading'}], ['failed', {state: 'failed'}], ['wrong region', loaded(ok, 'elsewhere')],
    ['not current', loaded(screenOf([detour], {ready: () => false}))], ['partial coverage', loaded(screenOf([detour], {coversGeometry: () => false}))],
    ['throwing', loaded(screenOf([detour], {ready: () => { throw new Error('boom'); }}))]]) assert.equal((await noted(value, lw, r)).note, NOTE, label);
  assert.equal((await noted(loaded(ok), lw, r)).note, HIT);
  // A refresh (`skippercast:boundaries`) re-renders the line, which reads the screen as it is now.
  let current = true, areas = [detour];
  const live = screenOf([], {ready: () => current, exportExclusions: () => ({features: areas.map(([name, geometry]) => ({properties: {NAME: name}, geometry}))})});
  assert.equal((await noted(loaded(live), lw, r)).note, HIT);
  current = false;
  assert.equal((await noted(loaded(live), lw, r)).note, NOTE, 'the screen went unavailable: the old name is gone, not kept');
  current = true; areas = [];
  assert.equal((await noted(loaded(live), lw, r)).note, null, 'refreshed without the area: no note');
  areas = [detour];
  // A late answer for the region left behind does not clear (or name anything on) the current run; the current region's does.
  assert.equal((await noted(loaded(ok, 'elsewhere'), lw, r)).note, NOTE);
  assert.equal((await noted(loaded(ok, 'fixture'), lw, r)).note, HIT);
  // The boundary listener: added once, removed with the stop, nothing without a document, no timer.
  const added = [], removed = [], doc = {addEventListener: (type, fn) => added.push([type, fn]), removeEventListener: (type, fn) => removed.push([type, fn])};
  let bumps = 0;
  const stop = m.watchBoundaries(() => { bumps++; }, doc);
  assert.equal(added.length, 1);
  assert.equal(added[0][0], 'skippercast:boundaries');
  added[0][1](); added[0][1]();
  assert.equal(bumps, 2, 'each refresh calls back');
  assert.equal(removed.length, 0);
  stop();
  assert.ok(removed.length === 1 && removed[0][0] === 'skippercast:boundaries' && removed[0][1] === added[0][1], 'the same listener, removed on unmount');
  assert.equal(typeof document, 'undefined', 'this test runs with no document');
  assert.doesNotThrow(() => m.watchBoundaries(() => {})(), 'server rendering has no document and needs none');
}));

test('run_line_selected_pick_and_no_side_effects: the note belongs to the timed pick; no list, time or route search changes; inactive states say nothing', async () => guarded(async m => {
  const a = pick(AWAY, undefined, 'a'), b = pick(WEST[0], undefined, 'b'), reef = {...pick(WEST[1], undefined, 'r1'), kind: 'reef'};
  const two = rank(AWAY, {picks: [a, b, reef]}), lw = state(HEADLAND);
  await prepare(two, lw);
  const picks = await listed(two, lw), [pa, pb, pr] = picks;
  assert.deepEqual(picks.map(p => p.id), ['a', 'b', 'r1']);
  assert.ok([pa, pb, pr].every(p => p.basis === 'water' && Array.isArray(p.routePoints)));
  // An area 40 m either side of the middle of a pick's own route (a segment of [harbor, ...bends, place]).
  const onRoute = (name, p, halfM) => { const path = [HARBOR, ...p.routePoints, p.at], i = Math.floor((path.length - 2) / 2); return [name, box(mid(path[i], path[i + 1]), halfM)]; };
  const detour = onRoute('Detour Sound', pa, 60), nearB = onRoute('Near Reef', pb, 40), nearR = onRoute('Reef Cove', pr, 40);
  const hit = (pick, area) => { const v = runRouteScreen(HARBOR, pick, screenOf([area])); return v.screened && !isClear(v); };
  assert.ok(hit(pa, detour) && hit(pb, nearB) && hit(pr, nearR), 'each area is on its own pick\'s route');
  assert.ok(!hit(pb, detour) && !hit(pa, nearB) && !hit(pa, nearR) && !hit(pb, nearR) && !hit(pr, nearB), 'and on no other pick\'s');
  const note = async (areas, ...args) => (await noted(loaded(screenOf(areas)), lw, two, ...args)).note;
  const calls = m.routeCalls, before = JSON.stringify(await listed(two, lw));
  assert.equal(await note([detour, nearB, nearR]), 'Route crosses or touches Detour Sound.', 'the top pick\'s route, not the nearest area');
  assert.equal(await note([nearB]), null, 'the top pick is not on the area that sits on another pick\'s route');
  assert.equal(await note([detour, nearB, nearR], 20, 'b'), 'Route crosses or touches Near Reef.', 'a selected listed spot is the pick timed');
  assert.equal(await note([detour], 20, 'b'), null, 'and the top pick\'s route is not read for it');
  assert.match((await noted(loaded(screenOf([nearB])), lw, two, 20, 'b')).html, /Up to [^<]* fishing at Reef b\./);
  const dropped = await noted(loaded(screenOf([detour, nearB])), lw, two, 20, 'gone');
  assert.equal(dropped.note, 'Route crosses or touches Detour Sound.', 'a selection the list does not hold falls back to the top pick\'s route');
  assert.match(dropped.html, /outside the ranked list, so times are for the top pick/);
  const mismatch = await noted(loaded(screenOf([nearR, detour])), lw, two, 20, null, 'r1');
  assert.equal(mismatch.note, 'Route crosses or touches Detour Sound.', 'a reef id never selects as a habitat: the top pick\'s route');
  assert.equal(await note([nearR], 20, null, 'r1'), null);
  // Still a planning line: the no-time state shows it; nothing else about the run moved.
  const slow = await noted(loaded(screenOf([detour])), lw, two, 2);
  assert.match(slow.html, /data-state="no-time"/);
  assert.equal(slow.note, 'Route crosses or touches Detour Sound.');
  assert.equal(JSON.stringify(await listed(two, lw)), before, 'the list is as it was');
  assert.equal(m.routeCalls, calls, 'repeated renders and every screen change searched no route');
  // Inactive states and other profiles: no note, and (fetch refused above) no request.
  const over = {...brief, windows: [{...WINDOW, start: '2026-10-12T08:00:00.000Z', end: '2026-10-12T09:00:00.000Z'}]};
  m.protectedScreen.value = loaded(screenOf([detour]));
  for (const [label, html] of [['no speed', await line(lw, two, null)], ['no window', await line(lw, two, 20, null, null, {...brief, windows: []})], ['over', await line(lw, two, 20, null, null, over)],
    ['no place', await line(lw, {...two, picks: []})], ['no harbor position', await line(lw, {...two, origin: undefined, picks: [{...a, nm: null}]})]]) {
    assert.doesNotMatch(html, /app-run-protected|protected area/, label);
  }
  assert.match(await line(lw, two, 20, null, null, over), /data-state="over"/);
  for (const other of ['kayak', 'shore', 'spear']) {
    m.profile.value = other;
    assert.equal(m.render(m.h(m.RunLine, {brief: {...brief, profile: other}, ranking: two, now: NOW})), '', other);
  }
  m.profile.value = 'boat';
  assert.equal(m.routeCalls, calls);
  // The basis says what the screen is and is not.
  const basis = m.runBasis('Morro Bay');
  assert.match(basis, /screened against the loaded protected-area boundaries, including a 70 m planning margin/);
  assert.match(basis, /does not determine whether transit or fishing is allowed; check the official rules/);
  assert.match(basis, /not a navigation route/);
}));
