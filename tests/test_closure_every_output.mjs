// SC-LAUNCH-1 (t_4062ed58): a geometry straddling a real committed MPA boundary must be refused at
// EVERY output that hands a location to a user or a device, not only the map. RED at 94d73d10f:
// the map reef marks, Where-to-look (atlas and terrain), survey outlines, the planner's boundary naming,
// the waypoints-only GPX export and the 100 m planning margin all let it through today.
// Fixture: a ~400 m square centred on a vertex of the committed ds582 Point Buchon SMR polygon
// (dist/data/protected-areas.geojson, WGS84 / EPSG:4326 lon,lat), its waypoint on the square's outside corner.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {pointInGeometry, geometryIntersects} from '../dist/geo-screen.js';
import {assessScreen, withheld, surveyFeatures, markFeatures} from '../web/map/habitat.ts';
import {screened as groundScreened} from '../web/map/charter-grounds.ts';
import {atlasPicks, habitatPicks} from '../web/ranking.ts';
import {rankedHabitat} from '../packages/coast/src/coast3d/regional.ts';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {buildExport, protectedPlanHits} from '../dist/trip-export.js';
import {getRegion} from '../dist/region.js';

const read = p => JSON.parse(readFileSync(new URL(`../dist/${p}`, import.meta.url), 'utf8'));
const mpas = read('data/protected-areas.geojson'), ATLAS = read('data/atlas.json');
const NAME = 'Point Buchon SMR';
const mpa = mpas.features.find(f => f.properties.NAME === NAME);
const ring = mpa.geometry.type === 'Polygon' ? mpa.geometry.coordinates[0] : mpa.geometry.coordinates[0][0];
const v = ring[Math.floor(ring.length / 3)];
const mLat = 1 / 111320, mLon = 1 / (111320 * Math.cos(v[1] * Math.PI / 180));
const square = {type: 'Polygon', coordinates: [[[v[0] - 200 * mLon, v[1] - 200 * mLat], [v[0] + 200 * mLon, v[1] - 200 * mLat], [v[0] + 200 * mLon, v[1] + 200 * mLat], [v[0] - 200 * mLon, v[1] + 200 * mLat], [v[0] - 200 * mLon, v[1] - 200 * mLat]]]};
const corner = square.coordinates[0].slice(0, 4).find(p => !pointInGeometry(p, mpa.geometry));
const NOW = Date.now(), LATER = new Date(NOW + 86400000).toISOString();
const SCREEN = assessScreen({areas: mpas.features, checkedAt: new Date(NOW).toISOString(), live: true}, NOW);
const target = {...ATLAS.targets[0], id: 'STRADDLE-1', latitude: corner[1], longitude: corner[0], area_ids: ['STRADDLE-AREA'], trip_rank: 1};
const atlas = {...ATLAS, targets: [target], areas: [{id: 'STRADDLE-AREA', geometry: square, extent_note: 'fixture'}], drifts: []};
const DATA = {region: {...read('regions/morro-bay/region.json'), id: 'morro-bay'}, atlas, survey: null, geology: null};
const WATER = () => ({state: 'water'});
async function v1Screen() {
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = async () => ({ok: true, json: async () => ({...mpas, checked_at: new Date().toISOString()})});
  globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { return await initProtectedAreas(null, () => {}); } finally { Object.assign(globalThis, saved); }
}

test('fixture straddles the real boundary with its waypoint outside', () => {
  assert.ok(geometryIntersects(square, mpa.geometry));
  assert.ok(corner && !pointInGeometry(corner, mpa.geometry));
});
test('map reef marks and the ?spot= card withhold it and name the boundary', () => {
  const w = withheld({...target, geometry: square}, SCREEN);
  assert.ok(w, 'withheld');
  assert.match(w.reading, /Point Buchon State Marine Reserve/);
  assert.ok(!markFeatures(atlas, 'reef', 'boat', SCREEN).features.some(f => (f.properties?.id ?? f.id) === 'STRADDLE-1'));
});
test('Where-to-look atlas picks refuse it', () => {
  assert.ok(!atlasPicks(DATA, SCREEN, 'reef', 300, null, undefined, WATER).some(p => p.id === 'STRADDLE-1'));
});
test('Where-to-look terrain picks refuse a straddling polygon', () => {
  const f = {type: 'Feature', id: 'h1', geometry: square, properties: {id: 'h1', region: 'morro-bay', exportable: true, screen_status: 'pass', screen_expires_at: LATER,
    waypoint_latitude: corner[1], waypoint_longitude: corner[0], depth_min_ft: 40, depth_max_ft: 80, terrain_score: 70, terrain_grade: 'B', fit_lingcod: 3}};
  assert.equal(habitatPicks(rankedHabitat([f], 'fit_lingcod', NOW), SCREEN, 'morro-bay', 'lingcod', 300, null, undefined, WATER).length, 0);
});
test('survey-habitat outlines are screened at run time', () => {
  const survey = {type: 'FeatureCollection', region_id: 'morro-bay', features: [{type: 'Feature', geometry: square, properties: {id: 's1', name: 'fixture', habitat_kind: 'rock', species_ids: ['reef']}}]};
  assert.equal(surveyFeatures({...DATA, survey}, 'reef', SCREEN).features.length, 0);
});
test('charter grounds refuse it (already true)', () => {
  assert.equal(groundScreened({latitude: corner[1], longitude: corner[0]}, square, SCREEN), false);
});
test('planner names the boundary for the straddling spot', async () => {
  const hits = protectedPlanHits(await v1Screen(), [{...target, geometry: square}]);
  assert.equal(hits.length, 1);
});
test('GPX / share / offline notes refuse it even in the default waypoints-only export', async () => {
  const screen = await v1Screen();
  assert.throws(() => buildExport({atlas, screen, ids: ['STRADDLE-1'], layers: {waypoints: true, outlines: false, alignments: false, exclusions: false}, region: getRegion(), allowResearch: true}),
    /Point Buchon/);
});
test('a 100 m planning margin applies in metres, not degrees (CRS check)', async () => {
  // 90 m due east is inside a 100 m margin; a degree-space margin (100 m of latitude) would wrongly pass it.
  const east = m => { for (const s of [1, -1]) { const p = [v[0] + s * m * mLon, v[1]]; if (!pointInGeometry(p, mpa.geometry) && !pointInGeometry([v[0] + s * 1 * mLon, v[1]], mpa.geometry)) return p; } };
  const p90 = east(90);
  assert.ok(p90, 'an outside point due east or west of the vertex');
  assert.ok(withheld({latitude: p90[1], longitude: p90[0]}, SCREEN), 'map gate holds a point 90 m outside');
  assert.equal((await v1Screen()).pointAllowed({latitude: p90[1], longitude: p90[0]}), false, 'export holds a point 90 m outside');
});
