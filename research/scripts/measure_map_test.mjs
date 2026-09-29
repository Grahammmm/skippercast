#!/usr/bin/env node
// Measure the map-engine test pages on a simulated phone.
//   node research/scripts/measure_map_test.mjs http://localhost:8787 [runs]
// Base-map raster tiles (OpenStreetMap, NOAA chart) are replaced by a blank tile so only the
// engine and the habitat layer are measured; both pages use the same bases.
// CPU is throttled 4x (a mid-range phone); transfer sizes are reported rather
// than simulated network time (CDP network emulation stalls routed requests). Headless
// Chromium renders WebGL in software (SwiftShader), which penalizes MapLibre;
// a real phone GPU will do better than these numbers.
import {chromium} from 'playwright';

const base = process.argv[2] || 'http://localhost:8787';
const runs = Number(process.argv[3] || 3);
const PAGES = {leaflet: '/map-test-leaflet.html', maplibre: '/map-test.html'};
const category = url => /vendor\/(leaflet|maplibre|pmtiles)/.test(url) ? 'library'
  : /atlas\.json|\.pmtiles|survey-habitat/.test(url) ? 'layer' : /map-test/.test(url) ? 'page' : 'other';
const BLANK_PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');
const median = values => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];

async function once(browser, engine, extra = '') {
  const context = await browser.newContext({viewport: {width: 390, height: 844}, deviceScaleFactor: 2});
  const page = await context.newPage();
  // Same blank base tile for both engines (aborted tiles keep MapLibre from reaching idle).
  await page.route(/tile\.openstreetmap\.org|charttools\.noaa\.gov/, route => route.fulfill({status: 200, contentType: 'image/png', body: BLANK_PNG}));
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', {rate: 4});
  await cdp.send('Network.enable');
  const bytes = {library: 0, layer: 0, page: 0, other: 0};
  let rangeRequests = 0;
  cdp.on('Network.loadingFinished', event => { const url = urls.get(event.requestId); if (url) bytes[category(url)] += event.encodedDataLength; });
  const urls = new Map();
  cdp.on('Network.requestWillBeSent', event => { urls.set(event.requestId, event.request.url); if ((event.request.headers.Range || event.request.headers.range)) rangeRequests++; });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  const start = Date.now();
  await page.goto(base + PAGES[engine] + extra, {waitUntil: 'load'});
  await page.waitForFunction(() => window.__mapTest, null, {timeout: 120000});
  const ready = Date.now() - start;
  const firstLayerBytes = bytes.layer;
  // Interaction: 12 pans of 150 px and a zoom 13 -> 15 -> 11 -> 13, logging frame intervals.
  await page.evaluate(() => {
    window.__frames = []; let last = performance.now();
    const tick = now => { window.__frames.push(now - last); last = now; if (!window.__stop) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  });
  const interactionStart = Date.now();
  for (let i = 0; i < 12; i++) {
    await page.evaluate(([x, y]) => window.__map.panBy(x, y), [i % 2 ? -150 : 150, i % 3 ? 90 : -90]);
    await page.evaluate(() => window.__map.idle());
  }
  for (const z of [14, 15, 12, 11, 13]) {
    await page.evaluate(zoom => window.__map.jumpTo(null, null, zoom), z);
    await page.evaluate(() => window.__map.idle());
  }
  const interactionMs = Date.now() - interactionStart;
  const frames = await page.evaluate(() => { window.__stop = true; return window.__frames.slice(1); });
  const sorted = [...frames].sort((a, b) => a - b);
  const result = {ready_ms: ready, reefs_in_view: (await page.evaluate(() => window.__mapTest)).reefs,
    library_kb: Math.round(bytes.library / 1000), layer_kb_first_view: Math.round(firstLayerBytes / 1000),
    layer_kb_after_panning: Math.round(bytes.layer / 1000), range_requests: rangeRequests,
    interaction_ms: interactionMs, p95_frame_ms: Math.round(sorted[Math.floor(sorted.length * 0.95)] || 0),
    long_frames_over_50ms: frames.filter(f => f > 50).length, errors: errors.length};
  await context.close();
  return result;
}

const browser = await chromium.launch({args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
const extra = process.argv[4] ? '?' + process.argv[4] : '';
const summary = {};
for (const engine of Object.keys(PAGES)) {
  const results = [];
  for (let i = 0; i < runs; i++) results.push(await once(browser, engine, extra));
  summary[engine] = Object.fromEntries(Object.keys(results[0]).map(k => [k, median(results.map(r => r[k]))]));
}
await browser.close();
console.log(JSON.stringify(summary, null, 1));
