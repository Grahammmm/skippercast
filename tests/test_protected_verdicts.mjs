// SC-PERF-PROTCHECK-1: the fixed cases the publisher's Python port is checked against (tests/unit/test_protected_screen_verdicts.py), and the
// browser's use of the publish-time verdicts: used only when the screen's boundary fingerprint equals the publication's, else the screen runs.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {boundaryFingerprint, geometryCoveredByBounds, screenPlace} from '../dist/geo-screen.js';
import {ranking} from '../web/ranking.ts';

const CASES = JSON.parse(readFileSync(new URL('./fixtures/protected_screen_cases.json', import.meta.url), 'utf8'));
const nameOf = f => f.properties?.FULLNAME || f.properties?.NAME || null;
const screen = (features = CASES.boundary, bounds = CASES.bounds) => ({ready: () => true, coversGeometry: g => geometryCoveredByBounds(g, bounds),
  exportExclusions: () => ({checked_at: 'x', features}), fingerprint: () => boundaryFingerprint(features.map(f => f.geometry), bounds, features.map(nameOf))});

test('the fixture answers are what the browser code gives', () => {
  const s = screen();
  for (const r of CASES.reefs) assert.deepEqual(screenPlace(s, {latitude: r.latitude, longitude: r.longitude, geometries: [r.geometry]}), CASES.expected[r.id], r.id);
  assert.equal(s.fingerprint(), CASES.fingerprint);
});

test('the fingerprint changes with any change to the boundary data or the envelope', () => {
  const geoms = CASES.boundary.map(f => structuredClone(f.geometry)), base = boundaryFingerprint(geoms, CASES.bounds, CASES.boundary.map(nameOf));
  geoms[0].coordinates[0][0][0] += 1e-9;
  assert.notEqual(boundaryFingerprint(geoms, CASES.bounds, CASES.boundary.map(nameOf)), base);
  assert.notEqual(boundaryFingerprint(geoms.slice(1), CASES.bounds, CASES.boundary.slice(1).map(nameOf)), base);
  assert.notEqual(boundaryFingerprint(CASES.boundary.map(f => f.geometry), [-121.9, 34.95, -120.55, 35.86], CASES.boundary.map(nameOf)), base);
});

test('a metadata-only refresh (same coordinates, new closure name) changes the fingerprint', () => {
  const geoms = CASES.boundary.map(f => f.geometry), names = CASES.boundary.map(nameOf), base = boundaryFingerprint(geoms, CASES.bounds, names);
  assert.equal(boundaryFingerprint(geoms, CASES.bounds, [...names]), base);
  assert.notEqual(boundaryFingerprint(geoms, CASES.bounds, [`${names[0]} (renamed)`, ...names.slice(1)]), base);
  assert.notEqual(boundaryFingerprint(geoms, CASES.bounds, [null, ...names.slice(1)]), base);
});

// The brief's list (web/ranking.ts publicationScreened): the stored verdict is shown only for a screen holding the data it was computed against.
const reef = (id, latitude, longitude, percent, protected_place) => ({id, canonical_habitat: true, name: id, label: 'Surveyed reef habitat', latitude, longitude,
  neighborhood_depth_ft: [40, 90], habitat_score: 50, species_fit: {lingcod: 3, 'rockfish-reef': 3}, resolution_m: 2, evidence_confidence: {percent}, area_ids: [id],
  terrain_interpretation: `${id} relief.`, ...(protected_place ? {protected_place} : {})});
const box = (lon, lat) => ({type: 'Polygon', coordinates: [[[lon - .002, lat - .002], [lon + .002, lat - .002], [lon + .002, lat + .002], [lon - .002, lat + .002], [lon - .002, lat - .002]]]});
const STORED = {inside: false, name: 'STORED NAME', distanceM: 123.4, screened: true};
const REAL = screenPlace(screen(), {latitude: 35.1, longitude: -121.6, geometries: [box(-121.6, 35.1)]});
const loaded = fingerprint => ({targets: [reef('r1', 35.1, -121.6, 90, STORED)], areas: [{id: 'r1', geometry: box(-121.6, 35.1)}], ...(fingerprint ? {protected_fingerprint: fingerprint} : {}),
  publication: {status: 'ready', region: 'morro-bay', archive_sha256: 'a'.repeat(64), export_sha256: 'b'.repeat(64), expires_at: new Date(Date.now() + 3600000).toISOString()}});
const DATA = {region: {...JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8')), id: 'morro-bay'}, atlas: JSON.parse(readFileSync(new URL('../dist/data/atlas.json', import.meta.url), 'utf8')), survey: null, geology: null};
const pick = (pub, s) => ranking({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: {status: 'ready', note: '', source: 't', boundaries: [], until: Infinity},
  terrain: {state: 'idle'}, now: Date.now(), place: () => ({state: 'water'}), publication: {state: 'ready', region: 'morro-bay', loaded: pub},
  plannerScreen: {state: 'loaded', region: 'morro-bay', screen: s}}).picks.find(p => p.id === 'r1');

const planner = s => ({pointAllowed: () => true, geometryAllowed: () => true, ...s});

test('with the same boundary data the stored verdict is shown and the screen is not run', () => {
  const s = planner(screen());
  s.exportExclusions = () => { throw Error('the screen ran'); };
  assert.deepEqual(pick(loaded(CASES.fingerprint), s)?.screen, STORED);
});
test('another boundary fingerprint, no fingerprint, or no stored verdict: the screen runs as before', () => {
  assert.deepEqual(pick(loaded('ps1-0000000000000000-1'), planner(screen()))?.screen, REAL);
  assert.deepEqual(pick(loaded(null), planner(screen()))?.screen, REAL);
  assert.deepEqual(pick({...loaded(CASES.fingerprint), targets: [reef('r1', 35.1, -121.6, 90)]}, planner(screen()))?.screen, REAL);
  const noPrint = planner(screen()); delete noPrint.fingerprint;
  assert.deepEqual(pick(loaded(CASES.fingerprint), noPrint)?.screen, REAL);
});
test('a screen that is not current still withholds the list', () => {
  const s = planner(screen()); s.ready = () => false;
  assert.equal(pick(loaded(CASES.fingerprint), s), undefined);
});
