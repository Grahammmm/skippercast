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
import {durationText, planRun} from '../web/brief/run.ts';
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
      export {RunLine, runPlace, runText, runBasis} from './web/brief/Run.tsx';
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
