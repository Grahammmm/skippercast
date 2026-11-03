// FSC-05: the Boat brief's run time, turn-back and fishing time take the water route (web/route.ts, FSC-04);
// the straight line stays only as a labelled fallback. Synthetic land-water products reuse the fixture of
// tests/test_route.mjs (zoom-12 tile 671/1616, 32×32 cells), so every case is offline.
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
import {planRun} from '../web/brief/run.ts';
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
const pick = (at, nm = distanceNm(HARBOR, at)) => ({id: 'a', kind: 'spot', name: 'Reef a', distance: `${nm} nm`, nm, at, depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.'});
const HARBOR = cell(4, 8), AWAY = cell(28, 8);
const rank = (at = AWAY, extra = {}) => ({source: 'atlas', label: 'Survey reef atlas', basis: '', picks: [pick(at)], empty: '', harbor: 'Fixture Harbor', origin: HARBOR, ...extra});
const HEADLAND = product([['l', 10, 0, 21, 23]]);

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'run-route-')), 'run.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {RunLine, runPlace, runText, runBasis} from './web/brief/Run.tsx';
      export {landWater, loadLandWaterLines} from './web/land-water.ts';
      export {cruiseSpeed} from './web/limits.ts';
      export {regionInfo} from './web/app/App.tsx';
      export {profile, region, selection, habitat} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  plugins: (await import('./helpers/esbuild-url.mjs')).rendererPlugins});
  mod = await import(pathToFileURL(out).href);
  return mod;
}
/** The rendered run line for a land-water state; the region is 'fixture'. */
async function line(lw, ranking = rank(), speed = 20) {
  const m = await load();
  m.regionInfo.value = {id: 'fixture', name: 'Fixture', center: [35.3, -120.9], timezone: TZ};
  m.profile.value = 'boat'; m.region.value = 'fixture'; m.selection.value = null; m.cruiseSpeed.value = speed; m.landWater.value = lw;
  return m.render(m.h(m.RunLine, {brief, ranking, now: NOW}));
}

test('a computed route: "by water" with the route nm, run time from it, less fishing time than the straight line', async () => {
  const {runPlace} = await load(), straight = distanceNm(HARBOR, AWAY), place = runPlace(rank(), null, null, state(HEADLAND), 'fixture');
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
  const {runPlace, runText} = await load(), straight = distanceNm(HARBOR, AWAY), walled = coastGrid([['l', 0, 22, 31, 22], ['m', 17, 22, 18, 22]]);
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
    const place = runPlace(r, null, null, lw, 'fixture');
    assert.equal(place.basis, 'straight', why);
    assert.equal(place.why, why);
    assert.equal(place.nm, r.picks[0].nm, `${why}: the pick's straight-line nm`);
    const html = await line(lw, r);
    assert.ok(html.includes(`${r.picks[0].nm.toFixed(1)} nm straight line (no water route: ${words[why]})`), `${why}: ${html.match(/app-run-detail[^<]*/)}`);
    assert.doesNotMatch(html, /nm by water/);
  }
  const base = planRun(brief, {name: 'Reef a', nm: straight}, 20, NOW), fall = planRun(brief, runPlace(rank(), null, null, IDLE, 'fixture'), 20, NOW);
  assert.deepEqual([fall.runMin, fall.depart, fall.turnBack, fall.fishMin], [base.runMin, base.depart, base.turnBack, base.fishMin], 'same nm, same times as before');
  const text = why => runText({...fall, kind: 'no-time', place: {name: 'Reef a', nm: 2, basis: 'straight', why}}, TZ).run;
  assert.match(text('too-far'), /2\.0 nm straight line \(no water route: too far to route\) · at least/);
  assert.match(text(undefined), /\(no water route: no land\/water data\)/, 'a place with no reason is still labelled');
});

test('lines-needed, then the lines load: the next render uses the route and nothing asks for the lines again', async () => {
  const m = await load(), walled = coastGrid([['l', 0, 22, 31, 22], ['m', 17, 22, 18, 22]]), r = rank(cell(14, 25), {origin: cell(14, 12)});
  assert.equal(m.runPlace(r, null, null, state(walled), 'fixture').why, 'lines-needed');
  assert.match(await line(state(walled), r), /straight line \(no water route: shoreline still loading\)/);
  const text = await readFile(new URL('./fixtures/land-water/coast.lines.json', import.meta.url), 'utf8');
  let asked = 0;
  const fetchFn = async () => { asked++; return {ok: true, text: async () => text}; };
  m.landWater.value = state(walled);
  await m.loadLandWaterLines('fixture', fetchFn);
  assert.equal(asked, 1);
  assert.equal(m.landWater.value.lines && typeof m.landWater.value.lines, 'object', 'the lines loaded');
  const html = await line(m.landWater.value, r);
  assert.match(html, /nm by water/);
  assert.doesNotMatch(html, /shoreline still loading/);
  await m.loadLandWaterLines('fixture', fetchFn);
  assert.equal(asked, 1, 'loaded lines are not requested a second time');
  assert.equal(m.runPlace(r, null, null, state(walled, false), 'fixture').why, 'no-route', 'failed lines do not read as still loading');
  assert.equal(m.runPlace(r, null, null, state(walled, null, 'other-region'), 'fixture').why, 'no-product', "another region's product is never used");
});

test('no harbor position: the lead is unchanged, no place and so no route; an unpositioned pick takes no route', async () => {
  const {runPlace} = await load(), none = rank(AWAY, {origin: undefined, harbor: undefined, picks: [{...pick(AWAY), nm: null}]});
  assert.equal(runPlace(none, null, null, state(HEADLAND), 'fixture'), null);
  assert.match(await line(state(HEADLAND), none), /No harbor position to measure from, so no run time\./);
  assert.equal(runPlace(rank(AWAY, {origin: undefined}), null, null, state(HEADLAND), 'fixture').why, 'no-product', 'a distance without an origin is the labelled line');
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
