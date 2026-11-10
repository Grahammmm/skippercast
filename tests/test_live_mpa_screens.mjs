// SC1407-06 (#1762 M4): the map's mark screen (web/map/marks.ts) and the planner's screen (dist/protected-areas.js) ask the
// same live CDFW ds582 query on every /map load. While one read is in flight they share it (dist/live-mpa.js): one request
// and one parsed answer, each screen still running its own checks and fallbacks, both stamped with the time the answer
// arrived. Offline: committed dist/ files, a held synthetic ds582 answer and the Worker's daily parts built here.
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {createLiveMpaReader} from '../dist/live-mpa.js';
import {MPA_QUERY, initProtectedAreas} from '../dist/protected-areas.js';
import {setRegion} from '../dist/region.js';
import {CHECKING, SCREEN_MAX_AGE_MS} from '../web/map/habitat.ts';
import {createMarks, markScreen} from '../web/map/marks.ts';
import {MPA_SERVICE, mpaQuery} from '../web/map/mpa.ts';
import {shareStatic, sharedFetch} from '../web/shared-fetch.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const HOUR = 3600000;
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MORRO = read('regions/morro-bay/region.json'), MPAS = read('data/protected-areas.geojson');
const iso = ms => new Date(ms).toISOString();
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise(resolve => setImmediate(resolve)); };
const gate = () => { const g = {}; g.wait = new Promise(resolve => { g.open = resolve; }); return g; };
const ok = body => ({ok: true, status: 200, json: async () => body});
const down = status => ({ok: false, status, json: async () => ({})});
const record = (at, geojson) => ({status: 'ok', data_retrieved_at: iso(at), data: {geojson}});

/**
 * The site offline. `live(call)` answers each ds582 request (it may hold); `daily` answers the Worker's parts
 * (a missing part is a 503); `patch` replaces committed files by path. `net.live` lists the ds582 requests.
 */
function site({live = () => down(503), daily = {}, patch = {}} = {}) {
  const net = {live: []};
  net.fetch = async url => {
    const at = new URL(String(url), PAGE);
    if (at.origin + at.pathname === MPA_SERVICE) {
      const call = {url: String(url), geometry: at.searchParams.get('geometry')};
      net.live.push(call);
      return live(call);
    }
    if (at.pathname === '/api/daily') {
      const part = at.searchParams.get('part');
      return part in daily ? ok({schema_version: 1, region_id: at.searchParams.get('region'), part, generated_at: iso(Date.now()),
        catch_probability: null, bite_score: null, sources: {[part]: daily[part]}}) : down(503);
    }
    const path = at.pathname.slice(1);
    if (path in patch) return ok(patch[path]);
    return existsSync(new URL(`../dist/${path}`, import.meta.url)) ? ok(read(path)) : down(404);
  };
  return net;
}
/** A held ds582 answer: `arrive()` lets the response through, `parse()` lets its body through; `parses` counts json() calls. */
function heldAnswer(body) {
  const arrival = gate(), parsing = gate(), held = {parses: 0, arrive: arrival.open, parse: parsing.open};
  held.live = () => arrival.wait.then(() => ({ok: true, status: 200, json: () => { held.parses++; return parsing.wait.then(() => body); }}));
  return held;
}

let saved;
/** The page's globals for both screens: v1's planner reads the global fetch and document, v2's marks read location. */
function page(net, region = 'morro-bay') {
  saved ??= {fetch: globalThis.fetch, document: globalThis.document};
  setRegion(MORRO);
  globalThis.fetch = net.fetch;
  globalThis.document = {getElementById: () => ({textContent: '', classList: {toggle() {}}}), dispatchEvent() {}};
  const href = `${PAGE}?region=${region}&target=reef`;
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}
test.afterEach(() => { if (saved) Object.assign(globalThis, saved); saved = undefined; setRegion(MORRO); });

const marksFor = (net, options = {}) => createMarks({fetchFn: net.fetch, page: () => PAGE, resolver: async () => ({resolveHabitatSelection: async () => null}), ...options});
/** The planner's screen (web/trip.ts, dist/account.js) with its startup refresh started. */
async function plannerFor(liveMpaRead) {
  const screen = await initProtectedAreas(null, () => {}, undefined, liveMpaRead);
  return {screen, refreshed: screen.refresh()};
}
/** The planner's live checked time, as its revision carries it. */
const plannerChecked = screen => screen.revision().split('|')[0];
/** The mark screen's checked time: a ready screen expires 36 hours after it. */
const marksChecked = () => markScreen.value.status === 'ready' ? iso(markScreen.value.until - SCREEN_MAX_AGE_MS) : null;
/** Each screen run alone over `answers`, with its own reader: the old isolated path. */
async function alone(answers, now) {
  const net = site(answers);
  page(net);
  const marks = marksFor(net, {now});
  await settle();
  const m = {status: markScreen.value.status, checked: marksChecked(), count: markScreen.value.boundaries.length};
  marks.destroy();
  const {screen, refreshed} = await plannerFor(createLiveMpaReader({fetchFn: net.fetch, now}));
  await refreshed;
  return {marks: m, planner: {ready: screen.ready(), checked: plannerChecked(screen), features: screen.exportExclusions()?.features.length ?? null}};
}

test('same_url_one_fetch_one_parse_one_arrival: the map and the planner share one request, one parse and its arrival time', async () => {
  assert.equal(mpaQuery(MORRO.mpa.bounds), MPA_QUERY, 'both screens ask the exact same URL for Morro Bay');
  const body = {type: 'FeatureCollection', features: MPAS.features};
  let clock = Date.now();
  const now = () => clock, held = heldAnswer(body), net = site({live: held.live});
  page(net);
  const reader = createLiveMpaReader({fetchFn: net.fetch, now});
  const marks = marksFor(net, {liveMpaRead: reader, now});
  const {screen, refreshed} = await plannerFor(reader);
  await settle();
  assert.equal(net.live.length, 1, 'one live request for both screens');
  assert.equal(markScreen.value, CHECKING);
  const arrived = clock;
  held.arrive(); await settle();
  clock += 90_000;   // a slow parse: neither screen's checked time moves past the arrival
  held.parse(); await refreshed; await settle();
  assert.equal(held.parses, 1, 'one parse for both screens');
  assert.equal(net.live.length, 1);
  assert.equal(markScreen.value.status, 'ready');
  assert.equal(screen.ready(), true);
  assert.equal(marksChecked(), iso(arrived), 'the mark screen is checked when the answer arrived');
  assert.equal(plannerChecked(screen), iso(arrived), 'the planner is checked when the answer arrived');
  assert.equal(markScreen.value.boundaries.length, MPAS.features.length);
  assert.ok(screen.exportExclusions().features.every((f, i) => f === MPAS.features[i]), 'the planner holds the shared parsed areas');
  marks.destroy();
  // Control: each screen alone over the same answer accepts the same areas.
  const control = await alone({live: () => ok(body)}, () => arrived);
  assert.ok(isDeepStrictEqual(control, {marks: {status: 'ready', checked: iso(arrived), count: MPAS.features.length},
    planner: {ready: true, checked: iso(arrived), features: MPAS.features.length}}), JSON.stringify(control));
});

test('exact_key_only: a mark screen with other bounds makes its own request', async () => {
  const body = {type: 'FeatureCollection', features: MPAS.features};
  const held = heldAnswer(body), net = site({live: held.live});
  page(net, 'southern-california');
  const reader = createLiveMpaReader({fetchFn: net.fetch});
  const marks = marksFor(net, {liveMpaRead: reader});
  const {refreshed} = await plannerFor(reader);
  await settle();
  assert.equal(net.live.length, 2, 'different bounds are never merged');
  assert.notEqual(net.live[0].geometry, net.live[1].geometry);
  held.arrive(); held.parse(); await refreshed; await settle();
  assert.equal(held.parses, 2);
  marks.destroy();
});

test('no_completed_replay: a refresh after the first answer asks again and is checked when its own answer arrives', async () => {
  const body = {type: 'FeatureCollection', features: MPAS.features};
  let clock = Date.now() - 2 * HOUR;
  const now = () => clock, net = site({live: () => ok(body)});
  page(net);
  const reader = createLiveMpaReader({fetchFn: net.fetch, now});
  const marks = marksFor(net, {liveMpaRead: reader, now});
  const {screen, refreshed} = await plannerFor(reader);
  await refreshed; await settle();
  const first = iso(clock);
  assert.equal(net.live.length, 1);
  assert.deepEqual([marksChecked(), plannerChecked(screen)], [first, first]);
  clock += HOUR;
  await screen.refresh();
  assert.equal(net.live.length, 2, 'the finished answer is not handed to the refresh');
  assert.equal(plannerChecked(screen), iso(clock), 'the refresh is checked when its answer arrived');
  assert.equal(marksChecked(), first, 'the map keeps its own check');
  marks.destroy();
});

test('each_reader_keeps_its_validator: one shared answer, accepted by the planner, below the map\'s minimum', async () => {
  // The live answer has exactly the planner's minimum; the map's region file asks for one more, which the daily record has.
  const minimum = MORRO.mpa.minimum_features, fallback = Date.now() - 3 * HOUR, arrived = Date.now() - HOUR;
  const extra = {...MPAS.features[0], properties: {...MPAS.features[0].properties, NAME: 'Test Reef SMR', FULLNAME: 'Test Reef State Marine Reserve'}};
  const fuller = {...MPAS, features: [...MPAS.features, extra]};
  assert.ok(fuller.features.length > minimum);
  const body = {type: 'FeatureCollection', features: MPAS.features.slice(0, minimum)};
  const strict = {...MORRO, mpa: {...MORRO.mpa, minimum_features: minimum + 1}};
  const held = heldAnswer(body), net = site({live: held.live, patch: {'regions/morro-bay/region.json': strict},
    daily: {'mpa-boundaries': record(fallback, fuller)}});
  page(net);
  const reader = createLiveMpaReader({fetchFn: net.fetch, now: () => arrived});
  const marks = marksFor(net, {liveMpaRead: reader});
  const {screen, refreshed} = await plannerFor(reader);
  await settle();
  held.arrive(); held.parse(); await refreshed; await settle();
  assert.equal(net.live.length, 1);
  assert.equal(held.parses, 1);
  assert.equal(screen.ready(), true, 'the planner accepts the answer at its own minimum');
  assert.equal(plannerChecked(screen), iso(arrived));
  assert.equal(screen.exportExclusions().features.length, minimum);
  // The map refuses the same answer and reads the daily feed's record, as it would alone: never the planner's live check.
  assert.equal(markScreen.value.status, 'ready');
  assert.equal(marksChecked(), iso(fallback), 'the record keeps its retrieval time');
  assert.equal(markScreen.value.boundaries.length, fuller.features.length);
  assert.ok(!markScreen.value.source.includes('this session'), markScreen.value.source);
  marks.destroy();
});

test('failure_fallback_and_staleness_parity: a failed or invalid answer falls back for both screens, as each alone', async t => {
  const recordAt = Date.now() - 5 * HOUR;
  const daily = {'mpa-boundaries': record(recordAt, MPAS)};
  const cases = {
    'HTTP failure': () => down(503),
    'transport failure': () => Promise.reject(new TypeError('network down')),
    'broken JSON': () => ({ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected end of JSON input'); }}),
    'provider error body': () => ok({error: {code: 500, message: 'down'}}),
    'transfer limit': () => ok({type: 'FeatureCollection', exceededTransferLimit: true, features: MPAS.features}),
    'too few areas': () => ok({type: 'FeatureCollection', features: MPAS.features.slice(0, 2)}),
    'bad geometry': () => ok({type: 'FeatureCollection', features: MPAS.features.map(f => ({...f, geometry: {type: 'Point', coordinates: [0, 0]}}))}),
  };
  for (const [name, live] of Object.entries(cases)) {
    await t.test(name, async () => {
      for (const withRecord of [true, false]) {
        const net = site({live, daily: withRecord ? daily : {}});
        page(net);
        const reader = createLiveMpaReader({fetchFn: net.fetch});
        const marks = marksFor(net, {liveMpaRead: reader});
        const {screen, refreshed} = await plannerFor(reader);
        await refreshed; await settle();
        const shared = {marks: {status: markScreen.value.status, checked: marksChecked(), count: markScreen.value.boundaries.length},
          planner: {ready: screen.ready(), checked: plannerChecked(screen), features: screen.exportExclusions()?.features.length ?? null}};
        marks.destroy();
        assert.equal(net.live.length, 1, `${name}: one request for both`);
        const control = await alone({live, daily: withRecord ? daily : {}});
        assert.ok(isDeepStrictEqual(shared, control), `${name} ${withRecord}: ${JSON.stringify(shared)} vs alone ${JSON.stringify(control)}`);
        if (withRecord) {
          assert.equal(shared.marks.status, 'ready');
          assert.equal(shared.marks.checked, iso(recordAt), 'the record keeps its retrieval time, never now');
          assert.equal(shared.planner.checked, iso(recordAt));
        } else {
          assert.notEqual(shared.marks.status, 'ready', 'no live answer and no record: the marks stay withheld');
          assert.equal(shared.planner.ready, false, 'the planner withholds on its saved snapshot');
        }
      }
    });
  }
});

test('refresh_and_disposal_do_not_rejuvenate: a destroyed mark screen ignores the shared answer; the planner still takes it', async () => {
  const body = {type: 'FeatureCollection', features: MPAS.features};
  const held = heldAnswer(body), net = site({live: held.live});
  page(net);
  const reader = createLiveMpaReader({fetchFn: net.fetch});
  const marks = marksFor(net, {liveMpaRead: reader});
  const {screen, refreshed} = await plannerFor(reader);
  await settle();
  assert.equal(net.live.length, 1);
  marks.destroy();
  held.arrive(); held.parse(); await refreshed; await settle();
  assert.equal(markScreen.value, CHECKING, 'no obsolete mark screen appears');
  assert.equal(screen.ready(), true);
});

test('the production chain: the Chart\'s sharedFetch marks and the planner meet on the page reader', async () => {
  assert.equal(shareStatic(sharedFetch), sharedFetch, 'chart.ts passes this exact function to createMarks');
  const body = {type: 'FeatureCollection', features: MPAS.features};
  const held = heldAnswer(body), net = site({live: held.live});
  page(net);
  const marks = createMarks({fetchFn: sharedFetch, page: () => PAGE, resolver: async () => ({resolveHabitatSelection: async () => null})});
  const {screen, refreshed} = await plannerFor(undefined);
  await settle();
  assert.equal(net.live.length, 1, 'the default chain makes one live request');
  held.arrive(); held.parse(); await refreshed; await settle();
  assert.equal(held.parses, 1);
  assert.equal(markScreen.value.status, 'ready');
  assert.equal(marksChecked(), plannerChecked(screen), 'one arrival time');
  marks.destroy();
  // An explicit test network without a reader stays isolated from the page reader.
  const other = heldAnswer(body), net2 = site({live: other.live});
  page(net2);
  globalThis.fetch = net.fetch;
  const isolated = marksFor(net2);
  const planner2 = await plannerFor(undefined);
  await settle();
  assert.deepEqual([net.live.length, net2.live.length], [2, 1], 'an injected fetchFn gets its own reader');
  held.arrive(); other.arrive(); other.parse(); await planner2.refreshed; await settle();
  isolated.destroy();
});
