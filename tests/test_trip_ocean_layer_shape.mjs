// RF1410-3: the Trip dialog's ocean coverage lines stay readable when a persisted regional ocean record has no usable `layers` container
// (web/trip-ocean-lines.ts). Synthetic JSON-compatible metadata against the production helper; no network.
import assert from 'node:assert/strict';
import test from 'node:test';

const {oceanLines} = await import('../web/trip-ocean-lines.ts');
const SST = 'sst-analysis', WCOFS = 'wcofs-surface-forecast', UNTIL = '2026-10-16T12:00:00.000Z';
const NOW = new Date('2026-10-16T11:00:00Z');
const NOT_SAVED = {water: 'not saved', currents: 'not saved'};
const rec = (state, extra = {}) => ({state, tiles: {saved: 0, listed: 1}, bytes: 0, ...extra});
const saved = () => rec('saved', {drawable_until: UNTIL});
const persisted = ocean => JSON.parse(JSON.stringify({ocean}));

test.beforeEach(() => { globalThis.fetch = () => { throw new Error('no network'); }; });

test('a regional record with layers omitted, undefined or null (as persisted JSON) falls back to not saved without throwing', () => {
  assert.deepEqual(oceanLines(persisted({schema_version: 1, path: 'regional'}), NOW), NOT_SAVED);
  assert.deepEqual(oceanLines({ocean: {schema_version: 1, path: 'regional', layers: undefined}}, NOW), NOT_SAVED);
  assert.deepEqual(oceanLines(persisted({schema_version: 1, path: 'regional', layers: null}), NOW), NOT_SAVED);
  assert.deepEqual(oceanLines({ocean: {layers: null}}, NOW, 'UTC'), NOT_SAVED, 'no path at all is the default regional branch');
});

test('arrays, strings, numbers and booleans as layers fall back like an empty map', () => {
  const empty = oceanLines({ocean: {path: 'regional', layers: {}}}, NOW);
  assert.deepEqual(empty, NOT_SAVED);
  for (const layers of [[], [saved(), saved()], '', 'sst-analysis', 5, 0, true, false]) {
    assert.deepEqual(oceanLines(persisted({path: 'regional', layers}), NOW), NOT_SAVED, JSON.stringify(layers));
  }
});

test('a valid layer beside an absent, null or unknown sibling keeps its own line; only the sibling falls back', () => {
  for (const zone of ['UTC', 'America/Los_Angeles']) {
    const both = oceanLines({ocean: {path: 'regional', layers: {[SST]: saved(), [WCOFS]: saved()}}}, NOW, zone);
    for (const sibling of [undefined, null, rec('mystery')]) {
      const water = oceanLines(persisted({path: 'regional', layers: {[SST]: saved(), [WCOFS]: sibling}}), NOW, zone);
      assert.deepEqual(water, {water: both.water, currents: 'not saved'}, `${zone} water saved, currents ${JSON.stringify(sibling)}`);
      const currents = oceanLines(persisted({path: 'regional', layers: {[SST]: sibling, [WCOFS]: saved()}}), NOW, zone);
      assert.deepEqual(currents, {water: 'not saved', currents: both.currents}, `${zone} currents saved, water ${JSON.stringify(sibling)}`);
    }
  }
  assert.equal(oceanLines({ocean: {path: 'regional', layers: {[SST]: saved()}}}, NOW, 'UTC').water, 'saved · not shown after Fri 12 pm · only for hours on or after the analysis');
  assert.equal(oceanLines({ocean: {path: 'regional', layers: {[WCOFS]: saved()}}}, NOW, 'America/Los_Angeles').currents, 'saved · not shown after Fri 5 am · only for forecast hours');
  const late = oceanLines({ocean: {path: 'regional', layers: {[SST]: saved(), [WCOFS]: null}}}, new Date(UNTIL));
  assert.deepEqual(late, {water: 'saved · past its age limit', currents: 'not saved'}, 'an expired layer stays expired beside a null sibling');
  assert.deepEqual(oceanLines({ocean: {path: 'regional', layers: {[SST]: rec('over-cap'), [WCOFS]: null}}}, NOW), {water: 'not saved: too large for this pack', currents: 'not saved'});
});

test('no ocean record is null; none and coastal-report keep their exact lines even with null layers', () => {
  assert.equal(oceanLines({}, NOW), null);
  assert.equal(oceanLines({ocean: undefined}, NOW), null);
  assert.equal(oceanLines({ocean: null}, NOW), null);
  const none = {water: 'not published for this area', currents: 'not published for this area'};
  assert.deepEqual(oceanLines({ocean: {path: 'none', layers: null}}, NOW), none);
  assert.deepEqual(oceanLines({ocean: {path: 'none'}}, NOW), none);
  const coastal = line => ({water: line, currents: line});
  assert.deepEqual(oceanLines({ocean: {path: 'coastal-report', layers: null, coastal: {saved_at: '2026-10-15T17:30:00.000Z'}}}, NOW, 'America/Los_Angeles'), coastal('from Coastal readings (saved Thu 10 am)'));
  assert.deepEqual(oceanLines({ocean: {path: 'coastal-report', coastal: null}}, NOW), coastal('from Coastal readings (not saved)'));
});

test('the helper does not mutate the record it reads', () => {
  const metas = [{ocean: {path: 'regional', layers: null}}, {ocean: {path: 'regional', layers: {[SST]: saved(), [WCOFS]: null}}}, {ocean: {path: 'regional'}}];
  for (const meta of metas) {
    const before = JSON.stringify(meta);
    const deep = o => { if (o && typeof o === 'object') { Object.freeze(o); Object.values(o).forEach(deep); } return o; };
    oceanLines(deep(meta), NOW);
    assert.equal(JSON.stringify(meta), before);
  }
});
