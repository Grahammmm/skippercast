#!/usr/bin/env node
// PERF-BASELINE-1 diagnostics (desktop, unthrottled): layout-shift sources, long tasks, and which callers spend time in each hot script.
// Usage: node reports/perf/diag.mjs <url> <out.json> [home]
import {writeFileSync} from 'node:fs';
import {chromium} from '@playwright/test';
const [url, out, home] = process.argv.slice(2);
const EXE = process.env.PW_CHROMIUM || `${process.env.HOME}/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome`;
const browser = await chromium.launch({executablePath: EXE});
const results = [];
for (let run = 1; run <= 2; run++) {
  const context = await browser.newContext({viewport: {width: 1350, height: 940}});
  await context.addInitScript(h => {
    try { localStorage.setItem('skippercast-first-run-v1', 'done'); sessionStorage.setItem('skippercast-flyover-v1', '1'); if (h) localStorage.setItem('skippercast-home-port-v1', 'morro-bay'); } catch {}
    const d = window.__diag = {shifts: [], long: []};
    const desc = n => { if (!n || !n.tagName) return String(n && n.nodeName); return n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + (n.className && typeof n.className === 'string' ? '.' + n.className.trim().split(/\s+/).slice(0, 3).join('.') : ''); };
    new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) d.shifts.push({t: Math.round(e.startTime), v: +e.value.toFixed(4), src: (e.sources || []).map(s => ({node: desc(s.node), from: [s.previousRect.y, s.previousRect.height].map(Math.round), to: [s.currentRect.y, s.currentRect.height].map(Math.round)}))}); }).observe({type: 'layout-shift', buffered: true});
    new PerformanceObserver(l => { for (const e of l.getEntries()) d.long.push([Math.round(e.startTime), Math.round(e.duration)]); }).observe({type: 'longtask', buffered: true});
  }, home === 'home');
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send('Profiler.enable'); await cdp.send('Profiler.setSamplingInterval', {interval: 1000}); await cdp.send('Profiler.start');
  await page.goto(url, {waitUntil: 'load', timeout: 60000});
  await page.waitForTimeout(16000);
  const {profile} = await cdp.send('Profiler.stop');
  const diag = await page.evaluate(() => window.__diag);
  // Self time per node, then attribute each hot-script sample to its nearest caller frame outside that script.
  const byId = new Map(profile.nodes.map(n => [n.id, n])), parent = new Map();
  for (const n of profile.nodes) for (const c of n.children || []) parent.set(c, n.id);
  const self = new Map();
  profile.samples.forEach((id, i) => self.set(id, (self.get(id) || 0) + (profile.timeDeltas[i] || 0) / 1000));
  const short = f => `${f.functionName || '(anon)'} ${(f.url || '').replace(/^.*\/assets\//, '')}:${f.lineNumber + 1}:${f.columnNumber + 1}`;
  const callers = {};
  for (const [id, ms] of self) {
    const n = byId.get(id); const u = n.callFrame.url || '';
    const hot = ['geo-screen', 'gpx', 'depth-contours', 'reef-trip-data', 'maplibre-gl'].find(h => u.includes('/assets/' + h)); if (!hot) continue;
    let p = parent.get(id), chain = [];
    while (p !== undefined) { const f = byId.get(p).callFrame; if (f.url && !f.url.includes('/assets/' + hot)) { chain.push(short(f)); if (chain.length >= 3) break; } p = parent.get(p); }
    const key = hot + ' <- ' + chain.join(' <- ');
    callers[key] = (callers[key] || 0) + ms;
  }
  const top = Object.entries(callers).sort((a, b) => b[1] - a[1]).slice(0, 15).map(([k, v]) => ({k, ms: Math.round(v)}));
  const cls = diag.shifts.reduce((s, x) => s + x.v, 0);
  results.push({run, cls: +cls.toFixed(4), shifts: diag.shifts.sort((a, b) => b.v - a.v).slice(0, 8), longTasks: diag.long, hotCallers: top});
  await context.close();
}
writeFileSync(out, JSON.stringify({url, results}, null, 1));
console.log(JSON.stringify({url, results}, null, 1).slice(0, 9000));
await browser.close();
