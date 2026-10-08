// Profile semantics (FE-04): web/profile.ts against the design § 8 table.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {
  DEFAULT_PROFILE, METHODS, PROFILES, PROFILE_TABLE, RAIL_IDS, TERRAIN_DEPTH_CEILING_FT, isProfile, planMethods, profileSemantics,
  speciesForProfile, terrainDepthLimitFt, withinDepth,
} from '../web/profile.ts';
import {createState, defaultSpecies} from '../packages/coast/src/state/experience.ts';
import {slo} from '../packages/coast/src/counties.ts';

const ROOT = new URL('..', import.meta.url).pathname;

test('the table matches design § 8 row for row', () => {
  assert.deepEqual(PROFILES, ['boat', 'shore', 'spear']);
  assert.equal(DEFAULT_PROFILE, 'boat');
  const rows = {
    boat: {defaultTarget: 'lingcod', maxDepthFt: 300, method: 'boat', fixedSpecies: [], whereToLook: 'reef-fit', swellTile: 'offshore',
      defaultLayers: ['seafloor', 'currents'], caveat: 'Habitat describes a place to look; fish presence is unverified.'},
    shore: {defaultTarget: 'surfperch', maxDepthFt: null, method: 'shore', fixedSpecies: ['surfperch', 'halibut'], whereToLook: 'shore-runs', swellTile: 'nearshore',
      defaultLayers: ['swell', 'water-temp'], caveat: 'Offshore seas do not measure breakers at your beach; check surf, access and water quality.'},
    spear: {defaultTarget: 'cabezon-shallow-reef', maxDepthFt: 60, method: 'dive', fixedSpecies: [], whereToLook: 'reef-shallow', swellTile: 'nearshore',
      defaultLayers: ['seafloor', 'swell'], caveat: 'In-water visibility is unverified; surface currents cannot clear a dive.'},
  };
  for (const [id, row] of Object.entries(rows)) {
    const {id: tableId, label, ...rest} = profileSemantics(id);
    assert.equal(tableId, id);
    assert.equal(label, id[0].toUpperCase() + id.slice(1));
    assert.deepEqual(rest, row, id);
    for (const layer of rest.defaultLayers) assert.ok(RAIL_IDS.includes(layer), `${id}: ${layer} is a rail id`);
    assert.ok(rest.caveat.endsWith('.') && !/\b(?:bite|guarantee|will be)\b/i.test(rest.caveat), `${id}: the caveat promises nothing`);
  }
  assert.ok(isProfile('spear') && !isProfile('kayak') && !isProfile(null));
  assert.deepEqual(METHODS, ['boat', 'shore', 'dive']);
});

test('the § 8 caveats are the ones written in the design', async () => {
  const design = await readFile(`${ROOT}docs/plans/front-end/design.md`, 'utf8');
  for (const profile of PROFILES) assert.ok(design.includes(`"${PROFILE_TABLE[profile].caveat}"`), `${profile} caveat is quoted in design § 8`);
});

test('plans are filtered by method: boat takes every plan, shore the sandy-shore species, dive bottom reef plans', () => {
  const plans = {
    reef: {kind: 'reef', control_mode: 'bottom'},
    halibut: {kind: 'soft', control_mode: 'bottom'},
    'kelp-bass': {kind: 'habitat', control_mode: 'bottom'},
    albacore: {kind: 'offshore', control_mode: 'water-column'},
    yellowtail: {kind: 'pelagic', control_mode: 'water-column'},
    lobster: {kind: 'habitat', control_mode: 'boat-comfort'},
    surfperch: {kind: 'surf', control_mode: 'surf', methods: ['shore']},
  };
  assert.deepEqual(planMethods('reef', plans.reef), ['boat', 'dive']);
  assert.deepEqual(planMethods('halibut', plans.halibut), ['boat', 'shore']);
  assert.deepEqual(planMethods('kelp-bass', plans['kelp-bass']), ['boat', 'dive']);
  assert.deepEqual(planMethods('albacore', plans.albacore), ['boat']);
  assert.deepEqual(planMethods('lobster', plans.lobster), ['boat'], 'boat-comfort control is not a dive plan');
  assert.deepEqual(planMethods('surfperch', plans.surfperch), ['shore'], 'an explicit methods list wins');
  assert.deepEqual(planMethods('mystery', {}), [], 'an unknown kind fits no method');
  assert.deepEqual(speciesForProfile(plans, 'boat'), ['lingcod', 'reef', 'halibut', 'kelp-bass', 'albacore', 'yellowtail', 'lobster']);
  assert.deepEqual(speciesForProfile(plans, 'shore'), ['surfperch', 'halibut']);
  assert.deepEqual(speciesForProfile(plans, 'spear'), ['cabezon-shallow-reef', 'reef', 'kelp-bass']);
});

test('the published Morro Bay plans all fit the boat profile and only bottom reef plans fit a dive', async () => {
  const {profiles} = JSON.parse(await readFile(`${ROOT}dist/regions/morro-bay/search-plans.json`, 'utf8'));
  const ids = Object.keys(profiles);
  assert.ok(ids.length > 0);
  for (const id of ids) assert.ok(planMethods(id, profiles[id]).includes('boat'), `${id} is a boat plan`);
  assert.deepEqual(speciesForProfile(profiles, 'spear').filter(id => id in profiles), ['reef']);
  assert.deepEqual(speciesForProfile(profiles, 'shore').filter(id => id in profiles), ['halibut']);
});

test('depth limits: 300 ft boat, 60 ft spear, none for shore; unknown depth stays in', () => {
  assert.equal(withinDepth('boat', 250), true);
  assert.equal(withinDepth('boat', 301), false);
  assert.equal(withinDepth('spear', 60), true);
  assert.equal(withinDepth('spear', 61), false);
  assert.equal(withinDepth('shore', 5000), true);
  assert.equal(withinDepth('spear', null), true);
  assert.equal(withinDepth('spear', Number.NaN), true);
});

test('PROFILE_TABLE depth limits and default targets equal packages/coast experience.ts', () => {
  // A synthetic, empty report at a fixed instant: createState only needs the shape.
  const now = new Date('2026-10-06T18:00:00Z');
  const report = {schemaVersion: 1, countyId: 'slo', generatedAt: now.toISOString(), forecasts: [], observations: [], tides: [], tideEvents: [],
    alerts: [], sources: [], catches: [], catchStatus: 'none', visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, habitatStatus: 'none'};
  assert.equal(TERRAIN_DEPTH_CEILING_FT, 300);
  assert.deepEqual(PROFILES.map(terrainDepthLimitFt), [300, 300, 60], 'boat 300, shore the ceiling, spear 60');
  for (const profile of PROFILES) {
    const state = createState(report, slo, profile, slo.defaultAreaId, undefined, undefined, now);
    assert.equal(state.maxDepth, terrainDepthLimitFt(profile), `${profile}: experience.ts maxDepth`);
    assert.equal(defaultSpecies(profile), PROFILE_TABLE[profile].defaultTarget, `${profile}: experience.ts defaultSpecies`);
    assert.equal(state.species, PROFILE_TABLE[profile].defaultTarget, `${profile}: createState selects the default target`);
  }
});
