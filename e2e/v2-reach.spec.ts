// #644 (walkthrough slice 5, owner decision C): the range to consider.
// 1. Boat with no range: "Where to look" offers Set range, which opens Your
//    limits at the range field (blank, no default; axe clean); saving 6 nm
//    keeps it on the device, the control reads "Range 6 nm", every listed
//    place is within 6 nm, and the Chart draws the dashed ring (MapLibre
//    renders it in view).
// 2. Shore has no range control and no ring; a cleared range removes the ring.
import {test, expect, checkA11y} from './fixtures.ts';

const REACH_KEY = 'skippercast-reach-v1';

test.beforeEach(async ({page}) => {
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
});

test('acceptance 1: Set range asks for the range, keeps it on the device, filters the list and draws the ring', async ({page, pageErrors, v2, isMobile}, info) => {
  await v2.open('app', {region: 'morro-bay', profile: 'boat'});
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  const root = page.locator(isMobile ? '.app-sheet-brief' : 'aside.app-brief');
  const where = root.locator('.app-where');
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-marks', /^[1-9]\d*$/);
  await expect(chart).not.toHaveAttribute('data-reach', /./);
  await where.getByRole('button', {name: 'Set range'}).click();
  const dialog = page.locator('dialog.app-limits-dialog[open]');
  await expect(dialog.getByRole('heading', {name: 'Your limits · Boat'})).toBeVisible();
  const range = dialog.getByLabel(/Range to consider/);
  await expect(range).toBeFocused();
  await expect(range).toHaveValue('');
  await checkA11y(page, 'v2-reach', info.project.name);
  await range.fill('6');
  await dialog.getByRole('button', {name: 'Save'}).click();
  await expect(page.locator('dialog.app-limits-dialog[open]')).toHaveCount(0);
  expect(JSON.parse(await page.evaluate(key => localStorage.getItem(key), REACH_KEY) ?? '{}')).toEqual({boat: 6});
  await expect(where.getByRole('button', {name: 'Range 6 nm'})).toBeVisible();
  const picks = where.locator('.app-pick > span:nth-child(2) .ui-mono');
  if (await picks.count()) for (const text of await picks.allTextContents()) expect(Number(/([\d.]+) nm/.exec(text)?.[1])).toBeLessThanOrEqual(6);
  else await expect(where.locator('.app-empty')).toContainText('6 nm of');
  await expect(chart).toHaveAttribute('data-reach', '6');
  if (isMobile) await page.locator('.ui-sheet-handle').press('Home');
  await expect(chart, 'MapLibre drew the ring in view').toHaveAttribute('data-reach-drawn', /^[1-9]\d*$/);
  await info.attach(`reach-${info.project.name}`, {body: await page.screenshot(), contentType: 'image/png'});
  expect(pageErrors).toEqual([]);
});

test('acceptance 2: Shore has no range control or ring, and a cleared range removes the ring', async ({page, pageErrors, v2, isMobile}) => {
  await page.addInitScript(key => { try { localStorage.setItem(key, JSON.stringify({boat: 8})); } catch { /* storage blocked */ } }, REACH_KEY);
  await v2.open('app', {region: 'morro-bay', profile: 'shore'});
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-marks', /\d/);
  await expect(page.locator('.app-where-range')).toHaveCount(0);
  await expect(chart).toHaveAttribute('data-reach', '');
  await v2.open('app', {region: 'morro-bay', profile: 'boat'});
  await expect(chart).toHaveAttribute('data-reach', '8');
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  await page.locator(isMobile ? '.app-sheet-brief .app-where-range' : 'aside.app-brief .app-where-range').click();
  const dialog = page.locator('dialog.app-limits-dialog[open]');
  await dialog.getByLabel(/Range to consider/).fill('');
  await dialog.getByRole('button', {name: 'Save'}).click();
  await expect(chart).toHaveAttribute('data-reach', '');
  await expect(page.locator(isMobile ? '.app-sheet-brief .app-where-range' : 'aside.app-brief .app-where-range')).toHaveText('Set range');
  expect(pageErrors).toEqual([]);
});
