// SCA-608 / F16-12: the saved trip-alert request keeps each leg's water/straight basis, or else the saved view must not
// show an unqualified distance; an old record with no basis reads 'unknown', never 'water'. Offline synthetic fixture
// (fabricated stop names and coordinates, no network, no account rows). Keep the independent controls, then exercise
// the real planner projection, server validator and parsed-row reader, and render the saved result.
import test from 'node:test';
import assert from 'node:assert/strict';
import {buildAlertPlan} from '../web/planner-alerts.ts';
import {PLANNING_MARGIN_M} from '../dist/geo-screen.js';
import {tripPlanSummary, tripRecaps} from '../web/alerts.ts';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const NOW = Date.parse('2026-10-08T17:00:00Z');
const region = {id: 'fixture', timezone: 'America/Los_Angeles', species: ['salmon'], forecast_points: [{id: 'fp1', name: 'Fixture area', latitude: 0, longitude: 0}]};
globalThis.REGIONS = {fixture: region};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {validateTrip, validateTripPlan, PLAN_LIMITS} = await import('../server/trips.ts');
const {publicTrip} = await import('../server/routes/trips.ts');
const settings = {profile: 'boat', ownBoatLimits: false, limits: {wind: 8, gust: 12, seas: 3}, factors: {sea: 1, wind: 1, custom: false}, boat: null};
const stops = [{id: 'a', name: 'Fixture A', lat: 0, lon: 0}, {id: 'b', name: 'Fixture B', lat: 0.1, lon: 0}, {id: 'h', name: 'Fixture Harbor', lat: 0.2, lon: 0, launch: true}];
const leg = (from, to, basis, screen) => ({from, to, nm: basis === 'water' ? 3.2 : 4, runMin: 20, basis,
  screen: {name: 'BOUNDARY-SENTINEL', geometry: {type: 'LineString', coordinates: [[0, 0], [0, 1]]}, ...screen}});
// Two legs: one water-routed, one straight-line fallback.
const input = {region, now: NOW, date: '2026-10-09', stops, unresolved: false, species: 'salmon', settings, refused: () => false,
  legs: () => ({legs: [leg('Fixture A', 'Fixture B', 'water', {inside: false, screened: true, distanceM: PLANNING_MARGIN_M}),
    leg('Fixture B', 'Fixture Harbor', 'straight', {inside: true, screened: true, distanceM: 0})], skipped: []})};

// What a later reader can say about a saved leg. Only an explicit tag counts; an untagged (old) record is unknown.
const basisOf = l => (l && (l.basis === 'water' || l.basis === 'straight')) ? l.basis : 'unknown';
// Contract, either outcome: every saved leg carries its basis, or it carries no distance at all (withheld).
// Qualification = the preview's boundary verdict kept as a historical note (as screened at save time, never a current
// verdict): {inside, screened} booleans. A basis tag alone is not enough; a straight/water distance also needs it.
const qualOf = l => (l && l.screen && typeof l.screen.inside === 'boolean' && typeof l.screen.screened === 'boolean') ? 'recorded' : 'none';
const qualified = l => (basisOf(l) !== 'unknown' && qualOf(l) === 'recorded') || !('nm' in l);
const contract = legs => legs.length > 0 && legs.every(qualified);
// Round trip through the JSON the POST body travels as.
const roundTrip = v => JSON.parse(JSON.stringify(v));

test('old untagged records read unknown, never water', () => {
  const old = {from: 'Fixture A', to: 'Fixture B', nm: 3.2, minutes: 20};
  assert.equal(basisOf(old), 'unknown');
  assert.equal(basisOf({...old, basis: 'bogus'}), 'unknown');
  assert.equal(basisOf({...old, basis: 'water'}), 'water');
  assert.equal(basisOf({...old, basis: 'straight'}), 'straight');
});

test('valid controls satisfy the contract and round-trip both bases', () => {
  const sc = {inside: false, name: null, distanceM: null, screened: true};
  const tagged = roundTrip([{from: 'A', to: 'B', nm: 3.2, minutes: 20, basis: 'water', screen: sc}, {from: 'B', to: 'C', nm: 4, minutes: 25, basis: 'straight', screen: {...sc, inside: true, name: 'Fixture area'}}]);
  assert.ok(contract(tagged));
  assert.deepEqual(tagged.map(basisOf), ['water', 'straight']);
  assert.deepEqual(tagged.map(l => l.screen.inside), [false, true], 'qualification survives the round trip per leg');
  const withheld = roundTrip([{from: 'A', to: 'B', minutes: 20}]);
  assert.ok(contract(withheld), 'a distance-free leg is acceptable');
});

test('checker detects the stated gap on synthetic results', () => {
  // independent negative control: fabricated saved legs, no dependence on buildAlertPlan
  assert.equal(contract([{from: 'A', to: 'B', nm: 3.2, minutes: 20}]), false, 'unqualified distance must be detected');
  assert.equal(contract([{from: 'A', to: 'B', nm: 3.2, minutes: 20, basis: 'water', screen: {inside: false, screened: true}}, {from: 'B', to: 'C', nm: 4, minutes: 25}]), false, 'one untagged leg must be detected');
  assert.equal(contract([{from: 'A', to: 'B', nm: 4, minutes: 25, basis: 'straight'}]), false, 'basis tag with lost boundary qualification must be detected');
  assert.equal(contract([{from: 'A', to: 'B', nm: 4, minutes: 25, basis: 'straight', screen: {}}]), false, 'empty qualification must be detected');
  assert.equal(contract([]), false);
});

test('planner leg qualifications survive request, validation, stored JSON and saved display', async t => {
  const r = buildAlertPlan(input);
  assert.equal(r.ok, true, 'fixture plan must build');
  // The preview already carries basis per leg (the valid side of the contract).
  assert.deepEqual(r.preview.legList.map(l => l.basis), ['water', 'straight']);
  const request = roundTrip(r.body);
  t.diagnostic(`request bases=${request.plan.legs.map(basisOf)} qualification=${request.plan.legs.map(qualOf)}`);
  assert.ok(contract(request.plan.legs), 'planner request must qualify its distances');
  assert.doesNotMatch(JSON.stringify(request.plan.legs), /BOUNDARY-SENTINEL|geometry|distanceM/);

  // POST serializes the validated plan; GET's row reader parses those same bytes.
  const validated = validateTrip(request, NOW);
  const row = {id: 'fixture', ...validated, plan: JSON.stringify(validated.plan), targets: JSON.stringify(validated.targets)};
  const read = publicTrip(row);
  assert.ok(contract(read.plan.legs), 'validation and storage must not strip the qualifications');
  assert.deepEqual(read.plan.legs.map(l => [l.basis, l.screen]), [
    ['water', {inside: false, screened: true, near: true}], ['straight', {inside: true, screened: true}],
  ]);
  const legacyLeg = {from: 'LEGACY-SENTINEL', to: 'Old stop', nm: 1.25, minutes: 8};
  const legacy = publicTrip({...row, plan: JSON.stringify({...validated.plan, legs: [legacyLeg]})});
  assert.equal(tripPlanSummary(legacy).legs[0].basis, 'unknown');
  assert.equal(tripPlanSummary({...legacy, plan: {...legacy.plan, legs: [{...legacyLeg, basis: 'bogus'}]}}).legs[0].basis, 'unknown');
  assert.deepEqual(validateTripPlan(legacy, region, 'salmon').plan.legs, [legacyLeg], 'legacy input still validates without inventing a tag');

  const compiled = await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {SavedTrips} from './web/app/TripAlerts.tsx';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'silent',
    jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  const {SavedTrips, render, h} = await import(`data:text/javascript,${encodeURIComponent(compiled.outputFiles[0].text)}`);
  const draw = trip => render(h(SavedTrips, {recaps: tripRecaps([trip], [], [], '2026-10-08'),
    names: {point: new Map(), species: new Map()}, remove: () => () => {}, useAgain: () => {}}));
  const html = draw(read);
  assert.match(html, /Not re-checked since it was saved\./);
  assert.match(html, /Not for navigation\./);
  assert.match(html, /Saved leg totals: 7\.2 nm · 40 min · Source: by water \/ straight line/);
  assert.match(html, /Fixture A → Fixture B · 3\.2 nm by water[^<]*Within 70 m of a protected area\./);
  assert.match(html, /Fixture B → Fixture Harbor · 4 nm straight line[^<]*Route crosses or touches a protected area\./);
  assert.doesNotMatch(html, /BOUNDARY-SENTINEL|geometry|distanceM/);
  const oldHtml = draw(legacy);
  assert.match(oldHtml, /Saved leg totals: 1\.25 nm · 8 min · Source: not recorded/);
  assert.doesNotMatch(oldHtml, /by water|straight line|LEGACY-SENTINEL/);
});

test('maximal planner snapshot fits the existing limits; a missing preview screen stays unchecked', () => {
  // Extra metadata must fit, and a missing preview screen must not become a negative protected-area finding.
  const name = '界'.repeat(80), longLeg = {from: name, to: name, nm: 300, runMin: 1440, basis: 'straight'};
  const r = buildAlertPlan({...input, stops: Array.from({length: 12}, (_, i) => ({...stops[0], id: `stop-${i}`, name})),
    legs: () => ({legs: Array.from({length: 13}, () => longLeg), skipped: []})});
  assert.equal(r.ok, true);
  assert.ok(Buffer.byteLength(JSON.stringify(r.body)) <= PLAN_LIMITS.body);
  const saved = validateTrip(roundTrip(r.body), NOW);
  assert.equal(saved.plan.spots.length, 12);
  assert.equal(saved.plan.legs.length, 13);
  assert.deepEqual(saved.plan.legs[0].screen, {inside: false, screened: false});
  assert.equal(tripPlanSummary(saved).legs[0].check, 'unchecked');
});

test('leg validation accepts only the compact historical metadata and rejects malformed qualifiers', () => {
  const screen = {inside: false, screened: true};
  const saved = {from: 'A', to: 'B', nm: 4, minutes: 20, basis: 'straight', screen};
  const validate = leg => validateTripPlan({plan: {legs: [leg]}}, region, 'salmon').plan.legs[0];
  assert.deepEqual(validate({...saved, path: [0, 0], screen: {...screen, geometry: ['private'], name: 'private'}}), saved,
    'the server never stores extra leg or boundary fields');
  for (const leg of [{...saved, basis: 'bogus'}, {...saved, screen: undefined}, {...saved, basis: undefined},
    {...saved, screen: {...screen, screened: 'true'}}, {...saved, screen: {inside: true, screened: false}},
    {...saved, screen: {inside: false, screened: false, near: true}}]) {
    assert.throws(() => validate(roundTrip(leg)), /invalid leg/);
  }
});
