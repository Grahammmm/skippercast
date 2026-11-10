// MAPLIVE-1: the private map-style previews on the real app map. Owner/admin session only, off by default,
// and nothing is requested for them until a switch is turned on. Synthetic fixtures answer the private files.
// MAPLIVE_SHOTS=<dir> also writes the phone (375 px) and tablet screenshots used in the PR.
import {test, expect} from './fixtures.ts';
import type {Page} from '@playwright/test';
import {stubLiveFeeds} from '../scripts/measure_startup.mjs';

const AREA = {region: 'morro-bay', presentation: 'chart', profile: 'boat', target: 'lingcod', view: '35.30,-120.95,10'};
const SHOTS = process.env.MAPLIVE_SHOTS;

const sstDoc = () => ({
  data_time: new Date(Date.now() - 3600e3).toISOString(), max_age_hours: 48, source_id: 'fixture', colours: ['#2b5d9e', '#43c08a', '#f29a2e', '#e2492f'],
  cells: {type: 'FeatureCollection', features: [{type: 'Feature', properties: {colour: '#43c08a', temperature_f: 58}, geometry: {type: 'Polygon', coordinates: [[[-121.1, 35.2], [-120.9, 35.2], [-120.9, 35.4], [-121.1, 35.4], [-121.1, 35.2]]]}}]},
  breaks: {type: 'FeatureCollection', features: []},
});

async function open(page: Page, v2: {open(page: 'app', params?: Record<string, string>): Promise<void>}, session: Record<string, unknown>) {
  await stubLiveFeeds(page);
  await page.route('**/api/session', route => route.fulfill({json: session}));
  const varRequests: string[] = [];
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/var/')) varRequests.push(new URL(request.url()).pathname); });
  await page.route('**/var/maplayer-sst-1/sst-preview.json', route => route.fulfill({json: sstDoc()}));
  await page.route('**/var/chlorophyll/**', route => route.fulfill({status: 404, body: 'missing'}));
  await v2.open('app', AREA);
  return varRequests;
}
const layers = async (page: Page) => { if (page.viewportSize()!.width < 1024) await page.getByRole('button', {name: 'Layers', exact: true}).click(); };

test('a visitor and a non-admin account see no private previews and make no request for them', async ({page, pageErrors, v2}) => {
  for (const session of [{signIn: '/#account', signedIn: false}, {signIn: '/#account', signedIn: true, is_admin: false, user: {id: 'u1', display_name: 'Skipper'}}]) {
    const varRequests = await open(page, v2, session);
    await layers(page);
    // The bottom sheet is also a named group "Layers" (RF1925-6), so name the rail itself.
    await expect(page.locator('.ui-rail[role="group"][aria-label="Layers"]')).toBeVisible();
    await expect(page.getByText('Private previews')).toHaveCount(0);
    await expect(page.locator('[data-preview]')).toHaveCount(0);
    expect(varRequests).toEqual([]);
  }
  expect(pageErrors).toEqual([]);
});

for (const [name, size] of [['phone-375', {width: 375, height: 812}], ['tablet-820', {width: 820, height: 1180}]] as const) {
  test(`owner: every preview is off at start, loads only when switched on, and fits at ${name}`, async ({page, pageErrors, v2}) => {
    await page.setViewportSize(size);
    const varRequests = await open(page, v2, {signIn: '/#account', signedIn: true, is_admin: true, user: {id: 'owner', display_name: 'G'}});
    await layers(page);
    await expect(page.getByText('Private previews')).toBeVisible();
    for (const label of ['Seafloor relief (medium)', 'Wind trails', 'Surface currents (HF radar)', 'Sea-surface temperature', 'Chlorophyll (satellite)']) {
      await expect(page.getByRole('button', {name: new RegExp(`^${label.replace(/[()]/g, '\\$&')}`)}).first()).toHaveAttribute('aria-pressed', 'false');
    }
    expect(varRequests, 'nothing for these layers on first paint').toEqual([]);
    await expect(page.locator('[data-preview]')).toHaveCount(0);

    await page.getByRole('button', {name: /^Sea-surface temperature/}).first().click();
    const row = page.locator('[data-preview="sst"]');
    await expect(row).toHaveAttribute('data-state', 'ready');
    await expect(row).toContainText('Analysis');
    expect(varRequests).toEqual(['/var/maplayer-sst-1/sst-preview.json']);

    await page.getByRole('button', {name: /^Chlorophyll \(satellite\)/}).first().click();
    await expect(page.locator('[data-preview="chlorophyll"]')).toHaveAttribute('data-state', 'unavailable');
    await expect(page.locator('[data-preview="chlorophyll"]')).toContainText('Nothing is drawn');
    expect(varRequests.every(p => p.startsWith('/var/'))).toBe(true);

    // The legend and rail stay inside the viewport with no sideways scroll.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    if (SHOTS) {
      await page.getByText('Private previews').scrollIntoViewIfNeeded();
      await page.screenshot({path: `${SHOTS}/maplive-1-${name}-rail.png`});
      await page.locator('[data-preview="sst"]').scrollIntoViewIfNeeded();
      await page.screenshot({path: `${SHOTS}/maplive-1-${name}-legend.png`});
    }

    await page.getByRole('button', {name: /^Sea-surface temperature/}).first().click();
    await expect(page.locator('[data-preview="sst"]')).toHaveCount(0);
    expect(pageErrors).toEqual([]);
  });
}
