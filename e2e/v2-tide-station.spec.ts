// Synthetic NOAA responses: exercise the actual picker, persistence and port action.
import {test, expect} from './fixtures.ts';

const NOW = '2026-10-08T19:00:00Z';
const stations = [
  {id: '9000001', name: 'Fixture North', lat: 35.7, lng: -121.1, type: 'S'},
  {id: '9000002', name: 'Fixture Port', lat: 35.36, lng: -120.85, type: 'S'},
  {id: '9000003', name: 'Fixture Outside', lat: 40, lng: -121, type: 'S'},
  {id: '9000004', name: 'Fixture South', lat: 35.2, lng: -121, type: 'S'},
  {id: '9000005', name: 'Fixture Bay', lat: 35.3, lng: -121, type: 'S'},
];

test('tide chooser saves three, switches, removes and restores; active only at 390 px', async ({page, v2, isMobile, pageErrors}) => {
  await page.clock.setFixedTime(new Date(NOW));
  await page.addInitScript(() => { localStorage.setItem('skippercast-profile-v1', 'boat'); localStorage.setItem('skippercast-home-port-v1', 'morro-bay'); });
  await v2.feed('**/feeds/data/regions/morro-bay/latest.json', {schema_version: 1, region_id: 'morro-bay', sources: {
    tides: {id: 'tides', name: 'Configured station', kind: 'prediction', url: 'https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9412110', checked_at: NOW, status: 'ok',
      data: {station: '9412110', predictions: [{time: '2026-10-08T21:00:00Z', height_ft: 4.1, type: 'H'}]}}
  }});
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Fixture unavailable'}}));
  await page.route('**/mdapi/prod/webapi/stations.json?*', route => route.fulfill({json: {stations}}));
  await page.route('**/api/prod/datagetter?*', route => route.fulfill({json: {predictions: [{t: '2026-10-08 21:00', v: '2.3', type: 'H'}]}}));
  await v2.open('app', {region: 'morro-bay'});
  const root = page.locator(isMobile ? '.app-sheet-brief' : 'aside.app-brief');
  const open = async () => {
    if (isMobile) await page.locator('.ui-sheet-handle').press('End');
    await root.getByRole('button', {name: /^Tide station:/}).click();
  };
  await open();
  const picker = root.getByLabel('Prediction station');
  await expect(picker).toHaveValue('');
  await expect(picker.locator('option')).toHaveCount(5);
  const add = root.getByRole('button', {name: 'Add current station'});
  await picker.selectOption('9000001');
  await add.click();
  const tide = root.locator('.ui-tile', {hasText: 'Tide'});
  await expect(tide.locator('.ui-tile-source')).toContainText('9000001 Fixture North');
  await expect(tide.locator('.ui-reading')).toHaveText('2.3');
  await page.reload();
  await open();
  await expect(picker).toHaveValue('9000001');
  await root.getByRole('button', {name: 'Use nearest to port'}).click();
  await expect(picker).toHaveValue('9000002');
  await expect(tide.locator('.ui-tile-source')).toContainText('9000002 Fixture Port');
  const saved = root.getByRole('group', {name: 'Saved tide stations'});
  await picker.selectOption('9000004'); await add.click();
  await expect(saved.getByRole('button', {name: /^Use /})).toHaveCount(3);
  await picker.selectOption('9000005'); await add.click();
  await expect(root.getByRole('status').filter({hasText: /Up to three/})).toBeVisible();
  await expect(saved.getByRole('button', {name: /^Use /})).toHaveCount(3);
  await expect(tide.locator('.ui-tile-source')).toContainText('9000004 Fixture South');
  await saved.getByRole('button', {name: 'Use Fixture North', exact: true}).click();
  await expect(tide.locator('.ui-tile-source')).toContainText('9000001 Fixture North');
  await expect(saved.getByRole('button', {name: 'Use Fixture North', exact: true})).toHaveAttribute('aria-pressed', 'true');
  if (isMobile) expect(page.viewportSize()!.width).toBe(390);
  for (const button of await saved.getByRole('button').all()) {
    await expect(button).toBeVisible();
    const box = (await button.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  }
  await page.reload(); await open();
  await expect(saved.getByRole('button', {name: /^Use /})).toHaveCount(3);
  await expect(picker).toHaveValue('9000001');
  await saved.getByRole('button', {name: 'Remove Fixture North', exact: true}).click();
  await expect(picker).toHaveValue('');
  await expect(tide.locator('.ui-tile-source')).toContainText('Configured station');
  await picker.selectOption('9000005'); await add.click();
  await expect(tide.locator('.ui-tile-source')).toContainText('9000005 Fixture Bay');
  await picker.selectOption('');
  await expect(tide.locator('.ui-tile-source')).toContainText('Configured station');
  expect(pageErrors).toEqual([]);
});
