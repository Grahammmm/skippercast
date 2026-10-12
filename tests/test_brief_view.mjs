// FE-37: the brief column renders the FE-31 model (design § 10). The brief
// modules are bundled with esbuild and rendered to strings over the synthetic
// Monterey fixtures of FE-31: tiles carry source and age, a tile past its
// limit renders stale with its age, no reading renders "—", and the column
// shows headline, deck, the lower-exposure line, caveat and local-report line.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const INFO = {id: 'monterey-point-sur', name: 'Monterey', center: [36.62, -121.9], timezone: 'America/Los_Angeles'};
const NOW = new Date('2026-10-08T21:00:00Z');

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'brief-')), 'brief.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export * from './web/brief/Brief.tsx';
      export {parseConditionsForecast} from './web/conditions.ts';
      export {Tiles, tileProps, ageText, sourceLine} from './web/brief/Tiles.tsx';
      export {Brief} from './web/app/Desktop.tsx';
      export {regionInfo} from './web/app/App.tsx';
      export {createCoastData} from './web/coast-data.ts';
      export {regionPlace} from './web/map/currents.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}
const sources = (over = {}) => ({info: INFO, feed: montereyDaily, coast: null, profile: 'boat', hour: null, ...over});

/** A synthetic /api/forecast answer for Monterey (values invented): NOAA wind and waves hourly for eight days from `start`, the runs issued `runAgeH` before NOW. */
function forecastFeed({runAgeH = 6, region = INFO.id} = {}) {
  const start = Date.parse('2026-10-08T07:00:00Z') / 1000, issued = NOW.getTime() / 1000 - runAgeH * 3600;
  const time = Array.from({length: 8 * 24}, (_, i) => start + i * 3600);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
  const meta = {last_run_initialisation_time: issued, data_end_time: time.at(-1)};
  return {region_id: region, retrieved: NOW.getTime() - 20 * 60_000, requested_points: [['monterey-bay', 36.7, -121.95], ['offshore-0-0', 36.5, -122.25]],
    models: {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [9, 'kn'], wind_gusts_10m: [14, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
      ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [5.1, 'ft'], wave_period: [12, 's']}))}}};
}

test('ageText and the source line: minutes, hours, days; no reading says unavailable', async () => {
  const {ageText, sourceLine} = await load();
  assert.deepEqual([ageText(45 * 60_000), ageText(5 * 3_600_000), ageText(72 * 3_600_000), ageText(-1)], ['45 min', '5 h', '3 d', 'clock ahead']);
  assert.equal(sourceLine({source: 'NDBC 46042', state: 'unavailable', ageMs: null}), 'NDBC 46042 · unavailable');
  assert.equal(sourceLine({source: 'NOAA tides', state: 'stale', ageMs: 5 * 3_600_000, lastGood: true}), 'NOAA tides · last good 5 h old');
  assert.equal(sourceLine({source: 'NOAA tides', state: 'stale', ageMs: 5 * 3_600_000, lastGood: true}, true), 'NOAA tides · last good 5 h');
});

test('a last-good tile renders stale and says the latest check failed', async () => {
  const {Tiles, render, h} = await load();
  const tile = {id: 'tide', label: 'Tide', value: 3.2, unit: 'ft', detail: 'next high · Monterey · MLLW', source: 'NOAA tides', sourceUrl: null,
    at: NOW.toISOString(), ageMs: 5 * 3_600_000, limitMs: 36 * 3_600_000, state: 'stale', lastGood: true};
  const html = render(h(Tiles, {tiles: [tile]}));
  assert.match(html, /data-state="stale"/);
  assert.match(html, /NOAA tides · last good 5 h old/);
  assert.match(html, /The latest check failed; this is the last good reading\./);
});

test('acceptance 1: a tile past its limit renders the stale state and its age', async () => {
  const {briefFrom, Tiles, render, h} = await load();
  const fresh = briefFrom(sources(), NOW);
  const water = fresh.tiles.find(t => t.id === 'water');
  assert.equal(water.state, 'fresh');
  const later = new Date(NOW.getTime() + 5 * 3_600_000);
  const stale = briefFrom(sources(), later).tiles.find(t => t.id === 'water');
  assert.equal(stale.state, 'stale');
  const html = render(h(Tiles, {tiles: [stale]}));
  assert.match(html, /data-state="stale"/);
  assert.match(html, /class="ui-tile-stale ui-eyebrow">stale</);
  assert.match(html, /NDBC 46042 · 5 h old/, 'the stale tile says how old its reading is');
  assert.match(html, new RegExp(`<span class="ui-reading">${stale.value}</span>`), 'the stale reading is still shown');
  assert.match(html, /Shown as stale after 3 h\./);
  const compact = render(h(Tiles, {tiles: [stale], compact: true}));
  assert.match(compact, /data-state="stale"/);
  assert.match(compact, /<span class="ui-mono">[^<]* · 5 h<\/span>/, 'the compact sheet tile keeps the age');
  assert.ok(compact.includes(`${stale.source} · 5 h`), 'the compact sheet tile keeps its short source with the age');
  assert.doesNotMatch(compact, /ui-popover|ui-tile-detail/, 'detail and basis wait for the full sheet');
});

test('without a regional forecast the wind and swell tiles read "—" and unavailable, never guessed', async () => {
  const {briefFrom, Tiles, render, h} = await load();
  const brief = briefFrom(sources(), NOW);
  assert.equal(brief.basis, 'regional');
  const html = render(h(Tiles, {tiles: brief.tiles}));
  assert.equal((html.match(/<span class="ui-reading">—<\/span>/g) || []).length, 2);
  assert.equal((html.match(/· unavailable/g) || []).length, 2);
  assert.match(html, /Reference level: MLLW\./, 'the tide basis names the reference level');
});

test('the column renders the model: headline, deck, lower-exposure line, caveat, local-report line', async () => {
  const {Brief, briefFrom, dailyFeed, regionInfo, render, h} = await load();
  const expected = briefFrom(sources(), NOW);
  regionInfo.value = INFO;
  dailyFeed.value = montereyDaily;
  try {
    const html = render(h(Brief, {now: NOW}));
    assert.match(html, /<aside class="app-brief" aria-label="Brief" data-basis="regional">/);
    assert.ok(html.includes(`<h1>${expected.headline}</h1>`));
    assert.match(html, /<p class="app-deck">/);
    assert.match(html, /class="ui-eyebrow">Lower exposure</);
    assert.ok(html.includes(expected.caveat));
    assert.match(html, /Local coast report unavailable here/);
    assert.equal((html.match(/class="ui-tile"/g) || []).length, 4);
    assert.doesNotMatch(html, /best bite|hotspot/i);
  } finally { regionInfo.value = null; dailyFeed.value = null; }
});

test('a feed for another region, or no region, leaves the brief empty', async () => {
  const {briefFrom, loadDailyFeed, dailyFeed} = await load();
  assert.equal(briefFrom(sources({info: {...INFO, id: 'morro-bay'}}), NOW), null);
  assert.equal(briefFrom(sources({info: null}), NOW), null);
  const fetchFn = async () => new Response(JSON.stringify(montereyDaily), {status: 200});
  assert.equal(await loadDailyFeed('morro-bay', fetchFn), null, 'identity check: region_id must match');
  assert.equal((await loadDailyFeed('monterey-point-sur', fetchFn))?.region_id, 'monterey-point-sur');
  dailyFeed.value = null;
});

test('#542: the sampled regional forecast fills the wind and swell tiles, fresh within its run limit', async () => {
  const {briefFrom, parseConditionsForecast, Tiles, render, h} = await load();
  const forecast = parseConditionsForecast(forecastFeed(), INFO.id, INFO.center);
  const brief = briefFrom(sources({forecast}), NOW);
  const wind = brief.tiles.find(t => t.id === 'wind'), swell = brief.tiles.find(t => t.id === 'swell');
  assert.deepEqual([wind.value, wind.state, wind.source, wind.detail], [9, 'fresh', 'NOAA GFS model · monterey-bay', 'gust 14 kt · from WNW']);
  assert.deepEqual([swell.value, swell.state, swell.detail], [5.1, 'fresh', '12 s · offshore forecast']);
  assert.equal(wind.ageMs, 6 * 3_600_000, 'the age runs from the model run');
  assert.ok(!brief.missing.includes('Fresh local forecast unavailable'));
  const html = render(h(Tiles, {tiles: brief.tiles}));
  assert.match(html, /NOAA GFS model · monterey-bay · 6 h old/);
  assert.equal((html.match(/<span class="ui-reading">—<\/span>/g) || []).length, 0);
});

test('#542: an old run reads stale with its age, never as fresh', async () => {
  const {briefFrom, parseConditionsForecast, Tiles, render, h} = await load();
  const brief = briefFrom(sources({forecast: parseConditionsForecast(forecastFeed({runAgeH: 30}), INFO.id, INFO.center)}), NOW);
  for (const id of ['wind', 'swell']) {
    const t = brief.tiles.find(x => x.id === id);
    assert.equal(t.state, 'stale', `${id} is stale`);
    assert.notEqual(t.value, null, `${id} still shows its reading`);
  }
  assert.ok(brief.missing.includes('Fresh local forecast unavailable'), 'buildDaily does not plan on the old run');
  assert.equal(brief.status, 'Unknown');
  const html = render(h(Tiles, {tiles: brief.tiles}));
  assert.equal((html.match(/NOAA GFS model · monterey-bay · 30 h old/g) || []).length, 2);
});

test('#542: a missing forecast, or one for another region, leaves wind and swell unavailable', async () => {
  const {briefFrom, parseConditionsForecast} = await load();
  const other = {...parseConditionsForecast(forecastFeed({region: 'morro-bay'}), 'morro-bay', null)};
  for (const forecast of [null, undefined, other]) {
    const brief = briefFrom(sources({forecast}), NOW);
    assert.deepEqual(brief.tiles.filter(t => t.id === 'wind' || t.id === 'swell').map(t => [t.value, t.state]), [[null, 'unavailable'], [null, 'unavailable']]);
  }
});

test('#542: the forecast loads once per region and point, and a failed load is tried again', async () => {
  const {ensureRegionalForecast, regionalForecast} = await load();
  let calls = 0, fail = true;
  const fetchFn = async url => { calls++; assert.match(String(url), /\/api\/forecast\?region=monterey-point-sur$/); return fail ? new Response('', {status: 503}) : new Response(JSON.stringify(forecastFeed()), {status: 200}); };
  const page = 'https://skippercast.test/map';
  assert.equal(await ensureRegionalForecast(INFO.id, INFO.center, fetchFn, page), null);
  fail = false;
  const f = await ensureRegionalForecast(INFO.id, INFO.center, fetchFn, page);
  assert.equal(f.point.id, 'monterey-bay');
  assert.equal(regionalForecast.value, f);
  await ensureRegionalForecast(INFO.id, INFO.center, fetchFn, page);
  assert.equal(calls, 2, 'the brief and the Conditions view share one request');
  regionalForecast.value = null;
});

test('#542: a visible page reloads a forecast older than 30 minutes and retries a failed load, with one listener and no timer', async () => {
  const {ensureRegionalForecast, refreshForecastIfStale, regionalForecast, FORECAST_MAX_AGE_MS} = await load();
  const listeners = [];
  const doc = {visibilityState: 'hidden', addEventListener: (type, fn) => listeners.push([type, fn])};
  globalThis.document = doc;
  try {
    let calls = 0, fail = false;
    const fetchFn = async () => { calls++; return fail ? new Response('', {status: 503}) : new Response(JSON.stringify(forecastFeed()), {status: 200}); };
    const page = 'https://skippercast.test/map';
    await ensureRegionalForecast(INFO.id, [36.7, -121.9], fetchFn, page);
    await ensureRegionalForecast(INFO.id, [36.7, -121.9], fetchFn, page);
    assert.deepEqual(listeners.map(l => l[0]), ['visibilitychange'], 'one listener only');
    const before = calls, now = Date.now();
    assert.equal(refreshForecastIfStale(now + FORECAST_MAX_AGE_MS - 60_000), null, 'a recent forecast is kept');
    assert.equal(calls, before);
    fail = true;
    await refreshForecastIfStale(now + FORECAST_MAX_AGE_MS + 60_000);
    assert.equal(calls, before + 1, 'an old forecast is fetched again');
    assert.equal(regionalForecast.value, null, 'the failed reload leaves no forecast');
    fail = false;
    doc.visibilityState = 'visible';
    listeners[0][1]();
    await new Promise(r => setTimeout(r, 50));
    assert.equal(calls, before + 2, 'the next visibility change retries after a failure');
    assert.ok(regionalForecast.value);
    listeners[0][1]();
    assert.equal(calls, before + 2, 'a fresh forecast is not fetched again');
  } finally { delete globalThis.document; regionalForecast.value = null; }
});

// FE-60 live check (#473): defects found on /map?region=morro-bay.
const MORRO_INFO = {id: 'morro-bay', name: 'Morro Bay & Avila', center: [35.34, -120.965], timezone: 'America/Los_Angeles',
  localAreas: [{id: 'estero-bay', name: 'Estero Bay', bounds: [-121.05, 35.32, -120.78, 35.47]}]};

test('#473: the brief reads the daily data feed (reports, tides) with the conditions feed\'s newer buoys first', async () => {
  const {loadDailyFeed, dailyFeed} = await load();
  const conditions = {schema_version: 1, region_id: 'monterey-point-sur', sources: {diablo: {id: 'diablo', name: 'NDBC 46042 every 30 min', kind: 'observation', url: 'https://example.test/46042', checked_at: NOW.toISOString(), status: 'ok', data: {station: '46042', observations: []}}}};
  const paths = [];
  const fetchFn = async path => {
    paths.push(String(path));
    return new Response(JSON.stringify(String(path).startsWith('/feeds/data/') ? montereyDaily : conditions), {status: 200});
  };
  try {
    const feed = await loadDailyFeed('monterey-point-sur', fetchFn);
    assert.deepEqual(paths.sort(), ['/feeds/conditions/regions/monterey-point-sur/latest.json', '/feeds/data/regions/monterey-point-sur/latest.json']);
    assert.deepEqual(feed.reports, montereyDaily.reports, 'the landing reports come from the daily feed');
    assert.equal(Object.keys(feed.sources)[0], 'diablo', 'the 30-minute buoy comes first');
    assert.ok(feed.sources.tides, 'the daily feed keeps its tides');
    // Where both feeds name one buoy key, the 30-minute copy wins.
    const stale = {...conditions.sources.diablo, name: 'NDBC 46042 daily', checked_at: '2026-01-01T00:00:00Z'};
    const collide = await loadDailyFeed('monterey-point-sur', async path => new Response(JSON.stringify(String(path).startsWith('/feeds/data/')
      ? {...montereyDaily, sources: {...montereyDaily.sources, diablo: stale}} : conditions), {status: 200}));
    assert.equal(collide.sources.diablo.name, 'NDBC 46042 every 30 min', 'the newer conditions buoy is not overwritten');
    // Either feed stands alone when the other fails.
    const only = prefix => async path => String(path).startsWith(prefix) ? fetchFn(path) : new Response('no', {status: 503});
    assert.deepEqual((await loadDailyFeed('monterey-point-sur', only('/feeds/data/'))).sources, montereyDaily.sources);
    assert.deepEqual((await loadDailyFeed('monterey-point-sur', only('/feeds/conditions/'))).sources, conditions.sources);
  } finally { dailyFeed.value = null; }
});

test('#473: the fleet line counts the region\'s trips by its landing names, not its display name', async () => {
  const {briefFrom} = await load();
  const feed = {...montereyDaily, region_id: 'morro-bay', landing_names: ['Morro Bay', 'Avila'],
    reports: [{date: '2026-10-07', boat: 'Avenger', port: 'Morro Bay'}, {date: '2026-10-07', boat: 'Flying Fish', port: 'Avila Beach'}]};
  const brief = briefFrom(sources({info: MORRO_INFO, feed}), NOW);
  assert.equal(brief.fleet?.text, '2 boats reported from Morro Bay & Avila Beach in the last 7 days');
});

test('#473: the brief asks for the coast report where the region binds one, with no layer on, and only once', async t => {
  const {bindBriefReport, createCoastData, regionPlace} = await load();
  const calls = [], original = globalThis.fetch;
  globalThis.fetch = async path => { calls.push(String(path)); return new Response('no', {status: 503}); };
  const client = createCoastData({clockEvents: null});
  t.after(() => { globalThis.fetch = original; client.destroy(); });
  const place = () => regionPlace(MORRO_INFO, 'boat', '');
  const stop = bindBriefReport(place, client);
  t.after(stop);
  await new Promise(resolve => setTimeout(resolve, 0));
  const reports = () => calls.filter(path => path.includes('coast/report')).length;
  assert.equal(reports(), 1, 'requested with no layer on');
  // The Swell layer asks for the same place: no second request.
  client.setPlace(place());
  await client.load('report');
  assert.equal(reports(), 1);
  // Outside a binding nothing is requested.
  const before = calls.length, other = createCoastData({clockEvents: null});
  bindBriefReport(() => regionPlace({id: 'monterey-point-sur', center: [36.62, -121.9], localAreas: []}, 'boat', ''), other)();
  other.destroy();
  assert.equal(calls.length, before);
});

test('P5 gaps: an unreadable feed says so and the headline stops waiting; unreadable both, readings unavailable', async () => {
  const {loadDailyFeed, dailyFeed, feedGaps, FEED_GAP, Headline, BriefGaps, render, h} = await load();
  const daily = async path => path.startsWith('/feeds/data/') ? new Response(JSON.stringify(montereyDaily), {status: 200}) : new Response('', {status: 503});
  await loadDailyFeed('monterey-point-sur', daily);
  assert.deepEqual(feedGaps.value, [FEED_GAP.conditions]);
  assert.match(render(h(BriefGaps, {brief: null})), /Live buoy feed could not be read/);
  await loadDailyFeed('monterey-point-sur', async () => new Response('', {status: 503}));
  assert.deepEqual(feedGaps.value, [FEED_GAP.both]);
  assert.match(render(h(Headline, {brief: null})), /Readings unavailable\./);
  await loadDailyFeed('monterey-point-sur', async () => new Response(JSON.stringify(montereyDaily), {status: 200}));
  assert.deepEqual(feedGaps.value, []);
  assert.match(render(h(Headline, {brief: null})), /Waiting for readings\./);
  dailyFeed.value = null;
});

test('P5 gaps: source gaps stay visible; what the model could not check folds into a disclosure', async () => {
  const {BriefGaps, render, h} = await load();
  const html = render(h(BriefGaps, {brief: {gaps: [{id: 'tides', label: 'NOAA tides', status: 'failed', text: 'NOAA tides: latest check failed; no earlier reading on hand.'}],
    missing: ['Tide curve unavailable for this date', 'Harbor entrance and full return route need a separate check']}}));
  assert.match(html, /<li data-status="failed">NOAA tides: latest check failed; no earlier reading on hand\.<\/li>/);
  assert.match(html, /<details class="app-gaps-more"><summary>Not checked in this brief \(2\)<\/summary>/);
  assert.equal(render(h(BriefGaps, {brief: {gaps: [], missing: []}})), '', 'nothing missing renders nothing');
});
