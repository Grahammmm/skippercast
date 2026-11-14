// SCB-12: prove the real built bootstrap downloads independently, without timing sleeps.
import {test, expect} from './fixtures.ts';

const MAIN = /\/assets\/main\.[0-9a-f]{10}\.js$/;
const LIBRARY = /\/assets\/maplibre-gl\.[0-9a-f]{10}\.js$/;

test('SCB-12: Chart library starts before a held shell finishes, with one library request', async ({page, pageErrors, v2}) => {
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let libraryRequests = 0;
  page.on('request', request => { if (LIBRARY.test(request.url())) libraryRequests++; });
  await page.route(MAIN, async route => { await held; await route.continue(); });
  const main = page.waitForRequest(MAIN), library = page.waitForRequest(LIBRARY);
  try {
    await page.goto(v2.url('app', {region: 'morro-bay'}), {waitUntil: 'commit'});
    await Promise.all([main, library]);
    await expect(page.locator('.app-chart')).toHaveCount(0, {timeout: 1000});
  } finally { release(); }
  await expect(page.locator('.app-chart canvas.maplibregl-canvas')).toBeVisible();
  expect(libraryRequests).toBe(1);
  expect(pageErrors).toEqual([]);
});

test('SCB-12: a failed early library still opens the shell and the normal map failure panel', async ({page, pageErrors, v2}) => {
  await page.route(LIBRARY, route => route.abort('failed'));
  await v2.open('app', {region: 'morro-bay'});
  await expect(page.locator('.app-location')).toContainText('Morro Bay');
  await expect(page.locator('.app-stage-failed')).toBeVisible();
  await expect(page.locator('.app-stage-failed button')).toBeVisible();
  expect(pageErrors).toEqual([]);
});
