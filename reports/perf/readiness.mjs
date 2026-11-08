#!/usr/bin/env node
// PERF-BASELINE-1 readiness harness (round 2). Replaces measure.mjs's "map usable" (a large canvas followed by a
// quiet main thread) with criteria that a blank canvas cannot satisfy. It records, per load:
//   * a CDP screencast (JPEG frames with wall-clock timestamps), saved to disk; analyse.py decides from the pixels
//     of the map canvas when the map is PAINTED (not a flat colour), when it stops changing (VISUALLY COMPLETE),
//     and, with the layer-off page as reference, whether an enabled layer visibly changed the picture;
//   * every request (start, end, status, bytes, failure), so analyse.py can say when the data of the enabled layer
//     (requests that the layer-off page does not make) had fully arrived, or failed;
//   * a synthetic INTERACTION PROBE after the load settles: a 60 px drag on the map canvas (mouse on desktop, touch on
//     the phone) and the time until the canvas pixels respond; none within 5 s is recorded as a failure;
//   * long tasks, FCP/LCP, the visible error/unavailable text, page errors, and CDP Performance.getMetrics with the
//     `Timestamp` metric sampled at both ends, so a CPU duty cycle uses the same window as its ScriptDuration delta.
// The screencast costs CPU, so these runs are NOT the A.3 timing baseline (measure.mjs); both are reported.
// Usage:
//   node reports/perf/readiness.mjs --base https://skippercast.com --pages live --profiles desktop,phone --runs 3 --out reports/perf/raw/ready-live.json --frames /tmp/frames
//   node reports/perf/readiness.mjs --probe-blank   # self-test: a blank canvas must NOT be reported painted/usable
import {writeFileSync, mkdirSync, readdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {chromium} from '@playwright/test';

const arg = (name, dflt) => { const i = process.argv.indexOf('--' + name); return i > 0 ? process.argv[i + 1] : dflt; };
const flag = name => process.argv.includes('--' + name);
const BASE = arg('base', 'https://skippercast.com');
const RUNS = +arg('runs', '3');
const OUT = arg('out', 'reports/perf/raw/ready.json');
const FRAMES = arg('frames', 'reports/perf/frames');
// Every acquisition has its own frame namespace (the batch label, default: the --out file name), so a later batch can never overwrite
// the frames of an earlier one (round 1b: six cold runs of ready-live-desktop.json lost their frames to ready-live-desktop-warm.json).
const BATCH = arg('batch', OUT.split('/').pop().replace(/\.json$/, ''));
const CAP = +arg('cap-ms', '90000');
const QUIET = +arg('quiet-ms', '3000');
const PROFILE_NAMES = arg('profiles', 'phone,desktop').split(',');
const PASSES = arg('passes', 'cold').split(',');
const ONLY = arg('only', '') ? arg('only', '').split(',') : null;
const EXE = process.env.PW_CHROMIUM || `${process.env.HOME}/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome`;

const HOME = {'skippercast-home-port-v1': 'morro-bay', 'skippercast-first-run-v1': 'done'};
const FIRST_RUN_DONE = {'skippercast-first-run-v1': 'done'};
const BRIEF = 'aside.app-brief, .app-sheet-brief';
const live = [
  {id: 'brief', path: '/map?region=morro-bay&ui=v2', storage: FIRST_RUN_DONE, ready: BRIEF},
  // map-home-returning: a saved home port AND a saved fishing profile (skippercast-profile-v1), as a returning visitor has; A.3's map-home had no profile, so the first-visit "How do you fish?" dialog was open.
  {id: 'map-home-returning', path: '/map', storage: {...HOME, 'skippercast-profile-v1': 'boat'}, ready: BRIEF},
  ...['none', 'swell', 'currents', 'stations', 'water-temp', 'chlorophyll', 'seafloor'].map(l => ({id: `live-layer-${l}`, path: `/map?region=morro-bay&ui=v2&layers=${l}`, storage: FIRST_RUN_DONE, ready: BRIEF})),
];
const relief = [['layer-base-medium', 'chl=off&currents=off'], ['layer-chlorophyll', 'currents=off'], ['layer-current', 'chl=off'], ['layer-tide', 'chl=off&currents=off&tide=1'],
  ['layer-bathy-2m', 'chl=off&currents=off&tiles=/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles'],
  ['layer-bathy-2m-z12', 'chl=off&currents=off&tiles=/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles', '12&lon=-120.87&lat=35.37']]
  .map(([id, q, z]) => ({id, path: `/research/scripts/map_style/bathy-deep-test.html?picker=off&${q}&zoom=${z || '9.5&lon=-121.15&lat=35.35'}`}));
const mainLayers = [
  {id: 'layer-wind', path: '/research/scripts/map_style/wind-test.html?zoom=9.5&lon=-121.15&lat=35.35'},
  {id: 'layer-sst', path: '/research/scripts/map_style/sst-test.html?zoom=9.5&lon=-121.15&lat=35.35', now: '2026-09-20T12:00:00Z'},
];
const PAGESETS = {live, 'layers-relief': relief, 'layers-main': mainLayers};
const UA = 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36';
const PROFILES = {
  phone: {context: {viewport: {width: 412, height: 915}, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true, userAgent: UA}, cpu: 4,
    net: {offline: false, latency: 150, downloadThroughput: 1.6 * 1024 * 1024 / 8, uploadThroughput: 750 * 1024 / 8}, cast: {maxWidth: 412, maxHeight: 915}},
  desktop: {context: {viewport: {width: 1350, height: 940}, deviceScaleFactor: 1}, cpu: 1, net: null, cast: {maxWidth: 675, maxHeight: 470}},
  'phone-wifi': {context: {viewport: {width: 412, height: 915}, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true, userAgent: UA}, cpu: 4, net: null, cast: {maxWidth: 412, maxHeight: 915}},
};

const OBSERVERS = `(() => {
  const P = window.__perf = {lcp: 0, cls: 0, longtasks: [], readyAt: null, ready: __READY__};
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) P.lcp = e.startTime; }).observe({type: 'largest-contentful-paint', buffered: true}); } catch {}
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) P.cls += e.value; }).observe({type: 'layout-shift', buffered: true}); } catch {}
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) P.longtasks.push([e.startTime, e.duration]); }).observe({type: 'longtask', buffered: true}); } catch {}
  // input delay: time from the browser receiving a probe event (event.timeStamp) to the page's capture handler running
  P.inputDelays = [];
  for (const type of ['pointermove', 'pointerdown']) window.addEventListener(type, e => { if (e.isTrusted) P.inputDelays.push([performance.now(), performance.now() - e.timeStamp]); }, {capture: true, passive: true});
  const poll = () => { const now = performance.now();
    if (P.ready && P.readyAt === null) { const el = document.querySelector(P.ready); if (el && /\\d/.test(el.textContent || '') && (el.textContent || '').trim().length > 80) P.readyAt = now; }
    if (now < 150000) setTimeout(poll, 100); };
  poll();
})();`;

// The largest canvas on the page (also inside open shadow roots), in CSS px; plus visible text that says something failed.
const PAGE_FACTS = () => {
  const out = [];
  const walk = root => { for (const c of root.querySelectorAll('canvas')) out.push(c); for (const el of root.querySelectorAll('*')) if (el.shadowRoot) walk(el.shadowRoot); };
  walk(document);
  let best = null;
  for (const c of out) { const r = c.getBoundingClientRect(); const a = r.width * r.height; if (!best || a > best.a) best = {a, x: r.left, y: r.top, w: r.width, h: r.height, cls: String(c.className || '').slice(0, 40)}; }
  const text = (document.body ? document.body.innerText : '').split('\n').map(s => s.trim()).filter(s => /unavailable|failed|couldn.t|could not|error|not available|try again|offline/i.test(s) && s.length < 160).slice(0, 8);
  // A point on the map that is really the map (not under a dialog, panel or control): nearest the canvas centre.
  let point = null, coverAtCentre = '';
  if (best) {
    const cx = best.x + best.w / 2, cy = best.y + best.h / 2;
    const top = document.elementFromPoint(cx, cy);
    coverAtCentre = top ? (top.tagName + '.' + String(top.className && top.className.baseVal !== undefined ? top.className.baseVal : top.className || '').slice(0, 50)) : '';
    const cand = [];
    for (let i = 1; i <= 9; i++) for (let j = 1; j <= 9; j++) cand.push([best.x + best.w * i / 10, best.y + best.h * j / 10]);
    cand.sort((a, b) => Math.hypot(a[0] - cx, a[1] - cy) - Math.hypot(b[0] - cx, b[1] - cy));
    for (const [x, y] of cand) {
      if (x < 0 || y < 0 || x + 70 > innerWidth || y > innerHeight) continue;
      const el = document.elementFromPoint(x, y), el2 = document.elementFromPoint(x + 60, y);
      const isMap = e => e && (e.tagName === 'CANVAS' || (e.closest && e.closest('.maplibregl-canvas-container, .maplibregl-map, [data-map]')));
      if (isMap(el) && isMap(el2)) { point = [x, y]; break; }
    }
  }
  return {canvas: best, canvases: out.length, messages: text, point, coverAtCentre};
};

async function load(browser, P, spec, pass, ctxHolder, id) {
  const {page, cdp, context} = ctxHolder;
  const reqs = new Map();
  const on = (name, fn) => { cdp.on(name, fn); return () => cdp.off(name, fn); };
  const offs = [
    on('Network.requestWillBeSent', e => { const old = reqs.get(e.requestId); const r = old || {id: e.requestId, url: e.request.url, type: e.type, start: e.timestamp, wall: e.wallTime, range: e.request.headers.Range || e.request.headers.range || null};
      if (old && e.redirectResponse) r.url = e.request.url; reqs.set(e.requestId, r); }),
    on('Network.responseReceived', e => { const r = reqs.get(e.requestId); if (r) Object.assign(r, {status: e.response.status, mime: e.response.mimeType, fromCache: !!(e.response.fromDiskCache || e.response.fromServiceWorker || e.response.fromPrefetchCache)}); }),
    on('Network.requestServedFromCache', e => { const r = reqs.get(e.requestId); if (r) r.fromCache = true; }),
    on('Network.dataReceived', e => { const r = reqs.get(e.requestId); if (r) r.received = (r.received || 0) + (e.encodedDataLength || 0); }),
    on('Network.loadingFinished', e => { const r = reqs.get(e.requestId); if (r) { r.end = e.timestamp; r.bytes = e.encodedDataLength; } }),
    on('Network.loadingFailed', e => { const r = reqs.get(e.requestId); if (r) { r.end = e.timestamp; r.failed = e.errorText; r.bytes = r.received || 0; } }),
  ];
  const frames = [];
  const dir = join(FRAMES, id); mkdirSync(dir, {recursive: true});
  if (readdirSync(dir).length) throw new Error(`frame directory ${dir} is not empty: refusing to overwrite earlier evidence`);
  const onFrame = async e => {
    const n = frames.length; frames.push({n, t: e.metadata.timestamp, recv: Date.now()});
    writeFileSync(join(dir, String(n).padStart(4, '0') + '.jpg'), Buffer.from(e.data, 'base64'));
    try { await cdp.send('Page.screencastFrameAck', {sessionId: e.sessionId}); } catch {}
  };
  cdp.on('Page.screencastFrame', onFrame);
  const errors = [];
  const onErr = e => errors.push(String(e && e.message || e).slice(0, 160));
  page.on('pageerror', onErr);
  await cdp.send('Performance.enable');
  const before = await cdp.send('Performance.getMetrics');
  let last = Date.now();
  const touch = () => { last = Date.now(); };
  cdp.on('Network.requestWillBeSent', touch); cdp.on('Network.loadingFinished', touch); cdp.on('Network.dataReceived', touch);
  await cdp.send('Page.startScreencast', {format: 'jpeg', quality: 60, everyNthFrame: 1, ...P.cast});
  const t0 = Date.now();
  await page.goto(BASE + spec.path, {waitUntil: 'commit', timeout: CAP});
  // Input-delay probe: once a second, a harmless pointer event in the top-left corner (a mouse move on desktop, a touch tap on the phone);
  // the page-side capture listener records how long each waited behind the main thread. The call itself also blocks until handled.
  let stopProbe = false;
  const sent = [];
  const probeLoop = (async () => {
    while (!stopProbe) {
      try {
        const t = Date.now();
        if (P.context.hasTouch) { await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: 2, y: 2}]}); await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []}); }
        else await cdp.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 2 + (sent.length % 5), y: 2});
        sent.push([t - t0, Date.now() - t]);
      } catch { /* navigating */ }
      await page.waitForTimeout(1000);
    }
  })();
  while (Date.now() - t0 < CAP && Date.now() - last < QUIET) await page.waitForTimeout(250);
  while (Date.now() - t0 < CAP) {
    const pending = [...reqs.values()].filter(r => r.end === undefined).length;
    if (Date.now() - last >= QUIET && pending === 0) break;
    if (Date.now() - last >= QUIET * 3) break;
    await page.waitForTimeout(250);
  }
  const settledMs = Date.now() - t0;   // the network has been quiet; the main thread may still be busy
  // keep probing until the page answers two probes in a row within 200 ms (the INP "good" bound), at most until CAP
  while (Date.now() - t0 < CAP) { const l = sent.slice(-2); if (l.length === 2 && l.every(x => x[1] <= 200) && l[1][0] + t0 > t0 + settledMs - 1500) break; await page.waitForTimeout(250); }
  const responsiveWaitMs = Date.now() - t0 - settledMs;
  stopProbe = true; await probeLoop;
  cdp.off('Network.requestWillBeSent', touch); cdp.off('Network.loadingFinished', touch); cdp.off('Network.dataReceived', touch);
  // metrics at the end of the observation window (before anything that waits behind the main thread)
  const after = await cdp.send('Performance.getMetrics');
  const facts = await page.evaluate(PAGE_FACTS);
  const inPage = await page.evaluate(() => { const p = window.__perf || {}; const fcp = performance.getEntriesByName('first-contentful-paint')[0];
    return {timeOrigin: performance.timeOrigin, fcp: fcp ? fcp.startTime : null, lcp: p.lcp || null, cls: p.cls ?? null, longtasks: p.longtasks || [], readyAt: p.readyAt, inputDelays: p.inputDelays || [], url: location.href}; });
  // interaction probe: drag the map 60 px and see whether the canvas pixels respond
  const probe = {done: false};
  if (facts.canvas && facts.canvas.w > 100) {
    const c = facts.canvas; probe.point = facts.point; probe.coverAtCentre = facts.coverAtCentre;
    if (!facts.point) probe.covered = true;
    const [cx, cy] = facts.point || [c.x + c.w / 2, c.y + c.h / 2];
    const nFrames = frames.length;
    probe.tInput = Date.now();
    try {
      if (P.context.hasTouch) {
        await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: cx, y: cy}]});
        for (let i = 1; i <= 6; i++) { await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: cx + 10 * i, y: cy}]}); await page.waitForTimeout(16); }
        await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
      } else {
        await cdp.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: cx, y: cy});
        await cdp.send('Input.dispatchMouseEvent', {type: 'mousePressed', x: cx, y: cy, button: 'left', clickCount: 1});
        for (let i = 1; i <= 6; i++) { await cdp.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: cx + 10 * i, y: cy, button: 'left', buttons: 1}); await page.waitForTimeout(16); }
        await cdp.send('Input.dispatchMouseEvent', {type: 'mouseReleased', x: cx + 60, y: cy, button: 'left', clickCount: 1});
      }
      probe.done = true;
    } catch (err) { probe.error = String(err.message || err).slice(0, 120); }
    probe.firstFrameAfter = nFrames;
    await page.waitForTimeout(5000);   // frames keep arriving; analyse.py finds the first that differs
  }
  await cdp.send('Page.stopScreencast');
  await page.waitForTimeout(200);
  cdp.off('Page.screencastFrame', onFrame);
  page.off('pageerror', onErr);
  for (const off of offs) off();
  const all = [...reqs.values()];
  const firstDoc = all.filter(r => r.type === 'Document').sort((a, b) => a.start - b.start)[0];
  const tStart = firstDoc ? firstDoc.start : Math.min(...all.map(r => r.start));
  const wallStartMs = (firstDoc ? firstDoc.wall : all[0].wall) * 1000;
  const m = (list, n) => (list.metrics.find(x => x.name === n) || {}).value || 0;
  return {
    url: BASE + spec.path, finalUrl: inPage.url, id, settledMs, responsiveWaitMs, wallStartMs, timeOrigin: inPage.timeOrigin, probe,
    fcp: inPage.fcp, lcp: inPage.lcp, inputDelays: inPage.inputDelays, probeSent: sent, cls: inPage.cls, longtasks: inPage.longtasks, readyAt: inPage.readyAt, canvas: facts.canvas, canvases: facts.canvases, messages: facts.messages, pageErrors: errors.slice(0, 6),
    frames, cast: P.cast, viewport: P.context.viewport,
    cpu: {windowS: m(after, 'Timestamp') - m(before, 'Timestamp'), scriptS: m(after, 'ScriptDuration') - m(before, 'ScriptDuration'), taskS: m(after, 'TaskDuration') - m(before, 'TaskDuration')},
    requests: all.map(r => ({url: r.url.startsWith('data:') ? r.url.slice(0, 64) : r.url, data: r.url.startsWith('data:'), kindType: r.type, status: r.status ?? null, bytes: r.bytes ?? null, fromCache: !!r.fromCache, failed: r.failed ?? null, range: r.range,
      startMs: Math.round((r.start - tStart) * 1000), endMs: r.end === undefined ? null : Math.round((r.end - tStart) * 1000)})).sort((a, b) => a.startMs - b.startMs),
  };
}

async function selfTestBlank() {
  // A page whose only content is a large blank canvas: no analysis may call it painted. Writes frames for analyse.py --blank.
  const browser = await chromium.launch({executablePath: EXE});
  const context = await browser.newContext({viewport: {width: 1350, height: 940}});
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  const dir = join(FRAMES, 'blank'); mkdirSync(dir, {recursive: true});
  const frames = [];
  cdp.on('Page.screencastFrame', async e => { frames.push({n: frames.length, t: e.metadata.timestamp}); writeFileSync(join(dir, String(frames.length - 1).padStart(4, '0') + '.jpg'), Buffer.from(e.data, 'base64')); try { await cdp.send('Page.screencastFrameAck', {sessionId: e.sessionId}); } catch {} });
  await cdp.send('Page.startScreencast', {format: 'jpeg', quality: 60, everyNthFrame: 1, maxWidth: 675, maxHeight: 470});
  await page.setContent('<body style="margin:0"><canvas style="width:1350px;height:940px;background:#cfe3f0"></canvas></body>');
  await page.waitForTimeout(2500);
  const facts = await page.evaluate(PAGE_FACTS);
  await cdp.send('Page.stopScreencast');
  await browser.close();
  writeFileSync(join(dir, 'blank.json'), JSON.stringify({frames, canvas: facts.canvas, cast: {maxWidth: 675, maxHeight: 470}, viewport: {width: 1350, height: 940}}));
  console.log('blank self-test frames:', frames.length, JSON.stringify(facts.canvas));
}

async function main() {
  if (flag('probe-blank')) return selfTestBlank();
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
    await cdp.send('Network.enable'); await cdp.send('Page.enable');
    await cdp.send('Network.clearBrowserCache');
    if (P.net) await cdp.send('Network.emulateNetworkConditions', P.net);
    if (P.cpu > 1) await cdp.send('Emulation.setCPUThrottlingRate', {rate: P.cpu});
    for (const pass of PASSES) {
      let r; const id = `${BATCH}.${prof}-${spec.id}-${pass}-${run}`;
      try { r = await load(browser, P, spec, pass, {page, cdp, context}, id); } catch (err) { r = {error: String(err && err.message || err), id}; }
      out.results.push({page: spec.id, profile: prof, pass, run, ...r});
      mkdirSync(dirname(OUT), {recursive: true}); writeFileSync(OUT, JSON.stringify(out));
      console.log(`${id}: settled=${r.settledMs} frames=${r.frames ? r.frames.length : 0} cpu=${r.cpu ? JSON.stringify(r.cpu) : ''}${r.error ? ' ERROR ' + r.error : ''}`);
      if (pass === 'cold' && PASSES.includes('warm')) await page.goto('about:blank');
    }
    await context.close();
  }
  await browser.close();
  out.finishedAt = new Date().toISOString();
  writeFileSync(OUT, JSON.stringify(out));
  console.log('wrote', OUT);
}
main().catch(err => { console.error(err); process.exit(1); });
