// SCFEAT-CATCH-1: real mark card, signed out; synthetic feed fixtures, device-only writes.
import {test, expect} from './fixtures.ts';
import {stubLiveFeeds} from '../scripts/measure_startup.mjs';

const KEY = 'skippercast.private-map-log.v1';
const AREA = {region: 'morro-bay', presentation: 'chart', profile: 'boat', target: 'lingcod', spot: 'SC26-001', view: '35.164314,-120.843179,14'};

test('map catch and blank persist locally without account writes; quota failure is honest', async ({page, pageErrors, v2}) => {
  await stubLiveFeeds(page);
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: false}}));
  await v2.open('app', AREA);
  const log = page.getByRole('region', {name: 'Private device log', exact: true});
  await expect(log.getByRole('button', {name: 'Log catch here'})).toBeVisible();
  const writes: string[] = [];
  page.on('request', request => { if (request.method() !== 'GET') writes.push(request.url()); });
  const before = await page.evaluate(() => ({href: location.href, history: history.length}));
  await log.getByRole('button', {name: 'Log catch here'}).click();
  await expect(log.getByRole('status')).toHaveText('Saved on this device only.');
  await log.getByRole('button', {name: 'Log blank here'}).click();
  await expect(log.locator('summary')).toHaveText('Device log (2)');
  expect(await page.evaluate(() => history.length)).toBe(before.history);
  const withoutView = (href: string) => { const u = new URL(href); u.searchParams.delete('view'); return u.href; };
  expect(withoutView(page.url())).toBe(withoutView(before.href));
  await page.reload();
  await log.locator('summary').click();
  await expect(log.locator('[data-private-entry]')).toHaveCount(2);
  await expect(log).toContainText('NOT FOR NAVIGATION');
  const rows = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), KEY);
  expect(rows.map((r: {kind: string}) => r.kind)).toEqual(['catch', 'blank']);
  expect(rows[0].position.latitude).toBeCloseTo(35.164314, 4);
  expect(rows[0].position.longitude).toBeCloseTo(-120.843179, 4);
  expect(rows[0].positionBasis).toBe('Selected map position; not live GPS');
  await page.evaluate(() => { Storage.prototype.setItem = () => { throw Error('quota'); }; });
  await log.getByRole('button', {name: 'Log catch here'}).click();
  await expect(log.getByRole('status')).toContainText('Not saved');
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!).length, KEY)).toBe(2);
  expect(writes).toEqual([]);
  expect(pageErrors).toEqual([]);
});
