// CI6-01B (docs/land-water-method.md, web/land-water.ts): "Where to look" ranks only places
// its land/water check confirms as water. Sol's implementation review (round 1, must-fix 1)
// reproduced a stall: with the candidates already on screen, a list pending on a delayed index
// stayed pending once the index loaded and left a candidate in a mixed cell, because the lines
// file was asked for only when `pending` changed. This mounts the real app.
// 1. Delayed index, every cell mixed (the committed index with its cells rewritten; the lines
//    file is the committed one, so its hash still matches): the list shows the check in
//    progress, the lines file is requested once the index lands, and the water places rank.
// 2. The committed index (today's ranked marks all fall in clean cells): places rank and the
//    lines file is never requested.
import {test, expect} from './fixtures.ts';

const INDEX = '**/regions/morro-bay/land-water.json';
const LINES = '**/regions/morro-bay/land-water-lines.json';

test.beforeEach(async ({page}) => {
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
});

async function whereToLook(page: import('@playwright/test').Page, isMobile: boolean) {
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  return page.locator(isMobile ? '.app-sheet-brief .app-where' : 'aside.app-brief .app-where');
}

test('a delayed index that leaves candidates in mixed cells loads the lines file and ranks the water places', async ({page, pageErrors, v2, isMobile}) => {
  let release!: () => void;
  const held = new Promise<void>(r => { release = r; });
  const lines: string[] = [];
  await page.route(INDEX, async route => {
    const response = await route.fetch(), index = await response.json();
    const cells = `m${index.constants.grid * index.constants.grid}`;
    for (const key of Object.keys(index.tiles)) index.tiles[key] = cells;
    await held;
    await route.fulfill({response, json: index});
  });
  page.on('request', request => { if (request.url().endsWith('/land-water-lines.json')) lines.push(request.url()); });
  await v2.open('app', {region: 'morro-bay', profile: 'boat'});
  const where = await whereToLook(page, isMobile);
  await expect(where.locator('.app-empty')).toHaveText('Checking land and water for these places…');
  expect(lines, 'no lines file while the index is held').toEqual([]);
  release();
  await expect(where.locator('.app-pick').first()).toBeVisible();
  expect(lines).toHaveLength(1);
  await expect(where.locator('.app-empty')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('with the committed index the places rank from clean cells and the lines file is never requested', async ({page, pageErrors, v2, isMobile}) => {
  const lines: string[] = [];
  await page.route(LINES, route => { lines.push(route.request().url()); return route.continue(); });
  await v2.open('app', {region: 'morro-bay', profile: 'boat'});
  const where = await whereToLook(page, isMobile);
  await expect(where.locator('.app-pick').first()).toBeVisible();
  await page.waitForLoadState('networkidle');
  expect(lines).toEqual([]);
  expect(pageErrors).toEqual([]);
});
