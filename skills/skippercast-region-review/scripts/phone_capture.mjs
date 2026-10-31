// Phone-viewport capture for region review. Live mode is read-only; held and candidate modes serve a run's held/ or candidate/ contours from disk.
import {createHash} from 'node:crypto';
import {existsSync, lstatSync, readdirSync, readFileSync, realpathSync} from 'node:fs';
import {mkdir, writeFile} from 'node:fs/promises';
import {basename, dirname, join, relative, resolve, isAbsolute, sep} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '../../..');
const HELD_ORIGIN = 'http://held.localhost';
const HELD_NAME = /^[a-z0-9][a-z0-9._-]*\.geojson$/;
const UNINSPECTED = 'not-visually-inspected';
export const VIEWPORTS = [{name: '390x844', width: 390, height: 844}, {name: '360x800', width: 360, height: 800}];

const present = p => { try { return lstatSync(p, {throwIfNoEntry: false}) !== undefined; } catch { return true; } };

// Compares real paths: the deepest existing ancestor is resolved through links, so a link cannot point --out into the work tree.
export function outsideRepo(path) {
  let base = resolve(path); const tail = [];
  while (!present(base)) { tail.unshift(basename(base)); base = dirname(base); }
  let real;
  try { real = join(realpathSync(base), ...tail); } catch { return false; } // dangling or unreadable ancestor: refuse
  const rel = relative(realpathSync(REPO), real);
  return rel === '..' || rel.startsWith('..' + sep) || isAbsolute(rel);
}

export function parseArgs(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i];
    if (!/^--(mode|origin|region|out|run)$/.test(key) || argv[i + 1] === undefined) throw new Error(`unknown or incomplete option: ${key}`);
    o[key.slice(2)] = argv[i + 1];
  }
  if (!['live', 'held', 'candidate'].includes(o.mode)) throw new Error('--mode must be live, held or candidate');
  if (o.mode === 'live') {
    if (!o.origin || new URL(o.origin).protocol !== 'https:') throw new Error('--origin must be an https: URL');
    if (!o.region || !o.out) throw new Error('live mode needs --region and --out');
  } else {
    if (!o.run) throw new Error(`${o.mode} mode needs --run`);
    o.out ??= join(o.run, 'REVIEW-PACKET', o.mode === 'held' ? 'phone' : 'phone-candidate');
  }
  if (!outsideRepo(o.out)) throw new Error('--out must be outside the repo work tree');
  return o;
}

export function heldRequestPlan(url, runDir, dir = 'held') {
  if (!['held', 'candidate'].includes(dir)) throw new Error('dir must be held or candidate');
  const u = new URL(url);
  if (u.protocol === 'data:' || u.protocol === 'blob:') return {action: 'continue'};
  if (u.origin !== HELD_ORIGIN) return {action: 'block'};
  if (u.pathname === '/') return {action: 'fulfil', file: join(HERE, 'held-preview.html')};
  const name = u.pathname.startsWith(`/${dir}/`) ? u.pathname.slice(dir.length + 2) : '';
  if (HELD_NAME.test(name)) return {action: 'fulfil', file: join(runDir, dir, name)};
  return {action: 'block', status: 404};
}

export function buildReceipt(p) {
  return {
    schema: 'region-phone-capture-v1', mode: p.mode, url: p.url, capturedAt: p.capturedAt ?? new Date().toISOString(),
    chromium: p.chromium,
    viewports: p.viewports.map(v => ({...v, visualInspection: UNINSPECTED})),
    requests: p.requests, blockedRequests: p.blockedRequests, textChecks: p.textChecks, pageErrors: p.pageErrors,
    failedResponses: p.failedResponses ?? [], consoleErrors: p.consoleErrors ?? [],
  };
}

export function inspectionState(receipt, reviewMarkdown) {
  return Object.fromEntries(receipt.viewports.map(v => [v.screenshot,
    reviewMarkdown.includes(v.screenshot) && reviewMarkdown.includes(v.screenshotSha256) ? 'cited-in-review' : UNINSPECTED]));
}

const SELECTORS = {
  held: ['#held-banner', '.contour-card'],
  live: ['.app-top-card .app-location', '.app-sheet-head', '.maplibregl-canvas', '.maplibregl-ctrl-attrib'],
};
SELECTORS.candidate = SELECTORS.held;

export async function capture(options) {
  const {mode, out, fulfil = {}} = options;
  if (!outsideRepo(out)) throw new Error('--out must be outside the repo work tree');
  if (lstatSync(out, {throwIfNoEntry: false})?.isSymbolicLink()) throw new Error('--out must not be a symlink');
  const receiptPath = join(out, 'capture-receipt.json');
  if (lstatSync(receiptPath, {throwIfNoEntry: false}) !== undefined) throw new Error(`refusing to overwrite ${receiptPath}`);
  const dir = mode === 'candidate' ? 'candidate' : 'held';
  let url;
  if (mode === 'live') {
    url = `${options.origin}/map?region=${encodeURIComponent(options.region)}&presentation=chart&ui=v2`;
  } else {
    const folder = join(options.run, dir);
    const names = mode === 'candidate' && !existsSync(folder) ? [] : readdirSync(folder).filter(n => HELD_NAME.test(n)).sort();
    if (mode === 'candidate' && !names.length) throw new Error(`candidate mode needs ${folder} with at least one .geojson`);
    url = `${HELD_ORIGIN}/?${mode === 'candidate' ? 'dir=candidate&' : ''}files=${names.join(',')}`;
  }
  await mkdir(out, {recursive: true});
  const {chromium} = await import('@playwright/test');
  const browser = await chromium.launch({headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const requests = [], blockedRequests = [], textChecks = [], pageErrors = [], failedResponses = [], consoleErrors = [], viewports = [];
  try {
    for (const vp of VIEWPORTS) {
      const context = await browser.newContext({viewport: {width: vp.width, height: vp.height}, isMobile: true, hasTouch: true, deviceScaleFactor: 2});
      const page = await context.newPage();
      const entries = new Map();
      const note = (request, outcome, status) => {
        const entry = {url: request.url(), method: request.method(), outcome, status};
        entries.set(request, entry); requests.push(entry);
        if (outcome === 'blocked') blockedRequests.push(entry.url);
      };
      page.on('pageerror', e => pageErrors.push(e.message));
      page.on('console', m => { if (m.type() === 'error') consoleErrors.push({viewport: vp.name, text: m.text()}); });
      page.on('response', r => { if (r.status() >= 400) failedResponses.push({viewport: vp.name, url: r.url(), status: r.status()}); const entry = entries.get(r.request()); if (entry && entry.status === null) entry.status = r.status(); });
      await page.route('**/*', async route => {
        const request = route.request(), target = request.url();
        const canned = fulfil[target] ?? fulfil[target.split('?')[0]];
        if (canned) { note(request, 'fulfilled', canned.status ?? 200); return route.fulfill(canned); }
        if (mode === 'live') { note(request, 'network', null); return route.continue(); }
        const plan = heldRequestPlan(target, options.run, dir);
        if (plan.action === 'continue') return route.continue();
        if (plan.action === 'block' && plan.status) { note(request, 'blocked', plan.status); return route.fulfill({status: plan.status, body: 'not found'}); }
        if (plan.action === 'block') { note(request, 'blocked', null); return route.abort('blockedbyclient'); }
        note(request, 'fulfilled', 200);
        return route.fulfill({status: 200, contentType: plan.file.endsWith('.html') ? 'text/html' : 'application/geo+json', body: readFileSync(plan.file)});
      });
      await page.goto(url);
      if (mode !== 'live') await page.waitForSelector('body[data-ready="true"], body[data-failed]', {timeout: 30000});
      else await page.waitForLoadState('networkidle', {timeout: 30000}).catch(e => pageErrors.push(`networkidle: ${e.message}`));
      const failed = await page.locator('body').getAttribute('data-failed');
      if (failed) pageErrors.push(`held preview failed: ${failed}`);
      const checks = mode === 'live' ? [...SELECTORS.live, 'title'] : SELECTORS[mode];
      for (const selector of checks) {
        if (selector === 'title') { textChecks.push({viewport: vp.name, selector, count: 1, text: await page.title()}); continue; }
        const found = page.locator(selector), count = await found.count();
        textChecks.push({viewport: vp.name, selector, count, text: count ? (await found.allInnerTexts()).join(' | ') : null});
      }
      const screenshot = `${mode}-${vp.name}.png`;
      const png = await page.screenshot({path: join(out, screenshot)});
      viewports.push({...vp, screenshot, screenshotSha256: createHash('sha256').update(png).digest('hex')});
      await context.close();
    }
    const receipt = buildReceipt({mode, url, chromium: browser.version(), viewports, requests, blockedRequests, textChecks, pageErrors, failedResponses, consoleErrors});
    await writeFile(receiptPath, JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});
    return receipt;
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const receipt = await capture(parseArgs(process.argv.slice(2)));
    console.log(`wrote ${receipt.viewports.length} screenshots and capture-receipt.json (${UNINSPECTED})`);
  } catch (error) {
    console.error(error.message); process.exitCode = 1;
  }
}
