// The v2 app shell (FE-05 desktop, FE-06 mobile; docs/plans/front-end/dev-plan.md): the
// web/app modules are bundled with esbuild and rendered to strings against a
// store read from a test address. Checks the shell's structure (masthead,
// command bar, brief, map chrome), that every control reflects the URL state
// it writes (profile, view, day, hour, layers, selection), that the brief's
// empty state invents no number, and that the copy and token rules hold.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {readdirSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import {lintFile} from '../scripts/check_tokens.mjs';
import {waterState} from './helpers/land-water.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const APP_FILES = ['web/app', 'web/app/views'].flatMap(dir => readdirSync(join(ROOT, dir)).filter(name => name.includes('.')).map(name => `${dir}/${name}`));
const ORIGIN = 'https://s.test/map';
const TZ = 'America/Los_Angeles';
/** The shell's clock in every render: Monday 2026-10-05, 1 pm Pacific, so chips and windows read the same whatever day the tests run. */
const NOW = new Date('2026-10-05T20:00:00Z');
/** The day chips of the 169-hour horizon from NOW: the eighth day repeats Monday, so it carries its date. */
const WEEK = ['Today', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon 12'];
/** The rendered chips (SC2252-06): each day with its verdict word; no feed is loaded in these renders, so every day reads Unknown. */
const CHIPS = WEEK.map(label => `${label}`);
/** 2 pm Pacific on Tuesday 2026-10-06. */
const TUE_2PM = '2026-10-06T21:00Z';

let shell;
async function load() {
  if (shell) return shell;
  const out = join(await mkdtemp(join(tmpdir(), 'shell-')), 'shell.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export * from './web/app/App.tsx';
      export {Planner} from './web/app/Planner.tsx';
      export {createPlanner} from './web/planner.ts';
      export {AccountMenu} from './web/app/AccountMenu.tsx';
      export {LanguageChoice} from './web/app/LanguageChoice.tsx';
      export {language, setLanguage} from './web/i18n.ts';
      export {session, ensureSession, refreshSession, readSession} from './web/account.ts';
      export {coordinates, titleCase, viewParam, MASTHEAD_VIEWS, TAB_VIEWS, ChatEntry, Location, DegradedNotice} from './web/app/Masthead.tsx';
      export {degraded, watchDegraded, installDegradedWatch} from './web/degraded.ts';
      export {targetOptions, windowText} from './web/app/CommandBar.tsx';
      export {Brief, emptyTiles, DISCLAIMER} from './web/app/Desktop.tsx';
      export {RAIL_ENTRIES, toggled} from './web/app/LayerRail.tsx';
      export {MarkCard, clearSelection, currentMark, placeholderMark, readingCard, terrainCard} from './web/app/MarkCard.tsx';
      export {chartMark} from './web/map/chart.ts';
      export {PresentationToggle, TerrainControls, PRESENTATIONS} from './web/app/MapStage.tsx';
      export {terrainActions, terrainFailed, terrainReason, UNAVAILABLE, NO_TERRAIN} from './web/map/stage.ts';
      export {beginWaypointPlacement, cancelWaypointPlacement, placeWaypoint, placementRefused} from './web/waypoint-placement.ts';
      export {Legend, RankedRow} from './web/app/Legend.tsx';
      export {rankedSpots} from './web/map/ranked.ts';
      export {landWater} from './web/land-water.ts';
      export {publishedChartFiles} from './web/chart-files.ts';
      export {markScreen} from './web/map/marks.ts';
      export {regionUnavailable} from './web/species.ts';
      export {CHECKING, assessScreen} from './web/map/habitat.ts';
      export {createStage, terrainMark, terrainReading} from './web/map/stage.ts';
      export {createHourClock} from './web/clock.ts';
      export {dayOptions, dockState, hourText, localParts, readout, zoneName} from './web/app/TimeDock.tsx';
      export {Mobile, LayersPanel, afterDetent, toggleLayers} from './web/app/Mobile.tsx';
      export {dragDetent, DRAG_MIN} from './web/ui/Sheet.tsx';
      export * as state from './web/state.ts';
      export {PROFILE_TABLE, RAIL_IDS} from './web/profile.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: preparedRendererPlugins,
  });
  shell = await import(pathToFileURL(out).href);
  return shell;
}
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))}; };

test('coordinate choice is exposed in settings and used by the plan rows', async () => {
  const {Planner, createPlanner, AccountMenu, render, h, state} = await load();
  state.configureStore({storage: memory()});
  const t = {id: 'fixture', label: 'Fixture', latitude: -0.5, longitude: 0.5};
  const model = createPlanner({atlas: {targets: [t], areas: []}, screen: {ready: () => false},
    region: {id: 'test', timezone: 'UTC', mpa: {bounds: [-1, -1, 1, 1]}}, storage: null,
    map: {getBounds: () => ({getWest: () => -1, getEast: () => 1, getSouth: () => -1, getNorth: () => 1})},
    getVisible: () => [t], loadPorts: async () => null, nav: {}, emit() {}});
  model.add(t.id);
  try {
    for (const [mode, label, expected] of [['dd', 'Decimal degrees', '0.50000° S, 0.50000° E'], ['ddm', 'Degrees and decimal minutes', '0° 30.000′ S, 0° 30.000′ E'], ['dms', 'Degrees minutes seconds', '0° 30′ 00.00″ S, 0° 30′ 00.00″ E']]) {
      state.setCoordinateFormat(mode);
      assert.ok(render(h(Planner, {model, open: false})).includes(expected));
      assert.match(render(h(AccountMenu, {})), new RegExp(`aria-pressed="true"[^>]*>${label}</button>`));
    }
  } finally { state.setCoordinateFormat('dd'); model.dispose(); }
});
test('language_choice: the account menu offers English and Español in both languages, and the pressed one follows the language signal', async () => {
  const {AccountMenu, LanguageChoice, language, setLanguage, session, render, h} = await load();
  const buttons = html => [...html.matchAll(/<button\b[^>]*\blang="(en|es)"[^>]*>([^<]*)<\/button>/g)].map(m => ({lang: m[1], label: m[2], pressed: /aria-pressed="true"/.test(m[0]), tag: m[0]}));
  const none = {getItem: () => null, setItem() {}};
  const before = session.value;
  try {
    for (const lang of ['en', 'es']) {
      setLanguage(lang, {storage: none, doc: null});
      const html = render(h(LanguageChoice, {}));
      assert.deepEqual(buttons(html).map(b => [b.lang, b.label, b.pressed]), [['en', 'English', lang === 'en'], ['es', 'Español', lang === 'es']], `${lang}: each language is named in itself, the current one is pressed`);
      assert.ok(buttons(html).every(b => /type="button"/.test(b.tag)), 'plain buttons, not a form control');
      assert.match(html, new RegExp(`<h2[^>]*>${lang === 'en' ? 'Language' : 'Idioma'}</h2>`));
      assert.match(html, /<section aria-labelledby="([^"]+)-language">\s*<h2 id="\1-language"/, 'the group is labelled by its heading');
    }
    // In the menu itself, once, before the coordinate format, whatever the account state.
    for (const state of [{state: 'loading'}, {state: 'offline'}, {state: 'disabled'}, {state: 'signed-out'}, {state: 'signed-in', name: 'Skipper'}]) {
      session.value = state; setLanguage('en', {storage: none, doc: null});
      const menu = render(h(AccountMenu, {})), inline = render(h(AccountMenu, {inline: true}));
      for (const html of [menu, inline]) {
        assert.equal(buttons(html).length, 2, `${state.state}: one chooser`);
        assert.ok(html.indexOf('>Language</h2>') > html.indexOf('Your boat') && html.indexOf('>Language</h2>') < html.indexOf('Coordinate format'), `${state.state}: between the boat and the coordinate format`);
      }
    }
  } finally { session.value = before; setLanguage('en', {storage: none, doc: null}); }
});
test('startup region reader shares parsed cold work and refuses distinct-key saturation', async () => {
  const {createRegionReader} = await load();
  const gates = new Map();
  const calls = [];
  const reader = createRegionReader(async (url, init) => {
    calls.push({url, init});
    const gate = Promise.withResolvers();
    gates.set(url, gate);
    return gate.promise;
  }, {limit: 2, timeoutMs: 1000});
  const first = reader('a');
  const same = reader('a');
  assert.equal(first, same);
  const second = reader('b');
  await assert.rejects(reader('c'), /saturated/);
  assert.equal(calls.length, 2);
  gates.get('regions/a/region.json').resolve(new Response(JSON.stringify({name: 'A', map: {center: [1, 2]}})));
  gates.get('regions/b/region.json').resolve(new Response(JSON.stringify({name: 'B', map: {center: [3, 4]}})));
  assert.equal((await first).name, 'A');
  assert.equal((await same).id, 'a');
  assert.equal((await second).id, 'b');
});

test('startup region reader bounds body work and holds non-cooperative slots', async () => {
  const {createRegionReader} = await load();
  const body = Promise.withResolvers();
  let reads = 0, signal;
  const reader = createRegionReader(async (_url, init) => {
    reads++; signal = init.signal;
    return {ok: true, json: () => body.promise};
  }, {limit: 1, timeoutMs: 15});
  await assert.rejects(reader('a'));
  assert.equal(signal.aborted, true);
  await assert.rejects(reader('b'), /saturated/);
  assert.equal(reads, 1);
  body.resolve({name: 'Late A', map: {center: [1, 2]}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((await reader('b')).name, 'Late A');
  assert.equal(reads, 2);
});

test('RF0850-2: a region change marks its chart file list pending until loadRegion publishes it or fails open', async () => {
  const {loadRegion, publishedChartFiles, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=rf0850-a`);
  assert.deepEqual(publishedChartFiles.peek(), {region: 'rf0850-a', files: null, pending: true}, 'pending, not null: the Chart waits');
  const json = body => async () => new Response(JSON.stringify(body));
  await loadRegion('rf0850-a', json({name: 'A', map: {center: [1, 2]}, chart_files: []}));
  assert.deepEqual(publishedChartFiles.peek(), {region: 'rf0850-a', files: []});
  state.syncFromURL(`${ORIGIN}?region=rf0850-b`);
  assert.deepEqual(publishedChartFiles.peek(), {region: 'rf0850-b', files: null, pending: true});
  assert.equal(await loadRegion('rf0850-b', async () => ({ok: false})), null);
  assert.deepEqual(publishedChartFiles.peek(), {region: 'rf0850-b', files: null}, 'a failed read: no list, every file fails open');
  state.syncFromURL(`${ORIGIN}?region=rf0850-c`);
  assert.equal(await loadRegion('rf0850-c', async () => { throw new Error('offline'); }), null);
  assert.deepEqual(publishedChartFiles.peek(), {region: 'rf0850-c', files: null});
});

test('app region publication shares a cold read but only the latest selection publishes', async () => {
  const {loadRegion, regionInfo, regionLoad, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  const gates = new Map();
  let calls = 0;
  const fetcher = async url => {
    calls++;
    const gate = Promise.withResolvers(); gates.set(url, gate);
    return gate.promise;
  };
  const first = loadRegion('morro-bay', fetcher);
  await new Promise(resolve => setImmediate(resolve));
  const latest = loadRegion('morro-bay', fetcher);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1, 'same-key requests share JSON work, despite caller cancellation');
  assert.equal(await first, null);
  state.syncFromURL(`${ORIGIN}?region=southern-california`);
  const south = loadRegion('southern-california', fetcher);
  await new Promise(resolve => setImmediate(resolve));
  gates.get('regions/southern-california/region.json').resolve(new Response(JSON.stringify({name: 'South', map: {center: [3, 4]}})));
  assert.equal((await south).name, 'South');
  gates.get('regions/morro-bay/region.json').resolve(new Response(JSON.stringify({name: 'Obsolete A', map: {center: [1, 2]}})));
  assert.equal(await latest, null);
  assert.equal(regionInfo.peek().name, 'South');
  assert.deepEqual(regionLoad.peek(), {id: 'southern-california', state: 'ready'});
});

test('app region timeout withdraws metadata and a reload retry can recover', async t => {
  const {loadRegion, regionInfo, regionLoad, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  t.mock.timers.enable({apis: ['setTimeout']});
  const body = Promise.withResolvers();
  const inits = [];
  const fetcher = async (_url, init) => {
    inits.push(init);
    return inits.length === 1 ? {ok: true, json: () => body.promise} :
      new Response(JSON.stringify({name: 'Recovered', map: {center: [1, 2]}}));
  };
  const pending = loadRegion('morro-bay', fetcher);
  await new Promise(resolve => setImmediate(resolve));
  t.mock.timers.tick(10_001);
  assert.equal(await pending, null);
  assert.equal(regionInfo.peek(), null);
  assert.deepEqual(regionLoad.peek(), {id: 'morro-bay', state: 'error'});
  assert.equal(inits[0].signal.aborted, true);
  assert.equal((await loadRegion('morro-bay', fetcher, true)).name, 'Recovered');
  assert.equal(inits[1].cache, 'reload');
  body.resolve({name: 'Too late', map: {center: [8, 9]}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(regionInfo.peek().name, 'Recovered');
});

test('app distinct-key saturation becomes an immediate visible region error', async () => {
  const {loadRegion, regionInfo, regionLoad, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  const gates = [];
  const fetcher = async () => {
    const gate = Promise.withResolvers(); gates.push(gate); return gate.promise;
  };
  const pending = [];
  try {
    for (const id of ['one', 'two', 'three', 'four']) {
      state.syncFromURL(`${ORIGIN}?region=${id}`);
      pending.push(loadRegion(id, fetcher));
      await new Promise(resolve => setImmediate(resolve));
    }
    state.syncFromURL(`${ORIGIN}?region=five`);
    assert.equal(await loadRegion('five', fetcher), null);
    assert.equal(gates.length, 4, 'saturation refuses before starting a fifth fetch');
    assert.equal(regionInfo.peek(), null);
    assert.deepEqual(regionLoad.peek(), {id: 'five', state: 'error'});
  } finally {
    for (const gate of gates) gate.resolve(new Response('{}'));
    await Promise.all(pending);
    await new Promise(resolve => setImmediate(resolve));
  }
});

test('startup region reader bounds stalled headers and recovers after a rejection', async () => {
  const {createRegionReader} = await load();
  const gate = Promise.withResolvers();
  let signal;
  const reader = createRegionReader(async (_url, init) => {
    signal = init.signal; return gate.promise;
  }, {limit: 1, timeoutMs: 15});
  await assert.rejects(reader('fixture'));
  assert.equal(signal.aborted, true);
  gate.reject(Error('late network failure'));
  await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(reader('other'), /late network failure/);
});

test('app startup fixture baseline records cold/warm cache reads without a speed claim', async t => {
  const {loadRegion, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  const cache = new Map(); let downloads = 0;
  const fetcher = async url => {
    if (!cache.has(url)) {
      downloads++;
      cache.set(url, JSON.stringify({name: 'Local fixture', map: {center: [1, 2]}}));
    }
    return new Response(cache.get(url));
  };
  const coldStart = performance.now();
  assert.equal((await loadRegion('morro-bay', fetcher)).name, 'Local fixture');
  const coldMs = performance.now() - coldStart;
  const warmStart = performance.now();
  assert.equal((await loadRegion('morro-bay', fetcher)).name, 'Local fixture');
  t.diagnostic(JSON.stringify({fixture: 'app metadata, synthetic browser cache', coldMs,
    warmMs: performance.now() - warmStart, downloads}));
  assert.equal(downloads, 1);
});

test('startup region reader rejects invalid metadata and allows a later same-key retry', async () => {
  const {createRegionReader} = await load();
  const bodies = [{}, {name: 'Invalid', map: {center: [null, 2]}},
    {name: 'Valid', map: {center: [1, 2]}}];
  const reader = createRegionReader(async () => new Response(JSON.stringify(bodies.shift())));
  assert.equal(await reader('fixture'), null);
  assert.equal(await reader('fixture'), null);
  assert.equal((await reader('fixture')).name, 'Valid');
});

test('startup region reader keeps region.json chart_files only when it is a list of names (RF0850-1)', async () => {
  const {createRegionReader} = await load();
  const base = {name: 'R', map: {center: [1, 2]}};
  const bodies = [{...base, chart_files: ['poster.svg']}, {...base, chart_files: []}, base, {...base, chart_files: 'poster.svg'}, {...base, chart_files: ['a', 2]}];
  const reader = createRegionReader(async () => new Response(JSON.stringify(bodies.shift())), {limit: 1});
  assert.deepEqual((await reader('r1')).chartFiles, ['poster.svg']);
  assert.deepEqual((await reader('r2')).chartFiles, [], 'an empty list is a list');
  for (const id of ['r3', 'r4', 'r5']) assert.equal('chartFiles' in await reader(id), false, id);
});

test('SC-LAUNCH-4: a cost-ceiling response from any reader puts the saved-data notice on the masthead and the mobile sheet', async () => {
  const {degraded, watchDegraded, installDegradedWatch, render, h, App, Mobile, narrow, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  const mark = (headers = {}) => new Response('{}', {headers: {'X-SC-Degraded': 'cost-ceiling', ...headers}});
  try {
    // Live responses leave the shell as it was.
    const live = watchDegraded(async () => new Response('{}'));
    await live('/feeds/data/regions/morro-bay/latest.json');
    assert.equal(degraded.peek(), null);
    assert.doesNotMatch(render(h(App)), /data-degraded/);
    // A free fallback (no saved copy) is marked without a time; the response reaches the caller untouched.
    const fallback = await watchDegraded(async () => mark())('/feeds/data/regions/morro-bay/latest.json');
    assert.equal(await fallback.text(), '{}');
    assert.deepEqual(degraded.peek(), {since: null});
    assert.match(render(h(App)), /<p class="app-limits-note app-degraded" role="status" data-degraded="cost-ceiling">Live data is paused for today to keep SkipperCast free; some readings are saved copies\.<\/p>/);
    // The page's own fetch, wrapped once at start-up, covers readers that never import the watcher; the oldest saved copy is shown.
    const scope = {fetch: async url => mark({'X-SC-Last-Known-At': String(url).includes('old') ? '2026-10-04T15:30:00Z' : '2026-10-05T18:00:00Z'})};
    installDegradedWatch(scope);
    await scope.fetch('/feeds/tiles/basemap/new.pmtiles');
    await scope.fetch('/feeds/data/old.json');
    await scope.fetch('/feeds/data/new.json');
    assert.deepEqual(degraded.peek(), {since: '2026-10-04T15:30:00.000Z'});
    assert.match(render(h(App)), /data-degraded="cost-ceiling">Live data is paused for today to keep SkipperCast free; some readings are saved copies from [^<]+\.<\/p>/);
    narrow.value = true;
    assert.match(render(h(Mobile, {now: NOW})), /data-degraded="cost-ceiling"/);
  } finally { degraded.value = null; narrow.value = false; }
});

test('freshness uses source timestamps and injected clock on the existing masthead', async () => {
  const {startupFreshness, freshness, render, h, App, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  const at = '2026-10-29T12:00:00Z';
  let now = Date.parse(at) + 60_000;
  const tiles = [{at, limitMs: 120_000, value: 10, state: 'fresh'}];
  const update = () => { freshness.value = startupFreshness(tiles, () => now, true); };
  try {
    update();
    assert.deepEqual(freshness.peek(), {state: 'ok', age: '1 min'});
    assert.match(render(h(App)), /data-state="ok"[^>]*aria-label="Freshness: Every reading is fresh".*?1 min/s);
    now += 60_000;
    update();
    assert.deepEqual(freshness.peek(), {state: 'stale', age: '2 min'});
    assert.match(render(h(App)), /data-state="stale"[^>]*aria-label="Freshness: A reading is stale".*?2 min/s);
    update(); // Same cached objects are not a new source clock.
    assert.equal(freshness.peek().age, '2 min');
    assert.equal(tiles[0].at, at);
  } finally { freshness.value = {state: 'unknown', age: null}; }
});

test('startup freshness binding advances without a network read and cleans up', async t => {
  const {bindStartupFreshness, freshness, regionInfo} = await load();
  regionInfo.value = null;
  t.mock.timers.enable({apis: ['setInterval']});
  const target = new EventTarget();
  const at = '2026-10-29T12:00:00Z';
  let now = Date.parse(at) + 60_000, online = true;
  let sourceReads = 0;
  const stop = bindStartupFreshness(() => {
    sourceReads++;
    return regionInfo.value ? [{at, limitMs: 120_000, value: 1, state: 'fresh'}] : [];
  }, {now: () => now, online: () => online, target});
  try {
    assert.equal(freshness.peek().state, 'unknown');
    regionInfo.value = {id: 'fixture'};
    assert.deepEqual(freshness.peek(), {state: 'ok', age: '1 min'});
    now += 60_000;
    t.mock.timers.tick(60_000);
    assert.deepEqual(freshness.peek(), {state: 'stale', age: '2 min'});
    online = false; target.dispatchEvent(new Event('offline'));
    assert.equal(freshness.peek().state, 'offline');
    online = true; target.dispatchEvent(new Event('online'));
    assert.deepEqual(freshness.peek(), {state: 'stale', age: '2 min'});
    regionInfo.value = null;
    assert.equal(freshness.peek().state, 'unknown', 'region withdrawal removes old source ages');
    stop();
    const before = sourceReads;
    t.mock.timers.tick(60_000);
    target.dispatchEvent(new Event('online'));
    regionInfo.value = {id: 'after-dispose'};
    assert.equal(sourceReads, before);
  } finally { stop(); regionInfo.value = null; freshness.value = {state: 'unknown', age: null}; }
});

test('startup freshness never calls missing, retained or future readings fresh', async () => {
  const {startupFreshness} = await load();
  const now = Date.parse('2026-10-29T12:00:00Z');
  const reading = {at: new Date(now - 60_000).toISOString(), limitMs: 120_000, value: 1, state: 'fresh'};
  const fresh = (tiles, online = true) => startupFreshness(tiles, () => now, online);
  assert.deepEqual(fresh([]), {state: 'unknown', age: null});
  assert.equal(fresh([reading], false).state, 'offline');
  assert.equal(fresh([{...reading, at: 'bad'}]).state, 'unknown');
  assert.equal(fresh([{...reading, at: new Date(now + 300_001).toISOString()}]).state, 'unknown');
  assert.equal(fresh([{...reading, value: null}]).state, 'unknown');
  assert.equal(fresh([reading, {...reading, state: 'unavailable'}]).state, 'unknown');
  assert.equal(fresh([{...reading, lastGood: true}]).state, 'stale');
  assert.equal(fresh([{...reading, state: 'stale'}]).state, 'stale');
  assert.equal(fresh([{...reading, at: new Date(now - 3_600_000).toISOString()}]).age, '1 h');
});

const count = (html, re) => (html.match(re) || []).length;
const attrs = (html, re) => [...html.matchAll(re)].map(m => m[1]);

/** Render the whole shell for `href` with a fresh store at the fixed clock `now`. */
async function renderShell(href, now = NOW) {
  const {App, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(href);
  return render(h(App, {now}));
}
/** The day chips of the group labelled Day in `html`, as [label, on]. */
const dayChips = html => [...html.match(/aria-label="Day"[^>]*>(.*?)<\/div>/s)[1].matchAll(/aria-pressed="(true|false)"[^>]*>(?:<svg.*?<\/svg>)?([^<]+)<\/button>/gs)].map(m => [m[2], m[1] === 'true']);

/** An hour clock over a settable reader and a manual scheduler: `fire()` runs the one waiting timeout. */
function manualClock(createHourClock, start) {
  let at = new Date(start), next = 1;
  const timers = new Map(), listeners = new Set();
  const doc = {hidden: false, addEventListener: (_t, fn) => listeners.add(fn), removeEventListener: (_t, fn) => listeners.delete(fn)};
  const clock = createHourClock({read: () => new Date(at), doc, schedule: (callback, delay) => { timers.set(next, callback); return next++; }, cancel: id => { timers.delete(id); }});
  return {clock, timers, listeners, set(value) { at = new Date(value); }, fire() { const [[id, callback]] = [...timers]; timers.delete(id); callback(); }};
}
const hourControl = html => html.match(/aria-label="Hour" aria-valuetext="([^"]*)" min="0" max="(\d+)"/).slice(1);

test('shared_clock_crosses_hour_without_navigation: the desktop dock, the phone hour edge and the map stage move together from one injected clock', async () => {
  const {App, createHourClock, createStage, dockState, narrow, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d`);
  // A browser just big enough for the stage: an address, a history that records writes, no-op events.
  const writes = [];
  globalThis.location = {href: `${ORIGIN}?region=morro-bay&presentation=3d`};
  globalThis.history = {state: null, pushState: (...a) => writes.push(a), replaceState: (...a) => writes.push(a)};
  const calls = [], handle = new Proxy({load: async () => true, destroy() {}}, {get: (target, name) => name in target ? target[name] : (...args) => { calls.push([name, ...args]); return true; }});
  const host = {dataset: {}, shadowRoot: {children: [], replaceChildren() { this.children = []; }}};
  const c = manualClock(createHourClock, '2026-10-05T20:59:59.999Z');
  const released = c.clock.retain();
  const stage = createStage({host, load: async () => ({styles: [], mountCoast: () => handle}), center: () => [35.37, -120.86], clock: c.clock, doc: {hidden: false, addEventListener() {}, removeEventListener() {}}, viewDelay: 0});
  try {
    for (let i = 0; i < 10; i++) await Promise.resolve();
    const before = {desktop: hourControl(render(h(App, {clock: c.clock}))), dock: dockState(c.clock.now.value, TZ).at, dataHour: host.dataset.hour};
    narrow.value = true;
    const phoneBefore = hourControl(render(h(App, {clock: c.clock})));
    narrow.value = false;
    assert.deepEqual(before.desktop, ['Today · 1 pm', '10']);
    assert.deepEqual(phoneBefore, ['Today · 1 pm', '10']);
    assert.equal(before.dataHour, '2026-10-05T20:00:00.000Z');
    assert.equal(c.timers.size, 1, 'the app, the layouts and the stage share one ticker');
    const steps = calls.length;
    c.set('2026-10-05T21:00:00Z');
    c.fire();
    const desktop = hourControl(render(h(App, {clock: c.clock})));
    narrow.value = true;
    const phone = hourControl(render(h(App, {clock: c.clock})));
    narrow.value = false;
    assert.deepEqual(desktop, ['Today · 2 pm', '9'], 'the dock default hour moved on');
    assert.deepEqual(phone, ['Today · 2 pm', '9'], 'the phone hour edge moved on');
    assert.equal(dockState(c.clock.now.value, TZ).at, Date.parse('2026-10-05T21:00:00Z'));
    assert.equal(host.dataset.hour, '2026-10-05T21:00:00.000Z', 'the map draws the hour the dock shows');
    assert.deepEqual(calls.slice(steps).filter(call => call[0] === 'setHour').map(call => call[1].toISOString()), ['2026-10-05T21:00:00.000Z']);
    assert.deepEqual(writes, [], 'no navigation, no history write');
    assert.equal(state.hour.value, null, 'nothing was chosen on the way');
  } finally {
    stage.destroy();
    released();
    narrow.value = false;
    delete globalThis.location; delete globalThis.history;
  }
  assert.equal(c.timers.size, 0);
  assert.equal(c.listeners.size, 0);
});

test('selected_hour_survives_clock_rollover: a chosen ?hour= is the same before and after the tick, in range or out', async () => {
  const {App, createHourClock, render, h, state} = await load();
  for (const chosen of ['2026-10-06T03:00Z', '2026-10-01T03:00Z']) {
    state.configureStore({v2: true, storage: memory()});
    state.syncFromURL(`${ORIGIN}?region=morro-bay&hour=${chosen}`);
    const c = manualClock(createHourClock, '2026-10-05T20:30:00Z');
    const release = c.clock.retain();
    const at = html => html.match(/aria-label="Hour" aria-valuetext="[^"]*"[^>]*>(<output[^>]*>[^<]*<\/output>)/)[0].replace(/ min="\d+" max="\d+" step="1" value="\d+"/, '');
    const first = at(render(h(App, {clock: c.clock})));
    for (const next of ['2026-10-05T21:00:00Z', '2026-10-05T22:00:00Z', '2026-10-05T23:00:00Z']) { c.set(next); c.fire(); }
    const after = at(render(h(App, {clock: c.clock})));
    release();
    assert.equal(after, first, `${chosen}: the dock reads the chosen hour the same after three ticks`);
    assert.equal(state.hour.value, chosen);
  }
});

test('fixed_now_and_play_remain_independent: a fixed now ignores the clock and starts no ticker', async () => {
  const {App, createHourClock, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  const c = manualClock(createHourClock, '2026-10-05T22:00:00Z');
  assert.deepEqual(hourControl(render(h(App, {now: NOW, clock: c.clock}))), ['Today · 1 pm', '10'], 'the fixed date is what the dock reads');
  assert.equal(c.timers.size, 0, 'rendering starts no ticker');
});

test('the shell has the masthead, the command bar, the brief column and the map chrome', async () => {
  const html = await renderShell(`${ORIGIN}?region=morro-bay`);
  assert.match(html, /<header class="app-masthead">/);
  assert.match(html, /Replay controls tour<\/button>/);
  assert.doesNotMatch(html, /Step 1 of 4/, 'the tour is opt-in, not competing with FirstRun or the flyover');
  assert.match(html, /class="app-brand" href="\/"[^>]*>.*SkipperCast/);
  assert.match(html, /class="app-location ui-mono" data-region="morro-bay">Morro Bay —</, 'the location names the region and leaves the centre blank until it loads');
  assert.match(html, /<nav aria-label="Views">/);
  assert.match(html, /<section class="app-command" aria-label="Command bar">/);
  assert.match(html, /<main class="app-main"><aside/);
  assert.deepEqual(attrs(html, /data-view="([a-z]+)"/g), ['coast', 'conditions', 'history', 'fleet', 'reports']);
  assert.match(html, /class="app-fresh" role="status" data-state="unknown" aria-label="Freshness: No readings yet"/);
  // FE-50: sign in is the account menu's button, closed until pressed.
  assert.match(html, /<div class="app-account"><button type="button" class="ui-button ui-button--quiet app-account-trigger" aria-expanded="false" aria-controls="([^"]+)">.*?Sign in<\/button><div id="\1" class="app-account-panel" hidden/);
  assert.match(html, /role="group" aria-label="Profile"/);
  assert.equal(count(html, /(?:Boat|Shore|Spear|Kayak)<\/button>/g), 4);
  assert.equal(count(html, /<label>Target<select/g), 1);
  assert.equal(count(html, /<label>Area<select/g), 1);
  assert.match(html, /<output class="app-window ui-mono" aria-label="Time window">Today · 1 pm<\/output>/);
  assert.deepEqual(dayChips(html), [['Today', true], ...CHIPS.slice(1).map(label => [label, false])], 'no ?day= means today, at the fixed clock');
  assert.match(html, /aria-label="Hour" aria-valuetext="Today · 1 pm" min="0" max="10" step="1" value="0"/, 'today runs from the current hour to 11 pm');
  assert.match(html, /<aside class="app-brief" aria-label="Brief">/);
  assert.match(html, /class="ui-eyebrow">Today's brief</);
  assert.match(html, /<h1>[A-Z][^<]*\.<\/h1>/, 'the headline is one sentence with a full stop');
  assert.equal(count(html, /class="ui-tile"/g), 4);
  for (const label of ['Wind', 'Swell', 'Water', 'Tide']) assert.match(html, new RegExp(`<span>${label}</span>`));
  assert.match(html, /<figure class="app-spark" aria-label="Tide curve">/);
  assert.match(html, /class="ui-eyebrow">Where to look</);
  assert.match(html, /<p class="app-caveat">Habitat describes a place to look; fish presence is unverified.<\/p>/);
  assert.equal(count(html, /separate clocks/g), 1, 'one disclaimer line per page');
  assert.match(html, /<section class="app-stage" tabindex="-1" aria-label="Map">/);
  assert.match(html, /<section class="app-legend" aria-label="Legend">/);
  assert.match(html, /role="group" aria-label="Layers"/);
  assert.equal(count(html, /class="ui-rail-item"/g), 10);
  assert.match(html, /role="group" aria-label="Time"/);
  assert.match(html, /<input type="range" class="ui-range ui-dock-range" aria-label="Hour"/);
  assert.doesNotMatch(html, /app-mark/, 'no mark card without a selection');
});

test('the brief invents no number: every tile reads "—" and keeps its source line and basis', async () => {
  const {emptyTiles, render, h, Brief, state} = await load();
  for (const nearshore of [false, true]) {
    const tiles = emptyTiles(nearshore);
    assert.deepEqual(tiles.map(t => t.reading), ['—', '—', '—', '—']);
    for (const t of tiles) { assert.ok(t.source && t.basis, t.label); assert.doesNotMatch(t.source, /\d/, `${t.label} source carries no age yet`); }
    assert.equal(tiles[1].source, nearshore ? 'Nearshore site —' : 'Offshore —');
  }
  state.configureStore({storage: memory()});
  state.syncFromURL(`${ORIGIN}?profile=spear`);
  const html = render(h(Brief, {}));
  assert.equal(count(html, /<span class="ui-reading">—<\/span>/g), 4);
  assert.equal(count(html, /<details class="ui-popover"/g), 4, 'each tile has its basis in a <details>');
  assert.match(html, /Nearshore site —/, 'spear takes the nearshore swell source');
  assert.match(html, /<p class="app-empty">Ranked places load with the map.<\/p>/, 'no ranked place before the region\'s marks load');
  assert.match(html, /In-water visibility is unverified/);
  // Kayak reads the offshore swell source and its own caveat.
  state.syncFromURL(`${ORIGIN}?profile=kayak`);
  const kayak = render(h(Brief, {}));
  assert.match(kayak, /Offshore —/, 'kayak takes the offshore swell source');
  assert.match(kayak, /a forecast cannot clear a paddle\./);
  state.syncFromURL(`${ORIGIN}?profile=spear`);
  const picks = [{id: 'r1', kind: 'spot', name: 'North reef', distance: '3.2 nm', depth: '~60–90 ft', fit: 'Fits lingcod habitat 3 of 3', reason: 'Hard bottom inside the limit.', screen: {inside: false, name: null, distanceM: null, screened: true}}];
  const ranked = render(h(Brief, {ranking: {source: 'atlas', label: 'Survey reef atlas', basis: 'Basis.', picks, empty: ''}}));
  assert.match(ranked, /<ol class="app-picks"><li data-mark="r1"><button type="button" class="app-pick" aria-pressed="false">/);
  assert.match(ranked, /class="app-where-source ui-mono">Survey reef atlas</, 'the ranking names its source');
  assert.match(ranked, /class="app-fit ui-eyebrow">Fits lingcod habitat 3 of 3</);
});

test('every control reflects the address: profile, view, day, hour, layers and the selection', async () => {
  const link = `${ORIGIN}?region=morro-bay&profile=shore&view=conditions&layers=swell,water-temp&spot=r12&day=2026-10-06&hour=${encodeURIComponent(TUE_2PM)}&target=halibut&area=estero`;
  const html = await renderShell(link);
  // The Conditions view (FE-32) covers the map: its section shows and the map chrome's rail, legend and card do not; the dock stays.
  assert.match(html, /<section class="app-conditions" aria-labelledby="app-conditions-title">/);
  assert.equal(count(html, /class="ui-rail-item"/g), 0);
  const coastView = await renderShell(link.replace('&view=conditions', ''));
  // Profile switch: exactly Shore is on, and the shore caveat and swell source follow.
  const chips = [...html.matchAll(/<button[^>]*class="ui-button ui-button--ghost ui-button--sm ui-chip"[^>]*aria-pressed="(true|false)"[^>]*>.*?<\/svg>(Boat|Shore|Spear|Kayak)/gs)].map(m => [m[2], m[1]]);
  assert.deepEqual(chips, [['Boat', 'false'], ['Shore', 'true'], ['Spear', 'false'], ['Kayak', 'false']]);
  assert.match(html, /Offshore seas do not measure breakers/);
  assert.match(html, /Nearshore site —/);
  // Views: the current one is aria-current and every link carries ?view= (coast drops it).
  assert.match(html, /href="[^"]*[?&]view=conditions[^"]*" aria-current="page" data-view="conditions"/);
  assert.match(html, /href="[^"]*[?&]view=history[^"]*" data-view="history"/);
  assert.doesNotMatch(html.match(/<a href="([^"]*)" data-view="coast"/)[1], /view=/, 'coast is the default and drops ?view=');
  // Target and area menus show the link's values.
  assert.match(html, /<label>Target<select><optgroup label="Shore targets"><option value="surfperch">Barred surfperch<\/option><option selected value="halibut">California halibut<\/option><\/optgroup><\/select>/, 'the coast targets\' names (FE-30)');
  assert.match(html, /<label>Area<select><option value>Whole region<\/option><option selected value="estero">Estero<\/option><\/select>/);
  // Rail and legend: swell and water temp on, the rest off; protected areas stay listed while their geometry loads (FE-19).
  const rail = Object.fromEntries([...coastView.matchAll(/<li class="ui-rail-item" data-on="(true|false)"><button[^>]*>.*?<span class="ui-rail-label">([^<]+)<\/span>/gs)].map(m => [m[2], m[1]]));
  assert.deepEqual(rail, {Seafloor: 'false', Currents: 'false', 'Water temp': 'true', 'Temp contrast': 'false', 'Temp fronts': 'false', Chlorophyll: 'false', 'Swell + wind': 'true', Stations: 'false', 'Charter fleet': 'false', Clouds: 'false'});
  assert.match(coastView, /class="app-legend-water-temp"/);
  assert.deepEqual(attrs(coastView, /class="app-swatch" data-layer="([a-z-]+)"/g), [], 'no colour key until a layer draws (FE-20)');
  // Dock: the chips run from the fixed clock (Monday), Tuesday 2026-10-06 is on and the slider sits at 2 pm local.
  assert.deepEqual(dayChips(html), CHIPS.map(label => [label, label === 'Tue']));
  assert.match(html, /aria-label="Hour" aria-valuetext="Tomorrow · 2 pm" min="0" max="23" step="1" value="14"/);
  assert.match(html, /<output class="ui-dock-readout ui-mono" aria-live="off">Tomorrow · 2 pm<\/output>/);
  assert.match(html, /class="app-dock-zone ui-mono">P[DS]T</, 'the zone shows once in the dock');
  assert.match(html, /aria-label="Time window">Tue · 2 pm<\/output>/);
  // Selection: the mark card names the spot with blank reading and source.
  assert.match(coastView, /<section class="app-mark" aria-label="Selected mark"><div class="app-mark-head"><h2 tabindex="-1">r12<\/h2>/);
  assert.match(coastView, /<p class="ui-reading">—<\/p><p class="app-mark-source ui-mono">Source —<\/p>/);
  assert.match(coastView, /aria-label="Clear selection"/);
});

test('the helpers behind the controls round-trip through the store keys', async () => {
  const {localParts, dayOptions, dockState, hourText, readout, toggled, targetOptions, coordinates, titleCase, viewParam, clearSelection, windowText, RAIL_ENTRIES, RAIL_IDS, state, MASTHEAD_VIEWS, TAB_VIEWS} = await load();
  assert.deepEqual([localParts(new Date(TUE_2PM), TZ).day, localParts(new Date(TUE_2PM), TZ).hour], ['2026-10-06', 14]);
  assert.deepEqual([hourText(0), hourText(12), hourText(14)], ['12 am', '12 pm', '2 pm']);
  // Day chips: the horizon's eight local days; a selected day outside the horizon is kept.
  const now = new Date('2026-10-05T20:00:00Z');
  assert.deepEqual(dayOptions(now, TZ, null).map(o => o.label), WEEK);
  assert.deepEqual(dayOptions(now, TZ, null).slice(0, 2), [{value: '2026-10-05', label: 'Today'}, {value: '2026-10-06', label: 'Tue'}]);
  assert.deepEqual(dayOptions(now, TZ, '2026-10-20').at(-1), {value: '2026-10-20', label: '10-20'});
  state.configureStore({storage: memory()});
  state.syncFromURL(ORIGIN);
  const today = dockState(now, TZ);
  assert.deepEqual([today.day, today.today, today.at, today.index, today.hours.length], ['2026-10-05', '2026-10-05', Date.parse('2026-10-05T20:00Z'), 0, 11], 'no ?day= or ?hour= means today, now');
  state.syncFromURL(`${ORIGIN}?hour=2026-09-01T20:00Z`);
  assert.equal(readout(dockState(now, TZ), TZ), '1 pm · outside the forecast', 'a stale hour is kept and said to be outside');
  state.syncFromURL(ORIGIN);
  assert.equal(windowText(now, TZ), 'Today · 1 pm');
  // Rail toggles keep rail order and write ?layers=none for an empty rail.
  assert.deepEqual(RAIL_ENTRIES.map(e => e.id).sort(), [...RAIL_IDS].sort(), 'every rail id has exactly one entry (their order may differ: the rail follows the draw order, the ids were appended)');
  assert.deepEqual(toggled(['swell'], 'seafloor', true), ['seafloor', 'swell']);
  assert.deepEqual(toggled(['seafloor', 'swell'], 'swell', false), ['seafloor']);
  assert.equal(state.layersParam(toggled(['seafloor'], 'seafloor', false)), 'none');
  assert.deepEqual(state.parseLayers(state.layersParam(toggled([], 'clouds', true))), ['clouds']);
  // Targets: the profile's list, with the link's target kept first when it is not in it.
  assert.deepEqual(targetOptions('shore', null), ['surfperch', 'halibut']);
  assert.deepEqual(targetOptions('boat', 'vermilion'), ['vermilion', 'lingcod']);
  assert.deepEqual(MASTHEAD_VIEWS, ['coast', 'conditions', 'history', 'fleet', 'reports']);
  assert.deepEqual(TAB_VIEWS, ['coast', 'conditions', 'history', 'reports']);
  assert.deepEqual([viewParam('coast'), viewParam('fleet')], [null, 'fleet']);
  assert.equal(coordinates([35.34, -120.965]), '35.34N 120.97W');
  assert.equal(titleCase('cabezon-shallow-reef'), 'Cabezon Shallow Reef');
  assert.equal(clearSelection(`${ORIGIN}?region=morro-bay&spot=r12&focus=r13&view=fleet`), `${ORIGIN}?region=morro-bay&view=fleet`);
});

test('SC-N3: the location keeps the region name whole and puts the coordinates in their own span', async () => {
  const {Location, regionInfo, render, h, state} = await load();
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  try {
    regionInfo.value = {id: 'morro-bay', name: 'Morro Bay & Avila', center: [35.34, -120.965], timezone: 'America/Los_Angeles'};
    assert.ok(render(h(Location)).includes('Morro Bay &amp; Avila <span class="app-location-coords">35.34N 120.97W</span>'));
    regionInfo.value = {id: 'avila', name: 'Stale', center: [35.18, -120.73], timezone: 'America/Los_Angeles'};
    assert.match(render(h(Location)), />Morro Bay —</, 'metadata for another region is not shown');
    regionInfo.value = null;
    const pending = render(h(Location));
    assert.match(pending, />Morro Bay —</);
    assert.doesNotMatch(pending, /app-location-coords/);
    state.syncFromURL(ORIGIN);
    assert.match(render(h(Location)), />No port chosen</);
  } finally { regionInfo.value = null; }
});

/** Render the shell for `href` as the mobile layout (what main.tsx does under 1,024 px). */
async function renderMobile(href) {
  const {narrow} = await load();
  narrow.value = true;
  // FirstRun reads the browser address to distinguish a named profile from a new visit.
  const previousLocation = globalThis.location;
  globalThis.location = {href};
  try { return await renderShell(href); } finally {
    narrow.value = false;
    if (previousLocation === undefined) delete globalThis.location;
    else globalThis.location = previousLocation;
  }
}

test('under 1,024 px the shell is the map, a top strip, one sheet at peek and a four-tab nav', async () => {
  const html = await renderMobile(`${ORIGIN}?region=morro-bay`);
  assert.match(html, /^<main class="app-mobile"><section class="app-stage" tabindex="-1" aria-label="Map">/, 'the map stage comes first and fills the viewport; the root is the page\'s one main (S4-46)');
  assert.doesNotMatch(html, /app-masthead|app-command|app-main|app-brief"|app-dock/, 'no desktop chrome');
  // Top strip: the brand and location card, the layers button, then the full-width profile switch.
  assert.match(html, /<header class="app-top"><div class="app-top-row"><div class="app-top-card"><a class="app-brand" href="\/">.*?<span class="app-location ui-mono" data-region="morro-bay">Morro Bay —<\/span><\/div><button[^>]*aria-label="Layers"[^>]*aria-pressed="false"/s);
  assert.match(html, /role="group" aria-label="Profile" class="ui-segmented app-profile"/);
  assert.equal(count(html, /(?:Boat|Shore|Spear|Kayak)<\/button>/g), 4);
  // One sheet at peek with the hour slider at its edge, then the brief in sheet order.
  assert.equal(count(html, /class="ui-sheet /g), 1);
  assert.match(html, /<section class="ui-sheet app-sheet" data-detent="peek" role="group" aria-label="Brief"><div class="ui-sheet-edge"><button type="button" class="ui-sheet-handle" aria-label="Expand Brief" aria-expanded="false"/);
  assert.match(html, /<\/button><div class="app-sheet-hour" role="group" aria-label="Time"><input type="range" class="ui-range ui-dock-range" aria-label="Hour" aria-valuetext="Today · 1 pm"[^>]*><output class="ui-dock-readout ui-mono" aria-live="off">Today · 1 pm<\/output><\/div><\/div>/);
  const body = html.slice(html.indexOf('<div class="ui-sheet-body">'), html.indexOf('<nav aria-label="Views"'));
  // SC-LAUNCH-3: the head names the lead's day (tomorrow, no time chosen); the dock's day heads the evidence below the lead.
  const order = ['class="ui-eyebrow">Tomorrow</span>', 'class="app-fresh" role="status"', '<h1>Waiting for readings.</h1>', 'class="ui-eyebrow">Today · 1 pm</span>', '<div class="app-tiles">', 'class="ui-eyebrow">Where to look', '<details class="app-details">', '<p class="app-caveat">', '<figure class="app-spark"',
    '<div class="app-sheet-menus"><div role="group" aria-label="Day"', '<label>Target<select', '<label>Area<select', '<footer class="app-brief-footer">', '<div class="app-account" data-inline="true">'];
  const at = order.map(s => body.indexOf(s));
  assert.ok(at.every(i => i >= 0), `every piece renders: ${JSON.stringify(order.filter((_, i) => at[i] < 0))}`);
  assert.deepEqual(at, [...at].sort((a, b) => a - b), 'in sheet order: lead-day eyebrow, freshness, headline, dock-day eyebrow, tiles, picks, Details with the caveat (#616), tide, menus, footer');
  assert.equal(count(body, /class="ui-tile"/g), 4);
  assert.equal(count(html, /<h1>/g), 1);
  assert.equal(count(html, /separate clocks/g), 1, 'one disclaimer line per page');
  assert.doesNotMatch(html, /ui-rail-item|app-legend/, 'the rail and legend wait for the layers button');
  // Tabs: the four views with icons, after the sheet.
  assert.match(html, /<nav aria-label="Views" class="app-tabs"><ul class="app-views">/);
  assert.deepEqual(attrs(html, /data-view="([a-z]+)"/g), ['coast', 'conditions', 'history', 'reports']);
  assert.equal(count(html, /data-view="[a-z]+"><svg/g), 4, 'each tab has its icon');
  assert.match(html, /aria-current="page" data-view="coast"/);
});

test('the mobile sheet reflects the address: the mark card stands in at peek, the hour and day follow the dock', async () => {
  const {render, h, LayersPanel, state, afterDetent, toggleLayers, dragDetent, DRAG_MIN} = await load();
  const html = await renderMobile(`${ORIGIN}?region=morro-bay&profile=spear&spot=r12&day=2026-10-06&hour=${encodeURIComponent(TUE_2PM)}&layers=clouds`);
  assert.match(html, /<section class="ui-sheet app-sheet app-sheet--mark" data-detent="peek" role="group" aria-label="Brief">/);
  assert.match(html, /<div class="ui-sheet-body"><div class="app-sheet-brief"><section class="app-mark" aria-label="Selected mark"><div class="app-mark-head"><h2 tabindex="-1">r12<\/h2>/);
  assert.doesNotMatch(html, /<h1>/, 'the card replaces the headline');
  assert.match(html, /aria-label="Hour" aria-valuetext="Tomorrow · 2 pm" min="0" max="23" step="1" value="14"/);
  assert.deepEqual(dayChips(html), CHIPS.map(label => [label, label === 'Tue']), 'the sheet\'s day menu runs from the fixed clock');
  assert.match(html, /Nearshore site —/);
  assert.match(html, /In-water visibility is unverified/);
  // The layers panel: the rail with the legend of what is on, and a Done button.
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay&layers=clouds`);
  const panel = render(h(LayersPanel, {onClose: () => {}}));
  assert.match(panel, /^<div class="app-sheet-layers"><div class="app-sheet-head"><span class="ui-eyebrow">Layers<\/span><button[^>]*>.*?Done<\/button><\/div><div class="ui-rail app-rail" role="group" aria-label="Layers">/s);
  assert.equal(count(panel, /class="ui-rail-item"/g), 10);
  assert.match(panel, /<li class="app-legend-clouds"><span class="app-legend-text">Clouds</);
  assert.deepEqual(attrs(panel, /class="app-swatch" data-layer="([a-z-]+)"/g), [], 'no cloud key until a frame shows (FE-20)');
  // Panel and detent rules: layers opens at half from peek, closes when the sheet drops to peek.
  assert.deepEqual(toggleLayers('brief', 'peek'), {panel: 'layers', detent: 'half'});
  assert.deepEqual(toggleLayers('brief', 'full'), {panel: 'layers', detent: 'full'});
  assert.deepEqual(toggleLayers('layers', 'half'), {panel: 'brief', detent: 'half'});
  assert.deepEqual(afterDetent('layers', 'peek'), {panel: 'brief', detent: 'peek'});
  assert.deepEqual(afterDetent('layers', 'full'), {panel: 'layers', detent: 'full'});
  // Drag: short drags snap back, a drag past the minimum steps once, a far drag goes to the end.
  assert.equal(dragDetent('peek', -(DRAG_MIN - 1), 700), 'peek');
  assert.equal(dragDetent('peek', -DRAG_MIN, 700), 'half');
  assert.equal(dragDetent('peek', -400, 700), 'full');
  assert.equal(dragDetent('half', 60, 700), 'peek');
  assert.equal(dragDetent('full', 400, 700), 'peek');
  assert.equal(dragDetent('full', -100, 700), 'full');
});

test('loadRegion fills the masthead from regions/<id>/region.json and leaves placeholders on failure', async () => {
  const {loadRegion, regionInfo, regionUnavailable, render, h, App, state} = await load();
  const fetched = [];
  const area = {id: 'estero-bay', name: 'Estero Bay', bounds: [-121.05, 35.32, -120.78, 35.47]};
  const ok = async url => { fetched.push(url); return {ok: true, json: async () => ({name: 'Morro Bay & Avila', timezone: TZ, map: {center: [35.34, -120.965], local_areas: [area, {id: 7}, null]}})}; };
  // The reviewed local areas come along for the coast report binding (FE-15's currents packet); malformed ones are dropped.
  assert.deepEqual(await loadRegion('morro-bay', ok), {id: 'morro-bay', name: 'Morro Bay & Avila', center: [35.34, -120.965], timezone: TZ, localAreas: [area]});
  assert.deepEqual(fetched, ['regions/morro-bay/region.json']);
  assert.deepEqual(regionUnavailable.value, {region: 'morro-bay', targets: {}});
  // CI6-02: the region's unavailable targets reach the target picker; malformed reasons are dropped.
  const named = async () => ({ok: true, json: async () => ({name: 'Morro Bay & Avila', timezone: TZ, map: {center: [35.34, -120.965], unavailable_targets: {lobster: 'Not in this region\u2019s researched list.', bad: 3}}})});
  assert.deepEqual((await loadRegion('morro-bay', named)).unavailableTargets, {lobster: 'Not in this region\u2019s researched list.'});
  assert.deepEqual(regionUnavailable.value, {region: 'morro-bay', targets: {lobster: 'Not in this region\u2019s researched list.'}});
  // SC-LAUNCH-3: a region that names its jurisdiction carries the fields web/regs.ts reads, for the brief's legality line.
  const ruled = async () => ({ok: true, json: async () => ({name: 'Morro Bay & Avila', timezone: TZ, map: {center: [35.34, -120.965]}, jurisdiction_id: 'california-central', species: ['reef', 'salmon'], assets: {regulations: 'data/regulations.json'}})});
  assert.deepEqual((await loadRegion('morro-bay', ruled)).rules, {id: 'morro-bay', timezone: TZ, species: ['reef', 'salmon'], jurisdiction_id: 'california-central', regulatory_authority_hosts: undefined, assets: {regulations: 'data/regulations.json'}});
  state.configureStore({storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  assert.match(render(h(App, {})), /data-region="morro-bay">Morro Bay &amp; Avila <span class="app-location-coords">35.34N 120.97W<\/span></);
  regionInfo.value = null;
  assert.equal(await loadRegion('x', async () => ({ok: false})), null);
  assert.equal(await loadRegion('x', async () => { throw new Error('offline'); }), null);
  assert.equal(regionInfo.value, null);
});

// FE-55 / SC0452-02: the chat entry renders only while the shared session read says the advisor gate is open
// (GET /api/session, which the account menu already reads), with no HEAD /chat.html probe.
test('the masthead chat entry renders nothing with the advisor off and links to the web chat when the session says on', async () => {
  const {session, ChatEntry, render, h} = await load();
  const ANCHOR = '<a class="ui-button ui-button--quiet" href="/chat.html" data-advisor-entry="true">Ask SkipperCast</a>';
  try {
    for (const loaded of [{state: 'loading'}, {state: 'offline'}, {state: 'disabled', advisor: false}, {state: 'signed-out', advisor: false}, {state: 'signed-in', name: 'Skipper', advisor: false}]) {
      session.value = loaded;
      assert.equal(render(h(ChatEntry, {})), '', `no Chat entry for ${JSON.stringify(loaded)}`);
    }
    session.value = {state: 'signed-out', advisor: false};
    const off = await renderShell(`${ORIGIN}?region=morro-bay`);
    assert.doesNotMatch(off, /data-advisor-entry|chat\.html|Ask SkipperCast/);
    // Chat is offered whether or not the site offers sign in, and whoever is signed in.
    for (const on of [{state: 'disabled', advisor: true}, {state: 'signed-out', advisor: true}, {state: 'signed-in', name: null, advisor: true}]) {
      session.value = on;
      assert.equal(render(h(ChatEntry, {})), ANCHOR, `Chat entry for ${on.state}`);
    }
    assert.match(await renderShell(`${ORIGIN}?region=morro-bay`), /class="app-fresh".*data-advisor-entry="true">Ask SkipperCast<\/a><div class="app-account">/s, 'between freshness and the account menu');
  } finally { session.value = {state: 'loading'}; }
});

test('the chat entry and the account menu share one session read and no HEAD /chat.html is sent', async () => {
  const {session, ensureSession, refreshSession, ChatEntry, render, h} = await load();
  const asked = [];
  const answer = (data, ok = true) => async (url, init) => { asked.push([url, init?.method ?? 'GET']); return {ok, json: async () => data}; };
  try {
    session.value = {state: 'loading'};
    const fetchFn = answer({signIn: null, signedIn: false, advisor: true});
    // The menu's and the chat entry's mount effects both call the one initializer, in either order, and remounts reuse its answer.
    const first = ensureSession(fetchFn), second = ensureSession(fetchFn);
    assert.equal(first, second, 'a pending read is shared');
    await Promise.all([first, second]);
    await ensureSession(fetchFn);
    assert.deepEqual(asked.map(([url]) => url), ['/api/session'], 'one GET /api/session');
    assert.ok(asked.every(([, method]) => method === 'GET'), 'no HEAD request at all');
    assert.equal(render(h(ChatEntry, {})).includes('data-advisor-entry'), true);
    // A failed explicit refresh withdraws the Chat entry (offline, as the account menu shows it).
    await refreshSession(async () => { throw new Error('offline'); });
    assert.deepEqual(session.value, {state: 'offline'});
    assert.equal(render(h(ChatEntry, {})), '');
    // A refresh that answers 'off' withdraws it too; an HTTP failure is offline.
    await refreshSession(answer({signIn: null, signedIn: false, advisor: false}));
    assert.equal(render(h(ChatEntry, {})), '');
    await refreshSession(answer({signIn: null, signedIn: false, advisor: true}));
    assert.equal(render(h(ChatEntry, {})).includes('data-advisor-entry'), true);
    await refreshSession(answer({advisor: true}, false));
    assert.equal(render(h(ChatEntry, {})), '', 'an unsuccessful answer shows no Chat entry even if its body says advisor');
  } finally { session.value = {state: 'loading'}; }
  const source = readFileSync(join(ROOT, 'web/app/Masthead.tsx'), 'utf8');
  assert.doesNotMatch(source, /method: 'HEAD'|probeAdvisor|checkAdvisor|advisorOn/, 'the masthead has no probe machinery left');
});

test('the map chrome offers Chart, 2D and 3D; without terrain the terrain choices are disabled and point at the reason', async () => {
  const toggle = html => [...html.match(/aria-label="Map presentation"[^>]*>(.*?)<\/div>/s)[1].matchAll(/<button([^>]*)>([^<]+)<\/button>/g)]
    .map(([, a, label]) => [label, /aria-pressed="true"/.test(a), /disabled/.test(a), /aria-describedby="app-stage-note"/.test(a)]);
  for (const narrowed of [false, true]) {
    const {narrow} = await load();
    narrow.value = narrowed;
    try {
      const terrain = await renderShell(`${ORIGIN}?region=morro-bay&presentation=3d`);
      assert.deepEqual(toggle(terrain), [['Chart', false, false, false], ['2D', false, false, false], ['3D', true, false, false]]);
      assert.match(terrain, /<div class="app-map" hidden><div class="app-chart"><\/div><\/div><div class="app-terrain" tabindex="-1" data-coast-theme="tokens"><\/div>/, 'the terrain host is shown with the token opt-in; the Chart host (FE-11) waits hidden');
      const none = await renderShell(`${ORIGIN}?region=channel-islands&presentation=3d`);
      assert.deepEqual(toggle(none), [['Chart', true, false, false], ['2D', false, true, true], ['3D', false, true, true]]);
      assert.match(none, /<p id="app-stage-note" class="app-stage-note" role="status">No reviewed coastal terrain covers this region yet.<\/p>/);
    } finally { narrow.value = false; }
  }
});

test('the mark card shows a Chart selection, then the terrain\'s on the Chart, then the link\'s atlas mark', async () => {
  const {MarkCard, currentMark, terrainCard, chartMark, terrainMark, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  const shore = {id: 'coastline:S1', name: 'Shoreline', kind: 'Mean High Water · Natural', reading: 'Lidar · ±2 m stated', source: 'NOAA NGS CUSP · source date 2010-11-01', basis: 'NOAA NGS CUSP shoreline, 1994–2010 sources.'};
  const reef = {latitude: 35.38, longitude: -120.88, id: 'reef:r1'};
  try {
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&spot=r12`);
    assert.equal(currentMark.value.name, 'r12', 'the atlas placeholder');
    terrainMark.value = reef;
    assert.equal(currentMark.value.name, 'r12', 'the terrain\'s selection shows only while the link names it');
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&spot=r12&habitat=reef:r1`);
    assert.deepEqual(currentMark.value, terrainCard(reef));
    assert.deepEqual(terrainCard(reef).position, {latitude: 35.38, longitude: -120.88});
    for (const [mode, expected] of [['dd', '35.38000° N, 120.88000° W'], ['ddm', '35° 22.800′ N, 120° 52.800′ W'], ['dms', '35° 22′ 48.00″ N, 120° 52′ 48.00″ W']]) {
      state.setCoordinateFormat(mode);
      assert.ok(render(h(MarkCard, {})).includes(expected));
    }
    state.setCoordinateFormat('dd');
    chartMark.value = shore;
    assert.equal(currentMark.value, shore, 'a Chart click wins');
    const html = render(h(MarkCard, {}));
    assert.match(html, /<h2 tabindex="-1">Shoreline<\/h2>.*Lidar · ±2 m stated.*NOAA NGS CUSP · source date 2010-11-01/s);
    chartMark.value = {...shore, terms: [{href: 'https://example.org/terms', label: 'Publisher terms'}]};
    assert.match(render(h(MarkCard, {})), /<a href="https:\/\/example.org\/terms" target="_blank" rel="noopener" aria-label="Publisher terms \(publisher's page, opens in a new tab\)">Publisher terms<\/a>/,
      'a mark with publisher terms links them inside its basis');
    assert.doesNotMatch(html, /Publisher terms/, 'a mark without them has none');
    chartMark.value = shore;
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d&spot=r12`);
    assert.equal(currentMark.value.name, 'r12', 'in the terrain its own panel speaks; the atlas mark stays');
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d`);
    assert.equal(currentMark.value, null);
  } finally { chartMark.value = null; terrainMark.value = null; }
});

test('FE-80: in 2D and 3D a terrain reading is the card, with the renderer\'s label and source clock verbatim, then its habitat', async () => {
  const {MarkCard, currentMark, readingCard, terrainCard, terrainMark, terrainReading, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  const reading = {latitude: 35.37, longitude: -120.86, heightM: -12, spacingM: 2, label: 'ORIGINAL SURVEY SAMPLE', value: '39 ft depth', location: '35.37000° N · 120.86000° W',
    detail: 'USGS survey · 2008-05-01 · 2 m display spacing. Nominal. Original spacing 2 m. Vertical references have not been reconciled.',
    source: {id: 2, label: 'USGS survey', kind: 'survey', resolutionM: 2, datum: 'Nominal', sourceDate: '2008-05-01', url: 'https://example.test'}};
  const reef = {latitude: 35.38, longitude: -120.88, id: 'reef:r1'};
  try {
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d&habitat=reef:r1`);
    terrainMark.value = reef;
    assert.deepEqual(currentMark.value, terrainCard(reef), 'the terrain\'s habitat shows in 2D and 3D too');
    terrainReading.value = reading;
    assert.deepEqual(currentMark.value, readingCard(reading));
    const html = render(h(MarkCard, {}));
    assert.match(html, /<h2 tabindex="-1">39 ft depth<\/h2>.*<p class="app-mark-kind">ORIGINAL SURVEY SAMPLE<\/p><p class="ui-mono">35\.37000° N, 120\.86000° W<\/p><p class="app-mark-copy" role="status">Protected areas not checked for this position: outside coverage or check unavailable\.<\/p><p class="app-mark-source ui-mono">USGS survey · 2008-05-01 · 2 m display spacing\. Nominal\. Original spacing 2 m\. Vertical references have not been reconciled\.<\/p>/s);
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&habitat=reef:r1`);
    assert.deepEqual(currentMark.value, terrainCard(reef), 'the Chart has no terrain reading');
  } finally { terrainMark.value = null; terrainReading.value = null; }
});

test('the shell files keep the token and copy rules, and app.html mounts the entry', async () => {
  for (const file of APP_FILES) {
    const source = readFileSync(join(ROOT, file), 'utf8');
    assert.deepEqual(lintFile(file, source), [], file);
    assert.doesNotMatch(source, /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u, `${file} has no emoji`);
    // FE-75: CoastMarkup is the one markup host (scripts/check_web.py enforces it across web/).
    if (file !== 'web/app/CoastMarkup.tsx') assert.doesNotMatch(source, /innerHTML/, `${file} renders through Preact`);
    assert.doesNotMatch(source, /\b(?:best spot|productive|catch rate|bite)\b/i, `${file} promises no fish`);
  }
  const page = await readFile(join(ROOT, 'dist/app.html'), 'utf8');
  assert.match(page, /<div id="app">/);
  assert.match(page, /<script type="module" src="\.\.\/web\/app\/main\.tsx"><\/script>/);
  assert.deepEqual(attrs(page, /<link rel="stylesheet" href="([^"]+)"/g), ['../web/tokens.css', '../web/ui/ui.css', '../web/app/app.css', '../web/landing/port-input.css', '../web/app/account.css', '../web/app/trip.css', '../web/app/helm.css'],
    'tokens first, then the primitives, then the shell, then the entry flow (FE-08), then the account dialogs (FE-50), then the trip plan (FE-51), then the Helm view (BF-helm-mode)');
  // FE-61: tests/test_no_v1_map_library.mjs checks that no tracked file names the retired 2D map library.
  assert.deepEqual(attrs(page, /src="(vendor\/[^"]+)"/g), [], 'the map page loads no vendored script: the passkey library loads when a ceremony starts (FE-50, SC0452-01)');
});


test('the time dock disables Play at the complete horizon end while preserving backward selection', async () => {
  const last = new Date(NOW.getTime() + 168 * 3_600_000).toISOString().slice(0, 16) + 'Z';
  const html = await renderShell(`${ORIGIN}?region=morro-bay&hour=${last}`);
  const button = html.match(/<button[^>]*aria-label="Play"[^>]*>/)[0];
  assert.match(button, / disabled(?:=|>| )/);
  assert.doesNotMatch(html.match(/<input[^>]*aria-label="Hour"[^>]*>/)[0], / disabled/);
  const before = new Date(NOW.getTime() + 167 * 3_600_000).toISOString().slice(0, 16) + 'Z';
  const prior = await renderShell(`${ORIGIN}?region=morro-bay&hour=${before}`);
  assert.doesNotMatch(prior.match(/<button[^>]*aria-label="Play"[^>]*>/)[0], / disabled/);
});

test('the legend keys the ranked trip spots while the Chart draws them (#422)', async () => {
  const {Legend, RankedRow, rankedSpots, markScreen, CHECKING, assessScreen, render, h, state, landWater} = await load();
  state.configureStore({v2: true, storage: memory()});
  const spot = {id: 's1', name: 'Spot 1', latitude: 35.37, longitude: -120.9, trip_rank: 1};
  landWater.value = waterState('morro-bay', [spot]);
  try {
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart`);
    assert.equal(render(h(RankedRow, {})), '', 'no plan, no row');
    rankedSpots.value = [spot];
    markScreen.value = CHECKING;
    assert.equal(render(h(RankedRow, {})), '', 'no spot drawn while the marks\' screen is checking');
    markScreen.value = assessScreen({areas: [], checkedAt: new Date(Date.now() - 60_000).toISOString(), live: false, closures: undefined}, Date.now());
    const html = render(h(Legend, {}));
    assert.match(html, /<li class="app-legend-ranked"><span class="app-swatch" data-layer="trip-ranked" aria-hidden="true"><\/span>Ranked trip spot; number: the planner(&#39;|')s order/);
    assert.match(html, /Ranked trip spots basis/);
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d`);
    assert.equal(render(h(RankedRow, {})), '', 'the terrain draws no ranked pins, so no row');
  } finally { rankedSpots.value = []; markScreen.value = CHECKING; }
});

test('SC1952-06: the armed Chart status shows a refusal as text, keeps the instruction and Cancel, and hides it when disarmed, in 3D or in another region', async () => {
  const {PresentationToggle, beginWaypointPlacement, cancelWaypointPlacement, placeWaypoint, placementRefused, assessScreen, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  const NAME = '<img src=x onerror=alert(1)> Reserve';
  const BOX = {type: 'Polygon', coordinates: [[[-121.01, 34.99], [-120.99, 34.99], [-120.99, 35.01], [-121.01, 35.01], [-121.01, 34.99]]]};
  const screen = assessScreen({areas: [{type: 'Feature', properties: {NAME, Type: 'SMR'}, geometry: BOX}], checkedAt: new Date().toISOString(), live: true}, Date.now());
  const status = () => render(h(PresentationToggle, {}));
  const got = [];
  try {
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart`);
    assert.doesNotMatch(status(), /Tap the Chart/, 'not armed: no status');
    beginWaypointPlacement('morro-bay', at => got.push(at));
    let html = status();
    assert.match(html, /Tap the Chart to place your waypoint\. <button[^>]*>Cancel waypoint<\/button>/);
    assert.doesNotMatch(html, /not checked|Inside|m from/, 'armed and untouched: no refusal');
    placeWaypoint('morro-bay', {lat: 35, lon: -121.2}, null);
    html = status();
    assert.match(html, /Tap the Chart to place your waypoint\. Protected areas not checked\. <button[^>]*>Cancel waypoint<\/button>/);
    placeWaypoint('morro-bay', {lat: 35, lon: -121}, screen);
    html = status();
    assert.ok(html.includes('Inside &lt;img src=x onerror=alert(1)> Reserve. '), html);
    assert.ok(!html.includes('<img'), 'a closure name is text, never markup');
    placeWaypoint('morro-bay', {lat: 35, lon: -120.99 + 30 / (111412.84 * Math.cos(35 * Math.PI / 180))}, screen);
    assert.match(status(), /Tap the Chart[^<]*\d+ m from &lt;img src=x onerror=alert\(1\)> Reserve\. <button/);
    placeWaypoint('morro-bay', {lat: 35, lon: -121}, screen);
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d`);
    assert.doesNotMatch(status(), /Tap the Chart|Inside/, 'not on the Chart: no refusal shown');
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart`);
    assert.match(status(), /Inside/);
    state.syncFromURL(`${ORIGIN}?region=another-region&presentation=chart`);
    assert.doesNotMatch(status(), /Tap the Chart|Inside/, 'armed for another region: no refusal shown');
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart`);
    cancelWaypointPlacement();
    assert.equal(placementRefused.value, null);
    assert.doesNotMatch(status(), /Tap the Chart|Inside/, 'cancel clears the status and the refusal');
    assert.equal(got.length, 0, 'no refused tap completed');
  } finally { cancelWaypointPlacement(); }
});

test('map_chrome_es_unavailable_and_placement: the toggle, groups, terrain buttons, terrain reasons and the placement prompt read Spanish, and English comes back byte for byte', async () => {
  const {PresentationToggle, TerrainControls, PRESENTATIONS, terrainActions, terrainFailed, terrainReason, UNAVAILABLE, NO_TERRAIN, beginWaypointPlacement, cancelWaypointPlacement, placeWaypoint,
    language, setLanguage, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  const none = {getItem: () => null, setItem() {}};
  const calls = [];
  const actions = {zoom: d => calls.push(['zoom', d]), reset: () => calls.push(['reset']), top: () => calls.push(['top']), sources() {}};
  const both = () => render(h(PresentationToggle, {})) + '\n' + render(h(TerrainControls, {}));
  try {
    assert.deepEqual(PRESENTATIONS.map(p => [p.value, p.label]), [['chart', 'Chart'], ['2d', '2D'], ['3d', '3D']], 'the compatibility list stays English with stable values');
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=2d`);
    terrainActions.value = actions;
    const en = both();
    for (const word of ['aria-label="Map presentation"', '>Chart</button>', 'aria-label="Terrain view"', 'aria-label="Zoom in"', 'aria-label="Zoom out"', 'aria-label="Reset map view"', 'aria-label="View from above"']) assert.ok(en.includes(word), `en: ${word}`);
    setLanguage('es', {storage: none, doc: null});
    const es = both();
    for (const word of ['aria-label="Presentación del mapa"', '>Carta</button>', '>2D</button>', '>3D</button>', 'aria-label="Vista del terreno"', 'aria-label="Acercar"', 'aria-label="Alejar"', 'aria-label="Restablecer la vista del mapa"', 'aria-label="Vista desde arriba"']) assert.ok(es.includes(word), `es: ${word}`);
    assert.ok(!/Zoom in|Map presentation|>Chart</.test(es), 'no English chrome left in Spanish');
    setLanguage('en', {storage: none, doc: null});
    assert.ok(both() === en, 'English output returns identically after a round trip');
    assert.equal(calls.length, 0, 'a language change presses no control');
    // No renderer actions: no terrain controls at all.
    terrainActions.value = null;
    assert.equal(render(h(TerrainControls, {})), '');

    // The reasons: unreviewed terrain, a renderer failure, and an unknown future reason that stays literal.
    terrainActions.value = actions;
    state.syncFromURL(`${ORIGIN}?region=another-region&presentation=chart`);
    setLanguage('es', {storage: none, doc: null});
    let html = render(h(PresentationToggle, {}));
    assert.ok(html.includes('>Aún no hay terreno costero revisado que cubra esta región.</p>'), html);
    assert.equal((html.match(/disabled/g) ?? []).length, 2, '2D and 3D stay disabled');
    assert.equal((html.match(/aria-describedby="app-stage-note"/g) ?? []).length, 2);
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart`);
    terrainFailed.value = true;
    assert.ok(render(h(PresentationToggle, {})).includes('>Los gráficos costeros no están disponibles. La carta, los pronósticos y las herramientas de viaje siguen funcionando.</p>'));
    setLanguage('en', {storage: none, doc: null});
    assert.ok(render(h(PresentationToggle, {})).includes(`>${UNAVAILABLE}</p>`));
    terrainFailed.value = false;
    assert.equal(terrainReason(NO_TERRAIN, 'en'), NO_TERRAIN);
    assert.equal(terrainReason('Some future reason.', 'es'), 'Some future reason.', 'an unknown reason passes through intact');
    assert.equal(terrainReason(null, 'es'), '');

    // Placement: the prompt, Cancel and the shared verdict read Spanish; the callbacks are the same.
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart`);
    const got = [];
    beginWaypointPlacement('morro-bay', at => got.push(at));
    setLanguage('es', {storage: none, doc: null});
    assert.match(render(h(PresentationToggle, {})), /Toca la Carta para colocar tu punto de ruta\. <button[^>]*>Cancelar punto de ruta<\/button>/);
    placeWaypoint('morro-bay', {lat: 35, lon: -121.2}, null);
    assert.match(render(h(PresentationToggle, {})), /Toca la Carta para colocar tu punto de ruta\. Áreas protegidas sin revisar\. <button/);
    setLanguage('en', {storage: none, doc: null});
    assert.match(render(h(PresentationToggle, {})), /Tap the Chart to place your waypoint\. Protected areas not checked\. <button[^>]*>Cancel waypoint<\/button>/);
    assert.equal(got.length, 0, 'the language change completed no placement');
    cancelWaypointPlacement();
  } finally { cancelWaypointPlacement(); terrainActions.value = null; terrainFailed.value = false; setLanguage('en', {storage: none, doc: null}); }
});

// S4-46 (RF1925-6): one top-level main per app view, and no two regions with one name.
const VOID_TAGS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);
/** Every element of rendered `html` with its attributes and the tags above it (a small tokenizer: the SSR output is well formed). */
function landmarkTree(html) {
  const out = [], stack = [];
  for (const m of html.matchAll(/<(\/?)([a-zA-Z][\w-]*)((?:[^>"]|"[^"]*")*?)(\/?)>/g)) {
    const [, closing, name, rest, selfClosing] = m, tag = name.toLowerCase();
    if (closing) { const at = stack.map(e => e.tag).lastIndexOf(tag); if (at >= 0) stack.length = at; continue; }
    const attr = Object.fromEntries([...rest.matchAll(/([\w:-]+)="([^"]*)"/g)].map(a => [a[1], a[2]]));
    const el = {tag, attr, ancestors: stack.map(e => e.tag + (e.attr.role ? `[role=${e.attr.role}]` : '') + (e.landmark ? '*' : ''))};
    el.landmark = tag === 'main' || attr.role === 'main' ? 'main' : attr.role === 'region' || (tag === 'section' && !attr.role && (attr['aria-label'] || attr['aria-labelledby'])) ? 'region' : tag === 'aside' ? 'complementary' : tag === 'nav' ? 'navigation' : null;
    if (el.landmark === 'main') el.role = 'main';
    out.push(el);
    if (!selfClosing && !VOID_TAGS.has(tag)) stack.push(el);
  }
  return out;
}
const regionName = (html, el) => el.attr['aria-label'] ?? (el.attr['aria-labelledby'] ? html.match(new RegExp(`id="${el.attr['aria-labelledby']}"[^>]*>([^<]*)<`))?.[1] : undefined);
/** [mains, mains nested in another landmark, duplicate region names] of one rendered page. */
function landmarkReport(html) {
  const tree = landmarkTree(html), mains = tree.filter(e => e.landmark === 'main');
  const nested = mains.filter(e => e.ancestors.some(a => a.endsWith('*') || /^(main|aside|nav)/.test(a)));
  const names = tree.filter(e => e.landmark === 'region').map(e => regionName(html, e)).filter(Boolean);
  return {mains: mains.length, nested: nested.length, duplicates: names.filter((n, i) => names.indexOf(n) !== i), names};
}

test('one_main_all_views_en_es: every app view has exactly one top-level main on the phone and the desktop, in both languages and presentations', async () => {
  const {narrow, setLanguage} = await load();
  const none = {getItem: () => null, setItem() {}};
  const real = {mobile: 0, desktop: 0};
  try {
    for (const lang of ['en', 'es']) {
      setLanguage(lang, {storage: none, doc: null});
      for (const view of ['coast', 'conditions', 'history', 'fleet', 'reports', 'plan']) {
        for (const presentation of ['chart', '2d', '3d']) {
          const href = `${ORIGIN}?region=morro-bay&view=${view}&presentation=${presentation}`;
          for (const [layout, html] of [['mobile', await renderMobile(href)], ['desktop', await renderShell(href)]]) {
            const label = `${layout} ${lang} ${view} ${presentation}`, report = landmarkReport(html);
            assert.equal(report.mains, 1, `${label}: exactly one main`);
            assert.equal(report.nested, 0, `${label}: the main is top level`);
            assert.deepEqual(report.duplicates, [], `${label}: no two regions share a name`);
            assert.doesNotMatch(html, /class="app-mobile-page"[^>]*><main|<main[^>]*class="app-mobile-page"/, `${label}: Reports and Plan own no main of their own`);
            real[layout]++;
          }
        }
      }
    }
  } finally { narrow.value = false; setLanguage('en', {storage: none, doc: null}); }
  assert.deepEqual(real, {mobile: 36, desktop: 36}, 'every case rendered');
  const mobile = await renderMobile(`${ORIGIN}?region=morro-bay&view=reports`);
  assert.match(mobile, /^<main class="app-mobile">/, 'the phone root is the main and keeps its class');
  assert.match(mobile, /<div class="app-mobile-page"><section class="app-firstrun"/, 'the first-run prompt keeps its place in the Reports page');
});

test('landmark_report: the helper flags a nested main and a repeated region name', () => {
  const bad = '<main><section aria-label="Map"><main></main></section><section aria-label="Map"></section></main>';
  assert.deepEqual(landmarkReport(bad), {mains: 2, nested: 1, duplicates: ['Map'], names: ['Map', 'Map']});
  assert.equal(landmarkReport('<div role="main"><div role="group"></div></div>').mains, 1);
});

test('conditions_named_region_once: the phone Conditions view has one Conditions region, the sheet is a named group, the chart keeps its own region', async () => {
  const {narrow, setLanguage} = await load();
  const none = {getItem: () => null, setItem() {}};
  try {
    for (const [lang, word] of [['en', 'Conditions'], ['es', 'Condiciones']]) {
      setLanguage(lang, {storage: none, doc: null});
      const html = await renderMobile(`${ORIGIN}?region=morro-bay&view=conditions`);
      const names = landmarkReport(html).names;
      assert.equal(names.filter(n => n === word).length, 1, `${lang}: one region named ${word}`);
      assert.match(html, new RegExp(`<section class="ui-sheet app-sheet" data-detent="[a-z]+" role="group" aria-label="${word}">`), `${lang}: the sheet is a named group`);
      assert.match(html, new RegExp(`<section class="app-conditions" aria-labelledby="app-conditions-title"><header class="app-conditions-head"><h2 id="app-conditions-title">${word}</h2>`), `${lang}: the labelled section and its heading stay`);
      assert.match(html, /class="app-conditions-chart" role="region" aria-label="[^"]+"/, `${lang}: the chart keeps its own region`);
      assert.match(html, /aria-label="(Expand|Collapse) /, `${lang}: the handle keeps its name`);
    }
    // Brief and Conditions sheets alike are named groups.
    setLanguage('en', {storage: none, doc: null});
    for (const view of ['coast', 'conditions']) {
      const html = await renderMobile(`${ORIGIN}?region=morro-bay&view=${view}`);
      assert.match(html, /<section class="ui-sheet app-sheet[^"]*" data-detent="[a-z]+" role="group" aria-label="(Brief|Conditions)">/);
    }
  } finally { narrow.value = false; setLanguage('en', {storage: none, doc: null}); }
});
