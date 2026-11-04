import test, {beforeEach, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {stationsInRegion, saveSavedTideStations, readSavedTideStations, tidePackURLs, TIDE_DIRECTORY_URL} from '../web/tide-stations.ts';
import {createTideSelection} from '../web/tide-selection.ts';

// An in-flight directory load that finishes after the selection changed may return its rows to its own caller
// but must not write stations or an error into the newer UI state. Synthetic stations and fixtures only.
const a = {id: '9000001', name: 'Fixture reference', lat: 35.1, lng: -121, type: 'R'};
const b = {id: '9000002', name: 'Fixture subordinate', lat: 35.8, lng: -121, type: 'S'};
const c = {...b, id: '9000005', name: 'Fixture third'}, d = {...a, id: '9000006', name: 'Fixture fourth'};
const config = {id: 'fixture', bounds: [-122, 35, -120, 36], station: a.id, name: a.name};
const other = {...config, id: 'other-region'};
const directory = {stations: [a, b, c, d]};
const hilo = {predictions: [{t: '2026-10-08 18:00', v: '3.2', type: 'H'}, {t: '2026-10-09 18:00', v: '3.3', type: 'H'}]};
const curve = {predictions: [{t: '2026-10-08 17:00', v: '1.2'}, {t: '2026-10-08 17:06', v: '1.3'}]};
const now = Date.parse('2026-10-08T17:00:00Z');
const DIRECTORY_ERROR = 'NOAA station directory unavailable. Retry when connected.';
const flush = () => new Promise(resolve => setImmediate(resolve));
const memory = () => {
  const values = new Map();
  return {values, getItem: k => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: k => values.delete(k)};
};
const realFetch = globalThis.fetch;
let held;
beforeEach(() => { globalThis.fetch = () => { throw new Error('unexpected global fetch'); }; });
afterEach(() => {
  globalThis.fetch = realFetch;
  for (const request of held?.pending ?? []) request.reject(new Error('released by test cleanup'));
});

/** Injected fetcher: every directory request waits for release()/reject(); prediction requests answer at once. */
function holdDirectory() {
  held = {directoryCalls: 0, predictionCalls: [], pending: []};
  const state = held;
  state.fetcher = async url => {
    if (url === TIDE_DIRECTORY_URL) {
      state.directoryCalls++;
      return new Promise((resolve, reject) => state.pending.push({resolve: () => resolve(Response.json(directory)), reject}));
    }
    state.predictionCalls.push(url);
    return Response.json(new URL(url).searchParams.get('interval') === 'hilo' ? hilo : curve);
  };
  state.release = () => state.pending.splice(0).forEach(r => r.resolve());
  state.fail = () => state.pending.splice(0).forEach(r => r.reject(new Error('directory down')));
  return state;
}
function restored(saved, active) {
  const storage = memory();
  saveSavedTideStations(config.id, {saved, active}, storage);
  return storage;
}
function assertQuiet(model, state, label) {
  assert.equal(model.error.value, '', `${label}: no abandoned directory error`);
  assert.equal(model.loading.value, false, `${label}: not loading`);
  assert.equal(model.reading.value, null, `${label}: no reading`);
  assert.deepEqual(model.stations.value, [], `${label}: no obsolete rows`);
  assert.deepEqual(state.predictionCalls, [], `${label}: no prediction request`);
}
const ids = rows => rows.map(s => s.id);
const expectedRows = ids(stationsInRegion(directory, config.bounds));

test('obsolete_directory_failure_after_default_is_ignored', {timeout: 5000}, async () => {
  const state = holdDirectory(), storage = restored([b.id, c.id], b.id);
  const model = createTideSelection(state.fetcher, storage);
  model.configure(config); await flush();
  assert.equal(model.choice.value, b.id); assert.equal(model.loading.value, true);
  assert.equal(model.choose(null), true);
  state.fail(); await flush();
  assert.equal(model.choice.value, null);
  assertQuiet(model, state, 'after default');
  assert.deepEqual(model.saved.value, [b.id, c.id], 'saved list intact');
  assert.deepEqual(readSavedTideStations(config.id, storage), {saved: [b.id, c.id], active: null});
  assert.equal(state.directoryCalls, 1);
});

test('obsolete_directory_failure_after_active_removal_is_ignored', {timeout: 5000}, async () => {
  const state = holdDirectory(), storage = restored([b.id, c.id], c.id);
  const model = createTideSelection(state.fetcher, storage);
  model.configure(config); await flush();
  model.remove(c.id);
  state.fail(); await flush();
  assert.equal(model.choice.value, null);
  assertQuiet(model, state, 'after active removal');
  assert.deepEqual(model.saved.value, [b.id]);
  assert.deepEqual(readSavedTideStations(config.id, storage), {saved: [b.id], active: null});

  const sole = holdDirectory(), soleStorage = restored([b.id], b.id);
  const alone = createTideSelection(sole.fetcher, soleStorage);
  alone.configure(config); await flush();
  alone.remove(b.id); sole.fail(); await flush();
  assertQuiet(alone, sole, 'after removing the only saved station');
  assert.deepEqual(alone.saved.value, []);
  assert.deepEqual(readSavedTideStations(config.id, soleStorage), {saved: [], active: null});
});

test('obsolete_directory_failure_after_reconfigure_is_ignored', {timeout: 5000}, async () => {
  for (const next of [null, other]) {
    const state = holdDirectory(), storage = restored([b.id], b.id);
    const model = createTideSelection(state.fetcher, storage);
    model.configure(config); await flush();
    model.configure(next);
    state.fail(); await flush();
    assertQuiet(model, state, next ? 'other region' : 'no region');
    assert.deepEqual(model.saved.value, []);
    assert.deepEqual(readSavedTideStations(config.id, storage), {saved: [b.id], active: b.id}, 'the abandoned region keeps its choice');
  }
});

test('obsolete_directory_success_cannot_publish_rows', {timeout: 5000}, async () => {
  const invalidators = {
    default: (model) => model.choose(null),
    removal: (model) => model.remove(b.id),
    reconfigure: (model) => model.configure(other),
    'new refresh': (model) => { void model.refresh(); },
  };
  for (const [label, invalidate] of Object.entries(invalidators)) {
    const state = holdDirectory(), model = createTideSelection(state.fetcher, restored([b.id], b.id));
    model.configure(config);
    const old = model.list();
    await flush();
    invalidate(model);
    state.release();
    const rows = await old; await flush();
    assert.deepEqual(ids(rows), expectedRows, `${label}: the obsolete list still resolves to its rows`);
    if (label === 'new refresh') {
      assert.deepEqual(ids(model.stations.value), expectedRows, 'the current refresh publishes its own rows');
      assert.equal(model.reading.value?.station.id, b.id, 'the current refresh loads the chosen station');
    } else if (label === 'reconfigure') {
      assert.deepEqual(model.stations.value, [], `${label}: rows of the abandoned region are not shown`);
      assert.equal(model.error.value, ''); assert.equal(model.loading.value, false);
    } else {
      assertQuiet(model, state, label);
    }
  }
});

test('shared_directory_failure_still_reaches_current_generation', {timeout: 5000}, async () => {
  const state = holdDirectory(), storage = restored([b.id, c.id, d.id], b.id);
  const model = createTideSelection(state.fetcher, storage);
  model.configure(config); await flush();
  const current = model.refresh();
  await flush();
  model.remove(c.id); // a non-active saved station must not end the current request or hide its error
  assert.equal(model.loading.value, true);
  state.fail(); await current; await flush();
  assert.equal(state.directoryCalls, 1, 'one shared directory request');
  assert.equal(model.error.value, DIRECTORY_ERROR);
  assert.equal(model.loading.value, false);
  assert.equal(model.reading.value, null);
  assert.deepEqual(state.predictionCalls, []);
  assert.equal(model.choice.value, b.id);
  model.remove(d.id);
  assert.equal(model.error.value, DIRECTORY_ERROR, 'removing a non-active station keeps the current directory failure');
});

test('current_default_chooser_failure_is_not_suppressed', {timeout: 5000}, async () => {
  const state = holdDirectory(), model = createTideSelection(state.fetcher, memory());
  model.configure(config); await flush();
  assert.equal(state.directoryCalls, 0);
  const first = model.list(); await flush();
  state.fail();
  assert.deepEqual(await first, []);
  assert.equal(model.error.value, DIRECTORY_ERROR, 'a current failure on the default station is still reported');
  // Retry in the order the Retry button uses: refresh clears the error, list refetches the reset catalog.
  void model.refresh(); const retry = model.list(); await flush();
  assert.equal(model.error.value, '');
  assert.equal(state.directoryCalls, 2, 'the rejected catalog was reset, so retry fetches again');
  state.release();
  assert.deepEqual(ids(await retry), expectedRows); await flush();
  assert.deepEqual(ids(model.stations.value), expectedRows);
  assert.equal(model.error.value, '');
  assert.deepEqual(state.predictionCalls, []);
});

test('pack_snapshot_survives_choice_change_without_ui_leak', {timeout: 5000}, async () => {
  const state = holdDirectory(), model = createTideSelection(state.fetcher, restored([b.id], b.id));
  model.configure(config); await flush();
  const pack = model.packURLs(config.id, now); await flush();
  assert.equal(model.choose(null), true);
  state.release();
  assert.deepEqual(await pack, tidePackURLs(b, now), 'the pack keeps the station it captured');
  await flush();
  assertQuiet(model, state, 'after pack');
  assert.equal(state.directoryCalls, 1);
  assert.deepEqual(await model.packURLs('wrong-region', now), []);
  assert.deepEqual(await model.packURLs(config.id, now), [], 'default choice has no pack');

  const failing = holdDirectory(), again = createTideSelection(failing.fetcher, restored([b.id], b.id));
  again.configure(config); await flush();
  const lost = assert.rejects(again.packURLs(config.id, now), /could not be resolved/);
  await flush(); again.choose(null); failing.fail(); await lost; await flush();
  assertQuiet(again, failing, 'failed pack after default');
});

test('configure_with_saved_stations_and_default_still_publishes_its_directory', {timeout: 5000}, async () => {
  const state = holdDirectory(), model = createTideSelection(state.fetcher, restored([b.id], null));
  model.configure(config); await flush();
  assert.equal(model.choice.value, null); assert.equal(state.directoryCalls, 1);
  state.release(); await flush();
  assert.deepEqual(ids(model.stations.value), expectedRows, 'the restore-time directory load is current, not obsolete');
  assert.equal(model.error.value, '');
  const failing = holdDirectory(), down = createTideSelection(failing.fetcher, restored([b.id], null));
  down.configure(config); await flush(); failing.fail(); await flush();
  assert.equal(down.error.value, DIRECTORY_ERROR, 'a current failure is reported');
});
