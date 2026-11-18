// SCA-608 / F16-12: the saved trip-alert request keeps each leg's water/straight basis, or else the saved view must not
// show an unqualified distance; an old record with no basis reads 'unknown', never 'water'. Offline synthetic fixture
// (fabricated stop names and coordinates, no network, no account rows). Valid controls must satisfy the contract. The
// affected control (the real buildAlertPlan output) is only *observed* (diagnostic): the test neither asserts the gap
// is desirable nor fails when it is fixed. A synthetic negative control proves the detector.
import test from 'node:test';
import assert from 'node:assert/strict';
import {buildAlertPlan} from '../web/planner-alerts.ts';

const NOW = Date.parse('2026-10-08T17:00:00Z');
const region = {id: 'fixture', timezone: 'America/Los_Angeles', species: ['salmon'], forecast_points: [{id: 'fp1', name: 'Fixture area', latitude: 35.1, longitude: -121}]};
const settings = {profile: 'boat', ownBoatLimits: false, limits: {wind: 8, gust: 12, seas: 3}, factors: {sea: 1, wind: 1, custom: false}, boat: null};
const stops = [{id: 'a', name: 'Fixture A', lat: 35.1, lon: -121}, {id: 'b', name: 'Fixture B', lat: 35.2, lon: -121.1}, {id: 'h', name: 'Fixture Harbor', lat: 35.0, lon: -121, launch: true}];
const leg = (from, to, basis) => ({from, to, nm: 3.2, runMin: 20, basis, screen: {}});
// Two legs: one water-routed, one straight-line fallback.
const input = {region, now: NOW, date: '2026-10-09', stops, unresolved: false, species: 'salmon', settings, refused: () => false,
  legs: () => ({legs: [leg('Fixture A', 'Fixture B', 'water'), leg('Fixture B', 'Fixture Harbor', 'straight')], skipped: []})};

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
  assert.equal(contract([{from: 'A', to: 'B', nm: 3.2, minutes: 20, basis: 'water'}, {from: 'B', to: 'C', nm: 4, minutes: 25}]), false, 'one untagged leg must be detected');
  assert.equal(contract([{from: 'A', to: 'B', nm: 4, minutes: 25, basis: 'straight'}]), false, 'basis tag with lost boundary qualification must be detected');
  assert.equal(contract([{from: 'A', to: 'B', nm: 4, minutes: 25, basis: 'straight', screen: {}}]), false, 'empty qualification must be detected');
  assert.equal(contract([]), false);
});

test('affected control: baseline observation only (passes before and after a fix)', t => {
  const r = buildAlertPlan(input);
  assert.equal(r.ok, true, 'fixture plan must build');
  // The preview already carries basis per leg (the valid side of the contract).
  assert.deepEqual(r.preview.legList.map(l => l.basis), ['water', 'straight']);
  const saved = roundTrip(r.body.plan.legs);
  t.diagnostic(`saved legs=${saved.length} keys=${Object.keys(saved[0]).join(',')} bases=${saved.map(basisOf).join(',')} qualification=${saved.map(qualOf).join(',')} contractHolds=${contract(saved)}`);
});
