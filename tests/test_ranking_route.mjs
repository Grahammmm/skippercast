// SC1322-10: a Boat pick's distance, run time and the range to consider use the water route (web/route.ts, FSC-04)
// where one is computed (web/ranking.ts `routedPicks`, web/brief/WhereToLook.tsx `boatPicks`); the straight line stays
// only as the labelled fallback, and the ranking order and the other profiles are unchanged. A fake `route` is injected
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
      export {WhereToLook, boatPicks, pickRun, routeAfterPaint} from './web/brief/WhereToLook.tsx';
      export {cruiseSpeed} from './web/limits.ts';
      export {reachRange} from './web/reach.ts';
      export {landWater} from './web/land-water.ts';
      export {profile, region} from './web/state.ts';
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

test('the Boat list renders by water on an open-water product; the range title says so; Shore and Kayak are unchanged', async () => {
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
  for (const profile of ['kayak', 'shore']) {
    const given = ranking(inputs({profile})), shown = given.picks.length ? given : {...given, picks: base.picks};
    assert.ok(isDeepStrictEqual(ranking(inputs({profile})), given), `${profile}: ranking() is unchanged`);
    m.profile.value = profile; m.landWater.value = {region: 'fixture', state: 'ready', model, lines: null, linesLoading: false};
    const out = m.render(m.h(m.WhereToLook, {ranking: shown}));
    assert.doesNotMatch(out, /by water|nm straight line|run ≥/, profile);
    for (const p of shown.picks) assert.ok(out.includes(`${p.distance} · ${p.depth}</span>`), `${profile} ${p.id}`);
    if (profile === 'kayak') assert.doesNotMatch(out, /by water where routed/);
  }
  m.profile.value = 'boat'; m.region.value = null; m.cruiseSpeed.value = null; m.reachRange.value = {};
  m.landWater.value = {region: null, state: 'idle', model: null, lines: null, linesLoading: false};
});
