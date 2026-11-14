// SC-PERF-LAZY-1 (PERF-BASELINE-1 B1, P6, P7): the ~15 MB reef export is not fetched with the first page.
// Fast link: it is requested only after the Chart's first idle frame. Save-Data or a slow connection: it is not requested at all
// until the angler taps "Load fishing spots (about N MB) on Wi-Fi". A failing export leaves the brief working and says so.
// The export bytes themselves are a stub (the ranking from real data is covered by tests/test_ranking_publication.mjs).
import {gzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';
import {stubLiveFeeds} from '../scripts/measure_startup.mjs';
import {syntheticTerrain} from './terrain-keyboard-fixture.ts';

const EXPORT = '**/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz';
for (const failure of ['held', 'expired', 'missing']) {
  test(`SCB-07-C: another region ${failure} visibly withholds habitat, with no export download`, async ({page, pageErrors, v2, isMobile}) => {
    await stubLiveFeeds(page);
    let exports = 0;
    await page.route('**/feeds/tiles/seafloor/regions/**/habitat-*', r => { exports++; return r.fulfill({status: 500}); });
    await page.route('**/feeds/tiles/seafloor/manifest-*.json', r => {
      const region = /manifest-(.*)\.json/.exec(new URL(r.request().url()).pathname)![1];
      const failed = region === 'cambria-san-simeon';
      if (failed && failure === 'missing') return r.fulfill({status: 404});
      return r.fulfill({json: {region, status: failed && failure === 'held' ? 'held' : 'ready', archive_sha256: 'a'.repeat(64),
        expires_at: new Date(Date.now() + (failed && failure === 'expired' ? -86400000 : 86400000)).toISOString()}});
    });
    await v2.open('app', {region: 'morro-bay', profile: 'boat'});
    await openFull(page, isMobile);
    await expect(brief(page, isMobile).locator('[data-habitat="unavailable"]')).toBeVisible();
    await expect(brief(page, isMobile).locator('[data-habitat="unavailable"]')).toHaveText('Reviewed habitat unavailable');
    await expect(brief(page, isMobile).locator('.app-pick')).toHaveCount(0);
    await expect(brief(page, isMobile).getByRole('button', {name: 'Set range'})).toBeVisible();
    expect(exports).toBe(0);
    expect(pageErrors).toEqual([]);
  });
}
const PUBLISHED_BYTES = 15_414_929;
test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
});

/** The seafloor manifest announces a 15.4 MB export; every request for the export itself is counted and answered by `answer`. */
async function stubExport(page: Page, answer: 'ok' | 'fail') {
  await stubLiveFeeds(page);
  const body = gzipSync('{}'), expires_at = new Date(Date.now() + 86400000).toISOString(), seen = {requests: 0};
  await page.route('**/feeds/tiles/seafloor/manifest-*.json', r => r.fulfill({json: {region: /manifest-(.*)\.json/.exec(new URL(r.request().url()).pathname)![1], status: 'ready', archive_sha256: 'a'.repeat(64), expires_at,
    export_file: 'habitat-export.geojson.gz', export_sha256: createHash('sha256').update(body).digest('hex'), export_bytes: PUBLISHED_BYTES, export_decoded_bytes: 2}}));
  await page.route(EXPORT, r => { seen.requests++; return answer === 'ok' ? r.fulfill({contentType: 'application/gzip', body}) : r.fulfill({status: 500, body: 'no'}); });
  return seen;
}
const brief = (page: Page, isMobile: boolean) => page.locator(isMobile ? '.app-sheet-brief' : 'aside.app-brief').locator('.app-where');
const openFull = async (page: Page, isMobile: boolean) => {
  if (!isMobile) return;
  await page.locator('.ui-sheet-handle').press('End');
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
};

test('fast link: the export is requested only after the Chart has first painted', async ({page, pageErrors, v2, isMobile}) => {
  const seen = await stubExport(page, 'ok');
  await v2.open('app', {region: 'morro-bay', profile: 'boat'});
  await expect.poll(() => seen.requests).toBe(1);
  // Both are page-clock times (ms since navigation): the Chart's first idle mark, and when the export request started.
  const times = await page.evaluate(() => ({
    idle: performance.getEntriesByName('skippercast-chart-idle')[0]?.startTime ?? null,
    fetch: (performance.getEntriesByType('resource') as PerformanceResourceTiming[]).find(e => e.name.includes('habitat-export'))?.startTime ?? null}));
  test.info().annotations.push({type: 'timing', description: `Chart first idle ${Math.round(times.idle ?? -1)} ms, export requested ${Math.round(times.fetch ?? -1)} ms`});
  expect(times.idle, 'the Chart reached its first idle frame').not.toBeNull();
  expect(times.fetch, 'the export request was made').not.toBeNull();
  expect(times.fetch!, 'the export was requested after the map first painted, not with the page').toBeGreaterThanOrEqual(times.idle!);
  await openFull(page, isMobile);
  await expect(brief(page, isMobile)).toBeVisible();
  await expect(brief(page, isMobile).locator('[data-reef="offer"]'), 'a fast link is not offered a button').toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('Save-Data: nothing is downloaded until the angler taps "Load fishing spots (about 15 MB) on Wi-Fi"', async ({page, pageErrors, v2, isMobile}) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'connection', {value: {saveData: true, effectiveType: '4g'}, configurable: true}));
  const seen = await stubExport(page, 'ok');
  await v2.open('app', {region: 'morro-bay', profile: 'boat'});
  await openFull(page, isMobile);
  const where = brief(page, isMobile), button = where.getByRole('button', {name: 'Load fishing spots (about 15 MB) on Wi-Fi'});
  await expect(button).toBeVisible();
  await expect(where.locator('[data-reef="offer"]')).toContainText('built-in list only');
  expect(seen.requests, 'the offer appeared without any download').toBe(0);
  await expect(page.locator('.app-chart')).toHaveAttribute('data-marks', /^[1-9]\d*$/); // the map still works without the reef data
  await button.click();
  await expect.poll(() => seen.requests).toBe(1);
  await expect(where.locator('[data-reef="offer"]')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('slow connection (3g): the same offer, and no download', async ({page, pageErrors, v2, isMobile}) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'connection', {value: {saveData: false, effectiveType: '3g'}, configurable: true}));
  const seen = await stubExport(page, 'ok');
  await v2.open('app', {region: 'morro-bay', profile: 'boat'});
  await openFull(page, isMobile);
  await expect(brief(page, isMobile).getByRole('button', {name: /^Load fishing spots \(about 15 MB\) on Wi-Fi$/})).toBeVisible();
  expect(seen.requests).toBe(0);
  expect(pageErrors).toEqual([]);
});

test('export failing: the brief and map still work, the page says the ranking did not load, and Try again asks once more', async ({page, pageErrors, v2, isMobile}) => {
  const seen = await stubExport(page, 'fail');
  await v2.open('app', {region: 'morro-bay', profile: 'boat'});
  await openFull(page, isMobile);
  const where = brief(page, isMobile), note = where.locator('[data-reef="unavailable"]');
  await expect(note).toContainText('could not be loaded');
  await expect(page.locator('.app-chart')).toHaveAttribute('data-marks', /^[1-9]\d*$/);
  await expect(where.locator('[data-habitat="unavailable"]')).toHaveText('Reviewed habitat unavailable');
  await expect(where.locator('.app-pick')).toHaveCount(0); // no silent atlas fallback
  const before = seen.requests;
  await note.getByRole('button', {name: 'Try again'}).click();
  await expect.poll(() => seen.requests).toBe(before + 1);
  expect(pageErrors).toEqual([]);
});

// Terrain-first visit (?presentation=2d): Chart is never mounted, so its idle frame never comes.
test('terrain-first, Save-Data: the offer is reachable without visiting Chart, and nothing is downloaded until the tap', async ({page, pageErrors, v2, isMobile}) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'connection', {value: {saveData: true, effectiveType: '4g'}, configurable: true}));
  const seen = await stubExport(page, 'ok');
  (await syntheticTerrain(page)).release();
  await v2.open('app', {region: 'morro-bay', profile: 'boat', presentation: '2d'});
  await expect.poll(() => page.locator('.app-terrain').evaluate(el => el.shadowRoot?.getElementById('scene')?.dataset.perspective)).toBe('2d');
  await openFull(page, isMobile);
  const where = brief(page, isMobile), button = where.getByRole('button', {name: 'Load fishing spots (about 15 MB) on Wi-Fi'});
  await expect(button).toBeVisible();
  expect(seen.requests, 'no silent export request').toBe(0);
  await button.click();
  await expect.poll(() => seen.requests).toBe(1);
  expect(pageErrors).toEqual([]);
});

test('terrain-first, fast link: the export loads by itself once the terrain has drawn', async ({page, pageErrors, v2}) => {
  const seen = await stubExport(page, 'ok');
  (await syntheticTerrain(page)).release();
  await v2.open('app', {region: 'morro-bay', profile: 'boat', presentation: '2d'});
  await expect.poll(() => seen.requests).toBe(1);
  expect(pageErrors).toEqual([]);
});
