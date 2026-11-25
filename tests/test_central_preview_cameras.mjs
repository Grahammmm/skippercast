// C41: the Central Coast preview camera profile (no browser, no network; the real-pair check runs only where the pairs are).
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {existsSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {CENTRAL_REGIONS, CONTOUR_PAIR, loadPinTable} from '../scripts/relief/central_picker_walkthrough.mjs';
import {PROFILE, TERRAIN_ONLY, UNCHANGED, checkProfile, judgeProfile, linesInView} from '../scripts/relief/central_preview_cameras.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const STYLE = 'c'.repeat(64);
const line = (...pts) => ({type: 'Feature', geometry: {type: 'LineString', coordinates: pts.map(([lat, lon]) => [lon, lat])}});
const pair = (region, lines) => CONTOUR_PAIR.map((name, i) => ({name, bytes: Buffer.from(JSON.stringify({type: 'FeatureCollection', features: lines,
  provenance: {region_id: region, set: 'ft-v3', units: 'ft', contours: STYLE, features: lines.length, ...(i === 0 ? {overview: {max_zoom: 12}} : {})}}))}));
const tableFor = pairs => loadPinTable(JSON.stringify({schema: 'central-rehearsal-pins/1', regions: Object.fromEntries(CENTRAL_REGIONS.map(region => [region,
  TERRAIN_ONLY.includes(region) ? {terrain_only: true} : {overview: sha(pairs[region][0].bytes), detail: sha(pairs[region][1].bytes)}]))}));

// Four fake contour regions: default camera far from the only line, proposal on it; Cambria's default already on its line.
const REGION = {'big-sur-coast': {bounds: [-122.2, 35.9, -121.45, 36.3], map: {center: [36.11, -121.87], zoom: 10}},
  'cambria-san-simeon': {bounds: [-121.95, 35.45, -120.95, 35.66], map: {center: [35.612, -121.17], zoom: 12}},
  'south-big-sur-san-simeon': {bounds: [-121.7, 35.7, -121.3, 36.0], map: {center: [35.78, -121.59], zoom: 10}},
  'point-arguello-conception': {bounds: [-121.1, 34.4, -120.4, 34.95], map: {center: [34.7, -120.69], zoom: 10}}};
const onProposal = region => { const [lat, lon] = PROFILE[region].center; return [line([lat - 0.01, lon], [lat + 0.01, lon + 0.01])]; };
const pairs = () => Object.fromEntries(Object.keys(PROFILE).map(r => [r, pair(r, onProposal(r))]));

test('linesInView counts a line that crosses the phone view and not one a degree away', () => {
  const view = [35.9, -121.5];
  assert.equal(linesInView({features: [line([35.89, -121.5], [35.91, -121.49])]}, view, 10), 1);
  assert.equal(linesInView({features: [line([36.9, -121.5], [36.91, -121.49])]}, view, 10), 0);
});

// Bug it catches: a vertex-only check misses a long segment whose two ends are both outside the viewport but whose middle crosses it.
test('linesInView counts a long segment that crosses the view with both ends outside, and a MultiLineString part', () => {
  const view = [35.9, -121.5];
  assert.equal(linesInView({features: [line([35.5, -121.5], [36.3, -121.5])]}, view, 10), 1);
  assert.equal(linesInView({features: [{type: 'Feature', geometry: {type: 'MultiLineString', coordinates: [[[-121.4, 34.0], [-121.4, 34.1]], [[-121.5, 35.8], [-121.5, 36.0]]]}}]}, view, 10), 1);
});

// Bug it catches: a profile that quietly gives Monterey or Santa Cruz a contour landing, or omits a contour region.
test('checkProfile: terrain-only regions never carry a camera; every contour region does; the shipped profile is valid', () => {
  assert.equal(checkProfile(PROFILE), 4);
  for (const r of TERRAIN_ONLY) assert.throws(() => checkProfile({...PROFILE, [r]: {center: [36.5, -122], zoom: 10}}), /terrain-only/);
  const {'big-sur-coast': _gone, ...fewer} = PROFILE;
  assert.throws(() => checkProfile(fewer), /big-sur-coast: profile needs/);
  assert.throws(() => checkProfile({...PROFILE, 'big-sur-coast': {center: [35.9, -121.5], zoom: 10.5}}), /profile needs/);
  assert.throws(() => checkProfile({...PROFILE, 'morro-bay': {center: [35.3, -120.8], zoom: 12}}), /not a Central Coast region/);
});

test('judgeProfile passes a profile whose centres sit on their pinned contours at each region\'s own zoom', () => {
  const p = pairs(), rows = judgeProfile(PROFILE, REGION, p, {table: tableFor(p)});
  assert.deepEqual(rows.map(r => r.ok), [true, true, true, true]);
  assert.ok(rows.every(r => r.crossingAtProposed >= 1));
  assert.equal(rows.find(r => r.region === 'big-sur-coast').crossingAtDefault, 0);
});

// Bugs it catches, one each: zooming in to hide a miss; a centre outside the region; a centre on empty water; Cambria's camera moved.
test('judgeProfile refuses a changed zoom, an out-of-bounds centre, an empty view and a moved Cambria', () => {
  const p = pairs(), table = tableFor(p), run = profile => judgeProfile(profile, REGION, p, {table});
  const bad = (profile, region) => run(profile).find(r => r.region === region);
  assert.match(bad({...PROFILE, 'big-sur-coast': {...PROFILE['big-sur-coast'], zoom: 12}}, 'big-sur-coast').problems.join(), /zoom 12 differs/);
  assert.match(bad({...PROFILE, 'big-sur-coast': {center: [37.5, -121.5], zoom: 10}}, 'big-sur-coast').problems.join(), /outside the region bounds/);
  assert.match(bad({...PROFILE, 'big-sur-coast': {center: [36.25, -122.15], zoom: 10}}, 'big-sur-coast').problems.join(), /no contour line crosses/);
  assert.equal(UNCHANGED.includes('cambria-san-simeon'), true);
  assert.match(bad({...PROFILE, 'cambria-san-simeon': {center: [35.6125, -121.17], zoom: 12}}, 'cambria-san-simeon').problems.join(), /keep its default camera/);
});

// Bug it catches: bytes of a neighbour's contour pair (or the caller's own hash) standing in for the region's pinned pair.
test('judgeProfile refuses a neighbour\'s contour pair under this region (the pin table is the trust root)', () => {
  const p = pairs(), table = tableFor(p);
  assert.throws(() => judgeProfile(PROFILE, REGION, {...p, 'big-sur-coast': p['point-arguello-conception']}, {table}), /differs from its published pin|provenance|region/);
  assert.throws(() => judgeProfile(PROFILE, REGION, {...p, 'big-sur-coast': undefined}, {table}), /pinned contour pair not supplied/);
});

// Bug it catches: the proposal table drifting from the repo's own region data (a region's default zoom or bounds change under it).
test('the shipped profile agrees with the repository\'s own regions/<id>/region.json', () => {
  const dir = fileURLToPath(new URL('../regions', import.meta.url));
  for (const [region, cam] of Object.entries(PROFILE)) {
    const {bounds: [w, s, e, n], map} = JSON.parse(readFileSync(join(dir, region, 'region.json')));
    assert.equal(cam.zoom, map.zoom, `${region} keeps its own zoom`);
    assert.ok(cam.center[1] >= w && cam.center[1] <= e && cam.center[0] >= s && cam.center[0] <= n, `${region} centre inside bounds`);
    assert.equal(UNCHANGED.includes(region), cam.center.join() === map.center.join(), `${region} unchanged only where listed`);
  }
});

const REAL = process.env.CENTRAL_REHEARSAL_PAIRS || '';
test('the real rehearsal pairs put a contour line in view at every proposed centre', { skip: (!REAL || !existsSync(REAL)) && 'real rehearsal pairs not present (set CENTRAL_REHEARSAL_PAIRS)' }, () => {
  const dir = fileURLToPath(new URL('../regions', import.meta.url)), regions = {}, real = {};
  for (const region of Object.keys(PROFILE)) {
    regions[region] = JSON.parse(readFileSync(join(dir, region, 'region.json')));
    real[region] = CONTOUR_PAIR.map(name => ({name, bytes: readFileSync(join(REAL, region, name))}));
  }
  const rows = judgeProfile(PROFILE, regions, real);
  assert.deepEqual(rows.filter(r => !r.ok), []);
  assert.equal(rows.find(r => r.region === 'big-sur-coast').crossingAtDefault, 0);
});
