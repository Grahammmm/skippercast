// BF-closures-everywhere: every output that names a place (ranked spot, leg, waypoint, GPX point, reach area, where-to-look row)
// passes the ONE protected-area screen (dist/geo-screen.js screenPlace) and carries its verdict. Unchecked is never "clear".
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {screenPlace, placeRefused, distanceM} from '../dist/geo-screen.js';
import * as ranking from '../web/ranking.ts';
import * as legs from '../web/trip-legs.ts';
import * as placement from '../web/waypoint-placement.ts';
import * as gpx from '../web/gpx-check.ts';
import {featuresGPX} from '../dist/gpx.js';
import * as reach from '../web/reach.ts';
import {assessScreen, CHECKING} from '../web/map/habitat.ts';

// A 0.02 x 0.02 degree reserve at 35.0 N; the fixture names it with markup on purpose.
const NAME = '<img src=x onerror=alert(1)> Reserve';
const BOX = {type: 'Polygon', coordinates: [[[-121.01, 34.99], [-120.99, 34.99], [-120.99, 35.01], [-121.01, 35.01], [-121.01, 34.99]]]};
const NOW = Date.now(), iso = new Date(NOW).toISOString();
const feature = {type: 'Feature', properties: {NAME, Type: 'SMR'}, geometry: BOX};
/** The planner's screen shape (protected-areas.js): fresh, or not loaded. */
const planner = (loaded = true) => ({ready: () => loaded, exportExclusions: () => loaded ? {checked_at: iso, features: [feature]} : null,
  pointAllowed: () => loaded, geometryAllowed: () => loaded});
const marks = assessScreen({areas: [feature], checkedAt: iso, live: true}, NOW);
const mLat = 1 / 111132.92, at = (lon, lat) => ({longitude: lon, latitude: lat});
const east = -120.99, mLon = 1 / (111412.84 * Math.cos(35 * Math.PI / 180));

test('a point on the polygon edge is inside; one 1 m outside is not inside but is refused by the planning margin', () => {
  const edge = screenPlace(planner(), at(east, 35));
  assert.equal(edge.inside, true); assert.equal(edge.distanceM, 0); assert.equal(edge.name, NAME); assert.equal(edge.screened, true);
  const near = screenPlace(planner(), at(east + 1 * mLon, 35));
  assert.equal(near.inside, false); assert.ok(near.distanceM > 0.5 && near.distanceM < 1.5, `distance ${near.distanceM}`);
  assert.ok(placeRefused(edge) && placeRefused(near));
  const far = screenPlace(planner(), at(east + 500 * mLon, 35));
  assert.equal(far.inside, false); assert.equal(placeRefused(far), false, 'well clear of the margin is not refused');
  assert.ok(Math.abs(distanceM(BOX, {type: 'Point', coordinates: [east + 200 * mLon, 35]}) - 200) < 1);
});

test('the same verdict from the marks screen (boundaries) as from the planner screen', () => {
  for (const p of [at(-121, 35), at(east + 1 * mLon, 35), at(east + 500 * mLon, 35)]) {
    const a = screenPlace(planner(), p), b = screenPlace(marks, p);
    assert.deepEqual(b, a);
  }
});

test('screen not loaded, not current, absent, or a region without a protected-areas file: screened false, never clear, refused', () => {
  const none = {inside: false, name: null, distanceM: null, screened: false};
  for (const s of [planner(false), CHECKING, null, undefined, {}, {status: 'unavailable', boundaries: []}, {ready: () => false, pointAllowed: () => true}]) {
    const v = screenPlace(s, at(-121, 35));
    assert.deepEqual(v, none); assert.ok(placeRefused(v));
  }
  assert.deepEqual(screenPlace(planner(), {}), none, 'a place with no coordinates cannot be cleared either');
});

test('a screen that only answers allowed or not: a no is inside, a yes is clear, both screened', () => {
  const s = {ready: () => true, pointAllowed: p => p.longitude > -120.9, geometryAllowed: () => true};
  assert.equal(screenPlace(s, at(-121, 35)).inside, true);
  const ok = screenPlace(s, at(-120.5, 35));
  assert.equal(ok.inside, false); assert.equal(ok.screened, true);
});

test('a leg whose endpoints are both outside but whose middle crosses the closure carries inside:true', () => {
  const stops = [{id: 'a', name: 'West', lat: 35, lon: -121.05}, {id: 'b', name: 'East', lat: 35, lon: -120.95}];
  const r = legs.tripLegs(null, [...stops, {id: 'c', name: 'Far', lat: 35.2, lon: -120.9}], 20, undefined, planner());
  assert.equal(r.legs[0].screen.inside, true); assert.equal(r.legs[0].screen.name, NAME);
  assert.equal(r.legs[1].screen.inside, false); assert.equal(r.legs[1].screen.screened, true);
  for (const leg of legs.tripLegs(null, stops, 20).legs) assert.equal(leg.screen.screened, false, 'no screen given: not checked');
});

test('water legs screen the routed polyline including endpoint connectors, not the straight chord', () => {
  const stops = [{id: 'a', name: 'West', lat: 35.05, lon: -121.05}, {id: 'b', name: 'East', lat: 35.05, lon: -120.95}];
  const route = points => () => ({ok: true, nm: 8, points: points.map(([longitude, latitude]) => ({longitude, latitude}))});
  const verdict = (choices, r) => legs.tripLegs(null, choices, 20, r, planner()).legs[0];
  const chord = verdict(stops, undefined);
  assert.equal(chord.screen.inside, false); assert.equal(chord.screen.screened, true);
  const crossing = verdict(stops, route([[-121.02, 35], [-120.98, 35]]));
  assert.equal(crossing.basis, 'water'); assert.equal(crossing.screen.inside, true); assert.equal(crossing.screen.name, NAME);
  const clear = verdict(stops, route([[-121, 35.1]]));
  assert.equal(clear.screen.inside, false); assert.equal(clear.screen.screened, true);
  const across = stops.map(p => ({...p, lat: 35}));
  assert.equal(verdict(across, route([[-121.05, 35.05], [-120.95, 35.05]])).screen.inside, false, 'a clear detour must not be screened as its blocked chord');
  assert.equal(verdict(across, route([[-120.98, 35]])).screen.inside, true, 'start connector crosses closure');
  assert.equal(verdict(across, route([[-121.02, 35]])).screen.inside, true, 'end connector crosses closure');
  assert.equal(verdict(across, () => ({ok: false, reason: 'no-route'})).screen.inside, true, 'failed routing screens the straight fallback');
});

test('a reach area that holds a closure whole is inside; the ring is still a plain ring of points', () => {
  const origin = at(-121, 35), ring = reach.reachRing(origin, 5, 128, planner());
  assert.equal(ring.screen.inside, true); assert.equal(ring.length, 129); assert.ok(Array.isArray(ring[0]));
  assert.equal(reach.reachRing(origin, 5).screen.screened, false);
  const away = reach.reachRing(at(-121, 36), 1, 64, planner());
  assert.equal(away.screen.inside, false); assert.equal(away.screen.screened, true);
});

test('a GPX with a point in the closure, near it, or an unloaded screen fails its check; structure-only without a screen', () => {
  const make = (...ps) => `<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">${ps.map(([name, lon, lat]) => `<wpt lat="${lat}" lon="${lon}"><name>${name}</name></wpt>`).join('')}</gpx>`;
  const inside = make(['In', -121, 35]), clear = make(['Out', -120.5, 35]), near = make(['Near', east + 20 * mLon, 35]);
  const want = {waypoints: 1};
  const bad = gpx.checkGpx(inside, want, planner());
  assert.equal(bad.ok, false); assert.match(bad.problems[0], /Inside or near/); assert.equal(bad.screen[0].inside, true);
  assert.equal(gpx.checkGpx(near, want, planner()).ok, false);
  assert.equal(gpx.checkGpx(clear, want, planner()).ok, true);
  for (const unloaded of [planner(false), null]) {
    const r = gpx.checkGpx(clear, want, unloaded);
    assert.equal(r.ok, false); assert.equal(r.problems[0], 'Protected areas not checked'); assert.equal(r.screen[0].screened, false);
  }
  assert.equal(gpx.checkGpx(inside, want).ok, true, 'no screen asked: the structure check alone');
});

test('GPX reference tracks may touch closures while fishable waypoints remain screened', () => {
  const point = {id: 'clear', name: 'Clear', latitude: 35, longitude: -120.5, user_waypoint: true, category: 'Fishing'};
  const contours = [{name: '100 ft', desc: 'Depth reference', geometry: {type: 'LineString', coordinates: [[-121.02, 35], [-120.98, 35]]}}];
  for (const waypoints of [[point], []]) {
    const xml = featuresGPX({}, {selected: waypoints, waypoints, areas: [], drifts: []}, 'References', {exclusions: [feature], contours});
    const result = gpx.checkGpx(xml, {waypoints: waypoints.length}, planner());
    assert.equal(result.ok, true, JSON.stringify(result));
    assert.equal(result.screen.length, waypoints.length);
    assert.ok(result.screen.every(v => v.screened && !placeRefused(v)));
    assert.equal(gpx.checkGpx(xml.replace('lat="34.99"', 'lat="91"'), {waypoints: waypoints.length}, planner()).ok, false, 'reference track coordinates still need structural validation');
  }
});

test('a waypoint click inside a closure is refused and placement stays armed; outside, the pick carries its verdict', () => {
  const got = [];
  placement.beginWaypointPlacement('r', p => got.push(p));
  assert.equal(placement.placeWaypoint('r', {lat: 35, lon: -121}, planner()), true);
  assert.equal(got.length, 0); assert.equal(placement.placementRefused.value.inside, true); assert.ok(placement.waypointPlacement.value, 'still armed');
  assert.equal(placement.placeWaypoint('r', {lat: 35.5, lon: -121}, planner()), true);
  assert.equal(got.length, 1); assert.equal(got[0].screen.inside, false); assert.equal(got[0].screen.screened, true); assert.equal(placement.placementRefused.value, null);
  placement.beginWaypointPlacement('r', p => got.push(p));
  assert.equal(placement.placeWaypoint('r', {lat: 35.5, lon: -121}), true);
  assert.equal(got.length, 1, 'no screen given: not checked is refused, the pick is not completed');
  assert.equal(placement.placementRefused.value.screened, false); assert.ok(placement.waypointPlacement.value, 'still armed');
  assert.equal(placement.placeWaypoint('r', {lat: 35.5, lon: -121}, planner()), true);
  assert.equal(got.length, 2); assert.equal(got[1].screen.screened, true); assert.equal(placement.placementRefused.value, null);
  assert.equal(placement.placeWaypoint('r', {lat: 35, lon: -121}, planner()), false, 'nothing armed: not a placement');
});

const WATER = () => ({state: 'water'});
const DATA = {region: {id: 'morro-bay', harbor: {name: 'Harbor', latitude: 35.37, longitude: -120.86}},
  atlas: {targets: [{id: 'in', label: 'In', latitude: 35, longitude: -121, neighborhood_depth_ft: [40, 80], area_ids: [], habitat_score: 90},
    {id: 'out', label: 'Out', latitude: 35.5, longitude: -121, neighborhood_depth_ft: [40, 80], area_ids: [], habitat_score: 80},
    {id: 'edge', label: 'Edge', latitude: 35, longitude: east + 1 * mLon, neighborhood_depth_ft: [40, 80], area_ids: [], habitat_score: 70}], areas: []}, survey: null, geology: null};

test('ranked atlas picks: inside and within-margin places are withheld, every pick carries a clear verdict, an unchecked screen lists none', () => {
  const picks = ranking.atlasPicks(DATA, marks, 'reef', 300, null, undefined, WATER);
  assert.deepEqual(picks.map(p => p.id), ['out']);
  for (const p of picks) assert.deepEqual([p.screen.screened, p.screen.inside], [true, false]);
  assert.equal(ranking.atlasPicks(DATA, CHECKING, 'reef', 300, null, undefined, WATER).length, 0);
});

test('rows are routed with their verdict, and the row line is plain text (a closure name with markup is never HTML)', async () => {
  const [pick] = ranking.atlasPicks(DATA, marks, 'reef', 300, null, undefined, WATER);
  const [routed] = ranking.routedPicks([pick], null, null, null, null, 4);
  assert.deepEqual(routed.screen, pick.screen);
  const src = readFileSync(new URL('../web/brief/WhereToLook.tsx', import.meta.url), 'utf8');
  assert.match(src, /screenLine\(pick\.screen\)/); assert.doesNotMatch(src, /dangerouslySetInnerHTML|innerHTML/);
  const line = /export function screenLine[\s\S]*?\n}\n/.exec(src)[0];
  assert.match(line, /`Inside \$\{v\.name/, 'the name goes into a text line');
  assert.match(line, /Protected areas not checked/);
});

test('the listed Boat picks (the list and the run line read them) keep each pick\'s screen verdict unchanged, routed or not', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'closures-where-')), 'where.mjs');
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: "export {listedBoatPicks} from './web/brief/WhereToLook.tsx';"},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  const {listedBoatPicks} = await import(pathToFileURL(out).href);
  const verdicts = [{inside: false, name: null, distanceM: null, screened: true}, {inside: false, name: NAME, distanceM: 40, screened: true}, {inside: false, name: null, distanceM: null, screened: false}];
  const origin = {latitude: 35.37, longitude: -120.86};
  const picks = verdicts.map((screen, i) => ({id: `p${i}`, kind: 'spot', name: `P${i}`, distance: '2 nm', nm: 2, at: {latitude: 35.4 + i / 100, longitude: -120.86}, depth: '~60 ft', fit: 'Fits', reason: 'Hard.', screen}));
  const r = {source: 'atlas', label: 'Survey reef atlas', basis: '', empty: '', harbor: 'Harbor', origin, picks};
  const lw = {region: 'closures', state: 'ready', model: {id: 'closures-model'}, lines: null, linesLoading: false};
  const route = (model, lines, from, to) => ({ok: true, nm: 3, points: []});
  const painted = listedBoatPicks(r, lw, 'closures', route);
  assert.ok(painted.length === 3 && painted.every(p => p.basis === 'straight'), 'nothing is routed while painting');
  painted.forEach((p, i) => assert.ok(isDeepStrictEqual(p.screen, verdicts[i]), `unrouted ${p.id} keeps its verdict`));
  ranking.routedPicks(picks, origin, lw.model, null, null, 4, route).forEach((p, i) => assert.ok(isDeepStrictEqual(p.screen, verdicts[i]), `routed ${p.id} keeps its verdict`));
});

// The enumeration is derived from each module's exports: a new exported function must be named here as carrying a verdict or as not naming a place.
const CARRIES = new Set(['atlasPicks', 'habitatPicks', 'ranking', 'routedPicks', 'tripLegs', 'placeWaypoint', 'checkGpx', 'reachRing', 'createPlanner',
  'currentRanking', 'boatPicks', 'listedBoatPicks', 'screenLine']);
const NO_PLACE = new Set(['harborOrigin', 'loadTerrainHabitat', 'loadReefPublication', 'recheckReefPublication', 'cancelWaypointPlacement', 'beginWaypointPlacement',
  'loadContourFile', 'nextFriday', 'planFit', 'parseReach', 'parseStoredReach', 'loadReach', 'saveReach', 'reachFor', 'nmText', 'parseSpearDepth', 'parseShoreSwim',
  'parseStoredSpear', 'loadSpear', 'saveSpear', 'shoreSwimLimit', 'parseStoredLaunch', 'loadLaunch', 'saveLaunch', 'isReachProfile', 'routeAfterPaint', 'choosePick',
  // Only aggregates confidence percentages; it neither names nor returns a place.
  'sharedConfidence', 'pickRun',
  // Only words a verdict it is handed (a refused placement's status, a leg's line); it screens nothing and names no place of its own.
  'verdictLine', 'diveText', 'WhereToLook']);
test('every exported function of the owned modules either carries a screen verdict or is listed as naming no place', () => {
  const fns = (mod, names = Object.keys(mod)) => names.filter(k => typeof mod[k] === 'function');
  const tsx = readFileSync(new URL('../web/brief/WhereToLook.tsx', import.meta.url), 'utf8');
  const names = [...fns(ranking), ...fns(legs), ...fns(placement), ...fns(gpx), ...fns(reach),
    ...[...tsx.matchAll(/^export function (\w+)/gm)].map(m => m[1])];
  for (const planner of [readFileSync(new URL('../web/planner.ts', import.meta.url), 'utf8')]) names.push(...[...planner.matchAll(/^export (?:async )?function (\w+)/gm)].map(m => m[1]));
  assert.ok(names.length > 20);
  const unknown = names.filter(n => !CARRIES.has(n) && !NO_PLACE.has(n));
  assert.deepEqual(unknown, [], `new exported function(s) not screened or classified: ${unknown}`);
  for (const n of CARRIES) assert.ok(names.includes(n), `${n} is no longer exported`);
});
