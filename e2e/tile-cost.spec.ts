// BF-tile-cost: what does one map view cost to serve? Opt-in audit
// (TILE_COST=1): load each app view (phone and laptop projects, Chart
// presentation), count the requests and bytes by kind and origin, write
// test-results/tile-cost.json and a Markdown table. Without TILE_COST the
// spec skips, so PR CI time is unchanged. No budget assertion here: the
// numbers are the audit, a budget is a later unit.
//
// Isolation without routing: Playwright's page/context routing turns off the
// browser's HTTP cache, which would make the warm pass a second cold pass. So
// this spec does not use e2e/fixtures.ts. Remote hosts fail to resolve
// (--host-resolver-rules) and the same-origin paths the local Worker proxies
// upstream are blocked over CDP (Network.setBlockedURLs); neither turns the
// cache off. Both show up as requestfailed: counted, never sized.
//
// Publishing: Playwright runs this file once per project, in serial, so each
// project's worker owns its rows. e2e/tile-cost-publish.ts saves each
// project's rows to its own file and publishes tile-cost.json only once every
// configured project's file is there, through writer-private temp files, so
// a partial snapshot never replaces a complete one.
import {appendFileSync} from 'node:fs';
import {join} from 'node:path';
import {APP_VIEWS} from '../web/state.ts';
import {test, expect, type Page} from '@playwright/test';
import {aggregate, type ResourceEntry, type Row} from './tile-cost.ts';
import {saveAndPublish} from './tile-cost-publish.ts';
import config from '../playwright.config.ts';

const ROOT = join(import.meta.dirname, '..');
const OUT = join(ROOT, 'test-results', 'tile-cost.json');
// Both project workers are children of one Playwright runner, so the runner's
// pid names the run: one directory per audit run, one file per project in it.
const RUN_DIR = join(ROOT, 'test-results', `tile-cost.run.${process.ppid}`);
const PROJECTS = config.projects!.map(p => p.name!);
const PER_PROJECT = APP_VIEWS.length * 2;   // views × cold/warm
const SETTLE_MS = 15_000;
// Paths the local Worker answers by fetching upstream (feeds, live forecast
// models): blocked so the audit stays offline, as e2e/fixtures.ts does by routing.
const BLOCKED_PATHS = ['*/feeds/*', '*/api/forecast*', '*/api/om/*'];
const rows: Row[] = [];   // this project's rows

test.skip(!process.env.TILE_COST, 'opt-in audit (TILE_COST=1)');
// Every name but localhost fails to resolve: remote origins never load, and
// no route is installed, so the HTTP cache stays on.
test.use({launchOptions: {...config.use?.launchOptions, args: ['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost']}});

test.beforeEach(async ({context, page}) => {
  // A returning visitor who finished the first-run steps; the Chart flyover already ran (as e2e/fixtures.ts sets up).
  await context.addInitScript(() => {
    try { localStorage.setItem('skippercast-first-run-v1', 'done'); sessionStorage.setItem('skippercast-flyover-v1', '1'); } catch { /* storage blocked */ }
  });
  const cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.setBlockedURLs', {urls: BLOCKED_PATHS});
});

// The page may keep talking (polling, tiles); cap the quiet wait at SETTLE_MS
// and record whether it ever went quiet, instead of failing the audit.
async function settle(page: Page): Promise<boolean> {
  try { await page.waitForLoadState('networkidle', {timeout: SETTLE_MS}); return true; }
  catch { return false; }
}

// Resource and navigation entries the page has timed; 0-byte transfers (disk
// cache, failed requests) read as null: counted, never sized.
async function readEntries(page: Page): Promise<ResourceEntry[]> {
  return page.evaluate(() => ([...performance.getEntriesByType('resource'), ...performance.getEntriesByType('navigation')] as PerformanceResourceTiming[])
    .map(e => ({url: e.name, transfer_bytes: e.transferSize || null, body_bytes: e.encodedBodySize || null})));
}

for (const view of APP_VIEWS) {
  test(`tile-cost ${view}`, async ({page, baseURL}, info) => {
    const origin = new URL(baseURL!).origin;
    const url = `/map?${new URLSearchParams({view, presentation: 'chart', ui: 'v2'})}`;
    const load = async (): Promise<{entries: ResourceEntry[]; settled: boolean}> => {
      const failed: string[] = [];
      const onFailed = (request: {url(): string}) => { failed.push(request.url()); };
      page.on('requestfailed', onFailed);
      await page.goto(url);
      await expect(page).toHaveTitle(/SkipperCast/);
      const settled = await settle(page);
      page.off('requestfailed', onFailed);
      return {entries: [...await readEntries(page), ...failed.map(url => ({url, transfer_bytes: null, body_bytes: null}))], settled};
    };
    const cold = await load();   // fresh context: the view's cold cost
    const warm = await load();   // same context and cache: the repeat cost
    const warmRow = aggregate(origin, view, info.project.name, 'warm', warm.entries, warm.settled, cold.entries);
    // A warm row only measures the repeat cost if the HTTP cache served
    // something the cold pass had to fetch; otherwise it is a second cold pass.
    expect(warmRow.reused_from_cold, `${view}: the warm pass reused a resource the cold pass fetched`).toBeGreaterThan(0);
    rows.push(aggregate(origin, view, info.project.name, 'cold', cold.entries, cold.settled), warmRow);
  });
}

// One report per project, last in its serial run.
test.describe.configure({mode: 'serial'});
test('tile-cost report', async ({}, info) => {
  expect(rows.length, `${info.project.name} audit rows`).toBe(PER_PROJECT);
  const commit = process.env.GITHUB_SHA || 'local';
  const all = saveAndPublish({runDir: RUN_DIR, out: OUT, projects: PROJECTS, perProject: PER_PROJECT, commit}, info.project.name, rows);
  if (all === null) {
    console.log(`\ntile-cost: ${info.project.name} rows saved; tile-cost.json is published once ${PROJECTS.join(' and ')} have all finished.\n`);
    return;
  }
  const kind = (r: Row, name: string) => r.by_kind[name]?.requests ?? 0;
  const remoteLine = (r: Row) => Object.entries(r.remote).map(([host, n]) => `${host}: ${n}`).join(', ') || '—';
  const table = [
    '| View | Project | Pass | Requests | Transfer B | Cache reused | Reused from cold | Tiles | Feeds | API | Settled |',
    '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ...all.map(r => `| ${r.view} | ${r.project} | ${r.pass} | ${r.requests} | ${r.transfer_bytes ?? '—'} | ${r.cache_reused} | ${r.reused_from_cold ?? '—'} | ${kind(r, 'tile')} | ${kind(r, 'feed')} | ${kind(r, 'api')} | ${r.settled ? 'yes' : 'no'} |`),
    '',
    'Remote requests (counted, bytes not measured here):',
    ...all.filter(r => r.pass === 'cold').map(r => `| ${r.view} | ${r.project} | ${remoteLine(r)} |`),
  ].join('\n');
  console.log(`\ntile-cost (${commit}):\n${table}\n`);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `### Tile cost per view\n${table}\n`);
});
