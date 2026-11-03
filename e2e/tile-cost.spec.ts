// BF-tile-cost: what does one map view cost to serve? Opt-in audit
// (TILE_COST=1): load each app view (phone and laptop projects, Chart
// presentation), count the requests and bytes by kind and origin, write
// test-results/tile-cost.json and a Markdown table. Without TILE_COST the
// spec skips, so PR CI time is unchanged. No budget assertion here: the
// numbers are the audit, a budget is a later unit.
//
// Playwright runs this file once per project, in serial, so each project's
// worker owns its rows; the shared JSONL is how the last report to finish
// sees every project's rows and the committed JSON is the complete run.
import {appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {APP_VIEWS} from '../web/state.ts';
import {test, expect} from './fixtures.ts';
import {aggregate, type ResourceEntry, type Row} from './tile-cost.ts';
import type {Page} from '@playwright/test';
import config from '../playwright.config.ts';

const ROOT = join(import.meta.dirname, '..');
const OUT = join(ROOT, 'test-results', 'tile-cost.json');
// Both project workers are children of one Playwright runner, so the runner's
// pid names the run: one shared rows file per audit run, none per worker.
const ROWS = join(ROOT, 'test-results', `tile-cost.rows.${process.ppid}.jsonl`);
const SETTLE_MS = 15_000;
const rows: Row[] = [];   // this project's rows; the file below carries every project's

test.skip(!process.env.TILE_COST, 'opt-in audit (TILE_COST=1)');

// The page may keep talking (polling, tiles); cap the quiet wait at SETTLE_MS
// and record whether it ever went quiet, instead of failing the audit.
async function settle(page: Page): Promise<boolean> {
  try { await page.waitForLoadState('networkidle', {timeout: SETTLE_MS}); return true; }
  catch { return false; }
}

// Resource and navigation entries the page has timed; 0-byte transfers (disk
// cache, aborted remotes) read as null: counted, never sized.
async function readEntries(page: Page): Promise<ResourceEntry[]> {
  return page.evaluate(() => ([...performance.getEntriesByType('resource'), ...performance.getEntriesByType('navigation')] as PerformanceResourceTiming[])
    .map(e => ({url: e.name, transfer_bytes: e.transferSize || null, body_bytes: e.encodedBodySize || null})));
}

for (const view of APP_VIEWS) {
  test(`tile-cost ${view}`, async ({page, v2, baseURL}, info) => {
    const origin = new URL(baseURL!).origin;
    const params = {view, presentation: 'chart'};
    const pass = async (p: 'cold' | 'warm') => {
      const failed: string[] = [];
      page.on('requestfailed', request => failed.push(request.url()));
      await v2.open('app', params);
      const settled = await settle(page);
      const entries = [...await readEntries(page), ...failed.map(url => ({url, transfer_bytes: null, body_bytes: null}))];
      const row = aggregate(origin, view, info.project.name, p, entries, settled);
      rows.push(row);
      appendFileSync(ROWS, JSON.stringify(row) + '\n');   // every project's report can see every row
    };
    await pass('cold');   // fresh context from the fixture: the view's cold cost
    await pass('warm');   // same context: the repeat cost
  });
}

// One report per project, last in its serial run: it renders whatever the
// shared rows file holds, so the final JSON is the complete run.
test.describe.configure({mode: 'serial'});
test('tile-cost report', async ({}, info) => {
  expect(rows.length, `${info.project.name} audit rows`).toBe(APP_VIEWS.length * 2); // views × cold/warm
  const all = existsSync(ROWS) ? readFileSync(ROWS, 'utf8').trim().split('\n').map(line => JSON.parse(line)) : rows;
  // The shared rows file is named by the runner's pid. It must hold this
  // project's rows and no more than one full run (views × projects × passes),
  // which catches a stale file from a reused pid. The last report to finish
  // sees every project's rows and writes the complete JSON over any partial.
  expect(all.length, 'audit rows so far').toBeGreaterThanOrEqual(rows.length);
  expect(all.length, 'complete audit run').toBeLessThanOrEqual(APP_VIEWS.length * 2 * config.projects.length);
  const commit = process.env.GITHUB_SHA || 'local';
  mkdirSync(dirname(OUT), {recursive: true});
  writeFileSync(OUT + '.tmp', JSON.stringify({schema: 'tile-cost-v1', commit, rows: all}, null, 1));
  renameSync(OUT + '.tmp', OUT);   // atomic: a reader never sees a half-written report
  const kind = (r: Row, name: string) => r.by_kind[name]?.requests ?? 0;
  const remoteLine = (r: Row) => Object.entries(r.remote).map(([host, n]) => `${host}: ${n}`).join(', ') || '—';
  const table = [
    '| View | Project | Pass | Requests | Transfer B | Tiles | Feeds | API | Settled |',
    '| --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ...all.map(r => `| ${r.view} | ${r.project} | ${r.pass} | ${r.requests} | ${r.transfer_bytes ?? '—'} | ${kind(r, 'tile')} | ${kind(r, 'feed')} | ${kind(r, 'api')} | ${r.settled ? 'yes' : 'no'} |`),
    '',
    'Remote requests (counted, bytes not measured here):',
    ...all.filter(r => r.pass === 'cold').map(r => `| ${r.view} | ${r.project} | ${remoteLine(r)} |`),
  ].join('\n');
  console.log(`\ntile-cost (${commit}):\n${table}\n`);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `### Tile cost per view\n${table}\n`);
});
