#!/usr/bin/env node
// PERF-BASELINE-1 measuring script (measure only; it changes nothing).
// Loads each page in headless Chromium under a phone and a desktop profile,
// cold then warm in the same browser context, N runs, and writes every raw
// number to JSON. Throttling is Chrome DevTools Protocol emulation:
//   phone   = 412x915 @2.625, touch, CPU 4x slowdown, "slow 4G" 1.6 Mbit/s down,
//             750 kbit/s up, 150 ms RTT (Lighthouse's mobile preset)
//   desktop = 1350x940 @1, no CPU or network throttling
// Usage:
//   node reports/perf/measure.mjs --base https://skippercast.com --pages live --runs 3 --out reports/perf/raw/live.json
//   node reports/perf/measure.mjs --base http://127.0.0.1:18771 --pages layers --runs 3 --out reports/perf/raw/layers.json
// Options: --profiles phone,desktop  --only <page id,...>  --cap-ms 60000  --quiet-ms 3000
// Public-read only: one browser, one page at a time, no parallel loads.
import {writeFileSync, mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {chromium} from '@playwright/test';

const arg = (name, dflt) => { const i = process.argv.indexOf('--' + name); return i > 0 ? process.argv[i + 1] : dflt; };
const BASE = arg('base', 'https://skippercast.com');
const RUNS = +arg('runs', '3');
const OUT = arg('out', 'reports/perf/raw/out.json');
const CAP = +arg('cap-ms', '60000');
const QUIET = +arg('quiet-ms', '3000');
const PROFILE_NAMES = arg('profiles', 'phone,desktop').split(',');
const ONLY = arg('only', '') ? arg('only', '').split(',') : null;
const EXE = process.env.PW_CHROMIUM || `${process.env.HOME}/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome`;   // full Chromium, new headless mode

const HOME = {'skippercast-home-port-v1': 'morro-bay', 'skippercast-first-run-v1': 'done'};
const FIRST_RUN_DONE = {'skippercast-first-run-v1': 'done'};
const BRIEF = 'aside.app-brief, .app-sheet-brief';
const PAGESETS = {
  live: [
    {id: 'landing', path: '/', storage: {}},
    // /ports/<id> answers 404 on the live site today (checked 2026-11-07), so there is no static port page to measure.
    // A shared region link: the brief and the Chart for Morro Bay, no saved home.
    {id: 'brief', path: '/map?region=morro-bay&ui=v2', storage: FIRST_RUN_DONE, ready: BRIEF},
    // A returning user with a saved home port opening /map (the app redirects to the home).
    {id: 'map-home', path: '/map', storage: HOME, ready: BRIEF},
    // The live Chart with one rail layer at a time (layers=none is the empty-rail baseline). "swell" carries wind; "stations" carries tide.
    ...['none', 'swell', 'currents', 'stations', 'water-temp', 'chlorophyll', 'seafloor'].map(l => ({id: `live-layer-${l}`, path: `/map?region=morro-bay&ui=v2&layers=${l}`, storage: FIRST_RUN_DONE, ready: BRIEF})),
  ],
  // research/scripts/map_style test pages served by serve_range.py (private layers; local only). All at the evidence camera, zoom 9.5 off Morro Bay.
  // layers-relief: a checkout of branch claude/mapstyle-2-relief (where MAPSTYLE-3b's 2 m shallow archive and MAPLAYER-TIDE-1 were merged).
  'layers-relief': [
    ...[['layer-base-medium', 'chl=off&currents=off'], ['layer-chlorophyll', 'currents=off'], ['layer-current', 'chl=off'], ['layer-tide', 'chl=off&currents=off&tide=1'],
      ['layer-bathy-2m', 'chl=off&currents=off&tiles=/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles'],
      ['layer-bathy-2m-z12', 'chl=off&currents=off&tiles=/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles', '12&lon=-120.87&lat=35.37']]
      .map(([id, q, z]) => ({id, path: `/research/scripts/map_style/bathy-deep-test.html?picker=off&${q}&zoom=${z || '9.5&lon=-121.15&lat=35.35'}`})),
  ],
  // layers-main: origin/main, where MAPLAYER-WIND-1 and MAPLAYER-SST-1 live.
  'layers-main': [
    {id: 'layer-wind', path: '/research/scripts/map_style/wind-test.html?zoom=9.5&lon=-121.15&lat=35.35'},
    // The retained SST analysis is from 2026-09-20; the page hides a stale overlay, so the page clock is set 3 h after the analysis (Date only; timers stay real).
    {id: 'layer-sst', path: '/research/scripts/map_style/sst-test.html?zoom=9.5&lon=-121.15&lat=35.35', now: '2026-09-20T12:00:00Z'},
  ],
};
const PROFILES = {
  phone: {context: {viewport: {width: 412, height: 915}, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36'},
  cpu: 4, net: {offline: false, latency: 150, downloadThroughput: 1.6 * 1024 * 1024 / 8, uploadThroughput: 750 * 1024 / 8}},
  desktop: {context: {viewport: {width: 1350, height: 940}, deviceScaleFactor: 1}, cpu: 1, net: null},
  // The same phone on fast Wi-Fi: CPU 4x slowdown, no network throttling (shows main-thread work that slow 4G hides behind timeouts).
  'phone-wifi': {context: {viewport: {width: 412, height: 915}, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36'}, cpu: 4, net: null},
};

// Runs in every document before its scripts: paint, layout-shift and long-task observers, plus a poll for the map canvas and the brief.
const OBSERVERS = `(() => {
  const P = window.__perf = {lcp: 0, lcpEl: '', cls: 0, longtasks: [], canvasAt: null, readyAt: null, ready: __READY__};
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) { P.lcp = e.startTime; P.lcpEl = (e.element && (e.element.tagName + '.' + (e.element.className || '').toString().slice(0, 40))) || e.url || ''; } }).observe({type: 'largest-contentful-paint', buffered: true}); } catch {}
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) P.cls += e.value; }).observe({type: 'layout-shift', buffered: true}); } catch {}
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) P.longtasks.push([e.startTime, e.duration]); }).observe({type: 'longtask', buffered: true}); } catch {}
  const canvases = (root, out) => { for (const c of root.querySelectorAll('canvas')) out.push(c); for (const el of root.querySelectorAll('*')) if (el.shadowRoot) canvases(el.shadowRoot, out); return out; };
  const poll = () => {
    const now = performance.now();
    if (P.canvasAt === null && document.body) { for (const c of canvases(document, [])) { const r = c.getBoundingClientRect(); if (r.width > 150 && r.height > 150) { P.canvasAt = now; break; } } }
    if (P.ready && P.readyAt === null) { const el = document.querySelector(P.ready); if (el && /\\d/.test(el.textContent || '') && (el.textContent || '').trim().length > 80) P.readyAt = now; }
    if (now < 120000) setTimeout(poll, 50);
  };
  poll();
})();`;

function kindOf(r) {
  const u = r.url, t = r.type;
  if (/\.pmtiles(\?|$)|\/tiles\/|\.pbf(\?|$)|\.mvt(\?|$)|GetMap|tile\.openstreetmap\.org/i.test(u)) return 'tiles';
  if (t === 'Document') return 'html';
  if (t === 'Script') return 'js';
  if (t === 'Stylesheet') return 'css';
  if (t === 'Font') return 'fonts';
  if (t === 'Image') return 'images';
  if (/json/i.test(r.mime || '') || /\.json(\?|$)/.test(u)) return 'json';
  return 'other';
}

async function load(page, cdp, url, spec) {
  const reqs = new Map();
  const on = (name, fn) => { cdp.on(name, fn); return () => cdp.off(name, fn); };
  const offs = [
    on('Network.requestWillBeSent', e => { const old = reqs.get(e.requestId); const r = old || {id: e.requestId, url: e.request.url, type: e.type, start: e.timestamp, wall: e.wallTime, range: e.request.headers.Range || e.request.headers.range || null, redirects: 0};
      if (old && e.redirectResponse) { r.redirects += 1; r.url = e.request.url; } reqs.set(e.requestId, r); }),
    on('Network.responseReceived', e => { const r = reqs.get(e.requestId); if (!r) return; const h = e.response.headers || {}; const g = k => h[k] ?? h[k.toLowerCase()] ?? Object.entries(h).find(([n]) => n.toLowerCase() === k.toLowerCase())?.[1] ?? null;
      Object.assign(r, {status: e.response.status, mime: e.response.mimeType, fromCache: !!(e.response.fromDiskCache || e.response.fromServiceWorker || e.response.fromPrefetchCache), protocol: e.response.protocol,
        encoding: g('content-encoding'), cacheControl: g('cache-control'), cfCache: g('cf-cache-status'), contentLength: g('content-length'), ttfbMs: e.response.timing ? e.response.timing.receiveHeadersEnd - e.response.timing.sendStart : null}); }),
    on('Network.requestServedFromCache', e => { const r = reqs.get(e.requestId); if (r) r.fromCache = true; }),
    on('Network.dataReceived', e => { const r = reqs.get(e.requestId); if (r) r.received = (r.received || 0) + (e.encodedDataLength || 0); }),
    on('Network.loadingFinished', e => { const r = reqs.get(e.requestId); if (r) { r.end = e.timestamp; r.bytes = e.encodedDataLength; } }),
    // A stream the page cancels after reading what it needs (dist/reef-trip-data.js reads exactly export_bytes) ends as
    // net::ERR_ABORTED with no total: count what arrived.
    on('Network.loadingFailed', e => { const r = reqs.get(e.requestId); if (r) { r.end = e.timestamp; r.failed = e.errorText; r.bytes = r.received || 0; } }),
  ];
  await cdp.send('Performance.enable');
  const before = await cdp.send('Performance.getMetrics');
  let last = Date.now();
  const touch = () => { last = Date.now(); };
  cdp.on('Network.requestWillBeSent', touch); cdp.on('Network.loadingFinished', touch); cdp.on('Network.dataReceived', touch);
  const t0 = Date.now();
  await page.goto(url, {waitUntil: 'commit', timeout: CAP});
  while (Date.now() - t0 < CAP && Date.now() - last < QUIET) await page.waitForTimeout(250);
  while (Date.now() - t0 < CAP) { // wait for QUIET ms with no network activity, at most CAP
    const pending = [...reqs.values()].filter(r => r.end === undefined).length;
    if (Date.now() - last >= QUIET && pending === 0) break;
    if (Date.now() - last >= QUIET * 3) break; // long-lived requests (streams) do not hold the run
    await page.waitForTimeout(250);
  }
  const settledMs = Date.now() - t0;
  const settled = settledMs < CAP;
  cdp.off('Network.requestWillBeSent', touch); cdp.off('Network.loadingFinished', touch); cdp.off('Network.dataReceived', touch);
  const inPage = await page.evaluate(() => {
    const P = window.__perf || {};
    const nav = performance.getEntriesByType('navigation')[0];
    const fcp = performance.getEntriesByName('first-contentful-paint')[0];
    const mem = performance.memory ? {usedJSHeap: performance.memory.usedJSHeapSize, totalJSHeap: performance.memory.totalJSHeapSize} : null;
    return {timeOrigin: performance.timeOrigin, fcp: fcp ? fcp.startTime : null, lcp: P.lcp || null, lcpEl: P.lcpEl, cls: P.cls ?? null, longtasks: P.longtasks || [],
      canvasAt: P.canvasAt, readyAt: P.readyAt, url: location.href, domContentLoaded: nav ? nav.domContentLoadedEventEnd : null, loadEvent: nav ? nav.loadEventEnd : null, mem};
  });
  const after = await cdp.send('Performance.getMetrics');
  for (const off of offs) off();
  const m = (list, n) => (list.metrics.find(x => x.name === n) || {}).value || 0;
  const all = [...reqs.values()];
  // Times relative to the start of the first document request (includes a client-side redirect to the saved home).
  const firstDoc = all.filter(r => r.type === 'Document').sort((a, b) => a.start - b.start)[0];
  const tStart = firstDoc ? firstDoc.start : Math.min(...all.map(r => r.start));
  const wallStart = firstDoc ? firstDoc.wall * 1000 : inPage.timeOrigin;
  const docOffset = Math.max(0, inPage.timeOrigin - wallStart); // ms from first navigation to the final document's time origin
  const rel = x => x === null || x === undefined ? null : Math.round(x + docOffset);
  const lt = inPage.longtasks;
  // Map usable: a visible map canvas, then the first moment with 1 s free of long tasks (a TTI-style definition).
  let usable = null;
  if (inPage.canvasAt !== null) {
    let t = inPage.canvasAt;
    for (const [s, d] of [...lt].sort((a, b) => a[0] - b[0])) { if (s + d <= t) continue; if (s < t + 1000) t = Math.max(t, s + d); else break; }
    usable = t;
  }
  const tbtEnd = usable ?? (settledMs - docOffset);
  const tbt = inPage.fcp === null ? null : lt.reduce((sum, [s, d]) => (s >= inPage.fcp && s < tbtEnd) ? sum + Math.max(0, d - 50) : sum, 0);
  const requests = all.map(r => ({url: r.url, type: r.type, kind: kindOf(r), status: r.status ?? null, bytes: r.bytes ?? null, fromCache: !!r.fromCache, range: r.range, encoding: r.encoding ?? null,
    cacheControl: r.cacheControl ?? null, cfCache: r.cfCache ?? null, protocol: r.protocol ?? null, failed: r.failed ?? null,
    startMs: Math.round((r.start - tStart) * 1000), endMs: r.end === undefined ? null : Math.round((r.end - tStart) * 1000), ttfbMs: r.ttfbMs === null || r.ttfbMs === undefined ? null : Math.round(r.ttfbMs)}))
    .sort((a, b) => a.startMs - b.startMs);
  const byKind = {};
  for (const r of requests) { const k = byKind[r.kind] ||= {requests: 0, bytes: 0, fromCache: 0}; k.requests += 1; k.bytes += r.bytes || 0; if (r.fromCache) k.fromCache += 1; }
  const pm = requests.filter(r => /\.pmtiles/.test(r.url) && r.range);
  const lcpRel = rel(inPage.lcp);
  return {
    url, finalUrl: inPage.url, settled, settledMs,
    fcpMs: rel(inPage.fcp), lcpMs: lcpRel, lcpElement: inPage.lcpEl, cls: inPage.cls === null ? null : +inPage.cls.toFixed(4),
    mapCanvasMs: rel(inPage.canvasAt), mapUsableMs: rel(usable), readyMs: rel(inPage.readyAt), domContentLoadedMs: rel(inPage.domContentLoaded), loadMs: rel(inPage.loadEvent),
    clientRedirectMs: Math.round(docOffset), tbtMs: tbt === null ? null : Math.round(tbt), longTasks: lt.length, longestTaskMs: lt.length ? Math.round(Math.max(...lt.map(x => x[1]))) : 0,
    scriptMs: Math.round((m(after, 'ScriptDuration') - m(before, 'ScriptDuration')) * 1000), taskMs: Math.round((m(after, 'TaskDuration') - m(before, 'TaskDuration')) * 1000),
    layoutMs: Math.round((m(after, 'LayoutDuration') - m(before, 'LayoutDuration')) * 1000), styleMs: Math.round((m(after, 'RecalcStyleDuration') - m(before, 'RecalcStyleDuration')) * 1000),
    jsHeapUsedBytes: m(after, 'JSHeapUsedSize'), jsHeapTotalBytes: m(after, 'JSHeapTotalSize'), domNodes: m(after, 'Nodes'),
    requestCount: requests.length, bytesTotal: requests.reduce((s, r) => s + (r.bytes || 0), 0), byKind,
    requestsBeforeLcp: lcpRel === null ? null : requests.filter(r => r.startMs <= lcpRel).length,
    requestsBeforeFcp: rel(inPage.fcp) === null ? null : requests.filter(r => r.startMs <= rel(inPage.fcp)).length,
    pmtiles: {rangeRequests: pm.length, bytes: pm.reduce((s, r) => s + (r.bytes || 0), 0), fromCache: pm.filter(r => r.fromCache).length},
    heaviest: [...requests].sort((a, b) => (b.bytes || 0) - (a.bytes || 0)).slice(0, 10).map(r => ({url: r.url, kind: r.kind, bytes: r.bytes, startMs: r.startMs, endMs: r.endMs})),
    requests,
  };
}

async function main() {
  const pages = PAGESETS[arg('pages', 'live')].filter(p => !ONLY || ONLY.includes(p.id));
  const browser = await chromium.launch({executablePath: EXE, args: ['--enable-precise-memory-info', '--ignore-gpu-blocklist']});
  const out = {base: BASE, runs: RUNS, quietMs: QUIET, capMs: CAP, startedAt: new Date().toISOString(), chromium: browser.version(), argv: process.argv.slice(2), profiles: PROFILES, results: []};
  for (const prof of PROFILE_NAMES) for (const spec of pages) for (let run = 1; run <= RUNS; run++) {
    const P = PROFILES[prof];
    const context = await browser.newContext({...P.context, locale: 'en-US', timezoneId: 'America/Los_Angeles', serviceWorkers: 'block'});
    await context.addInitScript(({storage, session}) => { try { for (const [k, v] of Object.entries(storage)) localStorage.setItem(k, v); for (const [k, v] of Object.entries(session)) sessionStorage.setItem(k, v); } catch { /* storage blocked */ } },
      {storage: spec.storage || {}, session: {'skippercast-flyover-v1': '1'}});
    await context.addInitScript(OBSERVERS.replace('__READY__', JSON.stringify(spec.ready || null)));
    if (spec.now) await context.addInitScript(at => { const shift = Date.parse(at) - Date.now(), RealDate = Date;
      class ShiftedDate extends RealDate { constructor(...a) { super(...(a.length ? a : [RealDate.now() + shift])); } static now() { return RealDate.now() + shift; } }
      globalThis.Date = ShiftedDate; }, spec.now);
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Network.clearBrowserCache');
    if (P.net) await cdp.send('Network.emulateNetworkConditions', P.net);
    if (P.cpu > 1) await cdp.send('Emulation.setCPUThrottlingRate', {rate: P.cpu});
    for (const pass of ['cold', 'warm']) {
      let r;
      try { r = await load(page, cdp, BASE + spec.path, spec); }
      catch (err) { r = {error: String(err && err.message || err)}; }
      out.results.push({page: spec.id, profile: prof, pass, run, ...r});
      mkdirSync(dirname(OUT), {recursive: true}); writeFileSync(OUT, JSON.stringify(out, null, 1));   // progress survives a crash
      console.log(`${prof} ${spec.id} ${pass} #${run}: fcp=${r.fcpMs} lcp=${r.lcpMs} usable=${r.mapUsableMs} ready=${r.readyMs} tbt=${r.tbtMs} cls=${r.cls} req=${r.requestCount} bytes=${r.bytesTotal} settled=${r.settled}${r.error ? ' ERROR ' + r.error : ''}`);
      if (pass === 'cold') await page.goto('about:blank');
    }
    await context.close();
  }
  await browser.close();
  out.finishedAt = new Date().toISOString();
  mkdirSync(dirname(OUT), {recursive: true});
  writeFileSync(OUT, JSON.stringify(out, null, 1));
  console.log('wrote', OUT);
}
main().catch(err => { console.error(err); process.exit(1); });
