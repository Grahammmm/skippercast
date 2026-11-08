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
import {screenPlace, placeRefused, distanceM, geometryCoveredByBounds, PLANNING_MARGIN_M} from '../dist/geo-screen.js';
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

// SC0022-04: a boundary file only speaks for the envelope it was asked for. Morro Bay's is [-121.9, 34.95, -120.55, 35.85].
const ENVELOPE = [-121.9, 34.95, -120.55, 35.85];
const covers = g => geometryCoveredByBounds(g, ENVELOPE);
const pt = (lon, lat) => ({type: 'Point', coordinates: [lon, lat]});
const nextUp = x => x + Math.max(Math.abs(x), 1) * Number.EPSILON, nextDown = x => x - Math.max(Math.abs(x), 1) * Number.EPSILON;
/** The smallest inset from the west edge, in degrees of longitude, at which a point is covered: the halo for `marginM`. */
function haloDegrees(marginM) {
  let out = 0, inn = 0.5;
  for (let i = 0; i < 60; i++) { const mid = (out + inn) / 2; if (geometryCoveredByBounds(pt(ENVELOPE[0] + mid, 35.4), ENVELOPE, marginM)) inn = mid; else out = mid; }
  return inn;
}
const NONE = {inside: false, name: null, distanceM: null, screened: false};
/** A production-shaped planner screen over an explicit (possibly empty) boundary set that declares its coverage. */
const bounded = (features = [feature], loaded = true) => ({...planner(loaded), exportExclusions: () => loaded ? {checked_at: iso, features} : null, coversGeometry: covers});

test('coverage_bounds_validate_and_check_every_part', () => {
  const inside = pt(-121.2, 35.4);
  assert.equal(geometryCoveredByBounds(inside, ENVELOPE), true);
  for (const bad of [undefined, null, 'x', {}, [], [1, 2, 3], [-121.9, 34.95, -120.55, 35.85, 0], [-121.9, 34.95, -120.55, '35.85'], [NaN, 34.95, -120.55, 35.85],
    [-121.9, 34.95, Infinity, 35.85], [-120.55, 34.95, -121.9, 35.85], [-121.9, 35.85, -120.55, 34.95], [-121.9, 34.95, -121.9, 35.85], [-121.9, 35, -120.55, 35],
    [-181, 34.95, -120.55, 35.85], [-121.9, 34.95, 181, 35.85], [-121.9, -91, -120.55, 35.85], [-121.9, 34.95, -120.55, 91], [170, 0, -170, 10], [-10, 89.99999, 10, 90]]) {
    assert.equal(geometryCoveredByBounds(inside, bad), false, `bounds ${JSON.stringify(bad)}`);
  }
  for (const bad of [-1, NaN, Infinity, -Infinity, '70', null, {}]) assert.equal(geometryCoveredByBounds(inside, ENVELOPE, bad), false, `margin ${String(bad)}`);
  for (const bad of [undefined, null, 'x', {}, {type: 'Point'}, {type: 'Point', coordinates: []}, {type: 'Point', coordinates: [-121]}, pt(NaN, 35.4), pt(-121.2, Infinity), pt('-121.2', 35.4),
    pt(-181, 35.4), pt(-121.2, 95), {type: 'LineString', coordinates: []}, {type: 'MultiPoint', coordinates: []}, {type: 'Polygon', coordinates: [[]]}, {type: 'Polygon', coordinates: []},
    {type: 'MultiPolygon', coordinates: [[]]}, {type: 'GeometryCollection', geometries: [inside]}, {type: 'Feature', geometry: inside}, {type: 'Point', coordinates: [[-121.2, 35.4]]}]) {
    assert.doesNotThrow(() => geometryCoveredByBounds(bad, ENVELOPE)); assert.equal(geometryCoveredByBounds(bad, ENVELOPE), false, `geometry ${JSON.stringify(bad)}`);
  }
  // Every part and ring counts: one part that escapes makes the whole shape uncovered.
  const out = [-124, 35.4], ok1 = [-121.3, 35.3], ok2 = [-121.1, 35.5], ok3 = [-121.2, 35.6];
  assert.equal(covers({type: 'MultiPoint', coordinates: [ok1, ok2]}), true);
  assert.equal(covers({type: 'MultiPoint', coordinates: [ok1, out]}), false);
  assert.equal(covers({type: 'LineString', coordinates: [ok1, ok2]}), true);
  assert.equal(covers({type: 'LineString', coordinates: [ok1, ok2, out]}), false, 'a line that leaves the envelope');
  assert.equal(covers({type: 'MultiLineString', coordinates: [[ok1, ok2], [ok2, out]]}), false);
  const ring = [ok1, ok2, ok3, ok1];
  assert.equal(covers({type: 'Polygon', coordinates: [ring]}), true);
  assert.equal(covers({type: 'Polygon', coordinates: [ring, [out, ok2, ok3, out]]}), false, 'a hole ring that escapes');
  assert.equal(covers({type: 'MultiPolygon', coordinates: [[ring], [ring.map(([x, y]) => [x - 5, y])]]}), false, 'the second polygon escapes');
  assert.equal(covers({type: 'MultiPolygon', coordinates: [[ring], [ring.map(([x, y]) => [x + 0.1, y])]]}), true);
  // Zero margin: the raw envelope edge is covered, just beyond it is not. With the planning margin the raw edge itself is not.
  for (const [p, q] of [[[ENVELOPE[0], 35.4], [nextDown(ENVELOPE[0]), 35.4]], [[ENVELOPE[2], 35.4], [nextUp(ENVELOPE[2]), 35.4]],
    [[-121.2, ENVELOPE[1]], [-121.2, nextDown(ENVELOPE[1])]], [[-121.2, ENVELOPE[3]], [-121.2, nextUp(ENVELOPE[3])]]]) {
    assert.equal(geometryCoveredByBounds(pt(...p), ENVELOPE, 0), true, `edge ${p}`);
    assert.equal(geometryCoveredByBounds(pt(...q), ENVELOPE, 0), false, `just beyond ${q}`);
    assert.equal(geometryCoveredByBounds(pt(...p), ENVELOPE), false, `${p} is within the halo of the edge`);
  }
  // An interior point is covered whatever the closure set; the helper never looks at closures, only at the declared envelope.
  assert.equal(screenPlace(bounded([]), at(-121.2, 35.4)).screened, true);
  assert.equal(screenPlace(bounded([]), at(-124, 35.4)).screened, false, 'a fresh empty boundary set is clear only inside its coverage');
});

test('coverage_requires_the_planning_halo', () => {
  const mLonAt = lat => 111412.84 * Math.cos(lat * Math.PI / 180) - 93.5 * Math.cos(3 * lat * Math.PI / 180), mLatAt = 111132.92;
  const eastEdge = lon => pt(ENVELOPE[2] - lon / mLonAt(35.4), 35.4), westEdge = m => pt(ENVELOPE[0] + m / mLonAt(35.85), 35.4);
  assert.equal(PLANNING_MARGIN_M, 70);
  // 30 m inside any query edge is unchecked; 100 m inside is checked.
  for (const m of [0, 30, 60]) { assert.equal(covers(eastEdge(m)), false, `${m} m inside the east edge`); assert.equal(covers(westEdge(m)), false, `${m} m inside the west edge`); }
  for (const m of [100, 500]) { assert.equal(covers(eastEdge(m)), true, `${m} m inside the east edge`); assert.equal(covers(westEdge(m)), true, `${m} m inside the west edge`); }
  assert.equal(covers(pt(-121.2, ENVELOPE[1] + 30 / mLatAt)), false, '30 m inside the south edge');
  assert.equal(covers(pt(-121.2, ENVELOPE[3] - 30 / mLatAt)), false, '30 m inside the north edge');
  assert.equal(covers(pt(-121.2, ENVELOPE[1] + 150 / mLatAt)), true);
  assert.equal(covers(pt(-121.2, ENVELOPE[3] - 150 / mLatAt)), true);
  // The halo is set in metres by the margin: 70 m is about 70 m, and twice the margin is twice the padding.
  const h70 = haloDegrees(70), h140 = haloDegrees(140);
  assert.ok(Math.abs(h70 * mLonAt(35.85) - 70) < 1, `halo ${h70 * mLonAt(35.85)} m`);
  assert.ok(Math.abs(h140 / h70 - 2) < 1e-6);
  assert.equal(haloDegrees(0) < 1e-12, true, 'no margin, no padding');
  // A whole shape must clear the halo, not only one vertex.
  assert.equal(covers({type: 'LineString', coordinates: [[-121.2, 35.4], westEdge(30).coordinates]}), false);
  // Premise: a closure wholly outside the query (so absent from its file) can lie within the planning margin of a place near the edge.
  const absent = {type: 'Polygon', coordinates: [[[ENVELOPE[0] - 0.01, 35.3], [ENVELOPE[0] - 30 / mLonAt(35.3), 35.3], [ENVELOPE[0] - 30 / mLonAt(35.3), 35.5], [ENVELOPE[0] - 0.01, 35.5], [ENVELOPE[0] - 0.01, 35.3]]]};
  const near = westEdge(30).coordinates, place = at(near[0], near[1]);
  assert.ok(distanceM(pt(...near), absent) < PLANNING_MARGIN_M, 'the omitted closure is inside the margin');
  const legacy = {ready: () => true, exportExclusions: () => ({checked_at: iso, features: []})};
  assert.equal(placeRefused(screenPlace(legacy, place)), false, 'the legacy fixture seam with no coverage method keeps its contract');
  assert.deepEqual(screenPlace(bounded([]), place), NONE, 'a declared envelope never turns the missing closure into a false clear');
  assert.ok(placeRefused(screenPlace(bounded([]), place)));
  assert.equal(screenPlace(bounded([]), at(near[0] + 300 / mLonAt(35.4), near[1])).screened, true, 'sufficiently inset is checked');
});

test('screen_place_uncovered_never_falls_back_to_clear', () => {
  const inside = at(-121.2, 35.4), outside = at(-124, 35.4);
  const boundary = cover => ({...marks, coversGeometry: cover}), allowedOnly = cover => ({ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, coversGeometry: cover});
  const shapes = [{geometry: pt(-121.2, 35.4)}, {geometry: pt(-124, 35.4)}, {geometries: [pt(-121.2, 35.4), pt(-124, 35.4)]}, {...inside, geometry: pt(-124, 35.4)}, {...inside, geometries: [pt(-124, 35.4)]}];
  const throws = () => { throw new Error('boom'); };
  for (const make of [boundary, allowedOnly, c => ({...planner(), coversGeometry: c})]) {
    for (const cover of [() => false, throws, () => undefined, () => 1, () => null, g => { if (g.coordinates[0] < -123) throw new Error('only the far part'); return true; }]) {
      for (const place of [outside, ...shapes.slice(1)]) {
        const v = screenPlace(make(cover), place);
        assert.deepEqual(v, NONE, `${JSON.stringify(place)}`); assert.ok(placeRefused(v));
      }
    }
    // Every supplied shape is asked, not just the first: the point is covered, the geometry is not, and the reverse.
    const asked = [], v = screenPlace(make(g => { asked.push(g.coordinates[0]); return g.coordinates[0] > -123; }), {...inside, geometry: pt(-124, 35.4)});
    assert.deepEqual(v, NONE); assert.ok(asked.includes(-124), 'the escaping geometry was asked');
    assert.deepEqual(screenPlace(make(g => g.coordinates[0] > -123), {...inside, geometries: [pt(-124, 35.4)]}), NONE);
    assert.equal(screenPlace(make(covers), inside).screened, true, 'a covered place is screened');
  }
  // Covered places keep their exact verdicts; legacy screens without the method are untouched.
  for (const p of [at(-121, 35), at(east + 1 * mLon, 35), at(east + 500 * mLon, 35)]) {
    assert.deepEqual(screenPlace({...planner(), coversGeometry: covers}, p), screenPlace(planner(), p));
    assert.deepEqual(screenPlace({...marks, coversGeometry: covers}, p), screenPlace(marks, p));
  }
  assert.equal(screenPlace(planner(), outside).screened, true, 'legacy planner fixture: no coverage method, old contract');
  assert.equal(screenPlace(marks, outside).screened, true);
  assert.equal(screenPlace(allowedOnly(undefined), outside).screened, true, 'a method that is not a function is no method');
  // A screen that is not loaded stays unchecked whatever it covers.
  assert.deepEqual(screenPlace(bounded([feature], false), inside), NONE);
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
  assert.match(src, /screenLine\(pick\.screen, lang\)/); assert.doesNotMatch(src, /dangerouslySetInnerHTML|innerHTML/);
  // SC0452-10: the lines come from the catalogue in both languages; run them, not the English source.
  const out = join(await mkdtemp(join(tmpdir(), 'closures-line-')), 'line.mjs');
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: "export {screenLine} from './web/brief/WhereToLook.tsx'; export {render} from 'preact-render-to-string'; export {h} from 'preact';"},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  const {screenLine, render, h} = await import(pathToFileURL(out).href);
  const verdict = (extra) => ({inside: false, name: NAME, distanceM: null, screened: true, ...extra});
  const lines = {
    en: [['Protected areas not checked', verdict({screened: false})], [`Inside ${NAME}`, verdict({inside: true, distanceM: 0})], [`70 m from ${NAME}`, verdict({distanceM: 70})],
      [`40 m from ${NAME}`, verdict({distanceM: 39.6})], ['Inside a protected area', verdict({inside: true, name: null})], ['12 m from a protected area', verdict({distanceM: 12.4, name: null})], [null, verdict({distanceM: 70.1})], [null, verdict({})]],
    es: [['Áreas protegidas sin revisar', verdict({screened: false})], [`Dentro de ${NAME}`, verdict({inside: true, distanceM: 0})], [`A 70 m de ${NAME}`, verdict({distanceM: 70})],
      [`A 40 m de ${NAME}`, verdict({distanceM: 39.6})], ['Dentro de un área protegida', verdict({inside: true, name: null})], ['A 12 m de un área protegida', verdict({distanceM: 12.4, name: null})], [null, verdict({distanceM: 70.1})], [null, verdict({})]],
  };
  for (const [lang, cases] of Object.entries(lines)) for (const [want, v] of cases) assert.equal(screenLine(v, lang), want, `${lang}: ${JSON.stringify(v)}`);
  assert.equal(screenLine(verdict({screened: false})), 'Protected areas not checked', 'English is the default');
  for (const lang of ['en', 'es']) {
    const html = render(h('span', null, screenLine(verdict({inside: true}), lang)));
    assert.ok(!html.includes('<img') && html.includes('&lt;img src=x onerror=alert(1)> Reserve'), `${lang}: the closure name is escaped text, never markup`);
  }
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
const NO_PLACE = new Set(['harborOrigin', 'loadTerrainHabitat', 'loadReefPublication', 'recheckReefPublication', 'reloadReefPublication', 'supersedeReefLoads', 'cancelWaypointPlacement', 'beginWaypointPlacement',
  'loadContourFile', 'nextFriday', 'planFit', 'parseReach', 'parseStoredReach', 'loadReach', 'saveReach', 'reachFor', 'nmText', 'parseSpearDepth', 'parseShoreSwim',
  'parseStoredSpear', 'loadSpear', 'saveSpear', 'shoreSwimLimit', 'parseStoredLaunch', 'loadLaunch', 'saveLaunch', 'isReachProfile', 'routeAfterPaint', 'choosePick',
  // Only aggregates confidence percentages; it neither names nor returns a place.
  'sharedConfidence', 'pickRun', 'routeWhyText',
  // Only words a verdict it is handed (a refused placement's status, a leg's line); it screens nothing and names no place of its own.
  'verdictLine', 'verdictParts', 'diveText', 'WhereToLook']);
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
