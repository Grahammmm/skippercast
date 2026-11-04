// SC1322-08: a refused outline or alignment names the protected area it hits; a check that cannot run stays the generic refusal.
import test from 'node:test';
import assert from 'node:assert/strict';
import {buildExport, DEFAULT_LAYERS} from '../dist/trip-export.js';
import {closureHits, PLANNING_MARGIN_M} from '../dist/geo-screen.js';

const GENERIC = 'A selected outline or alignment intersects a protected area, or cannot be checked. Turn off that layer or choose a different spot.';
const REGION = {id: 'test-coast', name: 'Test Coast', mpa: {bounds: [-10, -10, 10, 10]}, regulations_url: 'https://example.org/rules'};
const ring = (x, y, w = 1) => [[x, y], [x + w, y], [x + w, y + w], [x, y + w], [x, y]];
const polygon = (x, y, w = 1) => ({type: 'Polygon', coordinates: [ring(x, y, w)]});
const mpa = (name, geometry) => ({type: 'Feature', properties: {NAME: name, FULLNAME: `${name} SMR`}, geometry});

// The reef area is clear of every closure below; the alignment runs well east of it at y=0, the spare outline at y=6.
const atlasFixture = () => ({
  source_validation_date: '2026-09-20',
  targets: [{id: 'a', label: 'Reef a', latitude: 0, longitude: 0, area_ids: ['reef-a'], drift_id: 'align-a',
    habitat_grade: 'A', habitat_score: 80, center_depth_ft: 100, neighborhood_depth_ft: [90, 110], terrain_interpretation: 'Mapped structure',
    evidence_status: 'Fish presence unverified.', ais_status: 'AIS unverified.', survey_year: 2008, source_url: 'https://example.org/survey'}],
  areas: [{id: 'reef-a', geometry: polygon(-0.5, -0.5)}],
  drifts: [{id: 'align-a', geometry: {type: 'LineString', coordinates: [[6, 0], [7, 0]]}}],
});
// Mirrors dist/protected-areas.js: `geometryAllowed` is fresh && no hit; `inspect` reports fresh, status and names.
function screenFixture(features, {fresh = true, inspect = true} = {}) {
  const calls = [];
  const screen = {
    calls, ready: () => true, pointAllowed: () => true,
    geometryAllowed: g => fresh && !closureHits([g], features).length,
    exportExclusions: () => ({checked_at: '2026-09-22T17:00:00.000Z', features}),
  };
  if (inspect) screen.inspect = p => {
    calls.push(p);
    const hits = closureHits(p.geometries, features);
    return {status: hits.length ? 'excluded' : fresh ? 'clear' : 'unavailable', fresh, names: hits.map(f => f.properties.FULLNAME), matches: []};
  };
  return screen;
}
const request = (screen, layers = {alignments: true}, atlas = atlasFixture()) =>
  ({allowResearch: true, atlas, screen, ids: ['a'], region: REGION, now: new Date('2026-09-22T18:00:00.000Z'), layers: {...DEFAULT_LAYERS, ...layers}});
const message = fn => { try { fn(); } catch (error) { return error.message; } assert.fail('export was not refused'); };

test('an alignment over one named MPA names it with the planning margin, and the export is still refused', () => {
  const screen = screenFixture([mpa('Point Test', polygon(6.4, -0.1, 0.2))]);
  assert.equal(message(() => buildExport(request(screen))),
    `Alignment align-a: Inside or within ${PLANNING_MARGIN_M} m of Point Test SMR. Turn off that layer or choose a different spot.`);
  assert.deepEqual(screen.calls.map(c => c.geometries), [[atlasFixture().drifts[0].geometry]]);
});

test('a refused reef outline is labelled as an outline and named', () => {
  // A second copy of the reef id passes the whole-reef check (first match), so only the outline layer meets it.
  const atlas = atlasFixture();
  atlas.areas.push({id: 'reef-a', geometry: polygon(6, 6)});
  const screen = screenFixture([mpa('North Test', polygon(6.4, 6.4, 0.2))]);
  assert.equal(message(() => buildExport(request(screen, {outlines: true}, atlas))),
    `Reef outline reef-a: Inside or within ${PLANNING_MARGIN_M} m of North Test SMR. Turn off that layer or choose a different spot.`);
});

test('two names appear once each; five show three and "and 2 more"', () => {
  const two = screenFixture([mpa('Alpha', polygon(6.2, -0.1, 0.2)), mpa('Alpha', polygon(6.5, -0.1, 0.2)), mpa('Beta', polygon(6.8, -0.1, 0.1))]);
  assert.equal(message(() => buildExport(request(two))),
    `Alignment align-a: Inside or within ${PLANNING_MARGIN_M} m of Alpha SMR, Beta SMR. Turn off that layer or choose a different spot.`);
  const five = screenFixture(['A', 'B', 'C', 'D', 'E'].map((n, i) => mpa(n, polygon(6.1 + i * 0.15, -0.05, 0.1))));
  assert.equal(message(() => buildExport(request(five))),
    `Alignment align-a: Inside or within ${PLANNING_MARGIN_M} m of A SMR, B SMR, C SMR and 2 more. Turn off that layer or choose a different spot.`);
});

test('a stale or unavailable check keeps the exact generic refusal, even when the stale inspection lists names', () => {
  // No reef area, so the stale screen first meets the alignment (as when the check ages out between ready() and the layers).
  const atlas = () => { const a = atlasFixture(); a.targets[0].area_ids = []; return a; };
  const hit = [mpa('Point Test', polygon(6.4, -0.1, 0.2))];
  assert.equal(message(() => buildExport(request(screenFixture(hit, {fresh: false}), undefined, atlas()))), GENERIC);
  assert.equal(message(() => buildExport(request(screenFixture([], {fresh: false}), undefined, atlas()))), GENERIC);
  const unavailable = {...screenFixture(hit), inspect: () => ({status: 'unavailable', fresh: true, names: ['Point Test SMR']})};
  assert.equal(message(() => buildExport(request(unavailable))), GENERIC);
  const unnamed = {...screenFixture(hit), inspect: () => ({status: 'excluded', fresh: true, names: []})};
  assert.equal(message(() => buildExport(request(unnamed))), GENERIC);
});

test('a screen without inspect keeps the exact generic refusal', () => {
  assert.equal(message(() => buildExport(request(screenFixture([mpa('Point Test', polygon(6.4, -0.1, 0.2))], {inspect: false})))), GENERIC);
});

test('allowed outlines and alignments export unchanged without inspecting', () => {
  const screen = screenFixture([mpa('Far Test', polygon(-8, -8, 0.2))]);
  const result = buildExport(request(screen, {outlines: true, alignments: true}));
  assert.equal(result.counts.outlines, 1);
  assert.equal(result.counts.alignments, 1);
  assert.equal(screen.calls.length, 0);
});
