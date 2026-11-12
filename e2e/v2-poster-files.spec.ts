// RF0115-6 (web/map/poster.ts): a Chart mounted while its region.json is still loading does not ask for poster.svg
// until the list is known. A held region.json that then lists no poster: no poster request at all, and the map
// still works. A held region.json that lists it: exactly one request, shown over the Chart until its first idle.
// Synthetic local routes only; the committed fixtures are not edited. The held region.json is released only after
// the Chart has made its own engine request, so the poster would already have been asked on the old behaviour.
import {readFileSync} from 'node:fs';
import {expect, test} from './fixtures.ts';

const TINY = readFileSync(new URL('../tests/fixtures/basemap/tiny.pmtiles', import.meta.url));
const ARCHIVE = 'tiles/basemap/ca-coast-fixture.pmtiles';
const POSTER = '/regions/morro-bay/poster.svg';
const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" data-zoom="12" data-west="-121.2" data-north="35.6"><path d="M0 0l100 100l50 -20"/></svg>';
const PLACE = {region: 'morro-bay', profile: 'boat', view: '35.38000,-120.88000,12'};

test.beforeEach(async ({page, v2: _v2}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
  await page.route('**/feeds/tiles/basemap/manifest.json', route => route.fulfill({json: {schema_version: 1, key: ARCHIVE}}));
});

/** The archive answered by byte range, once `gate` opens (immediately when it is already open). */
async function serveArchive(page: import('@playwright/test').Page, gate: Promise<void>) {
  await page.route(`**/feeds/${ARCHIVE}`, async route => {
    await gate;
    const range = /bytes=(\d+)-(\d+)/.exec(route.request().headers().range ?? '');
    if (!range) return route.fulfill({body: TINY, headers: {'Accept-Ranges': 'bytes'}});
    const start = Number(range[1]), end = Math.min(Number(range[2]), TINY.length - 1);
    return route.fulfill({status: 206, body: TINY.subarray(start, end + 1),
      headers: {'Content-Range': `bytes ${start}-${end}/${TINY.length}`, 'Accept-Ranges': 'bytes', 'Content-Type': 'application/octet-stream'}});
  });
}

/** Hold region.json; `release(files)` sends the committed record with `chart_files` replaced. */
async function holdRegion(page: import('@playwright/test').Page) {
  let release!: (files: string[]) => void;
  const held = new Promise<string[]>(resolve => { release = resolve; });
  await page.route('**/regions/morro-bay/region.json', async route => {
    const response = await route.fetch(), record = await response.json();
    record.chart_files = await held;
    await route.fulfill({response, json: record});
  });
  return release;
}

test('pending_list_without_the_poster_never_asks_for_it', async ({page, pageErrors, v2}) => {
  const posters: string[] = [];
  page.on('request', request => { if (new URL(request.url()).pathname === POSTER) posters.push(request.url()); });
  await serveArchive(page, Promise.resolve());
  const release = await holdRegion(page);
  const engineAsked = page.waitForRequest(request => request.url().includes('/feeds/tiles/basemap/manifest.json'));
  await v2.open('app', PLACE);
  await engineAsked;
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  expect(posters, 'no poster request while the list is held').toEqual([]);
  const settled = page.waitForResponse(response => response.url().endsWith('/regions/morro-bay/region.json'));
  release(['land-water.json', 'shoreline.geojson']);
  await settled;
  await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible();
  await page.waitForLoadState('networkidle');
  expect(posters, 'no poster request after the list settled without it').toEqual([]);
  await expect(page.locator('.app-poster')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('pending_list_with_the_poster_asks_once_and_shows_it_until_the_first_idle', async ({page, pageErrors, v2}) => {
  const posters: string[] = [];
  page.on('request', request => { if (new URL(request.url()).pathname === POSTER) posters.push(request.url()); });
  await page.route(`**${POSTER}`, route => route.fulfill({body: SVG, contentType: 'image/svg+xml'}));
  let openEngine!: () => void;
  await serveArchive(page, new Promise<void>(resolve => { openEngine = resolve; }));
  const release = await holdRegion(page);
  const engineAsked = page.waitForRequest(request => request.url().includes('/feeds/tiles/basemap/manifest.json'));
  await v2.open('app', PLACE);
  await engineAsked;
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  expect(posters, 'no poster request while the list is held').toEqual([]);
  release(['poster.svg', 'land-water.json']);
  await expect(page.locator('.app-poster')).toBeVisible();
  expect(posters, 'exactly one request once the list names it').toHaveLength(1);
  openEngine();
  await expect(page.locator('.app-poster'), 'gone once the Chart has drawn').toHaveCount(0);
  expect(posters).toHaveLength(1);
  expect(pageErrors).toEqual([]);
});
