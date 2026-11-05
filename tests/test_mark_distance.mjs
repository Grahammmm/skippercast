// SC1822-09: the selected-mark card says how far the mark is from the home port or launch, for Boat and Kayak: by water where a route is
// computed, else the labelled straight line, with the one-way run at the saved cruise speed, in Where to look's own words. One pair,
// searched once after the paint, within ROUTE_BUDGET; no bearing; Shore and Spear unchanged; no line without an origin. Synthetic data, no network.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {distanceNm} from '../dist/spot-ranking.js';
import {ROUTE_BUDGET} from '../web/ranking.ts';
import {durationText, runMinutes} from '../web/brief/run.ts';
import {MARK_ROUTE_ATTEMPTS, markDistance, markDistanceLine, routeAfterPaint, straightDistance, usablePoint} from '../web/mark-distance.ts';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'mark-distance-')), 'card.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MarkCard} from './web/app/MarkCard.tsx';
      export {pickRun} from './web/brief/WhereToLook.tsx';
      export {regionPorts, plannerPort} from './web/ports.ts';
      export {launchPoints} from './web/launches.ts';
      export {launchChoice} from './web/reach.ts';
      export {markData} from './web/map/marks.ts';
      export {cruiseSpeed} from './web/limits.ts';
      export {profile, region} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const ORIGIN = {latitude: 35.37, longitude: -120.86};
const north = nm => ({latitude: ORIGIN.latitude + nm / 60, longitude: ORIGIN.longitude});
const MODEL = {id: 'fixture-model'};
const fake = answer => { const calls = []; return {calls, route: (model, lines, from, to) => { calls.push({model, lines, from, to}); return answer(to); }}; };
const port = (id, name, at) => ({id, name, region: 'morro-bay', status: 'active', forecast_point: 'x', forecast_name: 'x', match: [at.latitude, at.longitude]});
const mark = (at, over = {}) => ({id: 'spot:SC26-001', name: 'Synthetic mark', kind: 'Reef mark', reading: 'A reading', source: 'Source', basis: 'Basis', ...(at ? {position: at} : {}), ...over});

test('mark_distance_routed_uses_water_nm_and_saved_speed: the route wins, with an upward-rounded run and no bound', () => {
  const to = north(6), chord = distanceNm(ORIGIN, to), f = fake(() => ({ok: true, nm: chord * 1.5, points: []}));
  const d = markDistance(ORIGIN, to, MODEL, null, f.route);
  assert.equal(d.basis, 'water'); assert.ok(Math.abs(d.nm - chord * 1.5) < 1e-9); assert.equal(f.calls.length, 1, 'one pair, one route');
  const line = markDistanceLine('Morro Bay', d, 20);
  assert.equal(line, `Morro Bay · ${d.nm.toFixed(1)} nm by water · run 30 min`);
  assert.ok(!line.includes('≥') && !line.includes('straight'));
  assert.ok(MARK_ROUTE_ATTEMPTS <= ROUTE_BUDGET);
});

test('mark_distance_straight_is_labelled_and_lower_bounded: no route and every failure keep the chord', () => {
  const to = north(10), chord = distanceNm(ORIGIN, to);
  for (const reason of ['no-product', 'lines-needed', 'start-not-water', 'end-not-water', 'no-route', 'too-far']) {
    const d = markDistance(ORIGIN, to, MODEL, null, fake(() => ({ok: false, reason})).route);
    assert.equal(d.basis, 'straight', reason); assert.equal(d.nm, chord); assert.equal(d.why, reason);
  }
  for (const bad of [null, {ok: true, nm: NaN, points: []}, {ok: true, nm: -1, points: []}]) assert.equal(markDistance(ORIGIN, to, MODEL, null, () => bad).basis, 'straight');
  const f = fake(() => ({ok: true, nm: 1, points: []}));
  assert.equal(markDistance(ORIGIN, to, null, null, f.route).basis, 'straight'); assert.equal(f.calls.length, 0, 'no product, no search');
  const line = markDistanceLine('Morro Bay', straightDistance(ORIGIN, to), 20);
  assert.equal(line, `Morro Bay · ${chord.toFixed(1)} nm straight line · run ≥ ${durationText(runMinutes(chord, 20))}`);
  assert.equal(markDistanceLine('P', {nm: 3, basis: 'straight'}, null), 'P · 3.0 nm straight line', 'no speed omits only the run');
  assert.equal(markDistanceLine('P', {nm: 3, basis: 'straight'}, 0), 'P · 3.0 nm straight line', 'an unusable speed omits the run');
  assert.equal(markDistanceLine('P', {nm: 0, basis: 'water'}, 10), 'P · 0.0 nm by water · run 5 min', 'zero keeps the minimum run');
  assert.equal(markDistanceLine('P', {nm: 3.25, basis: 'water'}, null, 'es'), 'P · 3,3 nm por agua');
});

test('mark_distance_shore_spear_withheld_and_invalid_targets: unusable coordinates give no distance and no search', () => {
  for (const bad of [null, undefined, {latitude: NaN, longitude: 0}, {latitude: 0, longitude: Infinity}, {latitude: 91, longitude: 0}, {latitude: 0, longitude: -181}, {latitude: '1', longitude: 2}])
    assert.equal(usablePoint(bad), false);
  const f = fake(() => ({ok: true, nm: 1, points: []}));
  assert.equal(markDistance(ORIGIN, {latitude: 95, longitude: 0}, MODEL, null, f.route), null);
  assert.equal(markDistance(null, north(1), MODEL, null, f.route), null);
  assert.equal(f.calls.length, 0);
});

test('mark_distance_one_pair_budget_and_stale_cleanup: nothing searched at paint, one search after it, none after a cancel', () => {
  const f = fake(() => ({ok: false, reason: 'no-route'})), tasks = [], got = [];
  const cancel = routeAfterPaint(ORIGIN, north(4), MODEL, null, d => got.push(d), f.route, fn => tasks.push(fn) - 1, () => {});
  assert.equal(f.calls.length, 0, 'no synchronous route'); assert.equal(tasks.length, 1);
  tasks[0](); tasks[0]();
  assert.equal(f.calls.length, 1); assert.equal(got.length, 1, 'delivered once'); assert.equal(got[0].why, 'no-route');
  const stale = []; const cancelled = routeAfterPaint(ORIGIN, north(4), MODEL, null, d => stale.push(d), f.route, fn => tasks.push(fn) - 1, () => {});
  cancelled(); tasks[1]();
  assert.equal(stale.length, 0, 'a cancelled search never paints'); assert.equal(f.calls.length, 1);
  cancel();
});

async function card(setup, m = mark(north(5))) {
  const k = await load();
  k.profile.value = 'boat'; k.region.value = 'morro-bay'; k.cruiseSpeed.value = 20;
  k.regionPorts.value = null; k.plannerPort.value = null; k.launchPoints.value = null; k.launchChoice.value = {}; k.markData.value = null;
  setup?.(k);
  return k.render(k.h(k.MarkCard, {mark: m}));
}
const LINE = /<p class="ui-mono" data-mark-distance="(water|straight)">([^<]*)<\/p>/;

test('mark_distance_origin_matches_where_to_look: planner port over first, Kayak launch over port, pending hidden, harbor only after a terminal failure', async () => {
  const ports = [port('a', 'First Port', ORIGIN), port('b', 'Second Port', north(1))];
  const ready = k => { k.regionPorts.value = {region: 'morro-bay', state: 'ready', list: ports}; };
  let html = await card(ready);
  const k = await load();
  assert.match(html, LINE); const m1 = html.match(LINE);
  assert.equal(m1[1], 'straight');
  assert.equal(m1[2], `First Port · ${distanceNm(ORIGIN, north(5)).toFixed(1)} nm straight line${k.pickRun(distanceNm(ORIGIN, north(5)), 20, 'straight')}`, 'the words and run are Where to look\'s own');
  html = await card(kk => { ready(kk); kk.plannerPort.value = {region: 'morro-bay', id: 'b'}; });
  assert.match(html.match(LINE)[2], /^Second Port · /, 'the planner\'s choice');
  html = await card(kk => { ready(kk); kk.plannerPort.value = {region: 'other', id: 'b'}; });
  assert.match(html.match(LINE)[2], /^First Port · /, 'another region\'s choice is ignored');
  html = await card(kk => {
    ready(kk); kk.profile.value = 'kayak';
    kk.launchPoints.value = {region: 'morro-bay', points: [{id: 'l1', name: 'Fixture Ramp', kind: 'ramp', latitude: 35.4, longitude: -120.9}]}; kk.launchChoice.value = {'morro-bay': 'l1'};
  });
  assert.match(html.match(LINE)[2], /^Fixture Ramp · /, 'Kayak\'s launch wins');
  html = await card(kk => { ready(kk); kk.profile.value = 'kayak'; kk.launchChoice.value = {'morro-bay': 'gone'}; });
  assert.match(html.match(LINE)[2], /^First Port · /, 'a retired launch falls back to the port');
  for (const [name, setup] of [['ports not loaded', null], ['ports loading', kk => { kk.regionPorts.value = {region: 'morro-bay', state: 'loading', list: []}; }],
    ['other region ports', kk => { kk.regionPorts.value = {region: 'other', state: 'ready', list: ports}; }],
    ['failed, harbor of another region', kk => { kk.regionPorts.value = {region: 'morro-bay', state: 'failed', list: []}; kk.markData.value = {region: {id: 'other', harbor: {name: 'Wrong', latitude: 1, longitude: 2}}}; }],
    ['no region', kk => { kk.region.value = null; kk.regionPorts.value = {region: 'morro-bay', state: 'ready', list: ports}; }]])
    assert.doesNotMatch(await card(setup), /data-mark-distance/, name);
  html = await card(kk => { kk.regionPorts.value = {region: 'morro-bay', state: 'failed', list: []}; kk.markData.value = {region: {id: 'morro-bay', harbor: {name: 'Fixture Harbor', latitude: ORIGIN.latitude, longitude: ORIGIN.longitude}}}; });
  assert.match(html.match(LINE)[2], /^Fixture Harbor · /, 'matching-region harbor after a terminal failure');
  html = await card(kk => { kk.regionPorts.value = {region: 'morro-bay', state: 'ready', list: []}; kk.markData.value = {region: {id: 'morro-bay', harbor: {name: 'Fixture Harbor', latitude: ORIGIN.latitude, longitude: ORIGIN.longitude}}}; });
  assert.match(html.match(LINE)[2], /^Fixture Harbor · /, 'an empty list too');
});

test('mark_distance_shore_spear_withheld_and_invalid_targets_are_unchanged: the card is as it was', async () => {
  const ready = k => { k.regionPorts.value = {region: 'morro-bay', state: 'ready', list: [port('a', 'First Port', ORIGIN)]}; };
  for (const p of ['shore', 'spear']) assert.doesNotMatch(await card(k => { ready(k); k.profile.value = p; }), /data-mark-distance|nm straight line/, p);
  assert.doesNotMatch(await card(ready, mark(north(5), {withheld: true})), /data-mark-distance/, 'a withheld mark');
  assert.doesNotMatch(await card(ready, mark(null)), /data-mark-distance/, 'no position');
  assert.doesNotMatch(await card(ready, mark({latitude: NaN, longitude: 0})), /data-mark-distance/, 'invalid position');
  assert.doesNotMatch(await card(ready, mark({latitude: 95, longitude: 0})), /data-mark-distance/, 'out-of-range position');
  assert.doesNotMatch(await card(ready, mark(north(5), {trip: 'not-drawn', position: undefined})), /data-mark-distance/, 'a trip mark that is not drawn');
  const html = await card(ready);
  assert.doesNotMatch(html.match(LINE)[2], /bearing|course|°|heading/i, 'no bearing or course');
});

test('mark_distance_never_enters_share_export_or_requests: display text only, no fetch while rendering', async () => {
  const saved = globalThis.fetch; let fetched = 0;
  globalThis.fetch = () => { fetched++; throw new Error('network'); };
  try { await card(k => { k.regionPorts.value = {region: 'morro-bay', state: 'ready', list: [port('a', 'First Port', ORIGIN)]}; }); } finally { globalThis.fetch = saved; }
  assert.equal(fetched, 0);
});
