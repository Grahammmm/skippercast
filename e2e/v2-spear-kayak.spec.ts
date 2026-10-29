// #644 (walkthrough slice 5, part 2): Spear's dive limits and Kayak's launch.
// 1. Spear: "Where to look" shows the table's 60 ft; it opens Your limits at
//    the depth (axe clean); 30 ft from shore with a 400 yd swim is kept on the
//    device, the control says so, and every listed place is within the swim.
// 2. Kayak: with a range saved, Your limits offers the region's listed
//    launches; choosing one measures the range and the list from it.
import {test, expect, checkA11y} from './fixtures.ts';

test.beforeEach(async ({page}) => {
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
});

const brief = (isMobile: boolean) => isMobile ? '.app-sheet-brief' : 'aside.app-brief';
async function fullSheet(page: import('@playwright/test').Page, isMobile: boolean) {
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
}

test('acceptance 1: Spear sets its depth, dives from shore and keeps the list within the swim', async ({page, pageErrors, v2, isMobile}, info) => {
  await v2.open('app', {region: 'morro-bay', profile: 'spear'});
  await fullSheet(page, isMobile);
  const where = page.locator(`${brief(isMobile)} .app-where`);
  await expect(page.locator('.app-chart')).toHaveAttribute('data-marks', /\d/);
  const dive = where.locator('.app-where-range');
  await expect(dive).toHaveText('To 60 ft');
  await dive.click();
  const dialog = page.locator('dialog.app-limits-dialog[open]');
  await expect(dialog.getByRole('heading', {name: 'Your limits · Spear'})).toBeVisible();
  const depth = dialog.getByLabel(/Deepest dive/);
  await expect(depth).toBeFocused();
  await expect(depth).toHaveValue('60');
  await depth.fill('30');
  await dialog.getByLabel('Diving from').selectOption('shore');
  await dialog.getByLabel(/Farthest swim from shore/).fill('400');
  await checkA11y(page, 'v2-spear', info.project.name);
  await dialog.getByRole('button', {name: 'Save'}).click();
  await expect(page.locator('dialog.app-limits-dialog[open]')).toHaveCount(0);
  expect(JSON.parse(await page.evaluate(() => localStorage.getItem('skippercast-spear-v1')) ?? '{}')).toEqual({depthFt: 30, from: 'shore', shoreYd: 400});
  await expect(dive).toHaveText('To 30 ft · 400 yd from shore');
  await expect(where.locator('.app-pick, .app-empty').first()).toBeVisible();
  const picks = where.locator('.app-pick > span:nth-child(2) .ui-mono');
  await expect.poll(async () => (await picks.allTextContents()).every(t => /yd from shore/.test(t)) || await where.locator('.app-empty').count() > 0).toBe(true);
  for (const text of await picks.allTextContents()) {
    expect(Number(/~(\d+) yd from shore/.exec(text)?.[1])).toBeLessThanOrEqual(400);
    expect(Number(/–(\d+) ft/.exec(text)?.[1])).toBeLessThanOrEqual(30);
  }
  await info.attach(`spear-${info.project.name}`, {body: await page.screenshot(), contentType: 'image/png'});
  expect(pageErrors).toEqual([]);
});

test('acceptance 2: Kayak picks a listed launch and the range runs from it', async ({page, pageErrors, v2, isMobile}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-reach-v1', JSON.stringify({kayak: 3})); } catch { /* storage blocked */ } });
  await v2.open('app', {region: 'morro-bay', profile: 'kayak'});
  await fullSheet(page, isMobile);
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-reach', '3');
  const range = page.locator(`${brief(isMobile)} .app-where-range`);
  await expect(range).toHaveText('Range 3 nm');
  await range.click();
  const dialog = page.locator('dialog.app-limits-dialog[open]');
  const launch = dialog.getByLabel('Launch from');
  await expect(launch).toHaveValue('');
  await launch.selectOption('olde-port-beach');
  await dialog.getByRole('button', {name: 'Save'}).click();
  expect(JSON.parse(await page.evaluate(() => localStorage.getItem('skippercast-launch-v1')) ?? '{}')).toEqual({'morro-bay': 'olde-port-beach'});
  await expect(range).toHaveAttribute('title', /straight line from Olde Port Beach/);
  await expect(chart).toHaveAttribute('data-reach', '3');
  expect(pageErrors).toEqual([]);
});
