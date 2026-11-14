// RF0145-8 (web/land-water.ts): the mounted Brief does not ask for the region's land-water.json while its region.json
// is still loading (its Chart file list is pending). browser_delayed_metadata holds region.json, mounts the app, waits
// for the Brief's "Where to look" section, and requires zero index requests until the list settles:
// 1. a list that omits land-water.json: no index request at all, before or after the release;
// 2. a list that names it: exactly one request, only after the release, and the water places rank.
// Synthetic local routes only; the committed fixtures are not edited.
import {test, expect} from './fixtures.ts';

const REGION = '**/regions/morro-bay/region.json';
const INDEX = '/regions/morro-bay/land-water.json';
const PLACE = {region: 'morro-bay', profile: 'boat'};

test.beforeEach(async ({page}) => {
  // Test atlas metadata admission under explicit download deferral, not failed habitat.
  await page.addInitScript(() => Object.defineProperty(navigator, 'connection', {value: {saveData: true, effectiveType: '4g'}, configurable: true}));
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
});

/** Hold region.json; `release(files)` answers it with the committed record and `chart_files` replaced. */
async function holdRegion(page: import('@playwright/test').Page) {
  let release!: (files: string[]) => void;
  const held = new Promise<string[]>(resolve => { release = resolve; });
  await page.route(REGION, async route => {
    const response = await route.fetch(), record = await response.json();
    record.chart_files = await held;
    await route.fulfill({response, json: record});
  });
  return release;
}

async function whereToLook(page: import('@playwright/test').Page, isMobile: boolean) {
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  return page.locator(isMobile ? '.app-sheet-brief .app-where' : 'aside.app-brief .app-where');
}

/** Open the app with region.json held; resolves once the Brief's section is mounted and the page has gone quiet. */
async function openHeld(page: import('@playwright/test').Page, v2: {open(page: 'app', params?: Record<string, string>): Promise<void>}, isMobile: boolean, indexes: string[]) {
  page.on('request', request => { if (new URL(request.url()).pathname === INDEX) indexes.push(request.url()); });
  const release = await holdRegion(page);
  const regionAsked = page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/regions/morro-bay/region.json'));
  await v2.open('app', PLACE);
  await regionAsked;
  const where = await whereToLook(page, isMobile);
  await expect(where).toBeVisible();
  // Two frames after the Brief mounted: its own effects have run, and the old behaviour would already have asked.
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  return {release, where};
}

test('browser_delayed_metadata_omitting_the_index_never_requests_it', async ({page, pageErrors, v2, isMobile}) => {
  const indexes: string[] = [];
  const {release, where} = await openHeld(page, v2, isMobile, indexes);
  expect(indexes, 'no index request while region.json is held').toEqual([]);
  const settled = page.waitForResponse(response => response.url().endsWith('/regions/morro-bay/region.json'));
  release(['poster.svg', 'shoreline.geojson']);
  await settled;
  await page.waitForLoadState('networkidle');
  expect(indexes, 'no index request after the list settled without it').toEqual([]);
  await expect(where.locator('.app-pick')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('browser_delayed_metadata_naming_the_index_requests_it_once_after_the_release', async ({page, pageErrors, v2, isMobile}) => {
  const indexes: string[] = [];
  const {release, where} = await openHeld(page, v2, isMobile, indexes);
  expect(indexes, 'no index request while region.json is held').toEqual([]);
  release(['land-water.json', 'poster.svg']);
  await expect(where.locator('.app-pick').first()).toBeVisible();
  expect(indexes, 'exactly one request once the list names it').toHaveLength(1);
  expect(pageErrors).toEqual([]);
});
