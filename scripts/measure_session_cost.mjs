#!/usr/bin/env node
// SC-LAUNCH-4: record the requests one visitor session makes to SkipperCast,
// so the per-session cost (docs/operations/cost-ceiling.md) comes from a real
// browser on the real site, not from an estimate.
//
//   node scripts/measure_session_cost.mjs capture <base-url> <out.json>
//
// Three sessions, each in a fresh browser profile (empty HTTP cache, no
// service worker), phone viewport, Pacific time:
//   first-run  the landing page, then a port chosen, as a new visitor does;
//   brief      a returning visitor opening the Boat brief for Morro Bay;
//   map        the map: pan, zoom and three layers switched on.
// Every response is recorded with its URL, status, transfer size and the
// Worker's own cost headers (X-SC-Cache, X-Feed-Source, X-Feed-Generation).
// A request is "worker" when Cloudflare must run the Worker for it: the
// path is not a file of the built site (dist/client), which static-asset
// routing answers for free without invoking the Worker. Other hosts are
// "third-party" (their quota, not this account's).
//
// The R2 and D1 operations each Worker request causes are measured by
// tests/test_session_cost.mjs, which replays this capture through the Worker.
import {existsSync, readdirSync, statSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';

const ROOT = resolve(import.meta.dirname, '..');
const CLIENT = join(ROOT, 'dist/client');

/** Every file path the static-asset router can answer (with and without .html). */
function assetPaths() {
  const out = new Set();
  const walk = dir => { for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full);
    else { const rel = '/' + full.slice(CLIENT.length + 1); out.add(rel); if (rel.endsWith('.html')) out.add(rel.slice(0, -5)); }
  } };
  walk(CLIENT);
  return out;
}

export function classify(url, origin, assets) {
  const u = new URL(url);
  if (u.origin !== origin) return 'third-party';
  return assets.has(decodeURIComponent(u.pathname)) ? 'asset' : 'worker';
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

async function capture(base, out) {
  if (!existsSync(CLIENT)) throw Error('Run `pnpm build` first: the asset list comes from dist/client.');
  const {chromium} = await import('@playwright/test');
  const assets = assetPaths(), origin = new URL(base).origin, result = {base, captured_at: new Date().toISOString(), sessions: {}};
  const browser = await chromium.launch();
  try {
    for (const [name, run] of Object.entries(SESSIONS)) {
      const context = await browser.newContext({viewport: {width: 390, height: 844}, timezoneId: 'America/Los_Angeles', locale: 'en-US'});
      const rows = [], pending = [];
      context.on('response', response => {
        if (response.fromServiceWorker()) return;   // answered by the page's service worker: no network request
        pending.push((async () => {
          const request = response.request(), sizes = await request.sizes().catch(() => null), h = response.headers();
          rows.push({method: request.method(), url: response.url(), status: response.status(), kind: classify(response.url(), origin, assets),
            range: request.headers().range ?? null, bytes: sizes ? sizes.responseBodySize : null,
            cache: h['x-sc-cache'] ?? null, source: h['x-feed-source'] ?? null, generation: h['x-feed-generation'] ?? null});
        })());
      });
      const page = await context.newPage();
      await run(page, base);
      await Promise.all(pending);
      await context.close();
      result.sessions[name] = rows;
      const count = kind => rows.filter(r => r.kind === kind).length;
      console.log(`${name}: ${rows.length} responses, worker ${count('worker')}, asset ${count('asset')}, third-party ${count('third-party')}`);
    }
  } finally { await browser.close(); }
  writeFileSync(out, JSON.stringify(result, null, 1) + '\n');
}

if (import.meta.main ?? process.argv[1] === import.meta.filename) {
  const [mode, base, out] = process.argv.slice(2);
  if (mode !== 'capture' || !base || !out) { console.error('usage: measure_session_cost.mjs capture <base-url> <out.json>'); process.exit(2); }
  await capture(base.replace(/\/$/, ''), out);
}
