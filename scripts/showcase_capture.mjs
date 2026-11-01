#!/usr/bin/env node
// Browser side of scripts/showcase.py, using the repository's Playwright Chromium. Two modes:
//
// Capture: node scripts/showcase_capture.mjs job.json, where job.json is {base_url, out_dir, root, now (ISO),
//   seed, tolerance, color_scheme?, timezone?, setup?, local_storage?, session_storage?, pages: [{id, path,
//   viewport ('phone' | 'laptop' | {width, height}), full_page?, mobile?, wait_for?, actions?, settle_ms?,
//   local_storage?, session_storage?}]}. `setup` names a module (relative to this repository) whose default
//   export `async (context, {root, now, baseURL, here})` installs the repository's own network stubs; `root` is
//   the checkout being captured, so the stubs read that revision's data. Writes <id>.png and results.json.
// Compare: node scripts/showcase_capture.mjs job.json, where job.json is {compare: [{id, before, after}], out,
//   tolerance}; writes [{id, changed, exact, total, width, height, box}] to `out`.
//
// Frozen for every page: Date (page.clock.setFixedTime; timers keep running), Math.random (seeded), CSS
// animations and transitions, scrollbars, the text caret, reduced motion on, and every origin other than
// base_url (aborted, so no live service, tile or image decides a pixel). A load is kept once two frames in a
// row are identical, and each page is loaded fresh until two loads in a row give the same picture (within
// `tolerance`); a page that never repeats is reported as unsteady rather than silently kept.
import {mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {chromium} from '@playwright/test';

const job = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const here = resolve(import.meta.dirname, '..');
const VIEWPORTS = {phone: {width: 390, height: 844}, laptop: {width: 1280, height: 800}};
const FREEZE_CSS = `*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;animation-iteration-count:1!important;
transition:none!important;caret-color:transparent!important;scroll-behavior:auto!important;scrollbar-width:none!important}
::-webkit-scrollbar{display:none!important}`;
const LOADS = 4;   // fresh loads per page at most, until two in a row agree
const tolerance = job.tolerance ?? 0;
// Same binary rule as playwright.config.ts: PW_CHROMIUM when set, else Playwright's own Chromium.
const browser = await chromium.launch(process.env.PW_CHROMIUM ? {executablePath: process.env.PW_CHROMIUM} : {});
const differ = await browser.newPage();

/**
 * Pixel difference of two PNGs, decoded in a canvas (no image library needed). A pixel has changed when any
 * channel differs by more than `tolerance` levels out of 255; `exact` counts every pixel that differs at all; a
 * size difference counts the uncovered area as changed. Width, height and box are in the after image's pixels.
 */
async function diff(before, after) {
  const url = png => `data:image/png;base64,${png.toString('base64')}`;
  return differ.evaluate(async ([a, b, tolerance]) => {
    const load = src => new Promise((ok, fail) => { const i = new Image(); i.onload = () => ok(i); i.onerror = fail; i.src = src; });
    const [p0, q0] = await Promise.all([load(a), load(b)]);
    const width = Math.max(p0.width, q0.width), height = Math.max(p0.height, q0.height);
    const pixels = image => { const c = new OffscreenCanvas(width, height), g = c.getContext('2d'); g.drawImage(image, 0, 0); return g.getImageData(0, 0, width, height).data; };
    const p = pixels(p0), q = pixels(q0);
    const CELL = 16, cols = Math.ceil(width / CELL), cells = new Set();
    let changed = 0, exact = 0, x0 = width, y0 = height, x1 = -1, y1 = -1;
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const outside = x >= p0.width || y >= p0.height || x >= q0.width || y >= q0.height;
      const i = (y * width + x) * 4;
      const most = Math.max(Math.abs(p[i] - q[i]), Math.abs(p[i + 1] - q[i + 1]), Math.abs(p[i + 2] - q[i + 2]), Math.abs(p[i + 3] - q[i + 3]));
      if (outside || most) exact++;
      if (outside || most > tolerance) {
        changed++; cells.add(Math.floor(y / CELL) * cols + Math.floor(x / CELL));
        if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
    }
    // `cells`: the changed 16 px cells (row * cols + column), so the caller can outline separate areas.
    return {changed, exact, total: width * height, width: q0.width, height: q0.height, cell: CELL, cols, cells: [...cells].sort((a, b) => a - b),
      box: changed ? {x: x0, y: y0, w: Math.min(x1, q0.width - 1) - x0 + 1, h: Math.min(y1, q0.height - 1) - y0 + 1} : null};
  }, [url(before), url(after), tolerance]);
}

if (job.compare) {
  const rows = [];
  for (const pair of job.compare) rows.push({id: pair.id, ...await diff(readFileSync(pair.before), readFileSync(pair.after))});
  writeFileSync(job.out, JSON.stringify(rows, null, 1));
  await browser.close();
  process.exit(0);
}

mkdirSync(job.out_dir, {recursive: true});
const now = new Date(job.now);
const origin = new URL(job.base_url).origin;
const setup = job.setup ? (await import(pathToFileURL(resolve(here, job.setup)).href)).default : null;

function seededRandom(seed) {
  // mulberry32: the same sequence on both revisions, so "random" layout or jitter cannot differ.
  let a = seed >>> 0;
  Math.random = () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

async function settle(page, maxMs, fullPage) {
  // Two identical frames 400 ms apart. Returns the last frame and whether it settled.
  const shot = () => page.screenshot({animations: 'disabled', caret: 'hide', fullPage});
  const deadline = Date.now() + maxMs;
  let last = await shot();
  while (Date.now() < deadline) {
    await page.waitForTimeout(400);
    const next = await shot();
    if (next.equals(last)) return {png: next, settled: true};
    last = next;
  }
  return {png: last, settled: false};
}

/** One fresh load of a page in a new context: {row, png}. */
async function load(spec) {
  const viewport = typeof spec.viewport === 'string' ? VIEWPORTS[spec.viewport] : spec.viewport || VIEWPORTS.phone;
  const mobile = spec.mobile ?? viewport.width < 600;
  const context = await browser.newContext({
    viewport, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile, colorScheme: job.color_scheme || 'light', baseURL: job.base_url,
    reducedMotion: 'reduce', locale: 'en-US', timezoneId: job.timezone || 'America/Los_Angeles', serviceWorkers: 'block',
  });
  await context.route(url => url.origin !== origin && url.protocol !== 'data:' && url.protocol !== 'blob:', route => route.abort('blockedbyclient'));
  if (setup) await setup(context, {root: job.root, now, baseURL: job.base_url, here});
  await context.addInitScript(seededRandom, job.seed ?? 1);
  await context.addInitScript(({local, session}) => {
    // A null value removes the key (a first visit); anything else is stored as given.
    const apply = (store, entries) => { for (const [k, v] of Object.entries(entries)) if (v === null) store.removeItem(k); else store.setItem(k, v); };
    try { apply(localStorage, local); } catch { /* storage blocked */ }
    try { apply(sessionStorage, session); } catch { /* storage blocked */ }
  }, {local: {...job.local_storage, ...spec.local_storage}, session: {...job.session_storage, ...spec.session_storage}});
  await context.addInitScript(css => {
    const add = () => { const s = document.createElement('style'); s.textContent = css; document.documentElement.append(s); };
    if (document.documentElement) add(); else document.addEventListener('DOMContentLoaded', add);
  }, FREEZE_CSS);
  const page = await context.newPage();
  await page.clock.setFixedTime(now);
  const errors = [];
  page.on('pageerror', error => errors.push(String(error).slice(0, 300)));
  const row = {id: spec.id, path: spec.path, viewport, status: 'ok'};
  let png = null;
  try {
    const response = await page.goto(spec.path, {waitUntil: 'load', timeout: 45_000});
    row.http_status = response?.status() ?? null;
    if (!response || response.status() >= 400) {
      row.status = 'missing';
    } else {
      await page.waitForLoadState('networkidle', {timeout: 15_000}).catch(() => {});
      if (spec.wait_for) await page.locator(spec.wait_for).first().waitFor({state: 'visible', timeout: 20_000});
      for (const action of spec.actions || []) {
        if (action.click) await page.locator(action.click).first().click({timeout: 10_000});
        if (action.press) await page.keyboard.press(action.press);
        if (action.wait) await page.waitForTimeout(action.wait);
        if (action.wait_for) await page.locator(action.wait_for).first().waitFor({state: 'visible', timeout: 15_000});
      }
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      await page.waitForTimeout(spec.settle_ms ?? 1500);
      const shot = await settle(page, spec.max_settle_ms ?? 20_000, !!spec.full_page);
      png = shot.png;
      row.settled = shot.settled;
      row.title = await page.title();
    }
  } catch (error) {
    row.status = 'failed';
    row.error = String(error).split('\n')[0].slice(0, 300);
  }
  row.page_errors = errors;
  await context.close();
  return {row, png};
}

const results = [];
for (const spec of job.pages) {
  let last = await load(spec), row = last.row;
  row.loads = 1;
  // Load again until two fresh loads in a row agree: a picture that changes from load to load is not evidence.
  while (row.status === 'ok' && row.loads < LOADS) {
    const next = await load(spec);
    const agree = next.row.status === 'ok' && (await diff(last.png, next.png)).changed === 0;
    next.row.loads = row.loads + 1;
    last = next; row = next.row;
    if (agree) { row.steady = true; break; }
  }
  if (row.status === 'ok') {
    row.steady = row.steady === true;
    writeFileSync(join(job.out_dir, `${spec.id}.png`), last.png);
  }
  results.push(row);
  console.log(`${spec.id}: ${row.status}${row.status === 'ok' ? ` after ${row.loads} loads${row.steady ? '' : ', never the same twice'}` : ''}${row.error ? ` ${row.error}` : ''}`);
}
writeFileSync(join(job.out_dir, 'results.json'), JSON.stringify(results, null, 1));
await browser.close();
