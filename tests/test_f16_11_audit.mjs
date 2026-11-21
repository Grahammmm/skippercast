import assert from 'node:assert/strict';
import test from 'node:test';
import {draftKey} from '../dist/trip-export.js';
import {createPlanner} from '../web/planner.ts';

const now = new Date('2026-10-12T18:00:00Z');
const region = {id: 'test-coast', timezone: 'UTC', mpa: {bounds: [-1, -1, 1, 1]}};
const key = draftKey(region.id);
const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true};
const map = {getBounds: () => ({getWest: () => -1, getSouth: () => -1, getEast: () => 1, getNorth: () => 1})};

function publication(id, digit) {
  return {
    targets: [{id, label: id, canonical_habitat: true, latitude: 0, longitude: 0, habitat_grade: 'A', habitat_score: 90,
      neighborhood_depth_ft: [90, 120], resolution_m: 2, evidence_confidence: {percent: 90}, species_fit: {lingcod: 3, 'rockfish-reef': 3}, area_ids: [id]}],
    areas: [{id, target_ids: [id], geometry: {type: 'Polygon', coordinates: [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]}}],
    publication: {export_sha256: digit.repeat(64), expires_at: '2099-12-31T00:00:00Z', status: 'ready', region: region.id},
  };
}

function mount(store, loadReefs) {
  const writes = [], updates = [];
  const planner = createPlanner({atlas: {targets: [], areas: []}, region, screen, map, now: () => now, getVisible: () => [],
    landWater: async () => () => ({state: 'water'}), loadPorts: async () => ({ports: []}), loadReefs,
    storage: {getItem: k => store.get(k) ?? null, setItem(k, value) { writes.push(k); store.set(k, value); }},
    emit: update => updates.push(update.targets.map(t => t.id)), nav: {open() {}},
  });
  return {planner, writes, updates};
}

for (const operation of ['selectBest', 'restore']) {
  // A draft edit invalidates pending ranking, but merely disposing the old model used
  // to leave its response current: selection overwrote storage, and restore installed a stale ranked atlas.
  test(`F16-11: disposed ${operation} cannot apply its reef response after a new planner opens`, {timeout: 5000}, async t => {
    const store = new Map(), older = publication('old-reef', 'a'), newer = publication('new-reef', 'b');
    if (operation === 'restore') {
      const seed = mount(store, async () => older);
      try {
        await seed.planner.selectBest();
        assert.equal(JSON.parse(store.get(key)).rankedPlan.sha256, older.publication.export_sha256);
      } finally { seed.planner.dispose(); }
    }

    const started = Promise.withResolvers(), held = Promise.withResolvers();
    const old = mount(store, id => { started.resolve(id); return held.promise; });
    t.after(() => { held.resolve(older); });
    old.planner.open();
    const pending = old.planner[operation]();
    assert.equal(await started.promise, region.id, 'the old instance is waiting for this region’s reefs');
    old.planner.dispose();
    const previousAtlas = old.planner.tripAtlas.value;
    const updatesAtDisposal = old.updates.slice();

    const live = mount(store, async () => newer);
    t.after(() => live.planner.dispose());
    live.planner.open();
    await live.planner.selectBest();
    const saved = store.get(key), liveUpdates = live.updates.slice();
    assert.deepEqual(live.writes, [key], 'the live planner writes to the region’s draft key');
    assert.deepEqual(JSON.parse(saved).ids, ['new-reef']);
    assert.deepEqual(liveUpdates.at(-1), ['new-reef'], 'the live planner draws its ranked set');

    held.resolve(older);
    await pending;
    assert.deepEqual(old.writes, [], 'the disposed planner never writes');
    assert.equal(store.get(key), saved, 'the live draft survives unchanged');
    assert.equal(old.planner.tripAtlas.value, previousAtlas, 'the disposed planner never installs a ranked atlas');
    assert.deepEqual(old.updates, updatesAtDisposal, 'no late map updates from the disposed planner');
    assert.deepEqual(live.updates, liveUpdates, 'the live map is unaffected');
  });
}
