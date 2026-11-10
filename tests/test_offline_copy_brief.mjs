// SC1722-03: data the saved offline pack answered (X-SC-Offline, the pack's save time) is held in the brief as saved at that
// time, through the existing saved line, and is never written back as a newly fresh saved brief; the freshness chip keeps the
// source age while offline. The real loader, the real orchestration (web/brief/Brief.tsx) and the real chip run over scripted
// fetches; a network answer (no header) is unchanged.
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import test, {mock} from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const ID = 'monterey-point-sur', HOUR = 3_600_000;
const INFO = {id: ID, name: 'Monterey', center: [36.62, -121.9], timezone: 'America/Los_Angeles'};
const NOW = new Date('2026-10-08T21:00:00Z');
const PAGE = 'https://skippercast.test/map';
// The pack saved its answers 5 h ago; an older saved brief on the device is from 9 h ago; the device reads them now.
const PACK = Date.now() - 5 * HOUR, PACK_ISO = new Date(PACK).toISOString();
const OLDER = Date.now() - 9 * HOUR;

let bundle, n = 0;
async function load() {
  if (!bundle) {
    const out = join(await mkdtemp(join(tmpdir(), 'offline-copy-')), 'offline.mjs');
    await build({
      stdin: {resolveDir: ROOT, loader: 'ts', contents: `
        export * from './web/brief/Brief.tsx';
        export * from './web/brief/saved-brief.ts';
        export {loadConditionsForecast} from './web/conditions.ts';
        export {responseProvenance} from './web/offline-response.ts';
        export {startupFreshness, freshness, regionInfo} from './web/app/App.tsx';
        export {FreshnessDot} from './web/app/Masthead.tsx';
        export {language, localeOf} from './web/i18n.ts';
        export {prepareCatalogue} from './web/i18n-catalogue.ts';
        export {render} from 'preact-render-to-string';
        export {h} from 'preact';`},
      bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
    });
    bundle = pathToFileURL(out).href;
  }
  delete globalThis.document; // the app shell touches the page's document on import
  const m = await import(`${bundle}?${++n}`); // a fresh module (fresh request and held state) per test, as a fresh page load
  await m.prepareCatalogue('es');
  globalThis.document = {visibilityState: 'hidden', addEventListener: () => {}};
  return m;
}
test.after(() => { delete globalThis.document; });

/** A synthetic /api/forecast answer (values invented): the runs issued 6 h before NOW, the feed retrieved 20 min before it. */
function forecastFeed(region = ID) {
  const start = Date.parse('2026-10-08T07:00:00Z') / 1000, time = Array.from({length: 8 * 24}, (_, i) => start + i * 3600);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
  const meta = {last_run_initialisation_time: NOW.getTime() / 1000 - 6 * 3600, data_end_time: time.at(-1)};
  return {region_id: region, retrieved: NOW.getTime() - 20 * 60_000, requested_points: [['monterey-bay', 36.7, -121.95], ['offshore-0-0', 36.5, -122.25]],
    models: {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [9, 'kn'], wind_gusts_10m: [14, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
      ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [5.1, 'ft'], wave_period: [12, 's']}))}}};
}
const answer = (body, saved = null, status = 200) => new Response(JSON.stringify(body), {status, headers: saved === null ? {} : {'X-SC-Offline': saved}});
const forecastFetch = (saved = null, body = forecastFeed()) => async () => answer(body, saved);
const conditionsFor = id => ({schema_version: 1, region_id: id, sources: {diablo: {id: 'diablo', name: 'NDBC 46042', kind: 'observation', url: '', checked_at: NOW.toISOString(), status: 'ok'}}});
const partFor = id => ({...montereyDaily, region_id: id, part: 'brief', catch_probability: null, bite_score: null});
/**
 * The daily-side server: per read ('part', 'whole', 'live') a save time for the X-SC-Offline header (null: a network answer),
 * 'down' for HTTP 503, or {region} for another region's body. Every requested path is recorded.
 */
function server({part = null, whole = null, live = null} = {}) {
  const s = {paths: []};
  s.fetch = async path => {
    path = String(path); s.paths.push(path);
    const kind = path.startsWith('/api/daily') ? 'part' : path.startsWith('/feeds/data/') ? 'whole' : 'live', how = {part, whole, live}[kind];
    if (how === 'down') return new Response('', {status: 503});
    const id = typeof how === 'object' && how ? how.region : kind === 'part' ? new URL(path, PAGE).searchParams.get('region') : decodeURIComponent(path.split('/')[4]);
    const saved = typeof how === 'object' && how ? how.saved : how;
    return answer(kind === 'live' ? conditionsFor(id) : kind === 'part' ? partFor(id) : {...montereyDaily, region_id: id}, saved);
  };
  return s;
}
const memory = (init) => { const m = new Map(init ? [[init[0], init[1]]] : []); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => { m.set(k, String(v)); }, m}; };

/** The saved line as the brief shows it, in `lang`, with the region on screen. */
function savedLineHtml(m, lang = 'en', now = new Date()) {
  m.regionInfo.value = INFO;
  m.language.value = lang;
  try { return m.render(m.h(m.SavedLine, {now})); } finally { m.language.value = 'en'; }
}
const clock = (m, at, lang = 'en') => new Intl.DateTimeFormat(m.localeOf(lang), {weekday: 'short', hour: 'numeric', minute: '2-digit', timeZone: INFO.timezone, timeZoneName: 'short'}).format(new Date(at));

test('saved_header_bad_is_not_fresh: a missing header is a network answer; an unusable one is invalid; epoch zero is an ancient saved time', async () => {
  const {responseProvenance} = await load();
  const at = value => responseProvenance(new Headers(value === undefined ? {} : {'X-SC-Offline': value}), Date.now());
  assert.ok(isDeepStrictEqual(at(undefined), {kind: 'network'}));
  assert.ok(isDeepStrictEqual(at(PACK_ISO), {kind: 'saved', at: PACK}));
  assert.ok(isDeepStrictEqual(at('1970-01-01T00:00:00.000Z'), {kind: 'saved', at: 0}), 'the worker\'s epoch fallback is an old saved time, not now and not absence');
  for (const bad of ['', '   ', 'yesterday', 'NaN', new Date(Date.now() + 11 * 60_000).toISOString()]) assert.ok(isDeepStrictEqual(at(bad), {kind: 'invalid'}), JSON.stringify(bad));
  assert.equal(at(new Date(Date.now() + 5 * 60_000).toISOString()).kind, 'saved', 'a few minutes of clock skew is allowed');
});

test('saved_header_bad_is_not_fresh: the forecast loader carries the header time on a loaded answer and fails an unusable header', async () => {
  const {loadConditionsForecast} = await load();
  const read = fetchFn => loadConditionsForecast(ID, INFO.center, fetchFn, PAGE);
  const pack = await read(forecastFetch(PACK_ISO));
  assert.equal(pack.state, 'loaded');
  assert.equal(pack.savedAt, PACK);
  assert.equal((await read(forecastFetch())).savedAt, null, 'a network answer has no saved time');
  for (const bad of ['', 'garbage']) assert.ok(isDeepStrictEqual(await read(forecastFetch(bad)), {state: 'failed', reason: 'invalid'}), `header ${JSON.stringify(bad)} is never a network-like answer`);
  assert.ok(isDeepStrictEqual(await read(forecastFetch(PACK_ISO, forecastFeed('morro-bay'))), {state: 'failed', reason: 'invalid'}), 'another region\'s feed stays invalid, saved or not');
});

test('forecast_pack_saved_line_at_header_time: a pack forecast is held as saved at the header time and says so, in English and Spanish', async () => {
  const m = await load();
  m.regionInfo.value = INFO;
  m.dailyFeed.value = montereyDaily;
  await m.ensureRegionalForecast(ID, INFO.center, forecastFetch(PACK_ISO), PAGE);
  assert.equal(m.regionalForecastState.value.state, 'loaded');
  assert.ok(m.regionalForecast.value, 'the pack forecast is used');
  assert.ok(isDeepStrictEqual(m.savedBrief.value, {at: PACK, state: 'offline'}), 'the header time, not the time it was read and not the model run');
  const en = savedLineHtml(m), es = savedLineHtml(m, 'es');
  assert.ok(en.includes(`Saved offline copy from ${clock(m, PACK)}.`), en);
  assert.ok(es.includes(`Copia guardada sin conexión del ${clock(m, PACK, 'es')}.`), es);
  assert.match(en, /data-saved="offline"/);
  assert.doesNotMatch(en, /Updating now|Update failed/);
});

test('forecast_pack_saved_line_at_header_time: a network forecast shows no saved line; a failed retry keeps the pack time and says the update failed', async () => {
  const net = await load();
  net.regionInfo.value = INFO;
  net.dailyFeed.value = montereyDaily;
  await net.ensureRegionalForecast(ID, INFO.center, forecastFetch(), PAGE);
  assert.equal(net.savedBrief.value, null);
  assert.equal(savedLineHtml(net), '', 'no saved line for a network answer');
  const m = await load();
  m.regionInfo.value = INFO;
  m.dailyFeed.value = montereyDaily;
  let calls = 0;
  const packThenDown = async () => (++calls === 1 ? answer(forecastFeed(), PACK_ISO) : new Response('', {status: 500}));
  await m.ensureRegionalForecast(ID, INFO.center, packThenDown, PAGE);
  assert.ok(isDeepStrictEqual(m.savedBrief.value, {at: PACK, state: 'offline'}));
  await m.retryRegionalForecast();
  assert.equal(m.regionalForecastState.value.state, 'failed', 'the failure is the existing forecast failure state');
  assert.ok(isDeepStrictEqual(m.savedBrief.value, {at: PACK, state: 'failed'}), 'the hold and its time are kept, now saying the update failed');
  assert.ok(m.regionalForecast.value, 'the pack forecast stays on screen');
});

test('daily_part_whole_and_conditions_provenance: a pack brief part is held as saved at its header time, in one read', async () => {
  const m = await load();
  const s = server({part: PACK_ISO});
  const feed = await m.loadDailyFeed(ID, s.fetch);
  assert.equal(feed.region_id, ID);
  assert.ok(!s.paths.some(p => p.startsWith('/feeds/data/')), 'the admitted part needs no whole-feed read');
  assert.ok(isDeepStrictEqual(m.savedBrief.value, {at: PACK, state: 'offline'}));
  assert.equal(m.needsDailyLoad(ID), false, 'a completed pack read is not asked again by the next effect run');
});

test('daily_part_whole_and_conditions_provenance: a rejected part\'s header never taints the network whole feed that replaces it', async () => {
  const m = await load();
  const s = server({part: {region: 'morro-bay', saved: PACK_ISO}});
  await m.loadDailyFeed(ID, s.fetch);
  assert.ok(s.paths.some(p => p.startsWith('/feeds/data/')), 'the whole feed was read instead');
  assert.equal(m.savedBrief.value, null, 'no false saved notice');
});

test('daily_part_whole_and_conditions_provenance: a pack whole feed, a pack buoy feed beside a network daily, and a buoy-only read are each held as saved', async () => {
  for (const [name, opts, at] of [
    ['the whole feed from the pack', {part: 'down', whole: PACK_ISO}, PACK],
    ['the buoy feed from the pack beside a network daily', {live: PACK_ISO}, PACK],
    ['only the buoy feed, from the pack', {part: 'down', whole: 'down', live: PACK_ISO}, PACK],
    ['two saved feeds: the oldest time', {part: PACK_ISO, live: new Date(PACK - HOUR).toISOString()}, PACK - HOUR],
  ]) {
    const m = await load();
    await m.loadDailyFeed(ID, server(opts).fetch);
    assert.ok(isDeepStrictEqual(m.savedBrief.value, {at, state: 'offline'}), `${name}: ${JSON.stringify(m.savedBrief.value)}`);
  }
  const m = await load();
  await m.loadDailyFeed(ID, server({live: 'down'}).fetch);
  assert.equal(m.savedBrief.value, null, 'a failed read never taints or clears a hold: a network daily alone is fresh');
});

test('pack_never_renews_saved_store: a pack forecast and daily leave an older saved entry exactly as it was, in either order, and write none when there is none', async () => {
  const seed = async () => {
    const first = await load(), store = memory();
    first.enableSavedBrief(store);
    await first.loadDailyFeed(ID, server().fetch);
    const entry = JSON.parse(store.m.get(first.SAVED_BRIEF_KEY));
    entry.daily.at = OLDER;
    store.m.set(first.SAVED_BRIEF_KEY, JSON.stringify(entry));
    return {store, raw: store.m.get(first.SAVED_BRIEF_KEY)};
  };
  for (const order of ['daily first', 'forecast first']) {
    const {store, raw} = await seed(), m = await load();
    m.enableSavedBrief(store);
    assert.equal(m.showSavedBrief(ID), true);
    m.regionInfo.value = INFO;
    const daily = () => m.loadDailyFeed(ID, server({part: PACK_ISO}).fetch), forecast = () => m.ensureRegionalForecast(ID, INFO.center, forecastFetch(PACK_ISO), PAGE);
    if (order === 'daily first') { await daily(); await forecast(); } else { await forecast(); await daily(); }
    m.noteRegionInfo(ID);
    assert.equal(store.m.get(m.SAVED_BRIEF_KEY), raw, `${order}: the stored entry and its own time are untouched`);
    assert.equal(JSON.parse(raw).daily.at, OLDER);
    assert.ok(isDeepStrictEqual(m.savedBrief.value, {at: PACK, state: 'offline'}), 'the notice is the pack\'s time');
  }
  // A network daily beside a pack forecast does not overwrite the saved entry either; the first all-network read does.
  const {store, raw} = await seed(), m = await load();
  m.enableSavedBrief(store);
  m.regionInfo.value = INFO;
  await m.ensureRegionalForecast(ID, INFO.center, forecastFetch(PACK_ISO), PAGE);
  await m.loadDailyFeed(ID, server().fetch);
  assert.equal(store.m.get(m.SAVED_BRIEF_KEY), raw, 'mixed network and pack never writes');
  assert.ok(m.savedBrief.value && m.savedBrief.value.at === PACK);
  m.regionInfo.value = INFO;
  await m.ensureRegionalForecast(ID, INFO.center, forecastFetch(), PAGE); // same key: joined, nothing new
  const later = await load();
  later.enableSavedBrief(store);
  later.regionInfo.value = INFO;
  await later.ensureRegionalForecast(ID, INFO.center, forecastFetch(), PAGE);
  await later.loadDailyFeed(ID, server().fetch);
  assert.notEqual(store.m.get(later.SAVED_BRIEF_KEY), raw, 'ordinary persistence resumes once the data is network data');
  assert.equal(later.savedBrief.value, null);
  // No existing entry, or no store at all: an all-pack load writes nothing and does not throw.
  const empty = memory(), p = await load();
  p.enableSavedBrief(empty);
  p.regionInfo.value = INFO;
  await p.ensureRegionalForecast(ID, INFO.center, forecastFetch(PACK_ISO), PAGE);
  await p.loadDailyFeed(ID, server({part: PACK_ISO}).fetch);
  assert.equal(empty.m.size, 0);
  const none = await load();
  none.enableSavedBrief(null);
  await none.loadDailyFeed(ID, server({part: PACK_ISO}).fetch);
  assert.equal(none.savedBrief.value.state, 'offline');
});

test('pack_settle_and_pending_are_bounded: the restored brief\'s settle timer does not turn a pack answer into a failure; a restored one alone still fails', async () => {
  const first = await load(), store = memory();
  first.enableSavedBrief(store);
  await first.loadDailyFeed(ID, server().fetch);
  mock.timers.enable({apis: ['setTimeout']});
  try {
    const m = await load();
    m.enableSavedBrief(store);
    m.showSavedBrief(ID);
    assert.equal(m.savedBrief.value.state, 'updating');
    await m.loadDailyFeed(ID, server({part: PACK_ISO}).fetch);
    assert.equal(m.savedBrief.value.state, 'offline');
    mock.timers.tick(m.SAVED_SETTLE_MS + 1);
    assert.ok(isDeepStrictEqual(m.savedBrief.value, {at: PACK, state: 'offline'}), 'a late settle timer never relabels a pack success');
    const r = await load();
    r.enableSavedBrief(store);
    r.showSavedBrief(ID);
    mock.timers.tick(r.SAVED_SETTLE_MS + 1);
    assert.equal(r.savedBrief.value.state, 'failed', 'a restored brief that was never replaced still says the update failed');
  } finally { mock.timers.reset(); }
});

test('offline_source_age_not_save_or_arrival_age: offline the chip keeps the oldest source age; online is unchanged; no usable reading has no age', async () => {
  const {startupFreshness} = await load();
  const now = Date.parse('2026-10-29T12:00:00Z');
  const reading = (minutes, extra = {}) => ({at: new Date(now - minutes * 60_000).toISOString(), limitMs: 3 * HOUR, value: 1, state: 'fresh', ...extra});
  const at = (tiles, online) => startupFreshness(tiles, () => now, online);
  assert.ok(isDeepStrictEqual(at([reading(4)], false), {state: 'offline', age: '4 min'}));
  assert.ok(isDeepStrictEqual(at([reading(4), reading(150)], false), {state: 'offline', age: '2 h'}), 'the oldest source, not the pack save time or the read time');
  assert.ok(isDeepStrictEqual(at([reading(4, {state: 'stale'})], false), {state: 'offline', age: '4 min'}), 'offline wins over stale');
  assert.ok(isDeepStrictEqual(at([], false), {state: 'offline', age: null}), 'no source, no fabricated age');
  assert.ok(isDeepStrictEqual(at([reading(0, {at: new Date(now + 3_600_000).toISOString()})], false), {state: 'offline', age: null}), 'a future clock gives no age');
  assert.ok(isDeepStrictEqual(at([reading(4, {value: null})], false), {state: 'offline', age: null}));
  assert.ok(isDeepStrictEqual(at([reading(4)], true), {state: 'ok', age: '4 min'}), 'online is as before');
  assert.ok(isDeepStrictEqual(at([reading(4, {state: 'stale'})], true), {state: 'stale', age: '4 min'}));
});

test('offline_chip_en_es: the chip says Offline / Sin conexión beside its separate age; a network state has no such word', async () => {
  const m = await load();
  const chip = (lang, fresh) => { m.language.value = lang; m.freshness.value = fresh; try { return m.render(m.h(m.FreshnessDot, {})); } finally { m.language.value = 'en'; } };
  const en = chip('en', {state: 'offline', age: '4 min'}), es = chip('es', {state: 'offline', age: '4 min'});
  assert.ok(en.includes('data-fresh-offline="true">Offline<'), en);
  assert.ok(es.includes('data-fresh-offline="true">Sin conexión<'), es);
  for (const html of [en, es]) { assert.ok(html.includes('>4 min<'), 'the age stays in its own span'); assert.ok(html.includes('data-state="offline"')); }
  assert.ok(chip('en', {state: 'offline', age: null}).includes('>—<'), 'offline with no readable source: the word and a dash');
  for (const state of ['ok', 'stale', 'unknown']) assert.ok(!chip('en', {state, age: '4 min'}).includes('data-fresh-offline'), state);
});
