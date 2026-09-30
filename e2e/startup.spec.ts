// Map startup (P4-05): the startup JSON budget, the on-map legend, and data
// that now loads only when the screen using it opens.
import {readFileSync} from 'node:fs';
import {test, expect, openMap, checkA11y} from './fixtures.ts';
import {measureStartup, formatTable, stubLiveFeeds} from '../scripts/measure_startup.mjs';

const budget = JSON.parse(readFileSync(new URL('../scripts/startup-budget.json', import.meta.url), 'utf8'))['morro-bay'];

test('Morro Bay startup JSON from committed files stays within its budget', async ({page, pageErrors}, info) => {
  test.skip(info.project.name !== 'phone', 'measured once, at phone size');
  // Live feeds get deterministic stand-ins and the ArcGIS MPA query the committed
  // snapshot, so the app takes its production path and the budgeted number
  // (committed static files only) does not move with upstream data.
  await stubLiveFeeds(page, {id: 'morro-bay'});
  const result = await measureStartup(page, {path: '/?region=morro-bay#map'});
  console.log(formatTable(result));
  expect(result.rows.filter(r => /arcgis/.test(r.path)).length, 'the live MPA check answered (production path)').toBe(1);
  expect(result.rows.filter(r => /\/api\/daily\?.*part=mpa-boundaries/.test(r.path)), 'no MPA fallback').toEqual([]);
  expect(result.static, `static startup JSON ${result.static} bytes; budget ${budget.max_bytes} (scripts/startup-budget.json)`).toBeLessThanOrEqual(budget.max_bytes);
  expect(pageErrors).toEqual([]);
});

test('the legend opens in one tap, lists the visible layers and is keyboard accessible', async ({page, pageErrors}, info) => {
  await openMap(page);
  const chip = page.getByRole('button', {name: 'Legend'});
  await expect(chip).toBeVisible();
  await chip.click();
  const sheet = page.getByRole('dialog', {name: 'Map legend'});
  await expect(sheet).toBeVisible();
  await expect(sheet.locator('[data-legend="mpa"]')).toContainText('Protected areas');
  await expect(sheet.locator('[data-legend="grades"]')).toContainText('A/B/C');
  await expect(sheet.locator('[data-legend="charter"]')).toBeVisible();
  await expect(sheet.locator('[data-legend="commercial"]'), 'the commercial AIS layer is off').toHaveCount(0);
  await checkA11y(page, 'legend', info.project.name);
  await page.keyboard.press('Escape');
  await expect(sheet).toBeHidden();
  await expect(chip).toBeFocused();
  // Keyboard only: Enter opens it, the close button closes it.
  await page.keyboard.press('Enter');
  await expect(sheet).toBeVisible();
  await sheet.getByRole('button', {name: 'Close legend'}).focus();
  await page.keyboard.press('Enter');
  await expect(sheet).toBeHidden();
  expect(pageErrors).toEqual([]);
});

test('deferred data loads when the screen that uses it opens', async ({page, pageErrors}) => {
  const requested: string[] = [];
  page.on('request', request => { const url = new URL(request.url()); requested.push(url.pathname + url.search); });
  const deferred = [/^\/api\/intelligence\?/, /^\/feeds\/data\/regions\/morro-bay\/latest\.json/];
  await openMap(page);
  await expect(page.locator('#species-regulations summary .reg-badge')).not.toHaveText('');
  // "Where to focus" still ranks its search areas at startup, without being opened.
  const card = page.locator('.search-plan-card');
  await expect(card.locator(':scope > summary')).toHaveText(/^Where to focus · (?!loading)/);
  await expect(card).toHaveAttribute('data-loaded', 'true');
  await expect(card).not.toHaveAttribute('open', '');
  await page.waitForTimeout(1500);
  for (const pattern of deferred) expect(requested.filter(path => pattern.test(path)), `${pattern} before its screen opened`).toEqual([]);

  // Forecast: the uncertainty feed and the daily fishing evidence.
  const intelligence = page.waitForResponse(r => /\/api\/intelligence\?/.test(r.url()) && r.ok());
  const daily = page.waitForResponse(r => /\/feeds\/data\/regions\/morro-bay\/latest\.json/.test(r.url()) && r.ok());
  await page.locator('[data-nav="forecast"]').click();
  await Promise.all([intelligence, daily]);
  await expect(page.locator('#ensemble-content')).not.toHaveText('Loading ensemble sources…');
  await expect(page.locator('#bite-evidence')).not.toContainText('Daily fishing evidence is loading');
  expect(pageErrors).toEqual([]);
});
