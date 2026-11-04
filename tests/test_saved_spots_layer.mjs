// SC0922-04: "Your saved spots" on the Chart. A signed-in owner turns the layer on, the list is read once per session
// from GET /api/spots, each pin shows its name and its card the shared protected-area reading, never the private note;
// signed out or a failed read draws nothing and says why; a confirmed save (or an account write) reads the list again;
// nothing private enters the address, a feed, an export or the event. Synthetic rows and areas only; the screen is the real
// initProtectedAreas over an offline answer; no network.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {setRegion} from '../dist/region.js';

const ROOT = new URL('..', import.meta.url).pathname;
setRegion(JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8')));

let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'saved-spots-layer-')), 'layer.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export * from './web/map/saved-spots.ts';
      export {SavedSpotsRow, Legend} from './web/app/Legend.tsx';
      export {MarkCard} from './web/app/MarkCard.tsx';
      export {saveMarkSpot} from './web/saved-spots.ts';
      export {chartStyle, createChart, chartMark} from './web/map/chart.ts';
      export {LAYERS, SAVED_SPOTS_SOURCE} from './web/map/layers.ts';
      export {readPalette} from './web/map/palette.ts';
      export {picked} from './web/map/marks.ts';
      export {camera} from './web/map/stage.ts';
      export {session} from './web/account.ts';
      export * as state from './web/state.ts';
      export {signal} from '@preact/signals';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  ui = await import(pathToFileURL(out).href);
  return ui;
}

// A synthetic closure: a 0.01° square at (-121.0, 35.3) among eight far-away filler squares (the snapshot needs eight areas).
const CX = -121.0, CY = 35.3, HALF = 0.005, M_LON = 111320 * Math.cos(CY * Math.PI / 180);
const square = (x, y, d) => ({type: 'Polygon', coordinates: [[[x - d, y - d], [x + d, y - d], [x + d, y + d], [x - d, y + d], [x - d, y - d]]]});
const area = (name, geometry) => ({type: 'Feature', properties: {NAME: name, FULLNAME: `${name} State Marine Reserve`, Type: 'SMR', CCR: 'Section 632(b)'}, geometry});
const areas = checkedAt => ({type: 'FeatureCollection', checked_at: checkedAt,
  features: [area('Synthetic Reef', square(CX, CY, HALF)), ...Array.from({length: 8}, (_, i) => area(`Filler ${i}`, square(-121.8 + i * 0.01, 35.8, 0.001)))]});
async function realScreen() {
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = async () => ({ok: true, json: async () => areas(new Date().toISOString())});
  globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { return await initProtectedAreas(null, () => {}); } finally { Object.assign(globalThis, saved); }
}
const east = m => ({latitude: CY, longitude: CX + HALF + m / M_LON});
const loaded = screen => async id => ({state: 'loaded', region: id, screen});

const SIGNED_IN = () => Object.freeze({state: 'signed-in', name: 'Sam', advisor: false});
const NOTE = 'PRIVATE-NOTE-SENTINEL', OWNER = 'owner-sentinel', ROW_ID = '11111111-2222-3333-4444-555555555555';
const stored = (i, at, over = {}) => ({id: `${ROW_ID.slice(0, -2)}${String(i).padStart(2, '0')}`, owner: OWNER, name: `Spot ${i}`, lat: at.latitude, lon: at.longitude, note: NOTE, created_at: '2026-11-04T00:00:00Z', ...over});
const answer = (body, over = {}) => ({ok: true, status: 200, json: async () => body, ...over});

/** Microtasks only: no real timers, so mocked ones never stall it. */
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };

/** A fetch that records every call and answers `reply(call)`. */
function spy(reply) {
  const calls = [];
  const fetchFn = async (url, init) => { calls.push({url: String(url), init}); return reply({url: String(url), init, n: calls.length}); };
  return {calls, fetchFn};
}

async function harness(over = {}) {
  const k = await components();
  const {signal, state, savedSpotsOn, SAVED_SPOTS_SOURCE} = k;
  state.region.value = 'morro-bay'; state.presentation.value = 'chart'; state.appView.value = 'coast';
  savedSpotsOn.value = false;
  const who = signal(over.session ?? SIGNED_IN());
  const sets = [], last = {};
  const engine = signal({setData(id, data) { sets.push(id); last[id] = data; }});
  const chartMark = signal(null), events = new EventTarget();
  const net = over.net ?? spy(() => answer({spots: [stored(1, east(150), {name: 'Clear spot'}), stored(2, {latitude: CY, longitude: CX}, {name: 'Inside spot'}), stored(3, east(30), {name: 'Near spot'})]}));
  const screen = over.screen ?? await realScreen();
  const screens = [];
  const loadScreen = over.loadScreen ?? (async id => { screens.push(id); return {state: 'loaded', region: id, screen}; });
  const layer = k.createSavedSpotLayer({engine, chartMark, session: who, fetchFn: net.fetchFn, events, loadScreen});
  return {k, who, engine, chartMark, events, net, layer, last, sets, screens, screen,
    pins: () => last[SAVED_SPOTS_SOURCE]?.features ?? [],
    turnOn: async () => { k.setSavedSpotsOn(true); await flush(); },
    destroy: () => layer.destroy()};
}

test('off_signed_out_and_terrain_draw_nothing: no startup read, exact words, Chart-only, and no repeat read on rerender or remount', async () => {
  const {session: _s} = await components();
  for (const [s, words] of [[{state: 'signed-out', advisor: false}, 'Sign in to show your saved spots.'], [{state: 'loading'}, 'Checking your account…'],
    [{state: 'offline'}, 'Accounts need a connection.'], [{state: 'disabled', advisor: false}, 'Accounts are not available on this site.']]) {
    const h = await harness({session: s});
    assert.equal(h.k.savedSpotsStatus.value.text, words, s.state);
    assert.equal(h.k.savedSpotsStatus.value.canToggle, false, `${s.state} cannot enable`);
    await h.turnOn();
    assert.equal(h.k.savedSpotsOn.value, false, `${s.state}: the choice is refused`);
    assert.equal(h.net.calls.length, 0, `${s.state}: nothing asked`);
    assert.deepEqual(h.pins(), []);
    h.destroy();
  }
  const h = await harness();
  await flush();
  assert.equal(h.net.calls.length, 0, 'a signed-in session with the layer off asks for nothing');
  assert.equal(h.k.savedSpotsStatus.value.text, 'Off. Turn it on to show your saved spots on the Chart.');
  assert.equal(h.k.savedSpotsOn.value, false, 'off at the start');
  await h.turnOn();
  assert.equal(h.net.calls.length, 1);
  assert.equal(h.pins().length, 3);
  // Terrain: the choice is kept, nothing draws, the checkbox says Chart only and cannot change.
  h.k.state.presentation.value = '2d';
  await flush();
  assert.equal(h.k.state.stagePresentation.value, '2d', 'the terrain is shown');
  assert.equal(h.k.savedSpotsStatus.value.text, 'Chart only');
  assert.equal(h.k.savedSpotsStatus.value.canToggle, false);
  assert.equal(h.k.savedSpotsOn.value, true, 'the session-local choice is kept');
  assert.deepEqual(h.pins(), [], 'no private data reaches the terrain or the Chart while it shows');
  h.k.state.presentation.value = 'chart';
  await flush();
  assert.equal(h.pins().length, 3, 'back on the Chart the pins return without a new read');
  // Rerender, camera, region and profile changes, a remount: still one list read.
  h.k.state.region.value = 'other-region'; await flush(); h.k.state.region.value = 'morro-bay'; await flush();
  h.k.setSavedSpotsOn(false); await flush(); assert.deepEqual(h.pins(), []); await h.turnOn();
  h.destroy();
  const again = h.k.createSavedSpotLayer({engine: h.engine, chartMark: h.chartMark, session: h.who, fetchFn: h.net.fetchFn, events: h.events, loadScreen: loaded(h.screen)});
  await flush();
  assert.equal(h.net.calls.length, 1, 'the session\'s list is read once');
  assert.equal(h.pins().length, 3, 'the remounted layer draws from the same session\'s list');
  again.destroy();
});

test('one_read_per_session_and_fail_closed_retry: the request, the projection, every failure, and Try again only on request', async () => {
  const h = await harness();
  await h.turnOn();
  const [{url, init}] = h.net.calls;
  assert.equal(url, '/api/spots');
  assert.equal(init.credentials, 'same-origin'); assert.equal(init.cache, 'no-store'); assert.ok(init.signal instanceof AbortSignal);
  assert.deepEqual(Object.keys(init).sort(), ['cache', 'credentials', 'signal'], 'a plain read: no method, headers or body');
  const json = JSON.stringify(h.pins());
  for (const secret of [NOTE, OWNER, ROW_ID.slice(0, -2), '2026-11-04']) assert.ok(!json.includes(secret), `the source never holds ${secret}`);
  assert.deepEqual(h.pins().map(f => Object.keys(f.properties).sort()), [['key', 'name'], ['key', 'name'], ['key', 'name']]);
  assert.equal(h.k.savedSpotsStatus.value.text, 'Your saved spots are shown only to you.');
  assert.ok(!/\d/.test(h.k.savedSpotsStatus.value.text), 'no count or private value in the status');
  h.destroy();

  // Names: markup and emoji stay text, control characters go, empty is "Unnamed spot".
  const odd = [stored(1, east(150), {name: '<img src=x onerror=alert(1)>'}), stored(2, east(160), {name: 'Reef 🐟'}), stored(3, east(170), {name: 'a\u0000b\u0007c\u200b\ufffe'}), stored(4, east(180), {name: ''}), stored(5, east(190), {name: '   '})];
  const named = await harness({net: spy(() => answer({spots: odd}))});
  await named.turnOn();
  assert.deepEqual(named.pins().map(f => f.properties.name), ['<img src=x onerror=alert(1)>', 'Reef 🐟', 'abc\u200b', 'Unnamed spot', 'Unnamed spot']);
  named.destroy();

  // Zero and the cap of 100 rows are fine; every wrong answer fails the whole read closed.
  const many = n => Array.from({length: n}, (_, i) => stored(i, east(150 + i), {id: `id-${i}`}));
  const empty = await harness({net: spy(() => answer({spots: []}))});
  await empty.turnOn();
  assert.equal(empty.k.savedSpotsStatus.value.text, 'No saved spots yet.'); assert.deepEqual(empty.pins(), []);
  empty.destroy();
  const full = await harness({net: spy(() => answer({spots: many(100)}))});
  await full.turnOn();
  assert.equal(full.pins().length, 100);
  full.destroy();
  const bad = {
    '101st row': {spots: many(101)}, 'not an array': {spots: {}}, 'no spots key': {}, 'null body': null, 'a string': 'x',
    'duplicate id': {spots: [stored(1, east(150), {id: 'dup'}), stored(2, east(160), {id: 'dup'})]},
    'no id': {spots: [{...stored(1, east(150)), id: undefined}]}, 'long id': {spots: [stored(1, east(150), {id: 'x'.repeat(65)})]},
    'numeric id': {spots: [stored(1, east(150), {id: 7})]}, 'name not a string': {spots: [stored(1, east(150), {name: 7})]}, 'name 81 long': {spots: [stored(1, east(150), {name: 'n'.repeat(81)})]},
    'lat NaN (null)': {spots: [stored(1, east(150), {lat: null})]}, 'lat string': {spots: [stored(1, east(150), {lat: '35.3'})]}, 'pole': {spots: [stored(1, east(150), {lat: 90})]},
    'south pole': {spots: [stored(1, east(150), {lat: -90})]}, 'lon 180': {spots: [stored(1, east(150), {lon: 180})]}, 'lon -180': {spots: [stored(1, east(150), {lon: -180})]},
    'one bad row among good ones': {spots: [stored(1, east(150)), stored(2, east(160), {lon: 'x'}), stored(3, east(170))]},
  };
  for (const [label, body] of Object.entries(bad)) {
    const f = await harness({net: spy(() => answer(body))});
    await f.turnOn();
    assert.deepEqual(f.pins(), [], `${label}: nothing draws`);
    assert.equal(f.k.savedSpotsStatus.value.text, 'Your saved spots could not be loaded. Try again.', label);
    assert.equal(f.k.savedSpotsStatus.value.retry, true, label);
    f.destroy();
  }
  for (const [label, reply] of [['JSON', () => answer(null, {json: async () => { throw new SyntaxError('bad json'); }})], ['401', () => answer({}, {ok: false, status: 401})], ['403', () => answer({}, {ok: false, status: 403})],
    ['503', () => answer({}, {ok: false, status: 503})], ['network', () => { throw new TypeError('offline'); }]]) {
    const f = await harness({net: spy(reply)});
    await f.turnOn();
    assert.deepEqual(f.pins(), [], label);
    const status = f.k.savedSpotsStatus.value;
    assert.equal(status.text, 'Your saved spots could not be loaded. Try again.', label);
    assert.ok(!/offline|bad json|401|403|503/.test(status.text), 'no raw error');
    // A failed read is cached as failed: toggling, camera and region do not read again; only the explicit Try again does.
    f.k.setSavedSpotsOn(false); await flush(); f.k.setSavedSpotsOn(true); await flush(); f.k.state.region.value = 'elsewhere'; await flush(); f.k.state.region.value = 'morro-bay'; await flush();
    assert.equal(f.net.calls.length, 1, `${label}: no automatic retry`);
    f.k.retrySavedSpots(); f.k.retrySavedSpots(); await flush();
    assert.equal(f.net.calls.length, 2, `${label}: Try again reads once, however often it is pressed`);
    f.destroy();
  }
  // A read that never answers ends at 20 s as a failure; the pending read is not duplicated by a toggle.
  const hung = await harness({net: spy(({init}) => new Promise(() => { void init; }))});
  const timers = [];
  const real = globalThis.setTimeout;
  globalThis.setTimeout = (fn, ms, ...a) => { if (ms === 20000) { timers.push(fn); return 0; } return real(fn, ms, ...a); };
  try {
    await hung.turnOn();
    hung.k.setSavedSpotsOn(false); await flush(); hung.k.setSavedSpotsOn(true); await flush();
    assert.equal(hung.net.calls.length, 1, 'one pending read, however it is toggled');
    assert.equal(hung.k.savedSpotsStatus.value.text, 'Loading your saved spots…');
    assert.equal(timers.length, 1, 'a 20 second limit');
    timers[0](); await flush();
    assert.equal(hung.k.savedSpotsStatus.value.text, 'Your saved spots could not be loaded. Try again.');
  } finally { globalThis.setTimeout = real; hung.destroy(); }
});

test('in_flight_invalidation_keeps_replacement_timeout_and_ignores_late_answer', async t => {
  let finishA;
  const pendingA = new Promise(resolve => { finishA = resolve; });
  const net = spy(({n}) => n === 1 ? pendingA : n === 2 ? new Promise(() => {})
    : answer({spots: [stored(3, east(150), {name: 'Retried spot'})]}));
  const h = await harness({net});
  t.mock.timers.enable({apis: ['setTimeout']});
  try {
    await h.turnOn();
    assert.equal(net.calls.length, 1);
    h.events.dispatchEvent(new Event(h.k.SAVED_SPOTS_CHANGED));
    await flush();
    assert.equal(net.calls.length, 2, 'invalidation starts one replacement read');
    assert.equal(net.calls[0].init.signal.aborted, true, 'the old read is aborted');
    assert.equal(h.k.savedSpotsStatus.value.text, 'Loading your saved spots…');
    t.mock.timers.tick(19999); await flush();
    assert.equal(h.k.savedSpotsStatus.value.retry, false, 'replacement still has its full deadline');
    t.mock.timers.tick(1); await flush();
    assert.equal(net.calls[1].init.signal.aborted, true, 'replacement times out at 20 seconds');
    assert.equal(h.k.savedSpotsStatus.value.text, 'Your saved spots could not be loaded. Try again.');
    assert.equal(h.k.savedSpotsStatus.value.retry, true);
    assert.deepEqual(h.pins(), []);
    assert.equal(net.calls.length, 2, 'timeout does not retry automatically');
    h.k.retrySavedSpots(); await flush();
    assert.equal(net.calls.length, 3, 'explicit retry starts a fresh read');
    assert.deepEqual(h.pins().map(f => f.properties.name), ['Retried spot']);
    finishA(answer({spots: [stored(1, east(150), {name: 'Obsolete spot'})]}));
    await flush();
    assert.deepEqual(h.pins().map(f => f.properties.name), ['Retried spot'], 'late A cannot replace the retried result');
    assert.equal(h.k.savedSpotsStatus.value.text, 'Your saved spots are shown only to you.');
  } finally { h.destroy(); t.mock.timers.reset(); }
});

test('shared_verdict_inside_margin_unchecked_clear: the card words come from the shared screen and verdictLine', async () => {
  const h = await harness();
  await h.turnOn();
  const byName = name => h.pins().find(f => f.properties.name === name).properties;
  const card = name => { const m = h.k.savedSpotMark(byName(name)); assert.ok(m, name); return m; };
  const {verdictLine} = await import('../web/waypoint-placement.ts');
  assert.equal(h.screens.length, 1, 'the screen is asked for once the layer is on');
  assert.equal(card('Clear spot').reading, 'No protected-area overlap found in this check.');
  assert.equal(card('Inside spot').reading, 'Inside Synthetic Reef State Marine Reserve');
  assert.match(card('Near spot').reading, /^\d+ m from Synthetic Reef State Marine Reserve · Within 70 m of a protected area\.$/);
  const c = card('Clear spot');
  assert.equal(c.kind, 'Your saved spot · private'); assert.equal(c.source, 'Your account');
  assert.equal(c.rules, 'A saved position, not a recommendation. Check current rules before you fish.');
  assert.ok(c.regulations.href.startsWith('https://wildlife.ca.gov/'), 'the region\'s rules link');
  assert.ok(c.id.startsWith('private-saved:') && !c.id.includes(ROW_ID.slice(0, -2)), 'an ephemeral id, never the database id');
  assert.ok(!('position' in c) && !('trip' in c), 'no position or trip: the generic forecast, GPX and save paths get nothing');
  const text = JSON.stringify(c);
  for (const secret of [NOTE, OWNER, '35.3', '121.0', '2026-11-04']) assert.ok(!text.includes(secret), `the card never holds ${secret}`);
  assert.equal(h.k.readingFor({inside: false, name: null, distanceM: null, screened: false}), verdictLine({inside: false, name: null, distanceM: null, screened: false}));
  // Near is the shared line plus the margin words; exactly 70 m is still near, 71 m is clear.
  assert.equal(h.k.readingFor({inside: false, name: 'A', distanceM: 70, screened: true}), '70 m from A · Within 70 m of a protected area.');
  assert.equal(h.k.readingFor({inside: false, name: 'A', distanceM: 71, screened: true}), 'No protected-area overlap found in this check.');
  h.destroy();

  // Not checked: a failed, idle, loading, wrong-region, stale-without-coverage or legacy screen, a throw, an uncovered point and the halo edge.
  const farRow = stored(1, {latitude: 36.5, longitude: -120.0}, {name: 'Far spot'}), clearRow = stored(2, east(150), {name: 'Clear spot'});
  const real = await realScreen();
  const cases = {
    failed: async () => ({state: 'failed'}), idle: async () => ({state: 'idle'}), loading: async () => ({state: 'loading'}), throws: async () => { throw new Error('boom'); },
    'another region': async () => ({state: 'loaded', region: 'other-region', screen: real}),
    'no coverage method': async id => ({state: 'loaded', region: id, screen: {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true}}),
  };
  for (const [label, loadScreen] of Object.entries(cases)) {
    const f = await harness({loadScreen, net: spy(() => answer({spots: [clearRow]}))});
    await f.turnOn();
    assert.equal(f.k.savedSpotMark(f.pins()[0].properties).reading, 'Protected areas not checked', label);
    f.destroy();
  }
  const far = await harness({net: spy(() => answer({spots: [farRow, stored(3, {latitude: 35.3, longitude: -120.55 - 30 / M_LON}, {name: 'Edge spot'})]}))});
  await far.turnOn();
  for (const f of far.pins()) assert.equal(far.k.savedSpotMark(f.properties).reading, 'Protected areas not checked', `${f.properties.name}: outside coverage, still a pin`);
  far.destroy();

  // A pick and the minute re-read the verdict: a screen that stops covering the point turns the open card to not checked; no private point is fetched anywhere else.
  let covering = true;
  const flaky = {coversGeometry: g => covering && real.coversGeometry(g), exportExclusions: () => real.exportExclusions(), ready: () => real.ready(), pointAllowed: p => real.pointAllowed(p), geometryAllowed: g => real.geometryAllowed(g)};
  const intervals = [], realSet = globalThis.setInterval, realClear = globalThis.clearInterval;
  globalThis.setInterval = (fn, ms) => { intervals.push({fn, ms}); return intervals.length; };
  globalThis.clearInterval = () => {};
  const m = await harness({screen: flaky});
  try {
    await m.turnOn();
    assert.equal(intervals.length, 1); assert.equal(intervals[0].ms, 60000, 'once a minute while enabled');
    assert.ok(m.k.pickSavedSpot(m.pins()[1].properties, mark => { m.chartMark.value = mark; }));
    assert.equal(m.chartMark.value.reading, 'Inside Synthetic Reef State Marine Reserve');
    covering = false; intervals[0].fn(); await flush();
    assert.equal(m.chartMark.value.reading, 'Protected areas not checked', 'the minute reads the verdict again');
    assert.equal(m.net.calls.length, 1, 'a verdict never asks for the list or a point');
  } finally { globalThis.setInterval = realSet; globalThis.clearInterval = realClear; m.destroy(); }
});

test('private_pick_is_not_a_public_mark: the card, its actions, local close, and what clears it', async () => {
  const k = await components();
  const h = await harness();
  await h.turnOn();
  const before = k.picked.value;
  assert.equal(k.pickSavedSpot({key: 'nope'}, () => assert.fail('a stale key opens nothing')), false);
  assert.ok(k.pickSavedSpot(h.pins()[0].properties, mark => { h.chartMark.value = mark; }));
  assert.equal(k.picked.value, before + 1, 'focus moves to the card through the existing signal');
  const html = k.render(k.h(k.MarkCard, {mark: h.chartMark.value}));
  assert.match(html, /<h2[^>]*>Clear spot<\/h2>/);
  assert.match(html, /Your saved spot · private/); assert.match(html, /No protected-area overlap found in this check\./);
  assert.match(html, /A saved position, not a recommendation\. Check current rules before you fish\./);
  assert.match(html, /Clear selection/, 'the close button stays');
  assert.doesNotMatch(html, /Add to trip|Save research reference|GPX|Review &amp; export|Save this spot|app-mark-actions/, 'no trip, GPX or save action');
  for (const secret of [NOTE, OWNER, ROW_ID.slice(0, -2), '35.3', '121.0']) assert.ok(!html.includes(secret), `the card markup never holds ${secret}`);
  // A name that is markup renders as text.
  const tricky = k.render(k.h(k.MarkCard, {mark: {...h.chartMark.value, name: '<b>x</b>'}}));
  assert.ok(tricky.includes('&lt;b') && !tricky.includes('<b>x</b>'), 'markup renders as text');
  // Turn-off, another presentation, sign-out and a list change each clear the card at once.
  k.setSavedSpotsOn(false);
  assert.equal(h.chartMark.value, null, 'turning the layer off clears the card synchronously');
  assert.deepEqual(h.pins(), [], 'and the engine data');
  await h.turnOn();
  k.setSavedSpotsOn(false); k.setSavedSpotsOn(true); await flush();
  assert.equal(h.chartMark.value, null, 'no hidden-card resurrection');
  k.pickSavedSpot(h.pins()[0].properties, mark => { h.chartMark.value = mark; });
  k.state.presentation.value = '2d';
  assert.equal(h.chartMark.value, null, 'another presentation clears it');
  k.state.presentation.value = 'chart'; await flush();
  assert.equal(h.chartMark.value, null);
  k.pickSavedSpot(h.pins()[0].properties, mark => { h.chartMark.value = mark; });
  h.who.value = {state: 'signed-out', advisor: false};
  assert.equal(h.chartMark.value, null, 'sign-out clears it');
  assert.deepEqual(h.pins(), []);
  assert.equal(k.savedSpotsOn.value, false, 'and the choice');
  // A public mark keeps its actions and is unaffected.
  const pub = k.render(k.h(k.MarkCard, {mark: {id: 'spot:SC26-001', name: 'Reef', kind: 'Reef mark', reading: 'r', source: 's', basis: 'b'}}));
  assert.match(pub, /app-mark-actions/);
  h.destroy();
});

test('the legend row: a native checkbox, off, exact words, Try again, and the Chart styling from the palette', async () => {
  const k = await components();
  k.state.region.value = 'morro-bay'; k.state.presentation.value = 'chart'; k.savedSpotsOn.value = false;
  k.session.value = {state: 'signed-out', advisor: false};
  const row = () => k.render(k.h(k.SavedSpotsRow, {}));
  let html = row();
  assert.match(html, /<input type="checkbox"[^>]*disabled/); assert.ok(!/ checked/.test(html));
  assert.ok(html.includes('Your saved spots') && html.includes('Sign in to show your saved spots.'));
  k.session.value = SIGNED_IN();
  html = row();
  assert.ok(!/<input[^>]*disabled/.test(html) && !/<input[^>]*checked/.test(html), 'signed in: enabled and off');
  assert.ok(html.includes('Off. Turn it on to show your saved spots on the Chart.'));
  assert.doesNotMatch(html, /Try again/);
  // The registry entry and the style.
  const entry = k.LAYERS.find(e => e.id === 'saved-spots');
  assert.deepEqual([entry.control, entry.presentations, entry.sources, entry.time, entry.task, entry.attribution, entry.terrain], ['always', ['chart'], ['private-saved-spots'], ['static'], 'SC0922-04', undefined, undefined]);
  assert.equal(entry.basis, 'Your account’s saved positions, shown only to you; protected-area readings are planning context, not permission to fish.');
  const sentinel = k.readPalette(name => `token(${name})`), style = k.chartStyle({palette: sentinel, archive: null, page: 'https://s.test/map', region: 'morro-bay', base: 'night'});
  const ids = style.layers.map(l => l.id);
  assert.ok(ids.indexOf('saved-spot-pin') > ids.indexOf('ranked-pin') && ids.indexOf('saved-spot-pin') < ids.indexOf(style.layers.find(l => l.source === 'coastline').id), 'after the ranked pins, under the coastline');
  assert.deepEqual(style.sources['private-saved-spots'].data, {type: 'FeatureCollection', features: []}, 'the source starts empty');
  const pick = style.layers.find(l => l.id === 'saved-spot-pick');
  assert.equal(pick.paint['circle-radius'] * 2, 44, 'a 44 px target');
  assert.equal(style.layers.find(l => l.id === 'saved-spot-name').layout['text-field'][1], 'name', 'the name, not a rank number');
  for (const l of style.layers.filter(l => l.source === 'private-saved-spots')) for (const v of Object.values(l.paint)) if (typeof v === 'string') assert.ok(Object.values(sentinel).includes(v), 'palette roles only');
});

test('confirmed_mark_save_invalidates_private_layer: one detail-free event after a confirmed save; a burst is one read; off defers; failure and foreign sessions say nothing', async () => {
  const k = await components();
  const h = await harness();
  const heard = [];
  h.events.addEventListener(k.SAVED_SPOTS_CHANGED, event => heard.push(event));
  await h.turnOn();
  assert.equal(h.net.calls.length, 1);
  const screen = h.screen, session = h.who.peek();
  const mark = {id: 'spot:SC26-001', name: 'Synthetic mark', kind: 'Reef mark', reading: 'r', source: 's', basis: 'b', position: east(150)};
  const post = spy(({init}) => ({ok: true, status: 201, json: async () => ({id: ROW_ID, ...JSON.parse(init.body)})}));
  const deps = over => ({session: () => h.who.peek(), region: () => 'morro-bay', loadScreen: loaded(screen), fetchFn: post.fetchFn, events: h.events, ...over});
  const result = await k.saveMarkSpot(mark, deps());
  assert.equal(result.state, 'saved');
  assert.equal(heard.length, 1, 'one event');
  assert.equal(heard[0].type, 'skippercast:saved-spots-changed');
  assert.ok(!('detail' in heard[0]), 'no row, id, name, position or note on the event');
  assert.equal(h.pins().length, 0, 'the old list is emptied at once');
  await flush();
  assert.equal(h.net.calls.length, 2, 'one replacement read while the layer is active');
  assert.equal(h.pins().length, 3);
  // A burst of events is one read.
  h.events.dispatchEvent(new Event(k.SAVED_SPOTS_CHANGED)); h.events.dispatchEvent(new Event(k.SAVED_SPOTS_CHANGED)); h.events.dispatchEvent(new Event(k.SAVED_SPOTS_CHANGED));
  await flush();
  assert.equal(h.net.calls.length, 3, 'a burst coalesces into one replacement read');
  // Failures and uncertain answers emit nothing.
  heard.length = 0;
  for (const reply of [() => ({ok: false, status: 500, json: async () => ({})}), () => ({ok: true, status: 201, json: async () => ({id: ROW_ID, name: 'other', lat: 1, lon: 1})}),
    () => ({ok: true, status: 201, json: async () => null}), () => { throw new TypeError('offline'); }]) {
    const r = await k.saveMarkSpot(mark, deps({fetchFn: async () => reply()}));
    assert.notEqual(r.state, 'saved');
  }
  assert.equal(heard.length, 0, 'failure, an unconfirmed row and a network error emit none');
  // A session that changed while the answer was on its way: saved for the old one, silent for the new.
  const foreign = await k.saveMarkSpot(mark, deps({fetchFn: async (_u, init) => { h.who.value = SIGNED_IN(); return {ok: true, status: 201, json: async () => ({id: ROW_ID, ...JSON.parse(init.body)})}; }}));
  assert.equal(foreign.state, 'saved');
  assert.equal(heard.length, 0, 'a late foreign session emits none');
  assert.notEqual(h.who.peek(), session);
  h.destroy();

  // Off: the event marks the list stale; the read waits for the next turn-on.
  const off = await harness();
  await off.turnOn();
  off.k.setSavedSpotsOn(false); await flush();
  off.events.dispatchEvent(new Event(off.k.SAVED_SPOTS_CHANGED)); await flush();
  assert.equal(off.net.calls.length, 1, 'nothing is read while off');
  await off.turnOn();
  assert.equal(off.net.calls.length, 2, 'read at the next turn-on');
  assert.equal(off.pins().length, 3);
  off.destroy();

  // The account panel's own writes use the same event name, and only the spot writes (not the catch log).
  const account = readFileSync(new URL('../dist/account.js', import.meta.url), 'utf8');
  assert.ok(account.includes(`'${k.SAVED_SPOTS_CHANGED}'`));
  assert.equal(account.split('spotsChanged()').length - 1, 2, 'after the spot POST and the spot DELETE');
  assert.match(account, /api\('spots', \{method: 'POST'[^\n]*\n\s*\$\('#spot-form'\)\.reset\(\); spotsChanged\(\)/);
  assert.match(account, /api\('spots\/' \+ encodeURIComponent\(b\.dataset\.removeSpot\), \{method: 'DELETE', body: \{\}\}\); spotsChanged\(\)/);
});

test('account_change_and_destroy_ignore_late_answers: A to signed out to B, a late list, a late screen, and a destroyed layer', async () => {
  const k = await components();
  const lateA = {}, a = SIGNED_IN();
  const pending = new Promise(resolve => { lateA.resolve = resolve; });
  let n = 0;
  const net = spy(() => ++n === 1 ? pending : answer({spots: [stored(9, east(150), {name: 'B spot'})]}));
  const h = await harness({session: a, net});
  await h.turnOn();
  assert.equal(h.net.calls.length, 1);
  assert.equal(k.savedSpotsStatus.value.text, 'Loading your saved spots…');
  h.who.value = {state: 'signed-out', advisor: false}; await flush();
  const b = SIGNED_IN();
  assert.equal(b.name, a.name, 'the same display name');
  h.who.value = b; await flush();
  assert.equal(k.savedSpotsOn.value, false, 'the choice does not carry to the next account');
  assert.equal(h.net.calls.length, 1, 'turned off for the new session: nothing asked for it yet');
  await h.turnOn();
  assert.equal(h.net.calls.length, 2);
  assert.deepEqual(h.pins().map(f => f.properties.name), ['B spot']);
  lateA.resolve(answer({spots: [stored(1, east(150), {name: 'A spot'})]})); await flush();
  assert.deepEqual(h.pins().map(f => f.properties.name), ['B spot'], 'a late answer from A is ignored, though the display names match');
  // A card from A's list never survives into B.
  k.pickSavedSpot(h.pins()[0].properties, mark => { h.chartMark.value = mark; });
  h.who.value = SIGNED_IN(); await flush();
  assert.equal(h.chartMark.value, null);
  h.destroy();

  // A screen that arrives after a region switch is ignored; a list that arrives after destroy changes nothing.
  const slowScreen = {};
  const lateScreen = new Promise(resolve => { slowScreen.resolve = resolve; });
  const lateList = {};
  const listPending = new Promise(resolve => { lateList.resolve = resolve; });
  let reads = 0;
  const g = await harness({loadScreen: () => lateScreen, net: spy(() => ++reads === 1 ? answer({spots: [stored(1, east(150), {name: 'Clear spot'})]}) : listPending)});
  await g.turnOn();
  g.k.state.region.value = 'elsewhere'; await flush();
  slowScreen.resolve({state: 'loaded', region: 'morro-bay', screen: g.screen}); await flush();
  assert.equal(g.k.savedSpotMark(g.pins()[0]?.properties ?? {key: 's0'})?.reading ?? 'Protected areas not checked', 'Protected areas not checked', 'the screen for a region we left is not used');
  g.k.state.region.value = 'morro-bay';
  g.events.dispatchEvent(new Event(g.k.SAVED_SPOTS_CHANGED)); await flush();
  assert.equal(reads, 2, 'the replacement read is in flight');
  const setsBefore = g.sets.length;
  g.destroy();
  lateList.resolve(answer({spots: [stored(1, east(150), {name: 'After destroy'})]})); await flush();
  assert.equal(g.sets.length, setsBefore, 'a destroyed layer draws nothing more');
  assert.ok(!JSON.stringify(g.last).includes('After destroy'));
  g.events.dispatchEvent(new Event(g.k.SAVED_SPOTS_CHANGED)); await flush();
  assert.equal(reads, 2, 'a destroyed layer no longer listens');
});

test('the Chart wiring: a pin click opens the private card without touching the address; the layer is not in the link, history or storage', async () => {
  const k = await components();
  const nav = {href: 'https://s.test/map?region=morro-bay&presentation=chart&view=35.43100,-121.10000,10.9'};
  const writes = [];
  globalThis.location = nav;
  globalThis.history = {state: null, pushState(_s, _t, url) { writes.push(['push', String(url)]); }, replaceState(_s, _t, url) { writes.push(['replace', String(url)]); }};
  globalThis.dispatchEvent = () => true;
  const store = {getItem: () => null, setItem: (key, value) => writes.push(['storage', key, String(value)])};
  k.state.configureStore({v2: true, storage: store});
  k.state.syncFromURL(nav.href);
  writes.length = 0;
  const maps = [], features = [];
  class FakeMap {
    constructor(options) { this.options = options; this.handlers = {}; this.data = {}; maps.push(this); this.keyboard = this.touchZoomRotate = {disableRotation() {}}; }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type, event = {}) { for (const fn of this.handlers[type] ?? []) fn(event); }
    addControl() {} getCenter() { return {lat: this.options.center[1], lng: this.options.center[0]}; } getZoom() { return this.options.zoom; } jumpTo() {}
    getLayer(id) { return this.options.style.layers.some(l => l.id === id) ? {} : undefined; } setLayoutProperty() {}
    getSource(id) { return this.options.style.sources[id] ? {setData: data => { this.data[id] = data; }} : undefined; }
    queryRenderedFeatures(point, options) { const layers = options?.layers ?? point.layers; return features.filter(f => layers.includes(f.layer.id)); }
    resize() {} remove() {}
  }
  const control = class {};
  const lib = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}}, workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  const net = spy(({url}) => url === '/api/spots' ? answer({spots: [stored(1, east(150), {name: 'Chart spot'})]}) : answer({}, {ok: false, status: 404}));
  k.session.value = SIGNED_IN();
  k.savedSpotsOn.value = false;
  k.state.region.value = 'morro-bay';
  k.camera.value = {latitude: 35.431, longitude: -121.1, zoom: 10.9};
  const host = {dataset: {}};
  // The Chart mounts through its own entry, as the stage does.
  const chart = k.createChart({host, load: async () => lib, fetchFn: net.fetchFn, palette: () => k.readPalette(name => `token(${name})`), page: () => nav.href, viewDelay: 0});
  await flush();
  const [map] = maps;
  assert.ok(map, 'the Chart mounted');
  assert.equal(net.calls.filter(c => c.url === '/api/spots').length, 0, 'mounting the Chart asks nothing of the account');
  assert.deepEqual(map.data['private-saved-spots']?.features ?? [], []);
  k.setSavedSpotsOn(true); await flush(); await flush();
  assert.equal(net.calls.filter(c => c.url === '/api/spots').length, 1);
  const pin = map.data['private-saved-spots'].features[0];
  assert.equal(pin.properties.name, 'Chart spot');
  const before = k.picked.value;
  features.push({layer: {id: 'saved-spot-pick'}, properties: pin.properties});
  map.fire('click', {point: {x: 0, y: 0}, lngLat: {lng: pin.geometry.coordinates[0], lat: pin.geometry.coordinates[1]}});
  assert.equal(k.chartMark.value?.name, 'Chart spot', 'the pin opens its private card');
  assert.equal(k.picked.value, before + 1);
  assert.deepEqual(writes, [], 'turning the layer on and picking a pin write nothing to the address, history or storage');
  assert.equal(nav.href.includes('saved'), false);
  k.setSavedSpotsOn(false);
  assert.equal(k.chartMark.value, null);
  assert.deepEqual(map.data['private-saved-spots'].features, []);
  chart.destroy();
  assert.equal(k.chartMark.value, null);
});
