// SC0022-11: a signed-in planner offers the person's saved spots as stops through the ordinary user-waypoint path.
// Offline: a fixture list request, bounded synthetic screens, the production Planner component rendered to a string (its effects
// captured by a test-only stand-in for preact/hooks, its click handlers by preact's vnode hook), and a trap on every other network path.
import assert from 'node:assert/strict';
import test, {after, mock} from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugin} from './helpers/esbuild-url.mjs';
import {draftKey} from '../dist/trip-export.js';
import {geometryCoveredByBounds} from '../dist/geo-screen.js';

// Only the Planner component's own effects are captured (so a test can run and clean them up); every other module keeps the real hooks.
const hookStub = {name: 'hook-stub', setup: b => {
  b.onResolve({filter: /^preact\/hooks$/}, a => a.importer.endsWith('web/app/Planner.tsx') ? {path: 'hooks', namespace: 'hook-stub'} : null);
  b.onLoad({filter: /.*/, namespace: 'hook-stub'}, () => ({contents: 'export const useEffect = (fn, deps) => { (globalThis.__plannerEffects ??= []).push(fn); };', loader: 'js'}));
}};
const dir = await mkdtemp(join(tmpdir(), 'planner-saved-')), out = join(dir, 'ui.mjs');
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {Planner} from './web/app/Planner.tsx';
    export {createPlanner} from './web/planner.ts';
    export {session} from './web/account.ts';
    export {region as stateRegion} from './web/state.ts'; export {batch} from '@preact/signals';
    export {render} from 'preact-render-to-string'; export {h, options} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [rendererPlugin, hookStub]});
const m = await import(pathToFileURL(out).href);

// Nothing but the injected list request may reach a network: every other path is recorded and refused.
const traffic = [], beacons = [], realFetch = globalThis.fetch, realBeacon = globalThis.navigator?.sendBeacon;
globalThis.fetch = (...a) => { traffic.push(a); throw Error('no network in this test'); };
if (globalThis.navigator) globalThis.navigator.sendBeacon = (...a) => { beacons.push(a); return true; };
after(async () => {
  globalThis.fetch = realFetch; if (globalThis.navigator) globalThis.navigator.sendBeacon = realBeacon;
  m.session.value = {state: 'loading'}; m.stateRegion.value = null;
  await rm(dir, {recursive: true, force: true});
});

const NOW = new Date('2026-10-12T18:00:00Z');
const REGION = {id: 'test-coast', name: 'Test Coast', timezone: 'America/Los_Angeles', mpa: {bounds: [-125, 30, -115, 40]}};
const MAP = {getSize: () => ({x: 512, y: 512}), getBounds: () => ({getWest: () => -122, getEast: () => -120, getNorth: () => 36, getSouth: () => 34, contains: () => true})};
const ATLAS = {targets: [], areas: [], drifts: []};
const NAME = 'Reserve <i>X</i>', BOX = {type: 'Polygon', coordinates: [[[-121.01, 34.99], [-120.99, 34.99], [-120.99, 35.01], [-121.01, 35.01], [-121.01, 34.99]]]};
const mLon = 1 / (111412.84 * Math.cos(35 * Math.PI / 180)), EAST = -120.99;
const east = metres => ({lat: 35, lon: EAST + metres * mLon});
const OPEN = {lat: 35.2, lon: -120.7}, FAR = {lat: 35.2, lon: -118};
const NOTE = 'PRIVNOTE-7f3a <b>x</b>', OWNER = 'OWNERMARK-9c1d';
const uuid = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };

/** A bounded screen that speaks for [-122, 34, -120, 36] only; every part is mutable so a test can age or change it. */
function makeScreen(over = {}) {
  const s = {features: [{type: 'Feature', properties: {NAME}, geometry: BOX}], bounds: [-122, 34, -120, 36], live: true, checked: new Date().toISOString(), throws: false, ...over};
  return Object.assign(s, {ready: () => s.live, exportExclusions: () => s.live ? {checked_at: s.checked, features: s.features} : null, pointAllowed: () => s.live, geometryAllowed: () => s.live,
    coversGeometry: g => { if (s.throws) throw Error('coverage unavailable'); return geometryCoveredByBounds(g, s.bounds); }});
}
const row = (n, at = OPEN, name = `Spot ${n}`) => ({id: uuid(n), owner: OWNER, name, lat: at.lat, lon: at.lon, note: NOTE, created_at: '2026-10-01T00:00:00Z'});
const okList = spots => ({ok: true, status: 200, json: async () => ({spots})});
const gate = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };

function harness({screen = makeScreen(), spots = [row(1)], handler, stored = null, state = {state: 'signed-in', name: 'Sam'}, loadReefs} = {}) {
  const calls = [], store = new Map(stored ? [[draftKey(REGION.id), JSON.stringify(stored)]] : []), emitted = [];
  const savedSpotsFetch = (url, init) => { calls.push({url, init}); return handler ? handler(calls.length, url, init) : Promise.resolve(okList(spots)); };
  m.stateRegion.value = REGION.id; m.session.value = state;
  const storage = {getItem: k => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v); }};
  const planner = m.createPlanner({atlas: ATLAS, screen, region: REGION, map: MAP, getVisible: () => [], storage, now: () => NOW, landWater: async () => () => ({state: 'water'}),
    loadReefs, loadPorts: async () => ({ports: []}), emit: d => emitted.push(d), savedSpotsFetch, nav: {open() {}, showMap() {}, conditions() {}}});
  return {planner, calls, store, emitted, screen, saved: () => JSON.parse(store.get(draftKey(REGION.id)) ?? 'null')};
}
const open = async h => { h.planner.setSavedSpotsOpen(true); await settle(); };
const rowsOf = h => h.planner.savedSpots.value;
const waypointsOf = h => h.planner.draft.value.userWaypoints ?? [];
const sorted = a => JSON.stringify([...a].sort());

test('saved_spots_fetch_only_for_open_signed_in_session', async () => {
  for (const state of [{state: 'loading'}, {state: 'offline'}, {state: 'disabled'}, {state: 'signed-out'}]) {
    const h = harness({state}); await open(h);
    assert.equal(h.calls.length, 0, `${state.state}: no request`); assert.equal(h.planner.savedSpotsState.value, 'idle'); assert.equal(rowsOf(h).length, 0);
    h.planner.dispose();
  }
  const h = harness(); await settle();
  assert.equal(h.calls.length, 0, 'closed: no request');
  await open(h);
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].url, '/api/spots');
  assert.deepEqual([h.calls[0].init.credentials, h.calls[0].init.cache, h.calls[0].init.signal instanceof AbortSignal], ['same-origin', 'no-store', true]);
  assert.equal(h.planner.savedSpotsState.value, 'ready'); assert.deepEqual(rowsOf(h).map(r => r.name), ['Spot 1']);
  h.planner.setSavedSpotsOpen(true); await settle(); assert.equal(h.calls.length, 1, 'one load per opening');
  h.planner.setSavedSpotsOpen(false); await settle();
  assert.equal(rowsOf(h).length, 0, 'closing clears the account rows'); assert.equal(h.planner.savedSpotsState.value, 'idle');
  await open(h); assert.equal(h.calls.length, 2, 'a new opening loads again');
  // Sign-out clears rows; a signed-out reopen does not ask.
  m.session.value = {state: 'signed-out'}; await settle();
  assert.equal(rowsOf(h).length, 0); await open(h); assert.equal(h.calls.length, 2);
  h.planner.dispose();
  assert.deepEqual(traffic, [], 'nothing but the fixture request');
});

test('saved_spots_fetch_only_for_open_signed_in_session: failures fail the picker closed and keep the draft; Retry loads again', async () => {
  const bad = [
    ['401', () => Promise.resolve({ok: false, status: 401, json: async () => ({spots: [row(1)]})})],
    ['500', () => Promise.resolve({ok: false, status: 500, json: async () => ({})})],
    ['offline', () => Promise.reject(new TypeError('offline'))],
    ['non-JSON', () => Promise.resolve({ok: true, status: 200, json: async () => { throw SyntaxError('x'); }})],
    ['not an object', () => Promise.resolve({ok: true, status: 200, json: async () => []})],
    ['spots not an array', () => Promise.resolve({ok: true, status: 200, json: async () => ({spots: {}})})],
    ['101 spots', () => Promise.resolve(okList(Array.from({length: 101}, (_, i) => row(i + 1))))],
    ['duplicate ids', () => Promise.resolve(okList([row(1), row(1)]))],
    ['id not a UUID', () => Promise.resolve(okList([{...row(1), id: 's1'}]))],
    ['string latitude', () => Promise.resolve(okList([{...row(1), lat: '35'}]))],
    ['latitude 90', () => Promise.resolve(okList([{...row(1), lat: 90}]))],
    ['longitude 180', () => Promise.resolve(okList([{...row(1), lon: 180}]))],
    ['non-finite', () => Promise.resolve({ok: true, status: 200, json: async () => JSON.parse('{"spots":[{"id":"' + uuid(1) + '","name":"x","lat":1e999,"lon":1}]}')})],
    ['name over 80 units', () => Promise.resolve(okList([{...row(1), name: 'x'.repeat(81)}]))],
    ['name not text', () => Promise.resolve(okList([{...row(1), name: 7}]))],
  ];
  for (const [label, handler] of bad) {
    const stored = {ids: ['user:keep'], userWaypoints: [{id: 'user:keep', name: 'Keep', category: 'reef', latitude: 35.1, longitude: -120.8}], rankedPlan: null, name: 'Mine', date: '2026-10-12', avoidScope: 'map', layers: {waypoints: true, outlines: false, alignments: false, exclusions: false}};
    const h = harness({handler, stored}); await open(h);
    assert.equal(h.planner.savedSpotsState.value, 'failed', label); assert.equal(rowsOf(h).length, 0, label);
    assert.deepEqual(waypointsOf(h).map(w => w.id), ['user:keep'], `${label}: the existing plan is untouched`); assert.deepEqual(h.planner.draft.value.ids, ['user:keep']);
    h.planner.addSavedSpot(uuid(1)); assert.match(h.planner.savedSpotsStatus.value, /^Saved spot unavailable\./, label);
    h.planner.dispose();
  }
  let n = 0; const h = harness({handler: () => ++n === 1 ? Promise.reject(new TypeError('offline')) : Promise.resolve(okList([row(1)]))});
  await open(h); assert.equal(h.planner.savedSpotsState.value, 'failed');
  await h.planner.refreshSavedSpots(); assert.equal(h.planner.savedSpotsState.value, 'ready'); assert.equal(h.calls.length, 2); assert.equal(rowsOf(h).length, 1);
  h.planner.dispose();
});

test('saved_spots_fetch_only_for_open_signed_in_session: a request that never answers stops after 20 seconds', async () => {
  mock.timers.enable({apis: ['setTimeout']});
  try {
    const h = harness({handler: () => new Promise(() => {})}); await open(h);
    assert.equal(h.planner.savedSpotsState.value, 'loading');
    mock.timers.tick(19999); await settle(); assert.equal(h.planner.savedSpotsState.value, 'loading');
    mock.timers.tick(1); await settle(); assert.equal(h.planner.savedSpotsState.value, 'failed');
    h.planner.dispose();
  } finally { mock.timers.reset(); }
});

test('saved_spots_fetch_only_for_open_signed_in_session: a late answer never repopulates rows after close, reopen, sign-out, session replacement, region change or disposal', async () => {
  const run = async (disturb, label) => {
    const gates = [gate(), gate()], h = harness({handler: n => gates[n - 1].promise});
    await open(h); assert.equal(h.calls.length, 1, label);
    await disturb(h);
    return {h, gates};
  };
  // Closed and reopened: the first answer is stale, the second one counts.
  let r = await run(async h => { h.planner.setSavedSpotsOpen(false); await open(h); }, 'reopen');
  assert.equal(r.h.calls.length, 2); r.gates[1].resolve(okList([row(2)])); await settle(); r.gates[0].resolve(okList([row(1)])); await settle();
  assert.deepEqual(rowsOf(r.h).map(x => x.name), ['Spot 2']); r.h.planner.dispose();
  // Signed-in session replaced by another object with the same display name: the old request is stale.
  r = await run(async () => { m.session.value = {state: 'signed-in', name: 'Sam'}; await settle(); }, 'new session object');
  assert.equal(r.h.calls.length, 2, 'the replacement session loads on its own'); r.gates[1].resolve(okList([row(2)])); await settle(); r.gates[0].resolve(okList([row(1)])); await settle();
  assert.deepEqual(rowsOf(r.h).map(x => x.name), ['Spot 2']); r.h.planner.dispose();
  for (const [label, disturb] of [['closed', h => h.planner.setSavedSpotsOpen(false)], ['signed out', () => { m.session.value = {state: 'signed-out'}; }],
    ['region change', () => { m.stateRegion.value = 'other-coast'; }], ['disposed', h => h.planner.dispose()]]) {
    r = await run(disturb, label); r.gates[0].resolve(okList([row(1)])); await settle();
    assert.equal(rowsOf(r.h).length, 0, `${label}: the late answer is dropped`); assert.equal(r.h.planner.savedSpotsState.value, 'idle', label);
    r.h.planner.addSavedSpot(uuid(1)); assert.deepEqual(waypointsOf(r.h), [], label); r.h.planner.dispose();
  }
});

test('saved_spot_add_requires_current_bounded_screen', async () => {
  const cases = [['covered, no boundary near', OPEN, {}, false, /^No protected-area boundary found in this screen\. Not a legal clearance\.$/],
    ['inside a boundary', east(-100), {}, true, /^Inside Reserve <i>X<\/i>$/], ['30 m outside', east(30), {}, true, /^30 m from Reserve <i>X<\/i>$/],
    ['within the margin', east(65), {}, true, / m from Reserve/], ['well beyond the margin', east(500), {}, false, /^No protected-area boundary found/],
    ['outside the screen coverage', FAR, {}, true, /^Protected areas not checked$/], ['stale screen', OPEN, {live: false}, true, /^Protected areas not checked$/],
    ['coverage method throws', OPEN, {throws: true}, true, /^Protected areas not checked$/]];
  for (const [label, at, over, refused, reading] of cases) {
    const h = harness({spots: [row(1, at, 'Probe')], screen: makeScreen(over)}); await open(h);
    const [shown] = rowsOf(h); assert.equal(shown.refused, refused, label); assert.match(shown.reading, reading, label);
    h.planner.addSavedSpot(uuid(1)); // the direct call, not the button: the same answer
    if (refused) { assert.deepEqual(waypointsOf(h), [], `${label}: nothing added`); assert.equal(h.store.size, 0, label); assert.equal(h.planner.savedSpotsStatus.value, `Not added: ${shown.reading}.`); }
    else { assert.equal(waypointsOf(h).length, 1, label); assert.equal(h.planner.savedSpotsStatus.value, 'Added to this browser’s plan. Private notes are not copied.'); }
    h.planner.dispose();
  }
  // A screen with no coverage method (legacy or absent) and no screen at all read as not checked, never clear.
  for (const [label, screen] of [['no coverage method', (() => { const s = makeScreen(); delete s.coversGeometry; return s; })()], ['no screen', null]]) {
    const h = harness({screen}); await open(h);
    assert.deepEqual([rowsOf(h)[0].refused, rowsOf(h)[0].reading], [true, 'Protected areas not checked'], label);
    h.planner.addSavedSpot(uuid(1)); assert.deepEqual(waypointsOf(h), [], label); h.planner.dispose();
  }
  // Another region's screen: not checked, and Add refuses even when the rows are still held.
  const h = harness(); await open(h); assert.equal(rowsOf(h)[0].refused, false);
  m.stateRegion.value = 'other-coast'; await settle();
  assert.equal(rowsOf(h).length, 0); h.planner.addSavedSpot(uuid(1)); assert.deepEqual(waypointsOf(h), []); assert.match(h.planner.savedSpotsStatus.value, /^Saved spot unavailable\./); h.planner.dispose();
});

test('saved_spot_add_requires_current_bounded_screen: missing region invalidates held rows and late responses', async () => {
  for (const missing of [null, '']) {
    const h = harness(); await open(h);
    assert.equal(rowsOf(h)[0].refused, false);
    const before = JSON.stringify(h.planner.draft.value);
    // Hold effects until the end of the batch: the reading and direct Add must fail
    // closed even before the lifecycle effect has discarded the loaded account rows.
    m.batch(() => {
      m.stateRegion.value = missing;
      assert.deepEqual(rowsOf(h).map(r => [r.refused, r.reading]), [[true, 'Protected areas not checked']]);
      h.planner.addSavedSpot(uuid(1));
      assert.equal(JSON.stringify(h.planner.draft.value), before);
      assert.equal(h.store.size, 0, 'direct Add persists nothing without a matching region');
      assert.match(h.planner.savedSpotsStatus.value, /^Saved spot unavailable\./);
    });
    await settle();
    assert.equal(rowsOf(h).length, 0); assert.equal(h.planner.savedSpotsState.value, 'idle');
    await h.planner.refreshSavedSpots(); assert.equal(h.calls.length, 1, 'no fetch without a matching region');
    h.planner.dispose();

    const pending = gate(), late = harness({handler: () => pending.promise}); await open(late);
    m.stateRegion.value = missing;
    assert.equal(late.calls[0].init.signal.aborted, true);
    pending.resolve(okList([row(1)])); await settle();
    assert.equal(rowsOf(late).length, 0, 'late response cannot restore missing-region rows');
    assert.equal(late.planner.savedSpotsState.value, 'idle');
    late.planner.addSavedSpot(uuid(1)); assert.deepEqual(waypointsOf(late), []); assert.equal(late.store.size, 0);
    late.planner.dispose();
  }
});

test('saved_spot_add_requires_current_bounded_screen: the screen is read again at Add and at export, after the list was shown', async () => {
  const h = harness({spots: [row(1, east(500), 'Later closed'), row(2, east(500), 'Added first')]}); await open(h);
  assert.equal(rowsOf(h)[0].refused, false, 'shown as not refused');
  h.planner.addSavedSpot(uuid(2)); assert.equal(waypointsOf(h).length, 1);
  const bytes = await h.planner.exportFile('gpx'); assert.match(await bytes.text(), /Added first/);
  // The boundary file changes: a closure now covers the position. No tick, no re-render: Add still refuses, and the export hands over nothing.
  h.screen.features = [{type: 'Feature', properties: {NAME: 'New closure'}, geometry: {type: 'Polygon', coordinates: [[[-120.99, 34.99], [-120.9, 34.99], [-120.9, 35.01], [-120.99, 35.01], [-120.99, 34.99]]]}}];
  h.planner.addSavedSpot(uuid(1));
  assert.equal(waypointsOf(h).length, 1, 'the refused spot was not added'); assert.match(h.planner.savedSpotsStatus.value, /^Not added: Inside New closure\.$/);
  await assert.rejects(h.planner.exportFile('gpx'), /./, 'the copy already in the plan is checked again at export');
  h.planner.dispose();
});

test('saved_spot_copy_is_ordinary_waypoint', async () => {
  const stored = {ids: ['user:existing'], userWaypoints: [{id: 'user:existing', name: 'Existing', category: 'reef', latitude: 35.3, longitude: -120.9}], rankedPlan: null, name: 'Mine', date: '2026-10-12', avoidScope: 'map', layers: {waypoints: true, outlines: false, alignments: false, exclusions: false}};
  const spots = [row(1, OPEN, 'Alpha'), row(2, {lat: 35.21, lon: -120.7}, '  '), row(3, {lat: 35.22, lon: -120.7}, 'A\u0001B\uFFFE'), row(4, {lat: 35.23, lon: -120.7}, 'Alpha'),
    row(5, {lat: 35.24, lon: -120.7}, '<img src=x onerror=alert(1)>'), row(6, {lat: 35.3, lon: -120.9}, 'Existing')];
  const h = harness({spots, stored}); await open(h);
  assert.deepEqual(rowsOf(h).map(r => r.name), ['Alpha', 'Waypoint', 'AB', 'Alpha', '<img src=x onerror=alert(1)>', 'Existing'], 'default, control-character and duplicate names');
  assert.deepEqual(Object.keys(rowsOf(h)[0]).sort(), ['id', 'latitude', 'longitude', 'name', 'reading', 'refused'], 'a row holds no note, owner or date');
  for (let n = 1; n <= 5; n++) h.planner.addSavedSpot(uuid(n));
  const added = waypointsOf(h).slice(1);
  assert.equal(added.length, 5); assert.ok(added.every(w => w.category === 'other' && /^user:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(w.id)));
  assert.ok(added.every((w, i) => w.id !== `user:${uuid(i + 1)}`), 'a server id never becomes the waypoint id');
  assert.deepEqual(added.map(w => w.name), ['Alpha', 'Waypoint', 'AB', 'Alpha', '<img src=x onerror=alert(1)>']); assert.equal(new Set(added.map(w => w.id)).size, 5);
  assert.deepEqual(h.planner.draft.value.ids, ['user:existing', ...added.map(w => w.id)], 'existing selection kept, new ids appended in order');
  assert.deepEqual(Object.keys(added[0]).sort(), ['category', 'id', 'latitude', 'longitude', 'name']);
  // An identical ordinary waypoint is reused; a repeat click adds nothing; a deselected copy comes back on its own id.
  h.planner.addSavedSpot(uuid(6)); assert.equal(waypointsOf(h).length, 7, 'category differs (reef vs other): a new copy');
  h.planner.addSavedSpot(uuid(1)); h.planner.addSavedSpot(uuid(1)); assert.equal(waypointsOf(h).length, 7, 'repeat clicks are idempotent');
  const first = added[0].id;
  h.planner.toggleSpot(first, false); assert.ok(!h.planner.draft.value.ids.includes(first));
  h.planner.addSavedSpot(uuid(1)); assert.ok(h.planner.draft.value.ids.includes(first), 'the same copy is selected again'); assert.equal(waypointsOf(h).length, 7);
  h.planner.removeWaypoint(first); assert.equal(waypointsOf(h).length, 6);
  h.planner.addSavedSpot(uuid(1)); assert.equal(waypointsOf(h).length, 7); assert.notEqual(waypointsOf(h).at(-1).id, first, 'removed means a fresh copy');
  // Changed source data is not synchronized into an existing copy.
  const reload = harness({spots: [row(1, OPEN, 'Renamed')], stored: h.saved()}); await open(reload);
  reload.planner.addSavedSpot(uuid(1)); assert.equal(waypointsOf(reload).length, 8, 'a different name is a different waypoint'); assert.equal(waypointsOf(reload).filter(w => w.name === 'Alpha').length, 2);
  // A saved plan reloads with the copies and nothing else.
  const again = harness({spots: [], stored: reload.saved()}); assert.equal(waypointsOf(again).length, 8);
  again.planner.dispose(); reload.planner.dispose(); h.planner.dispose();
  // An identical ordinary waypoint (same name, category other, position) already in the browser's plan is reused, selected if it was not.
  const twin = {id: 'user:twin', name: 'Twin', category: 'other', latitude: 35.4, longitude: -120.6};
  const t = harness({spots: [row(7, {lat: 35.4, lon: -120.6}, ' Twin ')], stored: {...stored, userWaypoints: [...stored.userWaypoints, twin]}}); await open(t);
  t.planner.addSavedSpot(uuid(7)); assert.equal(waypointsOf(t).length, 2, 'no second copy'); assert.deepEqual(t.planner.draft.value.ids, ['user:existing', 'user:twin']); t.planner.dispose();
});

test('saved_spot_copy_is_ordinary_waypoint: the 100 waypoint limit, and a ranked plan is un-ranked as any added place does', async () => {
  const full = n => ({ids: Array.from({length: n}, (_, i) => `user:w${i}`), userWaypoints: Array.from({length: n}, (_, i) => ({id: `user:w${i}`, name: `W${i}`, category: 'reef', latitude: 34.1 + i / 1000, longitude: -121.5})),
    rankedPlan: null, name: 'Mine', date: '2026-10-12', avoidScope: 'map', layers: {waypoints: true, outlines: false, alignments: false, exclusions: false}});
  let h = harness({spots: [row(1), row(2, {lat: 35.25, lon: -120.7})], stored: full(99)}); await open(h);
  h.planner.addSavedSpot(uuid(1)); assert.equal(waypointsOf(h).length, 100); assert.equal(h.planner.savedSpotsStatus.value, 'Added to this browser’s plan. Private notes are not copied.');
  const kept = JSON.stringify(h.saved()); h.planner.addSavedSpot(uuid(2));
  assert.equal(h.planner.savedSpotsStatus.value, 'Your plan can keep at most 100 user waypoints. Remove one first.'); assert.equal(waypointsOf(h).length, 100); assert.equal(JSON.stringify(h.saved()), kept, 'nothing saved on refusal');
  h.planner.addSavedSpot(uuid(1)); assert.equal(h.planner.savedSpotsStatus.value, 'Added to this browser’s plan. Private notes are not copied.', 'a repeat at the limit adds nothing and is not an error'); h.planner.dispose();
  h = harness({spots: [row(1)], stored: full(100)}); await open(h); h.planner.addSavedSpot(uuid(1)); assert.equal(waypointsOf(h).length, 100); assert.match(h.planner.savedSpotsStatus.value, /at most 100/); h.planner.dispose();

  const reefs = {targets: [0, 1].map(i => ({id: `reef-${i}`, label: `Reef ${i}`, canonical_habitat: true, latitude: 35 + i / 100, longitude: -120.5, habitat_grade: 'A', habitat_score: 1000 - i, neighborhood_depth_ft: [90, 120],
    resolution_m: 2, evidence_confidence: {percent: 90}, species_fit: {lingcod: 3, 'rockfish-reef': 3}, area_ids: [`area-${i}`], terrain_interpretation: 'Raised structure', source_url: 'https://example.org/s', evidence_status: 'x'})),
    areas: [0, 1].map(i => ({id: `area-${i}`, target_ids: [`reef-${i}`], geometry: {type: 'Polygon', coordinates: [[[-120.5, 35 + i / 100], [-120.498, 35 + i / 100], [-120.498, 35.002 + i / 100], [-120.5, 35.002 + i / 100], [-120.5, 35 + i / 100]]]}})),
    publication: {export_sha256: 'a'.repeat(64), status: 'ready', expires_at: '2099-12-31T00:00:00Z', region: REGION.id}, source_validation_date: '2026-10-01'};
  h = harness({loadReefs: async () => reefs}); await settle(); await open(h);
  await h.planner.selectBest(); assert.equal(h.planner.ranked.value, true, h.planner.scopeStatus.value);
  const ranked = [...h.planner.draft.value.ids], seen = h.emitted.length;
  h.planner.addSavedSpot(uuid(1));
  assert.equal(h.planner.ranked.value, false, 'un-ranked'); assert.deepEqual(h.emitted.slice(seen), [{targets: [], areas: []}], 'only the clearing emit, no map fit');
  assert.deepEqual(h.planner.draft.value.ids.slice(0, ranked.length), ranked, 'the ranked selection is kept'); assert.equal(h.planner.draft.value.ids.length, ranked.length + 1);
  h.planner.dispose();
});

test('saved_spot_copy_is_ordinary_waypoint: two copies enter the leg display and the GPX check; nothing else changes', async () => {
  const h = harness({spots: [row(1, OPEN, 'Spot A'), row(2, {lat: 35.25, lon: -120.7}, 'Spot B')]}); await open(h);
  h.planner.addSavedSpot(uuid(1)); h.planner.addSavedSpot(uuid(2));
  const html = m.render(m.h(m.Planner, {model: h.planner, open: true}));
  assert.match(html, /Your stops in order/); assert.match(html, /Spot A → Spot B · [\d.]+ nm/); assert.match(html, /No home port chosen/);
  const file = await h.planner.exportFile('gpx'), gpx = await file.text();
  assert.match(file.name, /-2wp\.gpx$/); assert.deepEqual([...gpx.matchAll(/<wpt[^>]*><name>(.*?)<\/name>/g)].map(x => x[1]), ['Spot A', 'Spot B']);
  assert.equal(h.planner.summary.value.ok, true); assert.equal(h.planner.summary.value.counts.waypoints, 2);
  h.planner.dispose();
});

test('saved_spot_private_fields_never_leave_picker', async () => {
  const h = harness({spots: [row(1, OPEN, 'Visible spot'), row(2, {lat: 35.25, lon: -120.7}, 'Second')]}); await open(h);
  const html0 = m.render(m.h(m.Planner, {model: h.planner, open: true}));
  h.planner.addSavedSpot(uuid(1)); h.planner.addSavedSpot(uuid(2));
  const html = m.render(m.h(m.Planner, {model: h.planner, open: true}));
  const gpx = await (await h.planner.exportFile('gpx')).text(), notes = await (await h.planner.exportFile('notes')).text();
  const secrets = ['PRIVNOTE', OWNER, uuid(1), uuid(2), 'created_at', '<b>x</b>'];
  const outputs = {'picker before Add': html0, 'rendered plan': html, 'local draft': [...h.store.values()].join('\n'), 'GPX': gpx, 'offline notes': notes, 'ranked payloads': JSON.stringify(h.emitted),
    'share title and plan name': `${h.planner.draft.value.name}`, 'status lines': `${h.planner.savedSpotsStatus.value}${h.planner.actionStatus.value}${h.planner.scopeStatus.value}`, 'requests': JSON.stringify(h.calls.map(c => [c.url, c.init.method ?? 'GET', c.init.body ?? null]))};
  for (const [where, text] of Object.entries(outputs)) for (const s of secrets) assert.ok(!String(text).includes(s), `${where} must not contain ${s}`);
  assert.ok(gpx.includes('Visible spot') && gpx.includes('Second'), 'the deliberately copied names and positions are in the file');
  assert.ok(h.store.size === 1 && [...h.store.values()][0].includes('Visible spot'), 'and in the local draft only');
  assert.deepEqual(h.calls.map(c => [c.url, c.init.method ?? 'GET', c.init.body ?? null]), [['/api/spots', 'GET', null]], 'one read, nothing sent');
  assert.deepEqual(traffic, [], 'no other request'); assert.deepEqual(beacons, [], 'no telemetry beacon (no spot_saved event)');
  assert.ok(!h.emitted.some(d => d.fit), 'no map fit'); h.planner.dispose();
});

/** The Planner rendered with its effects captured; `effects.run()` runs them as an open dialog would, `effects.stop()` runs their cleanups. */
function view(h, isOpen = true) {
  globalThis.__plannerEffects = []; const taps = [], was = m.options.vnode;
  m.options.vnode = v => { if (v.type === 'button') taps.push(v.props); was?.(v); };
  let html; try { html = m.render(m.h(m.Planner, {model: h.planner, open: isOpen})); } finally { m.options.vnode = was; }
  const effects = globalThis.__plannerEffects, cleanups = [];
  return {html, taps, run: () => { for (const fn of effects) { const c = fn(); if (typeof c === 'function') cleanups.push(c); } }, stop: () => { while (cleanups.length) cleanups.pop()(); }};
}
const section = html => /<section class="export-card" id="export-saved-spots"[\s\S]*?<\/section>/.exec(html)?.[0] ?? null;

test('saved_spots_component_states_and_signed_out_parity', async () => {
  globalThis.document = {addEventListener() {}, removeEventListener() {}, dispatchEvent() {}};
  const stored = {ids: ['user:keep'], userWaypoints: [{id: 'user:keep', name: 'Keep', category: 'reef', latitude: 35.1, longitude: -120.8}], rankedPlan: null, name: 'Mine', date: '2026-10-12', avoidScope: 'map', layers: {waypoints: true, outlines: false, alignments: false, exclusions: false}};
  try {
    // Signed in: the section is there, labelled, with the disclosure; the rest of the planner reads as it does signed out.
    const spots = [row(1, OPEN, '<b>Bold</b> Reef'), row(2, east(-100), 'Closed one'), row(3, FAR, 'Far one')];
    const h = harness({spots, stored}); await open(h);
    const signedIn = view(h), sec = section(signedIn.html);
    assert.ok(sec, 'section rendered'); assert.match(sec, /aria-label="Your saved spots"/); assert.match(sec, /<h3>Your saved spots<\/h3>/);
    assert.ok(sec.includes('Add copies the name and position to this browser’s plan. Notes stay private. Exporting the plan includes its selected positions.'));
    assert.ok(sec.includes('&lt;b>Bold&lt;/b> Reef') && !sec.includes('<b>Bold'), 'a name is plain text'); assert.ok(!sec.includes('PRIVNOTE') && !sec.includes(OWNER));
    assert.ok(sec.includes('No protected-area boundary found in this screen. Not a legal clearance.')); assert.ok(sec.includes('Inside Reserve &lt;i>X&lt;/i>') && !sec.includes('<i>X')); assert.ok(sec.includes('Protected areas not checked'));
    const buttons = [...sec.matchAll(/<button\b(?:"[^"]*"|[^">])*>/g)].map(x => x[0]); assert.equal(buttons.length, 3);
    assert.deepEqual(buttons.map(b => /\bdisabled\b/.test(b)), [false, true, true], 'Add is disabled for a refused or unchecked row');
    assert.ok(!/(clear|safe)\b/i.test(sec.replace('Not a legal clearance', '').replace('No protected-area boundary found in this screen.', '')), 'never labelled clear');
    // The Add button is wired to the model, and the Retry button too.
    const adds = signedIn.taps.filter(t => t.children === 'Add to plan'); assert.equal(adds.length, 3);
    adds[0].onClick(); assert.deepEqual(waypointsOf(h).map(w => w.name), ['Keep', '<b>Bold</b> Reef']); adds[0].onClick(); assert.equal(waypointsOf(h).length, 2, 'no duplicate addition');
    adds[1].onClick(); assert.equal(waypointsOf(h).length, 2, 'a refused row cannot be added even by its handler'); assert.match(h.planner.savedSpotsStatus.value, /^Not added: Inside Reserve/);
    // Parity: the same plan signed out renders byte for byte as the signed-in page without its section (the share button's momentary "Preparing…" aside).
    const plain = html => html.replace('Preparing…', 'Share / Save file');
    await settle(); const signedInHtml = plain(view(h).html);
    m.session.value = {state: 'signed-out'}; await settle();
    const out = plain(view(h).html); assert.equal(section(out), null); assert.ok(!out.includes('saved spot'));
    // SC1822-04: the signed-in page also carries its own trip-alert section and storage sentence; with those two put back, signed out is the same planner.
    const alertSection = /<section class="export-card" id="planner-alert"[\s\S]*?<\/section>/.exec(signedInHtml)?.[0] ?? '';
    const withoutAlerts = signedInHtml.replace(alertSection, '').replace('Saved in this browser. Alert me for this trip saves a separate snapshot to your account.', 'Saved on this browser for each region. Separate from your account’s trip alerts.');
    assert.ok(withoutAlerts.replace(section(withoutAlerts), '') === out, 'signed out: the existing planner, unchanged');
    for (const state of [{state: 'loading'}, {state: 'offline'}, {state: 'disabled'}]) { m.session.value = state; await settle(); assert.ok(plain(view(h).html) === out, `${state.state}: no picker, same planner`); }
    assert.ok(waypointsOf(h).some(w => w.name === '<b>Bold</b> Reef'), 'sign-out keeps the person’s deliberate local copy');
    assert.equal(rowsOf(h).length, 0, 'and clears the fetched account rows'); h.planner.dispose();

    // Loading, empty, failed with Retry.
    const pending = gate(), loading = harness({handler: () => pending.promise}); await open(loading);
    assert.ok(section(view(loading).html).includes('Loading your saved spots…')); loading.planner.dispose();
    const empty = harness({spots: []}); await open(empty); assert.ok(section(view(empty).html).includes('No saved spots yet.')); empty.planner.dispose();
    let n = 0; const failing = harness({handler: () => ++n === 1 ? Promise.resolve({ok: false, status: 500, json: async () => ({note: NOTE})}) : Promise.resolve(okList([row(1)]))}); await open(failing);
    const failed = view(failing), fs = section(failed.html);
    assert.ok(fs.includes('Saved spots could not be loaded. Try again.') && !fs.includes('PRIVNOTE') && !fs.includes('No saved spots yet.'));
    const retry = failed.taps.find(t => t.children === 'Retry'); assert.ok(retry, 'a Retry button'); retry.onClick(); await settle();
    assert.equal(failing.calls.length, 2); assert.equal(failing.planner.savedSpotsState.value, 'ready'); failing.planner.dispose();
  } finally { delete globalThis.document; }
});

test('saved_spots_component_states_and_signed_out_parity: the dialog lifecycle asks only while open and stops when closed', async () => {
  globalThis.document = {addEventListener() {}, removeEventListener() {}, dispatchEvent() {}};
  const stored = {ids: ['user:keep'], userWaypoints: [{id: 'user:keep', name: 'Keep', category: 'reef', latitude: 35.1, longitude: -120.8}], rankedPlan: null, name: 'Mine', date: '2026-10-12', avoidScope: 'map', layers: {waypoints: true, outlines: false, alignments: false, exclusions: false}};
  try {
    const h = harness({stored}), hidden = view(h, false); hidden.run(); await settle();
    assert.equal(h.calls.length, 0, 'rendering a closed dialog asks for nothing'); assert.equal(section(hidden.html) !== null, true);
    hidden.stop();
    const shown = view(h, true); shown.run(); await settle();
    assert.equal(h.calls.length, 1, 'opening asks once'); assert.equal(rowsOf(h).length, 1);
    shown.stop(); await settle(); assert.equal(rowsOf(h).length, 0, 'closing clears the rows'); assert.equal(h.planner.savedSpotsState.value, 'idle');
    h.planner.dispose();
    m.session.value = {state: 'signed-out'}; const out = harness({stored, state: {state: 'signed-out'}}), signedOut = view(out, true); signedOut.run(); await settle(); signedOut.stop();
    assert.equal(out.calls.length, 0, 'signed out: no request even when open'); out.planner.dispose();
  } finally { delete globalThis.document; }
});
