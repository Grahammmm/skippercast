import {test, expect, openMap} from './fixtures.ts';
import {readFileSync} from 'node:fs';

test('a simulated current boundary check draws the map without the upstream feed', async ({page, pageErrors}) => {
  await page.route('**/feeds/data/**', route => route.fulfill({status: 503, json: {error: 'Offline boundary test'}}));
  await openMap(page);
  await expect(page.locator('#mpa-status')).toContainText('checked now');
  await expect(page.locator('#mpa-status')).not.toHaveClass(/error/);
  expect(pageErrors).toEqual([]);
});

test('unavailable current boundary checks still withhold fishing targets', async ({page, pageErrors}) => {
  const saved = JSON.parse(readFileSync('dist/data/protected-areas.geojson', 'utf8'));
  saved.checked_at = new Date(Date.now() - 72 * 3600_000).toISOString();
  await page.route('**/data/protected-areas.geojson', route => route.fulfill({json: saved}));
  await page.route(url => url.hostname === 'services2.arcgis.com', route => route.abort('blockedbyclient'));
  await page.route('**/api/daily?*', route => route.fulfill({status: 503, json: {error: 'Offline boundary test'}}));
  await page.route('**/feeds/data/**', route => route.fulfill({status: 503, json: {error: 'Offline boundary test'}}));
  await page.goto('/?region=morro-bay#map');
  await expect(page.locator('#mpa-status')).toContainText('live check unavailable');
  await expect(page.locator('#mpa-status')).toHaveClass(/error/);
  await expect(page.locator('#map .target-pin, #map .reef-cluster')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});
