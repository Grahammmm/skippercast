#!/usr/bin/env node
// SC-PERF-JUMP-1: layout shift of /map on a local e2e server, at the PERF-BASELINE-1 widths. Usage: node reports/perf/cls-local.mjs <base-url> [runs]
import {chromium} from '@playwright/test';

const base = process.argv[2] || 'http://localhost:8787', runs = Number(process.argv[3] || 3);
const SIZES = {phone: {width: 390, height: 844, isMobile: true, hasTouch: true}, desktop: {width: 1350, height: 940}};
const desc = n => n ? `${n.nodeName.toLowerCase()}${n.className && typeof n.className === 'string' ? '.' + n.className.trim().split(/\s+/).join('.') : ''}` : '?';
const exe = process.env.PW_CHROMIUM;
const browser = await chromium.launch(exe ? {executablePath: exe} : {});
for (const [name, v] of Object.entries(SIZES)) {
  const values = [];
  for (let i = 0; i < runs; i++) {
    const context = await browser.newContext({viewport: {width: v.width, height: v.height}, isMobile: !!v.isMobile, hasTouch: !!v.hasTouch, serviceWorkers: 'block', timezoneId: 'America/Los_Angeles', locale: 'en-US'});
    await context.route(u => new URL(u).origin !== new URL(base).origin && !/^(data|blob):/.test(u), r => r.abort('blockedbyclient'));
    const page = await context.newPage();
    await page.addInitScript(() => {
      window.__shifts = [];
      new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__shifts.push({t: Math.round(e.startTime), v: +e.value.toFixed(4), src: (e.sources || []).map(s => (s.node ? s.node.nodeName + '.' + s.node.className : '?') + ' ' + [s.previousRect.y, s.previousRect.height] + '->' + [s.currentRect.y, s.currentRect.height])}); }).observe({type: 'layout-shift', buffered: true});
    });
    await page.goto(`${base}/map?region=morro-bay`, {waitUntil: 'load'});
    await page.waitForSelector('.app-legend, .app-brief, .app-sheet', {timeout: 30000});
    await page.waitForTimeout(6000);
    const shifts = await page.evaluate(() => window.__shifts);
    const cls = shifts.reduce((a, s) => a + s.v, 0);
    values.push(cls);
    if (i === 0) console.log(name, 'sources', JSON.stringify(shifts.filter(s => s.v > 0.001), null, 0));
    await context.close();
  }
  console.log(name, 'CLS per run', values.map(x => x.toFixed(4)).join(' '), 'median', [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)].toFixed(4));
}
await browser.close();
