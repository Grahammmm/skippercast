// SC1352-11: a browser that refuses site data throws from the localStorage getter itself (SecurityError).
// The trip ids, the planner and the six first-run exports read it through one guarded getter and carry on without storage.
// Offline: every module is imported before the getter is blocked; globals are restored after each case.
import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.REGIONS = undefined;
const {browserStorage} = await import('../dist/browser-storage.js');
const trip = await import('../web/trip.ts');
const {createPlanner} = await import('../web/planner.ts');
const first = await import('../dist/first-run.js');
const {draftKey} = await import('../dist/trip-export.js');
const {BOAT_KEY} = await import('../dist/boat-handling.js');

const blocked = () => { throw new DOMException('site data blocked', 'SecurityError'); };
/** Run `fn` with the named globals replaced, restoring the exact descriptors afterwards. */
function withGlobals(values, fn) {
  const saved = Object.keys(values).map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]);
  try {
    for (const [k, v] of Object.entries(values)) Object.defineProperty(globalThis, k, v);
    return fn();
  } finally {
    for (const [k, d] of saved) { if (d) Object.defineProperty(globalThis, k, d); else Reflect.deleteProperty(globalThis, k); }
  }
}
const throwing = {localStorage: {configurable: true, get: blocked}};
const memory = () => { const data = new Map(); return {data, getItem: k => data.has(k) ? data.get(k) : null, setItem: (k, v) => data.set(k, String(v)), removeItem: k => data.delete(k)}; };

const NOW = new Date('2026-10-12T18:00:00Z');
const REGION = {id: 'test-coast', name: 'Test Coast', timezone: 'America/Los_Angeles', mpa: {bounds: [-10, -10, 10, 10]}};
const ATLAS = {targets: [{id: 'old-1', label: 'Old 1', latitude: 0.5, longitude: 0.5, habitat_grade: 'B', center_depth_ft: 80, neighborhood_depth_ft: [70, 90]}], areas: [], drifts: []};
const SCREEN = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, exportExclusions: () => ({features: [], checked_at: NOW.toISOString()})};
const MAP = {getSize: () => ({x: 512, y: 512}), getBounds: () => ({getWest: () => -1, getEast: () => 1, getNorth: () => 1, getSouth: () => -1, contains: () => true})};
const planner = (extra = {}) => createPlanner({atlas: ATLAS, screen: SCREEN, region: REGION, map: MAP, getVisible: () => [], now: () => NOW,
  landWater: async () => () => ({state: 'water'}), loadReefs: async () => ({targets: [], areas: []}), emit: () => {}, nav: {open() {}, showMap() {}, conditions() {}}, ...extra});

test('the shared getter returns working storage, and null when the getter throws or storage is absent', () => {
  const s = memory();
  assert.equal(withGlobals({localStorage: {configurable: true, value: s}}, browserStorage), s);
  assert.equal(withGlobals(throwing, browserStorage), null);
  assert.equal(withGlobals({localStorage: {configurable: true, value: undefined}}, browserStorage), null);
});

test('saved_ids_and_start_trip_throwing_storage_getter', () => {
  withGlobals(throwing, () => assert.deepEqual(trip.savedIds('test-coast'), []));
  withGlobals({localStorage: {configurable: true, value: undefined}}, () => assert.deepEqual(trip.savedIds('test-coast'), []));
  // Working storage and an injected one are read as before.
  const s = memory(); s.setItem(draftKey('test-coast'), JSON.stringify({ids: ['a', 'a', 'b', 3]}));
  assert.deepEqual(trip.savedIds('test-coast', s), ['a', 'b']);
  withGlobals({localStorage: {configurable: true, value: s}}, () => assert.deepEqual(trip.savedIds('test-coast'), ['a', 'b']));
  assert.deepEqual(trip.savedIds('test-coast', null), []);
  assert.deepEqual(trip.savedIds(null, s), []);
  // startTrip's first refresh runs through region.subscribe with the getter blocked.
  const listeners = [], intervals = [];
  trip.tripIds.value = ['stale'];
  withGlobals({...throwing, location: {configurable: true, value: {hash: '', href: 'https://fixture.test/map'}}, document: {configurable: true, value: {addEventListener: (n, f) => listeners.push(n)}},
    addEventListener: {configurable: true, value: (n) => listeners.push(n)}, setInterval: {configurable: true, value: f => intervals.push(f) && 0}}, () => {
    assert.doesNotThrow(() => trip.startTrip());
  });
  assert.deepEqual(trip.tripIds.value, []);
  assert.ok(listeners.includes('hashchange') && listeners.includes('storage') && listeners.includes('skippercast:trip-ranked'), 'start-up listeners still installed');
  assert.equal(intervals.length, 1, 'the recheck timer is still scheduled');
});

test('planner_throwing_getter_keeps_visit_draft', () => {
  const p = withGlobals(throwing, () => planner());
  try {
    assert.match(p.storageNote.value, /storage is unavailable/);
    withGlobals(throwing, () => p.toggleSpot('old-1', true));
    assert.deepEqual(p.draft.value.ids, ['old-1'], 'the edit survives in memory');
    assert.match(p.storageNote.value, /storage is unavailable/, 'no successful browser save is announced');
  } finally { p.dispose(); }
});

test('planner_explicit_storage_bypasses_global_getter', () => {
  const nullStore = withGlobals(throwing, () => planner({storage: null}));
  try {
    assert.match(nullStore.storageNote.value, /storage is unavailable/);
    nullStore.toggleSpot('old-1', true);
    assert.deepEqual(nullStore.draft.value.ids, ['old-1']);
    assert.match(nullStore.storageNote.value, /storage is unavailable/);
  } finally { nullStore.dispose(); }
  const s = memory();
  const working = withGlobals(throwing, () => planner({storage: s}));
  try {
    assert.match(working.storageNote.value, /^Saved on this browser/);
    working.toggleSpot('old-1', true);
    assert.deepEqual(JSON.parse(s.data.get(draftKey('test-coast'))).ids, ['old-1']);
    assert.match(working.storageNote.value, /^Saved on this browser/);
  } finally { working.dispose(); }
  const failing = planner({storage: {getItem() { throw Error('read'); }, setItem() { throw Error('write'); }}});
  try {
    failing.toggleSpot('old-1', true);
    assert.deepEqual(failing.draft.value.ids, ['old-1']);
    assert.match(failing.storageNote.value, /storage is unavailable/);
  } finally { failing.dispose(); }
});

test('first_run_exports_throwing_getter', () => {
  withGlobals(throwing, () => {
    assert.equal(first.pendingStep(), null);
    assert.equal(first.startFirstRun(), false);
    assert.equal(first.advance(), false);
    assert.equal(first.finish(), false);
    assert.equal(first.savePreset('skiff'), false);
    assert.equal(first.initFirstRun(), null);
  });
});

test('first_run_injected_storage_with_global_blocked', () => {
  const s = memory(), now = new Date('2026-10-12T18:00:00Z');
  withGlobals(throwing, () => {
    assert.equal(first.startFirstRun(s), true);
    assert.equal(first.pendingStep(s), 'boat');
    assert.equal(first.advance(s), true);
    assert.equal(first.pendingStep(s), 'answer');
    assert.equal(first.savePreset('skiff', s, now), true);
    const saved = JSON.parse(s.data.get(BOAT_KEY));
    assert.deepEqual([saved.preset, saved.saved_at, saved.boat.loa_ft], ['skiff', now.toISOString(), 17]);
    assert.equal(first.finish(s), true);
    assert.equal(first.pendingStep(s), null);
    assert.equal(first.savePreset('nope', s, now), false);
    s.setItem(first.FIRST_RUN_KEY, 'malformed');
    assert.equal(first.pendingStep(s), null);
  });
});

test('a first-run write with working global storage uses it', () => {
  const s = memory();
  withGlobals({localStorage: {configurable: true, value: s}}, () => {
    assert.equal(first.startFirstRun(), true);
    assert.equal(first.pendingStep(), 'boat');
  });
  assert.equal(s.data.get(first.FIRST_RUN_KEY), 'boat');
});
