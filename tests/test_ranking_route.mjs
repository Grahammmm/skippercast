// SC1322-10: a Boat pick's distance, run time and the range to consider use the water route (web/route.ts, FSC-04)
// where one is computed (web/ranking.ts `routedPicks`, web/brief/WhereToLook.tsx `boatPicks`); the straight line stays
// only as the labelled fallback, and the ranking order and the other profiles are unchanged. SC2207-05: Kayak does the
// same from its chosen launch (distance, range, reason beside a straight line), without run times; Shore and Spear stay
// un-routed. A fake `route` is injected
// for the counts; the rendered "by water" case uses the synthetic open-water product of tests/test_run_route.mjs.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {distanceNm} from '../dist/spot-ranking.js';
import {assessScreen} from '../web/map/habitat.ts';
import {ROUTE_BUDGET, TOP, ranking, routedPicks} from '../web/ranking.ts';
import {runMinutes, durationText} from '../web/brief/run.ts';
import {landWaterModel} from '../web/land-water.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MORRO = read('regions/morro-bay/region.json'), NOW = Date.now();
const DATA = {region: {...MORRO, id: 'morro-bay'}, atlas: read('data/atlas.json'), survey: null, geology: null};
const CHECKED = assessScreen({areas: read('data/protected-areas.geojson').features, checkedAt: new Date(NOW).toISOString(), live: true}, NOW);
const WATER = () => ({state: 'water'});
const inputs = (patch = {}) => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: CHECKED, terrain: {state: 'unavailable'}, now: NOW, place: WATER, ...patch});

const ORIGIN = {latitude: 35.37, longitude: -120.86};
/** A pick `nm` straight-line nm due north of ORIGIN. */
const at = nm => ({latitude: ORIGIN.latitude + nm / 60, longitude: ORIGIN.longitude});
const pick = (id, nm) => ({id, kind: 'spot', name: `Reef ${id}`, distance: `${nm.toFixed(1)} nm`, nm: distanceNm(ORIGIN, at(nm)), at: at(nm), depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.', screen: {inside: false, name: null, distanceM: null, screened: true}});
/** A fake route: `answer(to)` per call, every call recorded. */
const fake = answer => { const calls = []; const route = (model, lines, from, to) => { calls.push({model, lines, from, to}); return answer(to); }; return {route, calls}; };
const times = k => fake(to => ({ok: true, nm: distanceNm(ORIGIN, to) * k, points: []}));
const MODEL = {id: 'fixture-model'};

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'ranking-route-')), 'where.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {WhereToLook, boatPicks, currentRanking, pickRun, routeAfterPaint, routeWhyText} from './web/brief/WhereToLook.tsx';
      export {launchPoints} from './web/launches.ts';
      export {launchChoice} from './web/reach.ts';
      export {markData, markScreen} from './web/map/marks.ts';
      export {cruiseSpeed} from './web/limits.ts';
      export {reachRange} from './web/reach.ts';
      export {landWater} from './web/land-water.ts';
      export {profile, region, species} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  mod = await import(pathToFileURL(out).href);
  return mod;
}

test('a route at 1.4 × the straight line: the pick nm and run time use the route, basis water, "by water"', async () => {
  const {route, calls} = times(1.4), p = pick('a', 8), [got] = routedPicks([p], ORIGIN, MODEL, null, null, TOP, route);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].model, MODEL);
  assert.equal(got.basis, 'water');
  assert.ok(Math.abs(got.nm - p.nm * 1.4) < 1e-9, `${got.nm} vs ${p.nm}`);
  assert.equal(got.distance, `${(p.nm * 1.4).toFixed(1)} nm by water`);
  const {pickRun} = await load();
  assert.equal(pickRun(got.nm, 20, got.basis), ` · run ${durationText(runMinutes(p.nm * 1.4, 20))}`);
  assert.equal(pickRun(p.nm, 20, 'straight'), ` · run ≥ ${durationText(runMinutes(p.nm, 20))}`, 'the straight line stays a lower bound');
  assert.notEqual(pickRun(got.nm, 20, 'water'), pickRun(p.nm, 20, 'water'), 'the run time follows the route nm');
});

test('the range keeps a place by its water distance; one outside it by straight line is never routed', () => {
  // Straight 9 nm, route 13 nm, range 12: dropped, and the next pick fills its place.
  const long = fake(to => ({ok: true, nm: Math.abs(to.latitude - at(9).latitude) < 1e-9 ? 13 : distanceNm(ORIGIN, to), points: []}));
  const picks = [pick('a', 9), pick('b', 5), pick('c', 6), pick('d', 7), pick('e', 8)];
  const got = routedPicks(picks, ORIGIN, MODEL, null, 12, TOP, long.route);
  assert.deepEqual(got.map(p => p.id), ['b', 'c', 'd', 'e']);
  assert.ok(got.every(p => p.basis === 'water'));
  // A route at exactly the range is kept.
  assert.equal(routedPicks([pick('a', 9)], ORIGIN, MODEL, null, 12, TOP, fake(() => ({ok: true, nm: 12, points: []})).route).length, 1);
  // Straight 13 nm, range 12: dropped without a route.
  const never = times(1);
  assert.deepEqual(routedPicks([pick('far', 13)], ORIGIN, MODEL, null, 12, TOP, never.route), []);
  assert.equal(never.calls.length, 0);
});

test('every FSC-04 failure keeps the straight line, labelled with why, and is kept or dropped by it', () => {
  for (const reason of ['no-product', 'lines-needed', 'start-not-water', 'end-not-water', 'no-route', 'too-far']) {
    const {route} = fake(() => ({ok: false, reason}));
    const [kept, ...rest] = routedPicks([pick('a', 9), pick('far', 13)], ORIGIN, MODEL, null, 12, TOP, route);
    assert.equal(rest.length, 0, `${reason}: 13 nm straight line is outside 12`);
    assert.equal(kept.basis, 'straight', reason);
    assert.equal(kept.why, reason);
    assert.equal(kept.nm, pick('a', 9).nm, reason);
    assert.equal(kept.distance, `${pick('a', 9).nm.toFixed(1)} nm straight line`, reason);
  }
  // Without an origin nothing is routed and the straight line is labelled; without a distance the dash stays.
  const none = times(1), [unrouted, dash] = routedPicks([pick('a', 3), {...pick('b', 4), nm: null, distance: '—'}], undefined, MODEL, null, null, TOP, none.route);
  assert.equal(none.calls.length, 0);
  assert.equal(unrouted.distance, `${pick('a', 3).nm.toFixed(1)} nm straight line`);
  assert.equal(dash.distance, '—');
});

test('40 candidates: at most ROUTE_BUDGET routes; picks past it keep the straight line', () => {
  const picks = Array.from({length: 40}, (_, i) => pick(`p${i}`, 1 + i * 0.25));
  const all = times(20), got = routedPicks(picks, ORIGIN, MODEL, null, 12, TOP, all.route);
  assert.equal(all.calls.length, ROUTE_BUDGET, 'every route runs past the range, so the budget is spent');
  assert.ok(got.length <= TOP && got.every(p => p.basis === 'straight' && p.why === undefined), JSON.stringify(got.map(p => p.id)));
  assert.equal(got[0].id, `p${ROUTE_BUDGET}`, 'the first pick past the budget keeps its straight line');
  const ok = times(1);
  assert.equal(routedPicks(picks, ORIGIN, MODEL, null, null, TOP, ok.route).length, TOP);
  assert.equal(ok.calls.length, TOP, 'it stops once the list is full');
});

test('the brief memoises each route and never uses another region\'s product', async () => {
  const {boatPicks} = await load();
  const r = {source: 'atlas', label: 'Survey reef atlas', basis: '', empty: '', harbor: 'Fixture Harbor', origin: ORIGIN, picks: [pick('a', 3), pick('b', 4)]};
  const lw = {region: 'fixture', state: 'ready', model: MODEL, lines: null, linesLoading: false}, f = times(1.2);
  const first = boatPicks(r, lw, 'fixture', f.route);
  assert.equal(f.calls.length, 2);
  const again = boatPicks({...r, picks: [...r.picks]}, lw, 'fixture', f.route);
  assert.equal(f.calls.length, 2, 'a re-render with the same inputs routes nothing again');
  assert.ok(isDeepStrictEqual(first, again));
  boatPicks(r, {...lw, lines: false}, 'fixture', f.route);
  assert.equal(f.calls.length, 4, 'a new lines answer routes again');
  const other = times(1.2), got = boatPicks(r, {...lw, region: 'elsewhere'}, 'fixture', other.route);
  assert.ok(other.calls.length === 2 && other.calls.every(c => c.model === null), 'another region\'s model is never used');
  assert.ok(got.every(p => p.basis === 'straight' || p.basis === 'water'));
});

test('the brief paints from memoised routes only, then routes the rest after the paint', async () => {
  const {boatPicks, routeAfterPaint} = await load();
  const r = {source: 'atlas', label: 'Survey reef atlas', basis: '', empty: '', harbor: 'Fixture Harbor', origin: ORIGIN, picks: [pick('a', 3), pick('b', 4), pick('c', 5)]};
  const lw = {region: 'paint', state: 'ready', model: {id: 'paint-model'}, lines: null, linesLoading: false}, f = times(1.3);
  const left = {n: 0}, painted = boatPicks(r, lw, 'paint', f.route, 0, left);
  assert.equal(f.calls.length, 0, 'the paint computes no route');
  assert.equal(left.n, 3);
  assert.ok(painted.every(p => p.basis === 'straight' && p.why === undefined && p.distance.endsWith('straight line')), JSON.stringify(painted));
  let done = 0;
  routeAfterPaint(r, lw, 'paint', f.route, () => { done++; });
  assert.equal(f.calls.length, 0, 'routing waits for a later task');
  for (let i = 0; i < 20 && !done; i++) await new Promise(res => setTimeout(res, 0));
  assert.equal(done, 1);
  assert.equal(f.calls.length, 3, 'one route per pick, each once');
  const after = {n: 0}, routed = boatPicks(r, lw, 'paint', f.route, 0, after);
  assert.ok(after.n === 0 && routed.every(p => p.basis === 'water'), JSON.stringify(routed));
  const cancel = routeAfterPaint({...r, picks: [pick('d', 6)]}, lw, 'paint', f.route, () => { done++; });
  cancel();
  await new Promise(res => setTimeout(res, 5));
  assert.ok(done === 1 && f.calls.length === 3, 'a cancelled run routes nothing');
});

test('the Boat list renders by water on an open-water product; the range title says so; Shore and Spear are unchanged', async () => {
  const m = await load();
  const G = 32, N = 4096, cell = (col, row) => ({latitude: Math.atan(Math.sinh(Math.PI * (1 - 2 * (1616 + (row + 0.5) / G) / N))) * 180 / Math.PI, longitude: (671 + (col + 0.5) / G) / N * 360 - 180});
  const coast = JSON.parse(readFileSync(new URL('./fixtures/land-water/coast.json', import.meta.url), 'utf8'));
  const model = landWaterModel({...coast, bounds: [-12110000, 3530000, -12075000, 3555000], tiles: {'12/671/1616': `w${G * G}`}}, 'fixture');
  const from = cell(4, 8), to = cell(28, 8), straight = distanceNm(from, to);
  const r = {source: 'atlas', label: 'Survey reef atlas', basis: 'b', empty: '', harbor: 'Fixture Harbor', origin: from, reach: 30,
    picks: [{id: 'a', kind: 'spot', name: 'Reef a', distance: `${straight.toFixed(1)} nm`, nm: straight, at: to, depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.', screen: {inside: false, name: null, distanceM: null, screened: true}}]};
  m.region.value = 'fixture'; m.profile.value = 'boat'; m.cruiseSpeed.value = 20; m.reachRange.value = {boat: 30};
  m.landWater.value = {region: 'fixture', state: 'ready', model, lines: null, linesLoading: false};
  const [routed] = m.boatPicks(r);
  assert.equal(routed.basis, 'water');
  const html = m.render(m.h(m.WhereToLook, {ranking: r}));
  assert.match(html, new RegExp(`${routed.nm.toFixed(1)} nm by water · ~60–90 ft · run ${durationText(runMinutes(routed.nm, 20))}<`));
  assert.match(html, /title="Range to consider: 30 nm by water where routed, else straight line, from Fixture Harbor"/);
  m.landWater.value = {region: null, state: 'idle', model: null, lines: null, linesLoading: false};
  assert.match(m.render(m.h(m.WhereToLook, {ranking: r})), new RegExp(`${straight.toFixed(1)} nm straight line · ~60–90 ft · run ≥ `), 'no product: the labelled straight line');
  // The ranking's order is unchanged: a longer Boat candidate list starts with the same picks.
  const base = ranking(inputs()), more = ranking(inputs({top: ROUTE_BUDGET}));
  assert.ok(base.picks.length === TOP && more.picks.length > TOP && isDeepStrictEqual(more.picks.slice(0, TOP), base.picks));
  for (const profile of ['spear', 'shore']) {
    const given = ranking(inputs({profile})), shown = given.picks.length ? given : {...given, picks: base.picks};
    assert.ok(isDeepStrictEqual(ranking(inputs({profile})), given), `${profile}: ranking() is unchanged`);
    m.profile.value = profile; m.landWater.value = {region: 'fixture', state: 'ready', model, lines: null, linesLoading: false};
    const out = m.render(m.h(m.WhereToLook, {ranking: shown}));
    assert.doesNotMatch(out, /by water|nm straight line|run ≥/, profile);
    for (const p of shown.picks) assert.ok(out.includes(`${p.distance} · ${p.depth}</span>`), `${profile} ${p.id}`);
  }
  m.profile.value = 'boat'; m.region.value = null; m.cruiseSpeed.value = null; m.reachRange.value = {};
  m.landWater.value = {region: null, state: 'idle', model: null, lines: null, linesLoading: false};
});

// ---- SC2207-05: Kayak from its chosen launch -------------------------------------------------------------------------

// A target the reef publication does not gate, so currentRanking reads the atlas this test supplies.
const GRID = 32, N4 = 4096, TARGET = 'cabezon-shallow-reef';
const tileCell = (col, row) => ({latitude: Math.atan(Math.sinh(Math.PI * (1 - 2 * (1616 + (row + 0.5) / GRID) / N4))) * 180 / Math.PI, longitude: (671 + (col + 0.5) / GRID) / N4 * 360 - 180});
const coastFixture = JSON.parse(readFileSync(new URL('./fixtures/land-water/coast.json', import.meta.url), 'utf8'));
/** An open-water product over the zoom-12 fixture tile, with an optional land block 'l' (rects: [col0, row0, col1, row1]). */
const waterProduct = (land = []) => {
  const a = Array.from({length: GRID * GRID}, () => 'w');
  for (const [c0, r0, c1, r1] of land) for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) a[r * GRID + c] = 'l';
  return landWaterModel({...coastFixture, bounds: [-12110000, 3530000, -12075000, 3555000], tiles: {'12/671/1616': a.join('').replace(/(.)\1*/g, m => m[0] + m.length)}}, 'fixture');
};
const READY = model => ({region: 'morro-bay', state: 'ready', model, lines: null, linesLoading: false});
const IDLE = {region: null, state: 'idle', model: null, lines: null, linesLoading: false};
const rankedFor = (m, patch = {}) => m.currentRanking(NOW, ROUTE_BUDGET, patch);
const kayakRank = (origin, picks, reach) => ({source: 'atlas', label: 'Survey reef atlas', basis: 'b', empty: '', harbor: origin?.name ?? 'Launch', origin, reach, picks});

test('Kayak: the water list takes the chosen launch as the route start, the range keeps water distance in ranking order, and equality stays', async () => {
  const m = await load(), launch = {latitude: ORIGIN.latitude, longitude: ORIGIN.longitude, name: 'Fixture Ramp'};
  // Straight 2 nm, water 4 nm, range 3 nm: dropped, and a fifth candidate fills the list; order of the rest is unchanged.
  const long = fake(to => ({ok: true, nm: Math.abs(to.latitude - at(2).latitude) < 1e-9 ? 4 : distanceNm(ORIGIN, to), points: []}));
  const picks = [pick('a', 2), pick('b', 1), pick('c', 1.2), pick('d', 1.4), pick('e', 1.6)];
  const lw = {region: 'k1', state: 'ready', model: {id: 'k1-model'}, lines: null, linesLoading: false};
  const got = m.boatPicks(kayakRank(launch, picks, 3), lw, 'k1', long.route);
  assert.deepEqual(got.map(p => p.id), ['b', 'c', 'd', 'e']);
  assert.ok(long.calls.every(c => c.from === launch), 'the route starts at the chosen launch');
  assert.ok(got.every(p => p.basis === 'water' && p.distance.endsWith('nm by water')));
  // A water route of exactly the range is inside it; a straight line outside the range is never routed.
  const exact = fake(() => ({ok: true, nm: 3, points: []}));
  assert.equal(m.boatPicks(kayakRank(launch, [pick('x', 2)], 3), lw, 'k2', exact.route).length, 1);
  const never = times(1);
  assert.deepEqual(m.boatPicks(kayakRank(launch, [pick('far', 3.5)], 3), lw, 'k3', never.route), []);
  assert.equal(never.calls.length, 0);
  // No saved range: no cutoff.
  assert.equal(m.boatPicks(kayakRank(launch, [pick('y', 8)], null), lw, 'k4', long.route).length, 1);
});

test('Kayak: each FSC-04 failure keeps the labelled straight line and names why beside it; a route not yet computed says so; Boat copy is unchanged', async () => {
  const m = await load();
  const why = {'no-product': 'no land/water data', 'lines-needed': 'shoreline still loading', 'start-not-water': 'launch/origin not on confirmed water',
    'end-not-water': 'place not on confirmed water', 'no-route': 'no water path found', 'too-far': 'route search limit reached'};
  for (const [reason, text] of Object.entries(why)) {
    const {route} = fake(() => ({ok: false, reason})), [got] = m.boatPicks(kayakRank(ORIGIN, [pick('a', 3)], null), {region: `w-${reason}`, state: 'ready', model: MODEL, lines: null, linesLoading: false}, `w-${reason}`, route);
    assert.equal(got.why, reason);
    assert.equal(got.distance, `${pick('a', 3).nm.toFixed(1)} nm straight line`, reason);
    assert.equal(m.routeWhyText(got), text, reason);
  }
  assert.equal(m.routeWhyText({...pick('a', 3), basis: 'straight'}), 'water route not computed');
  assert.equal(m.routeWhyText({...pick('a', 3), basis: 'water'}), null, 'a routed pick needs no reason');
  assert.equal(m.routeWhyText({...pick('a', 3), nm: null, distance: '—', basis: 'straight'}), null, 'no distance: the dash, no reason');
  // Rendered through the real route: no product, a launch off the water, a place off the water, a route not yet computed, a routed pick.
  m.region.value = 'fixture'; m.profile.value = 'kayak'; m.cruiseSpeed.value = 20; m.reachRange.value = {kayak: 10};
  const model = waterProduct(), from = tileCell(4, 8), to = tileCell(28, 8), onWater = {...from, name: 'Fixture Ramp'};
  const render = r => m.render(m.h(m.WhereToLook, {ranking: r}));
  const near = distanceNm(from, to), mk = (origin, p = to) => kayakRank(origin, [{...pick('a', 1), at: p, nm: distanceNm(origin, p), distance: `${distanceNm(origin, p).toFixed(1)} nm`}], 10);
  try {
    m.landWater.value = {region: 'fixture', state: 'ready', model, lines: null, linesLoading: false};
    assert.match(render(mk(onWater)), /water route not computed/, 'nothing memoised yet: no invented failure');
    const [routed] = m.boatPicks(mk(onWater), m.landWater.value, 'fixture');
    assert.equal(routed.basis, 'water');
    assert.ok(routed.nm >= near - 1e-9, 'the water route is no shorter than the straight line');
    let html = render(mk(onWater));
    assert.match(html, new RegExp(`${routed.nm.toFixed(1)} nm by water · ~60–90 ft</span>`));
    assert.doesNotMatch(html, /route-why|water route not computed|run ≥|· run /, 'routed, and Kayak never gets Boat run text');
    // A launch 2 km inside land (beyond the 300 m snap): the labelled straight line and why; nothing is forced onto water.
    const inland = {...tileCell(2, 8), name: 'Far Ramp'};
    m.landWater.value = {region: 'fixture', state: 'ready', model: waterProduct([[0, 0, 8, 31]]), lines: null, linesLoading: false};
    m.boatPicks(mk(inland), m.landWater.value, 'fixture');
    html = render(mk(inland));
    assert.match(html, /nm straight line · ~60–90 ft<\/span><span class="app-pick-route-why" data-route-why="start-not-water"> · launch\/origin not on confirmed water</);
    const offshore = tileCell(28, 8);
    m.landWater.value = {region: 'fixture', state: 'ready', model: waterProduct([[24, 0, 31, 31]]), lines: null, linesLoading: false};
    m.boatPicks(mk(onWater, offshore), m.landWater.value, 'fixture');
    assert.match(render(mk(onWater, offshore)), /data-route-why="end-not-water"> · place not on confirmed water</);
    m.landWater.value = IDLE;
    m.boatPicks(mk(onWater), IDLE, 'fixture');
    html = render(mk(onWater));
    assert.match(html, /data-route-why="no-product"> · no land\/water data</);
    assert.doesNotMatch(html, /run ≥/);
    // Boat renders the same list exactly as before: its run text, no reason line.
    m.profile.value = 'boat';
    assert.doesNotMatch(render(mk(onWater)), /route-why/);
    assert.match(render(mk(onWater)), /nm straight line · ~60–90 ft · run ≥ /);
  } finally {
    m.profile.value = 'boat'; m.region.value = null; m.cruiseSpeed.value = null; m.reachRange.value = {};
    m.landWater.value = IDLE;
  }
});

test('Kayak: the range title says by water, the Boat run text stays off with a stored speed, and Shore and Spear render un-routed', async () => {
  const m = await load();
  const r = {...kayakRank(ORIGIN, [pick('a', 3)], 5), harbor: 'Fixture Ramp'};
  try {
    m.region.value = 'fixture'; m.cruiseSpeed.value = 20; m.reachRange.value = {kayak: 5};
    m.profile.value = 'kayak';
    const html = m.render(m.h(m.WhereToLook, {ranking: r}));
    assert.match(html, /title="Range to consider: 5 nm by water where routed, else straight line, from Fixture Ramp"/);
    assert.doesNotMatch(html, /· run /);
    for (const profile of ['shore', 'spear']) {
      m.profile.value = profile;
      const out = m.render(m.h(m.WhereToLook, {ranking: r}));
      assert.doesNotMatch(out, /route-why|by water|water route not computed/, profile);
      assert.match(out, /3\.0 nm · ~60–90 ft<\/span>/, `${profile}: the ranking's own distance`);
    }
  } finally {
    m.profile.value = 'boat'; m.region.value = null; m.cruiseSpeed.value = null; m.reachRange.value = {};
  }
});

test('Kayak: currentRanking starts from the chosen launch; a second launch, region, model or lines answer never reuses another route; the budget holds', async () => {
  const m = await load(), model = waterProduct([[10, 0, 21, 23]]);
  const rank = ranking(inputs({profile: 'kayak', target: TARGET, coast: TARGET, top: 40}));
  const ids = rank.picks.map(p => p.id).slice(0, 5);
  assert.ok(ids.length >= 5, `the fixture atlas ranks at least five Kayak places (${ids.length})`);
  const cols = [14, 18, 24, 26, 28], targets = ATLAS_TARGETS(ids, cols.map(c => tileCell(c, 8)));
  const LAUNCH_A = {id: 'ramp-a', name: 'Ramp A', kind: 'ramp', ...tileCell(4, 8)}, LAUNCH_B = {id: 'ramp-b', name: 'Ramp B', kind: 'ramp', ...tileCell(4, 28)};
  try {
    m.region.value = 'morro-bay'; m.profile.value = 'kayak'; m.species.value = TARGET; m.reachRange.value = {kayak: 10};
    m.markData.value = {...DATA, atlas: {...DATA.atlas, targets}}; m.markScreen.value = CHECKED;
    m.landWater.value = READY(model);
    m.launchPoints.value = {region: 'morro-bay', points: [LAUNCH_A, LAUNCH_B]};
    // No launch chosen, a launch no longer listed, and another region's list: no launch origin (the home/loading fallback).
    for (const [choice, list] of [[{}, null], [{'morro-bay': 'gone'}, null], [{'morro-bay': 'ramp-a'}, {region: 'elsewhere', points: [LAUNCH_A]}]]) {
      m.launchChoice.value = choice; if (list) m.launchPoints.value = list;
      const r0 = m.currentRanking(NOW);
      assert.notEqual(r0.harbor, 'Ramp A', JSON.stringify(choice));
      m.launchPoints.value = {region: 'morro-bay', points: [LAUNCH_A, LAUNCH_B]};
    }
    m.launchChoice.value = {'morro-bay': 'ramp-a'};
    const a = m.currentRanking(NOW, ROUTE_BUDGET);
    assert.equal(a.harbor, 'Ramp A');
    assert.ok(a.origin.latitude === LAUNCH_A.latitude && a.origin.longitude === LAUNCH_A.longitude, 'the ranking measures from the launch');
    const f = times(1), first = m.boatPicks(a, m.landWater.value, 'morro-bay', f.route);
    assert.ok(first.length > 0 && f.calls.every(c => c.from.latitude === LAUNCH_A.latitude && c.from.longitude === LAUNCH_A.longitude), 'every route starts at the chosen launch');
    const n = f.calls.length;
    m.boatPicks(a, m.landWater.value, 'morro-bay', f.route);
    assert.equal(f.calls.length, n, 'the same launch and inputs route nothing again');
    // A second launch has its own coordinates, so nothing of the first launch's routes is reused.
    m.launchChoice.value = {'morro-bay': 'ramp-b'};
    const b = m.currentRanking(NOW, ROUTE_BUDGET);
    assert.equal(b.harbor, 'Ramp B');
    m.boatPicks(b, m.landWater.value, 'morro-bay', f.route);
    assert.ok(f.calls.length > n && f.calls.slice(n).every(c => c.from.latitude === LAUNCH_B.latitude), 'the second launch routes afresh from itself');
    // A new region, model or lines answer starts afresh as well.
    const k = f.calls.length;
    m.boatPicks(b, READY(waterProduct()), 'morro-bay', f.route);
    assert.ok(f.calls.length > k, 'another model: routed again');
    const k2 = f.calls.length;
    m.boatPicks(b, {...READY(waterProduct()), lines: false}, 'morro-bay', f.route);
    assert.ok(f.calls.length > k2, 'another lines answer: routed again');
    // At most ROUTE_BUDGET routes per list, however many candidates.
    const many = Array.from({length: 40}, (_, i) => pick(`m${i}`, 1 + i * 0.05)), cap = times(30);
    m.boatPicks(kayakRank(ORIGIN, many, 3), {region: 'cap', state: 'ready', model: MODEL, lines: null, linesLoading: false}, 'cap', cap.route);
    assert.equal(cap.calls.length, ROUTE_BUDGET);
  } finally {
    m.profile.value = 'boat'; m.region.value = null; m.species.value = null; m.reachRange.value = {}; m.launchChoice.value = {}; m.launchPoints.value = null;
    m.markData.value = null; m.landWater.value = IDLE;
  }
});

test('Kayak: the page paints with no route computed, then routes one per task after the paint, and a second launch cancels the first', async () => {
  const m = await load();
  const mk = origin => kayakRank(origin, [pick('a', 1), pick('b', 1.5), pick('c', 2)], 10);
  const lw = {region: 'kp', state: 'ready', model: {id: 'kp-model'}, lines: null, linesLoading: false}, f = times(1.2);
  const left = {n: 0};
  const painted = m.boatPicks(mk(ORIGIN), lw, 'kp', f.route, 0, left);
  assert.equal(f.calls.length, 0, 'the first render computes zero routes');
  assert.ok(left.n === 3 && painted.every(p => p.basis === 'straight' && p.why === undefined));
  let done = 0, seen = 0;
  const cancel = m.routeAfterPaint(mk(ORIGIN), lw, 'kp', f.route, () => { done++; });
  const before = f.calls.length;
  await new Promise(res => setTimeout(res, 0));
  seen = f.calls.length;
  assert.ok(seen - before <= 1, 'one new route per task');
  for (let i = 0; i < 20 && !done; i++) await new Promise(res => setTimeout(res, 0));
  assert.equal(done, 1);
  assert.equal(f.calls.length, 3, 'each route once');
  cancel();
  // A cancelled run for another launch computes nothing.
  const other = {...ORIGIN, latitude: ORIGIN.latitude + 0.5}, c2 = m.routeAfterPaint(mk(other), lw, 'kp', f.route, () => { done++; });
  c2();
  await new Promise(res => setTimeout(res, 5));
  assert.ok(done === 1 && f.calls.length === 3, 'cancellation prevents obsolete work');
});

/** The real atlas's `ids` moved to `where`, so a synthetic water product can hold them. */
function ATLAS_TARGETS(ids, where) {
  return DATA.atlas.targets.filter(t => ids.includes(t.id)).map(t => ({...t, ...where[ids.indexOf(t.id)]}));
}
