// SC2222-01: the brief's daily and conditions feeds are read again when the page becomes visible
// after 30 minutes or after a read that got neither, as the forecast is (#542): no timer, one
// visibilitychange listener, and a region switch during a refresh is never overwritten.
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
const ID = 'monterey-point-sur', MIN = 60_000;
const listeners = [];
const doc = {visibilityState: 'hidden', addEventListener: (type, fn) => listeners.push([type, fn])};

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'brief-refresh-')), 'brief.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `export * from './web/brief/Brief.tsx';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  globalThis.document = doc; // after the import, so the first load binds the listener here
  return mod;
}
test.after(() => { delete globalThis.document; });

/** A synthetic feed host: each feed answers for the region in its path, or 503 when switched off; `held` parks every read until released. */
function server({daily = true, live = true} = {}) {
  const s = {daily, live, paths: [], held: null};
  s.fetch = async path => {
    path = String(path); s.paths.push(path);
    if (s.held) await new Promise(r => s.held.push(r));
    if (path.startsWith('/api/daily')) return new Response('', {status: 404}); // SC2222-03: the brief part refused, so the whole feed is read
    const isDaily = path.startsWith('/feeds/data/'), id = decodeURIComponent(path.split('/')[4]);
    if (!(isDaily ? s.daily : s.live)) return new Response('', {status: 503});
    const conditions = {schema_version: 1, region_id: id, sources: {diablo: {id: 'diablo', name: 'NDBC 46042', kind: 'observation', url: '', checked_at: '2026-10-08T21:00:00Z', status: 'ok'}}};
    return new Response(JSON.stringify(isDaily ? {...montereyDaily, region_id: id} : conditions), {status: 200});
  };
  s.release = () => { const w = s.held; s.held = null; w.forEach(r => r()); };
  return s;
}
const fire = async () => { for (const [type, fn] of listeners) if (type === 'visibilitychange') fn(); await new Promise(r => setTimeout(r, 20)); };

test('edge 7: no refresh before any load', async () => {
  const {refreshDailyIfStale} = await load();
  assert.equal(refreshDailyIfStale(Date.now() + 120 * MIN), null);
});

test('edge 1: kept at 29 min; at 31 min one read of each feed for the same region', async () => {
  const {loadDailyFeed, refreshDailyIfStale, dailyFeed, DAILY_MAX_AGE_MS, FORECAST_MAX_AGE_MS} = await load();
  assert.equal(DAILY_MAX_AGE_MS, FORECAST_MAX_AGE_MS, 'one 30-minute rule');
  const s = server();
  await loadDailyFeed(ID, s.fetch);
  const t = Date.now(), first = dailyFeed.value;
  assert.equal(refreshDailyIfStale(t + 29 * MIN), null);
  assert.equal(s.paths.length, 3, 'no fetch while fresh');
  await refreshDailyIfStale(t + 31 * MIN);
  assert.deepEqual(s.paths.slice(3).sort(), [`/api/daily?region=${ID}&part=brief`, `/feeds/conditions/regions/${ID}/latest.json`, `/feeds/data/regions/${ID}/latest.json`]);
  assert.notEqual(dailyFeed.value, first, 'the new read replaces the feed');
  assert.equal(dailyFeed.value.region_id, ID);
});

test('edge 2: a first read that got neither feed is read again at 1 min; success fills the feed and clears the gap', async () => {
  const {loadDailyFeed, refreshDailyIfStale, dailyFeed, feedGaps, FEED_GAP} = await load();
  const s = server({daily: false, live: false});
  assert.equal(await loadDailyFeed(ID, s.fetch), null);
  assert.deepEqual(feedGaps.value, [FEED_GAP.both], 'a failed first load behaves as before');
  s.daily = s.live = true;
  await refreshDailyIfStale(Date.now() + MIN);
  assert.equal(s.paths.length, 6);
  assert.equal(dailyFeed.value?.region_id, ID);
  assert.deepEqual(feedGaps.value, []);
});

test('edge 3: a refresh that reads neither keeps the shown feed and gaps; a daily-only refresh shows the conditions gap', async () => {
  const {loadDailyFeed, refreshDailyIfStale, dailyFeed, feedGaps, FEED_GAP} = await load();
  const s = server({live: false});
  await loadDailyFeed(ID, s.fetch);
  const feed = dailyFeed.value, gaps = feedGaps.value;
  assert.deepEqual(gaps, [FEED_GAP.conditions]);
  s.daily = false;
  const pending = refreshDailyIfStale(Date.now() + 31 * MIN);
  assert.equal(feedGaps.value, gaps, 'the gap lines are not cleared while the refresh reads');
  assert.equal(await pending, feed);
  assert.equal(dailyFeed.value, feed, 'the old feed object stays');
  assert.equal(feedGaps.value, gaps, 'the old gap lines stay');
  // The failed refresh kept the old read time, so the next visible page tries again.
  s.daily = true; s.live = true;
  await refreshDailyIfStale(Date.now() + 31 * MIN);
  assert.deepEqual(feedGaps.value, []);
  s.live = false;
  await refreshDailyIfStale(Date.now() + 62 * MIN);
  assert.notEqual(dailyFeed.value, feed);
  assert.deepEqual(feedGaps.value, [FEED_GAP.conditions], 'the same line a first load shows');
});

test('edge 4: a pending load is not read twice; a hidden page reads nothing, a visible one reads again', async () => {
  const {loadDailyFeed, refreshDailyIfStale} = await load();
  const s = server({daily: false, live: false});
  s.held = [];
  const first = loadDailyFeed(ID, s.fetch);
  assert.equal(refreshDailyIfStale(Date.now() + 120 * MIN), null, 'no second concurrent read');
  assert.equal(s.paths.length, 2);
  s.release(); await first;
  doc.visibilityState = 'hidden';
  await fire();
  assert.equal(s.paths.length, 3, 'hidden: no read');
  doc.visibilityState = 'visible';
  await fire();
  assert.equal(s.paths.length, 6, 'visible after a failed read: both feeds again');
  doc.visibilityState = 'hidden';
});

test('edge 5: a region switch while a refresh is in flight: the later region\'s feed and gaps win', async () => {
  const {loadDailyFeed, refreshDailyIfStale, dailyFeed, feedGaps, FEED_GAP} = await load();
  const a = server(), b = server({live: false});
  await loadDailyFeed(ID, a.fetch);
  a.held = [];
  const refresh = refreshDailyIfStale(Date.now() + 31 * MIN);
  assert.ok(refresh, 'the refresh started');
  await loadDailyFeed('morro-bay', b.fetch);
  a.release(); await refresh;
  assert.equal(dailyFeed.value.region_id, 'morro-bay', 'the stale refresh is not written');
  assert.deepEqual(feedGaps.value, [FEED_GAP.conditions]);
  assert.equal(refreshDailyIfStale(Date.now() + 29 * MIN), null, 'the newer load is the one kept fresh');
});

test('edge 6: one visibilitychange listener drives both the forecast and the daily refresh', async () => {
  const {loadDailyFeed, ensureRegionalForecast, regionalForecast} = await load();
  let forecastCalls = 0;
  const s = server({daily: false, live: false});
  await loadDailyFeed(ID, s.fetch);
  await ensureRegionalForecast(ID, [36.62, -121.9], async () => { forecastCalls++; return new Response('', {status: 503}); }, 'https://skippercast.test/map');
  assert.deepEqual(listeners.map(l => l[0]), ['visibilitychange'], 'one listener only');
  doc.visibilityState = 'visible';
  await fire();
  assert.equal(forecastCalls, 2, 'the failed forecast is read again');
  assert.equal(s.paths.length, 6, 'the failed feeds are read again');
  doc.visibilityState = 'hidden';
  regionalForecast.value = null;
});
