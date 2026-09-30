#!/usr/bin/env node
// Measure the JSON a region's map downloads at startup (P4-05).
// Usage: pnpm build && node scripts/measure_startup.mjs [--region morro-bay] [--stub | --stub-mpa] [--json]
//
// Loads /?region=<id>#map in Chromium against the built site under
// `wrangler dev` (e2e/serve.mjs, started here unless E2E_URL points at a
// running one), with every other origin blocked as in the browser tests.
// Records each JSON or GeoJSON response body and prints a table, split in two:
//   static  committed files the site serves (atlas, region JSON, protected
//           areas, ...). The CI budget (e2e/startup.spec.ts, limit in
//           scripts/startup-budget.json) checks this total, measured with no
//           interaction until the network is quiet: deferred data only counts
//           as saved if it is not fetched then either.
//   live    published feeds and Worker APIs (/api/*, /feeds/*, and the ArcGIS
//           MPA query). Their size moves with upstream data, so they are
//           reported for information only.
// With --stub (and always in the budget test) the live feeds are answered by
// deterministic stand-ins (stubLiveFeeds) that pass the app's checks, so the
// app takes its normal success path and the static total does not depend on
// what upstream published today. Without --stub the live sizes are real;
// --stub-mpa answers only the ArcGIS MPA query (which the tests' origin block
// would otherwise fail), so the live feeds are real and the path is production's.
// "Before interactive" counts bytes received before the first survey marker
// is visible. Sizes are decoded body bytes, not compressed transfer sizes.
import {spawn} from 'node:child_process';
import {existsSync, readdirSync, readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const root = resolve(import.meta.dirname, '..');
const QUIET_MS = 2500;

/** Whether a response is JSON data the page parses. */
export function isJSON(url, contentType = '') {
  const path = new URL(url).pathname;
  return /json/i.test(contentType) || /\.(geo)?json$/i.test(path);
}

/** Whether a same-origin path is a live feed or API rather than a committed file. */
export const isLive = path => /^\/(?:api|feeds)\//.test(path);

/** Group, total and sort recorded responses; `static` is the budgeted total. */
export function summarise(entries) {
  const rows = new Map();
  for (const e of entries) {
    const key = e.path;
    const row = rows.get(key) || {path: key, bytes: 0, requests: 0, beforeInteractive: false, live: !!e.live};
    row.bytes += e.bytes; row.requests += 1; row.beforeInteractive ||= e.beforeInteractive;
    rows.set(key, row);
  }
  const list = [...rows.values()].sort((a, b) => Number(a.live) - Number(b.live) || b.bytes - a.bytes);
  const sum = list => list.reduce((n, e) => n + e.bytes, 0);
  return {rows: list, interactive: sum(entries.filter(e => e.beforeInteractive)), startup: sum(entries),
    static: sum(entries.filter(e => !e.live)), live: sum(entries.filter(e => e.live))};
}

const HOUR = 3600;
const WIND = ['wind_speed_10m', 'wind_gusts_10m', 'wind_direction_10m', 'visibility', 'precipitation', 'temperature_2m', 'cloud_cover', 'weather_code'];
const WAVE = ['wave_height', 'wave_period', 'wave_direction', 'wind_wave_height', 'wind_wave_period', 'wind_wave_direction',
  'swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_period', 'secondary_swell_wave_direction'];
const VALUES = {wind_speed_10m: 8, wind_gusts_10m: 12, wind_direction_10m: 315, visibility: 20000, precipitation: 0, temperature_2m: 15, cloud_cover: 40,
  weather_code: 1, wave_height: 1.2, wave_period: 11, wave_direction: 300, wind_wave_height: 0.4, wind_wave_period: 4, wind_wave_direction: 315,
  swell_wave_height: 1.1, swell_wave_period: 12, swell_wave_direction: 295, secondary_swell_wave_height: 0.3, secondary_swell_wave_period: 15, secondary_swell_wave_direction: 200};
const MODELS = {gfs_global: WIND, ecmwf_ifs025: WIND, ncep_gfswave016: WAVE, ecmwf_wam: WAVE};

/** A calm, current shared forecast for `region` in the /api/forecast shape (a test stand-in, not data). */
export function stubForecast(region, now = Date.now()) {
  const start = Math.floor(now / 1000 / HOUR) * HOUR - 8 * HOUR, time = Array.from({length: 192}, (_, i) => start + i * HOUR);
  const models = Object.fromEntries(Object.entries(MODELS).map(([id, fields]) => [id, {
    data: region.forecast_points.map(p => ({latitude: p.latitude, longitude: p.longitude, generationtime_ms: 1, utc_offset_seconds: 0, timezone: 'GMT',
      timezone_abbreviation: 'GMT', elevation: 0, hourly_units: {}, hourly: {time, ...Object.fromEntries(fields.map(f => [f, time.map(() => VALUES[f])]))}})),
    meta: {last_run_initialisation_time: start, last_run_modification_time: start + HOUR, last_run_availability_time: start + HOUR,
      data_end_time: time.at(-1), temporal_resolution_seconds: HOUR, update_interval_seconds: 6 * HOUR, provider: 'Test stand-in',
      cycle_iso: new Date(start * 1000).toISOString().replace('.000', '')},
  }]));
  return {region_id: region.id, requested_points: region.forecast_points.map(p => [p.id, p.latitude, p.longitude]), models, currents: null, retrieved: now};
}

/**
 * Answer the live feeds `page` requests with deterministic stand-ins that
 * pass the app's checks (so no fallback to a bundled snapshot is taken), and
 * the ArcGIS MPA query with the region's committed MPA snapshot, as a
 * successful live check would. Region `id` defaults to Morro Bay.
 */
export async function stubLiveFeeds(page, {id = 'morro-bay', feeds = true} = {}) {
  const read = path => JSON.parse(readFileSync(resolve(root, path), 'utf8'));
  const region = read(`dist/regions/${id}/region.json`);
  const mpas = read(`dist/${region.assets.protected_areas}`), rules = read(`dist/${region.assets.regulations}`);
  const now = () => new Date().toISOString();
  const json = (route, body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
  const head = () => ({schema_version: 1, region_id: region.id, generated_at: now(), catch_probability: null, bite_score: null});
  await page.route(url => url.hostname === 'services2.arcgis.com', route => json(route, mpas));
  if (!feeds) return;
  await page.route(url => /^\/(?:api|feeds)\//.test(url.pathname) && !url.pathname.startsWith('/api/session'), route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (path === '/api/forecast') return json(route, stubForecast(region));
    if (path === '/api/daily') {
      const part = url.searchParams.get('part');
      if (part === 'regulations') return json(route, {...head(), part, regulations: rules});
      if (part === 'mpa-boundaries') return json(route, {...head(), part, sources: {[part]: {status: 'ok', data_retrieved_at: now(), data: {geojson: mpas}}}});
      return json(route, {...head(), part, sources: {}});
    }
    if (path === '/api/habitat') return json(route, {schema_version: 1, region_id: region.id, layers: {}});
    if (path === '/api/intelligence') return json(route, {schema_version: 1, region_id: region.id, generated_at: now(), sources: {}});
    if (path.startsWith('/api/om/')) return json(route, {error: true}, 503);
    if (/^\/feeds\/conditions\/.*latest\.json$/.test(path)) return json(route, {...read('tests/fixtures/feeds/live-latest.json'), region_id: region.id, generated_at: now()});
    if (/^\/feeds\/data\/(?:regions\/[\w-]+\/)?latest\.json$/.test(path)) return json(route, {...read('tests/fixtures/feeds/daily-latest.json'), region_id: region.id});
    if (path === '/feeds/data/coastal/status.json') return json(route, {schema_version: 1, scope: 'california-coast-directory', generated_at: now(), sources: {}});
    if (path === '/feeds/data/recent-intel.json') return json(route, {schema_version: 1, generated_at: now(), candidates: [], checks: {}, health: {status: 'ok', watchlist_queries: 0}});
    return json(route, {error: 'Not stubbed'}, 404);
  });
}

/**
 * Record JSON responses while `page` opens `path`; resolves once the network
 * has been quiet for QUIET_MS after the first marker is visible.
 */
export async function measureStartup(page, {path = '/?region=morro-bay#map', timeout = 60_000} = {}) {
  const entries = [];
  let interactive = false, last = Date.now(), origin = null;
  // Requests still waiting for a response. A request counts as answered at its
  // response, not when its body finishes: a body the page never reads (a 404
  // it ignores) may never "finish". JSON bodies are awaited through `reads`.
  const reads = [], inflight = new Set();
  const settle = request => { inflight.delete(request); last = Date.now(); };
  page.on('request', request => { inflight.add(request); last = Date.now(); });
  page.on('requestfailed', settle);
  page.on('response', response => {
    settle(response.request());
    const url = response.url();
    if (!url.startsWith('http')) return;
    // The page's own origin: its document is the first response.
    if (!origin && response.request().isNavigationRequest()) origin = new URL(url).origin;
    const u = new URL(url), live = u.origin !== origin || isLive(u.pathname);
    const type = response.headers()['content-type'] || '';
    if (!isJSON(url, type) || response.status() >= 300) return;
    const before = !interactive;
    reads.push(response.body().then(body => {
      entries.push({path: u.origin === origin ? u.pathname + u.search : u.origin + u.pathname, bytes: body.length, beforeInteractive: before, live});
    }, () => {}));
  });
  const started = Date.now();
  await page.goto(path);
  await page.locator('#map .leaflet-marker-icon').first().waitFor({state: 'visible', timeout});
  interactive = true;
  const interactiveMs = Date.now() - started;
  while (Date.now() - started < timeout) {
    if (!inflight.size && Date.now() - last >= QUIET_MS) break;
    await page.waitForTimeout(250);
  }
  await Promise.all(reads);
  return {...summarise(entries), interactiveMs};
}

const kb = n => `${(n / 1024).toFixed(1)} KB`;
export function formatTable({rows, interactive, startup, interactiveMs, static: fixed, live}) {
  const width = Math.max(40, ...rows.map(r => r.path.length));
  const lines = [`${'JSON response'.padEnd(width)}  ${'size'.padStart(10)}  kind    phase`];
  for (const r of rows) lines.push(`${r.path.padEnd(width)}  ${kb(r.bytes).padStart(10)}  ${r.live ? 'live  ' : 'static'}  ${r.beforeInteractive ? 'before interactive' : 'after interactive'}${r.requests > 1 ? ` (${r.requests} requests)` : ''}`);
  lines.push('', `Static files (budgeted): ${kb(fixed)} (${fixed} bytes)`, `Live feeds (information only): ${kb(live)} (${live} bytes)`,
    `All JSON: ${kb(startup)} (${startup} bytes); before interactive (${interactiveMs} ms): ${kb(interactive)}`);
  return lines.join('\n');
}

function localChromium() {
  if (process.env.PW_CHROMIUM) return process.env.PW_CHROMIUM;
  const dir = '/opt/pw-browsers';
  if (process.env.CI || !existsSync(dir)) return undefined;
  return readdirSync(dir).filter(n => /^chromium-\d+$/.test(n)).sort().reverse()
    .map(n => `${dir}/${n}/chrome-linux/chrome`).find(p => existsSync(p));
}

async function waitFor(url, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { if ((await fetch(url)).ok) return; } catch { /* not up yet */ }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(`${url} did not answer within ${ms} ms`);
}

async function main() {
  const args = process.argv.slice(2);
  const region = args.includes('--region') ? args[args.indexOf('--region') + 1] : 'morro-bay';
  const asJSON = args.includes('--json'), stub = args.includes('--stub'), mpaOnly = args.includes('--stub-mpa');
  const port = process.env.E2E_PORT || '8787';
  let base = process.env.E2E_URL, server;
  if (!base) {
    base = `http://localhost:${port}`;
    server = spawn(process.execPath, ['e2e/serve.mjs'], {cwd: root, stdio: ['ignore', 'ignore', 'inherit'], env: {...process.env, E2E_PORT: port}});
  }
  const {chromium} = await import('@playwright/test');
  const executablePath = localChromium();
  const browser = await chromium.launch(executablePath ? {executablePath} : {});
  try {
    await waitFor(`${base}/api/health`, 120_000);
    const context = await browser.newContext({baseURL: base, viewport: {width: 390, height: 844}, serviceWorkers: 'block'});
    const origin = new URL(base).origin;
    await context.route(url => url.origin !== origin && url.protocol !== 'data:' && url.protocol !== 'blob:', route => route.abort('blockedbyclient'));
    await context.addInitScript(() => { try { localStorage.setItem('skippercast-first-run-v1', 'done'); } catch { /* storage blocked */ } });
    const page = await context.newPage();
    if (stub || mpaOnly) await stubLiveFeeds(page, {id: region, feeds: stub});
    const result = await measureStartup(page, {path: `/?region=${encodeURIComponent(region)}#map`});
    console.log(asJSON ? JSON.stringify({region, stub, ...result}, null, 1) : `Region: ${region}${stub ? ' (live feeds stubbed)' : ''}\n${formatTable(result)}`);
  } finally {
    await browser.close();
    server?.kill('SIGTERM');
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  main().catch(error => { console.error(error); process.exit(1); });
}
