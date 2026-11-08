#!/usr/bin/env node
// PERF-BASELINE-1: one CPU profile of a page load (desktop, no throttling), summarised by self time per function and per script.
// Usage: node reports/perf/profile.mjs <url> <out.json> [home]   ("home" sets the saved home port before load)
import {writeFileSync} from 'node:fs';
import {chromium} from '@playwright/test';
const [url, out, home] = process.argv.slice(2);
const EXE = process.env.PW_CHROMIUM || `${process.env.HOME}/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome`;
const browser = await chromium.launch({executablePath: EXE});
const context = await browser.newContext({viewport: {width: 1350, height: 940}});
await context.addInitScript(h => { try { localStorage.setItem('skippercast-first-run-v1', 'done'); sessionStorage.setItem('skippercast-flyover-v1', '1'); if (h) localStorage.setItem('skippercast-home-port-v1', 'morro-bay'); } catch {} }, home === 'home');
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send('Profiler.enable');
await cdp.send('Profiler.setSamplingInterval', {interval: 500});
await cdp.send('Profiler.start');
await page.goto(url, {waitUntil: 'load', timeout: 60000});
await page.waitForTimeout(15000);
const {profile} = await cdp.send('Profiler.stop');
const dt = new Map();
const ids = profile.samples, deltas = profile.timeDeltas;
for (let i = 0; i < ids.length; i++) dt.set(ids[i], (dt.get(ids[i]) || 0) + (deltas[i] || 0) / 1000);
const byFn = new Map(), byUrl = new Map();
for (const n of profile.nodes) {
  const ms = dt.get(n.id) || 0; if (!ms) continue;
  const f = n.callFrame, u = (f.url || '(native)').replace(/^https?:\/\/[^/]+/, '');
  const key = `${f.functionName || '(anon)'} ${u}:${f.lineNumber + 1}`;
  byFn.set(key, (byFn.get(key) || 0) + ms); byUrl.set(u, (byUrl.get(u) || 0) + ms);
}
const top = m => [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 30).map(([k, v]) => ({k, ms: Math.round(v)}));
const summary = {url, totalMs: Math.round([...dt.values()].reduce((a, b) => a + b, 0)), byUrl: top(byUrl), byFunction: top(byFn)};
writeFileSync(out, JSON.stringify(summary, null, 1));
console.log(JSON.stringify(summary, null, 1));
await browser.close();
