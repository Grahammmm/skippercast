#!/usr/bin/env node
// SC-PERF-REEFDIET-1: browser measurement of the reef-data load, full export vs slim file, with PERF-BASELINE-1's profiles
// (reports/perf/measure.mjs): full Chromium (new headless), CDP emulation, a fresh context per run (cold), long tasks from a
// PerformanceObserver and an input-responsiveness probe (a timer every 50 ms, lag = how late it fired).
// This loads the page's real loader (dist/reef-trip-data.js) against a local copy of the published files; it is NOT the whole app page
// (the slim file is unpublished, so a live page cannot request it). Node timings are a different measurement and are not mixed in here.
// Usage: node scripts/reef_slim_browser.mjs <dir with manifest.json + habitat-export.geojson.gz + habitat-slim-<sha16>.geojson.gz> [--runs 3] [--out file.json]
import {createServer} from 'node:http';
import {readFileSync, writeFileSync, existsSync} from 'node:fs';
import {extname, join, normalize} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i > 0 ? process.argv[i + 1] : d; };
const ROOT = fileURLToPath(new URL('..', import.meta.url));
const PROFILES = {
  phone: {context: {viewport: {width: 412, height: 915}, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true}, cpu: 4,
    net: {offline: false, latency: 150, downloadThroughput: 1.6 * 1024 * 1024 / 8, uploadThroughput: 750 * 1024 / 8}},
  'phone-wifi': {context: {viewport: {width: 412, height: 915}, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true}, cpu: 4, net: null},
  desktop: {context: {viewport: {width: 1350, height: 940}, deviceScaleFactor: 1}, cpu: 1, net: null},
};
const TYPES = {'.js': 'text/javascript', '.html': 'text/html', '.json': 'application/json'};
function fixtureServer(data) {
  const manifest = readFileSync(join(data, 'manifest.json'));
  return createServer((req, res) => {
    const path = decodeURIComponent(req.url.split('?')[0]);
    if (path === '/blank.html') { res.setHeader('content-type', 'text/html'); return res.end('<!doctype html><title>x</title>'); }
    if (path.startsWith('/feeds/tiles/seafloor/manifest-')) { res.setHeader('content-type', 'application/json'); res.setHeader('cache-control', 'no-store'); return res.end(manifest); }
    if (path.startsWith('/feeds/tiles/seafloor/regions/')) {
      const file = join(data, path.split('/').at(-1));
      if (!existsSync(file)) { res.statusCode = 404; return res.end(); }
      res.setHeader('content-type', 'application/gzip'); res.setHeader('cache-control', 'no-store'); return res.end(readFileSync(file));
    }
    const file = normalize(join(ROOT, path));
    if (!file.startsWith(join(ROOT, 'dist')) || !existsSync(file)) { res.statusCode = 404; return res.end(); }
    res.setHeader('content-type', TYPES[extname(file)] || 'application/octet-stream'); res.end(readFileSync(file));
  });
}

const inPage = async slim => {
  const lags = [], long = [];
  new PerformanceObserver(l => { for (const e of l.getEntries()) long.push(e.duration); }).observe({type: 'longtask', buffered: true});
  let last = performance.now(), stop = false;
  (function tick() { if (stop) return; const n = performance.now(); lags.push(n - last - 50); last = n; setTimeout(tick, 50); })();
  const {loadReefTripBrief, loadReefTrip} = await import('/dist/reef-trip-data.js');
  const t0 = performance.now();
  let outcome = 'ok', targets = 0, usedSlim = null;
  try {
    const got = await (slim ? loadReefTripBrief : loadReefTrip)('morro-bay');
    targets = got.targets.length; usedSlim = got.slim === true;
  } catch (e) { outcome = String(e.message || e); }
  const ms = performance.now() - t0;
  await new Promise(r => setTimeout(r, 300));
  stop = true;
  const files = performance.getEntriesByType('resource').filter(e => e.name.includes('/regions/')).map(e => ({file: e.name.split('/').at(-1), transfer: e.transferSize, encoded: e.encodedBodySize}));
  return {outcome, load_ms: Math.round(ms), targets, usedSlim, longTaskCount: long.length, longTaskMs: Math.round(long.reduce((a, b) => a + b, 0)),
    longestMs: Math.round(Math.max(0, ...long)), maxTimerLagMs: Math.round(Math.max(0, ...lags)), files};
};

/** Playwright's evaluate has no timeout. The caller closes the context even after a deadline. */
export async function captureReefRun(page, variant, timeout = 180_000) {
  let timer;
  try {
    return await Promise.race([
      page.evaluate(`(${inPage.toString()})(${variant === 'slim'})`),
      new Promise(resolve => { timer = setTimeout(() => resolve({outcome: 'timeout', usedSlim: null}), timeout); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

const med = a => [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)];

/** Summarize one profile/variant cohort without borrowing a fallback or a failed load. */
export function summariseReefRuns(runs, variant) {
  const good = runs.filter(r => r.outcome === 'ok' && r.usedSlim === (variant === 'slim'));
  const counts = {comparable: good.length > 0, included: good.length, excluded: runs.length - good.length};
  if (!counts.comparable) return {...counts, load_ms: null};
  return {...counts, load_ms: med(good.map(r => r.load_ms)), longTaskMs: med(good.map(r => r.longTaskMs)),
    longestMs: med(good.map(r => r.longestMs)), maxTimerLagMs: med(good.map(r => r.maxTimerLagMs)),
    transfer: good[0].files.map(f => `${f.file}:${f.transfer}`).join(',')};
}

async function main() {
  const data = process.argv[2], runs = +arg('runs', '3'), out = arg('out', '');
  const executablePath = process.env.PW_CHROMIUM || `${process.env.HOME}/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome`;
  const {chromium} = await import('@playwright/test');
  const server = fixtureServer(data);
  let browser;
  const results = [];
  try {
    await new Promise(r => server.listen(0, '127.0.0.1', r));
    const base = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({executablePath, headless: true});
    for (const [profile, p] of Object.entries(PROFILES)) for (const variant of ['full', 'slim']) {
      for (let run = 1; run <= runs; run++) {
        const context = await browser.newContext(p.context);
        let capture;
        try {
          const page = await context.newPage();
          const cdp = await context.newCDPSession(page);
          await page.goto(`${base}/blank.html`);
          if (p.cpu > 1) await cdp.send('Emulation.setCPUThrottlingRate', {rate: p.cpu});
          if (p.net) await cdp.send('Network.emulateNetworkConditions', p.net);
          capture = await captureReefRun(page, variant);
        } catch (error) {
          capture = {outcome: error.name === 'TimeoutError' ? 'timeout' : 'error', error: String(error.message || error), usedSlim: null};
        } finally {
          await context.close();
        }
        const result = {profile, variant, run, ...capture};
        results.push(result);
        console.log(JSON.stringify(result));
      }
    }
  } finally {
    server.close();
    await browser?.close();
  }
  console.log('\nmedians (successful matching runs only)');
  for (const profile of Object.keys(PROFILES)) for (const variant of ['full', 'slim']) {
    const summary = summariseReefRuns(results.filter(r => r.profile === profile && r.variant === variant), variant);
    if (!summary.comparable) process.exitCode = 1;
    console.log(profile, variant, summary.comparable ? 'comparable' : 'inconclusive', JSON.stringify(summary));
  }
  if (out) writeFileSync(out, JSON.stringify(results, null, 1));
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  main().catch(error => { console.error(error); process.exitCode = 1; });
}
