#!/usr/bin/env node
// SC-LAUNCH-4: record the requests one visitor session makes to SkipperCast,
// so the per-session cost (docs/operations/cost-ceiling.md) comes from a real
// browser on the real site, not from an estimate.
//
//   node research/scripts/measure_session_cost.mjs capture <base-url> <out.json>
//
// Three sessions, each in a fresh browser profile (empty HTTP cache, no
// service worker), phone viewport, Pacific time:
//   first-run  the landing page, then a port chosen, as a new visitor does;
//   brief      a returning visitor opening the Boat brief for Morro Bay;
//   map        the map: pan, zoom and three layers switched on.
// For a build-matched capture, a same-origin path in dist/client is an
// "asset"; other same-origin paths are attributed to the "worker". Without
// a build match, all same-origin responses are "unclassified", not a cost
// estimate. Other origins are "third-party" (outside this account's quota).
//
// The R2 and D1 operations each Worker request causes are read from the
// Worker's code path per request and checked by the counting fakes in
// tests/test_cost_ceiling.mjs; this capture does not replay them.
import {readFileSync, readdirSync, statSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';

const ROOT = resolve(import.meta.dirname, '../..');
const CLIENT = join(ROOT, 'dist/client');

/** Every file path the static-asset router can answer (with and without .html). */
function assetPaths(client) {
  const out = new Set();
  const walk = dir => { for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full);
    else { const rel = '/' + full.slice(client.length + 1); out.add(rel); if (rel.endsWith('.html')) out.add(rel.slice(0, -5)); }
  } };
  walk(client);
  return out;
}

const BUILD_ID = /^[0-9a-f]{10}$/;
const buildId = value => typeof value === 'string' && BUILD_ID.test(value) ? value : null;

function referenceBuild(client) {
  try {
    const id = buildId(JSON.parse(readFileSync(join(client, 'precache.json'), 'utf8'))?.build);
    if (id) return {id, assets: assetPaths(client)};
  } catch { /* A missing or unreadable reference cannot qualify. */ }
  return {id: null, assets: new Set()};
}

async function observedBuild(request, origin) {
  try {
    const response = await request.get(origin + '/api/health', {
      headers: {'Cache-Control': 'no-cache, no-store'}, maxRedirects: 0, timeout: 5000,
    });
    try {
      if (!response.ok()) return null;
      const {service, build, revision} = await response.json();
      if (service === 'SkipperCast' && buildId(build)) {
        return {id: build, revision: typeof revision === 'string' && /^[0-9a-f]{40}$/.test(revision) ? revision : null};
      }
    } finally { await response.dispose(); }
  } catch { /* A probe failure, including invalid JSON, is missing evidence. */ }
  return null;
}

// Labels are constants, never arbitrary paths, origins, or query parameters.
const EXACT_ROUTES = new Set(['/', '/map', '/api/daily', '/api/om', '/api/session', '/api/health']);
const ROUTE_GROUPS = ['/feeds/tiles', '/feeds/data', '/feeds/conditions', '/feeds', '/api/coast', '/api',
  '/assets', '/basemap', '/tiles', '/regions', '/data'];
function routeClass(path) {
  return EXACT_ROUTES.has(path) ? path : ROUTE_GROUPS.find(p => path.startsWith(p + '/')) ?? 'other';
}

function addAggregate(groups, kind, route, status, count, bytes, missingBytes) {
  const key = JSON.stringify([kind, route, status]);
  if (!groups.has(key)) groups.set(key, {kind, route, status, count: 0, bytes: 0, missing_bytes: 0});
  const group = groups.get(key);
  group.count += count;
  group.bytes += bytes;
  group.missing_bytes += missingBytes;
}

const SESSIONS = {
  async 'first-run'(page, base) {
    await page.goto(base + '/', {waitUntil: 'networkidle'});
    await page.getByRole('button', {name: /Morro Bay/}).first().click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(8000);
  },
  async brief(page, base) {
    await page.addInitScript(() => { localStorage.setItem('skippercast-first-run-v1', 'done'); localStorage.setItem('skippercast-profile-v1', 'boat'); });
    await page.goto(base + '/map?region=morro-bay&view=conditions', {waitUntil: 'networkidle'});
    await page.waitForTimeout(8000);
  },
  async map(page, base) {
    await page.addInitScript(() => { localStorage.setItem('skippercast-first-run-v1', 'done'); localStorage.setItem('skippercast-profile-v1', 'boat'); });
    await page.goto(base + '/map?region=morro-bay', {waitUntil: 'networkidle'});
    const box = await page.locator('canvas').first().boundingBox();
    const cx = box ? box.x + box.width / 2 : 195, cy = box ? box.y + box.height / 2 : 400;
    for (const [dx, dy] of [[120, 0], [0, 120], [-160, -60]]) {
      await page.mouse.move(cx, cy); await page.mouse.down(); await page.mouse.move(cx + dx, cy + dy, {steps: 8}); await page.mouse.up();
      await page.waitForTimeout(1500);
    }
    for (let i = 0; i < 3; i++) { await page.mouse.move(cx, cy); await page.mouse.wheel(0, -400); await page.waitForTimeout(1500); }
    for (const layers of ['water-temp', 'swell', 'seafloor']) {
      await page.goto(base + `/map?region=morro-bay&layers=${layers}`, {waitUntil: 'networkidle'});
      await page.waitForTimeout(3000);
    }
  },
};

export async function captureSessions(browser, base, client = CLIENT) {
  const origin = new URL(base).origin;
  const {id, assets} = referenceBuild(client);
  const issues = new Set(id ? [] : ['reference-build-missing']);
  const sessions = {};
  let revision;
  const check = async request => {
    const observed = await observedBuild(request, origin);
    if (!observed) issues.add('health-build-missing');
    else {
      if (observed.id !== id) issues.add('health-build-mismatch');
      if (revision !== undefined && observed.revision !== revision) issues.add('deployment-revision-changed');
      revision = observed.revision;
    }
  };

  for (const [name, run] of Object.entries(SESSIONS)) {
    const context = await browser.newContext({viewport: {width: 390, height: 844}, timezoneId: 'America/Los_Angeles', locale: 'en-US'});
    const groups = new Map(), pending = [];
    let documents = 0;
    const record = async response => {
      if (response.fromServiceWorker()) return; // Not a network response.
      const url = new URL(response.url()), request = response.request(), status = response.status();
      if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
      const sameOrigin = url.origin === origin;
      let path = '';
      if (sameOrigin) {
        try { path = decodeURIComponent(url.pathname); } catch { /* Do not retain malformed paths. */ }
        if (request.resourceType() === 'document' && ![301, 302, 303, 307, 308].includes(status)) {
          documents++;
          const html = await response.text().catch(() => '');
          const stamp = /<meta name="skippercast-build" content="([0-9a-f]{10})">/.exec(html)?.[1];
          if (!stamp) issues.add('document-build-missing');
          else if (stamp !== id) issues.add('document-build-mismatch');
        }
        if (/^\/assets\/.*\.[0-9a-f]{10}\.[a-z0-9]+$/.test(path) && !assets.has(path)) {
          issues.add('foreign-fingerprinted-asset');
        }
      }
      const kind = !sameOrigin ? 'third-party' : assets.has(path) ? 'asset' : 'worker';
      const sizes = await request.sizes().catch(() => null);
      addAggregate(groups, kind, sameOrigin ? routeClass(path) : 'external', status, 1,
        sizes?.responseBodySize ?? 0, sizes ? 0 : 1);
    };
    const onResponse = response => pending.push(record(response));
    try {
      await check(context.request);
      context.on('response', onResponse);
      try { await run(await context.newPage(), origin); }
      catch { issues.add('session-incomplete'); } // Keep a partial receipt; never log raw navigation errors.
      context.off('response', onResponse);
      await Promise.all(pending);
      if (!documents) issues.add('document-build-missing');
      await check(context.request);
      sessions[name] = groups;
    } finally { await context.close(); }
  }

  // Fail the full capture, not just requests after the change was detected.
  const eligible = issues.size === 0;
  for (const [name, groups] of Object.entries(sessions)) {
    const final = new Map();
    for (const {kind, route, status, count, bytes, missing_bytes} of groups.values()) {
      addAggregate(final, eligible || kind === 'third-party' ? kind : 'unclassified', route, status, count, bytes, missing_bytes);
    }
    sessions[name] = [...final.values()];
  }
  return {reference_build: id, attribution: eligible ? 'matched' : 'unclassified',
    eligible_for_cost_estimates: eligible, issues: [...issues].sort(), sessions};
}

async function capture(base, out) {
  const {chromium} = await import('@playwright/test');
  const browser = await chromium.launch();
  let result;
  try { result = await captureSessions(browser, base); }
  finally { await browser.close(); }
  writeFileSync(out, JSON.stringify(result, null, 1) + '\n');
  console.log(`Attribution: ${result.attribution}${result.issues.length ? ` (${result.issues.join(', ')})` : ''}`);
  for (const [name, groups] of Object.entries(result.sessions)) {
    const count = kind => groups.reduce((sum, row) => sum + (row.kind === kind ? row.count : 0), 0);
    console.log(`${name}: worker ${count('worker')}, asset ${count('asset')}, third-party ${count('third-party')}, unclassified ${count('unclassified')}`);
  }
  if (!result.eligible_for_cost_estimates) process.exitCode = 1;
}

if (import.meta.main ?? process.argv[1] === import.meta.filename) {
  const [mode, base, out] = process.argv.slice(2);
  if (mode !== 'capture' || !base || !out) { console.error('usage: measure_session_cost.mjs capture <base-url> <out.json>'); process.exit(2); }
  await capture(base.replace(/\/$/, ''), out);
}
