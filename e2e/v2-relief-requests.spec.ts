// MB-12: first load adds 0 B for the owner-only seafloor relief layer. With the layer off, the app makes no relief
// request (pointer, archive range read or tile), and a theme toggle makes no non-telemetry HTTP request.
// Contours have no off control, so this does not measure their off-state requests.
// Byte budgets for the layer itself are measured by scripts/check_relief_budget.py; nothing here downloads data.
import {test, expect} from './fixtures.ts';
import type {Page} from '@playwright/test';
import {stubLiveFeeds} from '../scripts/measure_startup.mjs';

const AREA = {region: 'morro-bay', presentation: 'chart', profile: 'boat', target: 'lingcod', view: '35.30,-120.95,10'};
const OWNER = {signIn: '/#account', signedIn: true, is_admin: true, user: {id: 'owner', display_name: 'G'}};
// The pointer, the archive and any tile of it: catalog/relief/<region>.json, feeds/**.pmtiles, bottom-relief:// tiles.
const RELIEF = /\/catalog\/relief\/|\/feeds\/.*\.pmtiles(?:$|\?)|\/relief\/.*\.pmtiles/i;

async function openWithOwner(page: Page, v2: {open(page: 'app', params?: Record<string, string>): Promise<void>}) {
  const all: string[] = [];
  page.on('request', request => { const u = new URL(request.url()); if (u.protocol.startsWith('http')) all.push(`${request.method()} ${u.pathname}`); });
  await stubLiveFeeds(page);
  await page.route('**/api/session', route => route.fulfill({json: OWNER}));
  await v2.open('app', AREA);
  await expect(page.locator('.app-chart canvas.maplibregl-canvas')).toBeVisible();
  await page.waitForLoadState('networkidle');
  // Let the base imagery finish arriving: the count must hold still for 1.5 s before anything is measured.
  for (let last = -1; last !== all.length;) { last = all.length; await page.waitForTimeout(1500); }
  return all;
}
const layersSheet = async (page: Page) => { if (page.viewportSize()!.width < 1024) await page.getByRole('button', {name: 'Layers', exact: true}).click(); };

test('MB-12: with the relief layer off the app makes no relief request', async ({page, pageErrors, v2}) => {
  const all = await openWithOwner(page, v2);
  await layersSheet(page);
  await expect(page.getByRole('button', {name: /^Seafloor relief \(medium\)/}).first()).toHaveAttribute('aria-pressed', 'false');
  expect(all.filter(r => RELIEF.test(r.split(' ')[1])), 'relief requests while the layer is off').toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('MB-12: a theme toggle with the layer off triggers no resource request', async ({page, pageErrors, v2, isMobile}) => {
  const all = await openWithOwner(page, v2);
  await layersSheet(page);
  await expect(page.getByRole('button', {name: /^Seafloor relief \(medium\)/}).first()).toHaveAttribute('aria-pressed', 'false');
  if (isMobile) {
    // Close the layers sheet, then lift the app sheet to reach its account button.
    await page.getByRole('button', {name: 'Layers', exact: true}).click();
    await page.locator('.ui-sheet-handle').focus();
    await page.keyboard.press('End');
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
  }
  await page.locator('.app-account-trigger').click();
  const theme = page.getByRole('region', {name: 'Map theme'});
  await expect(theme).toBeVisible();
  await page.waitForLoadState('networkidle');
  const before = all.length;
  for (const choice of ['Light', 'Dark', 'Light']) {
    const button = theme.getByRole('button', {name: choice, exact: true});
    await button.click();
    await expect(button).toHaveAttribute('aria-pressed', 'true');
    if (choice === 'Light') await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    else await expect(page.locator('html')).not.toHaveAttribute('data-theme', 'light');
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  }
  await page.waitForLoadState('networkidle');
  // Telemetry can flush asynchronously, independently of the theme toggle (CI run 44222344613).
  expect(all.slice(before).filter(r => r !== 'POST /api/telemetry'), 'resource requests after the theme toggles').toEqual([]);
  expect(all.filter(r => RELIEF.test(r.split(' ')[1]))).toEqual([]);
  expect(pageErrors).toEqual([]);
});
