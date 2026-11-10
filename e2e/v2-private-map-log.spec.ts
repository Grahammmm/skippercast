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
  // The page's anonymous funnel beacon (web/telemetry.ts) is sent when its 10 s flush timer fires, or on 'pagehide' (the reload below).
  // A runner slow enough to cross 10 s inside this window posts it: main failed twice in a row that way (2026-11-07 21:03, 2026-11-08 00:24 UTC). It is no account write.
  page.on('request', request => { if (request.method() !== 'GET' && new URL(request.url()).pathname !== '/api/telemetry') writes.push(request.url()); });
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

test('Spanish controls save a v1 English record and show an earlier English entry as stored under lang="en"', async ({page, pageErrors, v2}) => {
  // SC1407-12: a synthetic earlier entry, exactly as the v1 store wrote it in English.
  const reading = {label: 'Wind', model: 'NOAA GFS', grid: 'about 13 km', value: '12 kt', gap: '', point: 'regional', validAt: 1794506400000, issuedAt: 1794502800000, cell: null};
  const gap = {...reading, label: 'Seas', model: 'NOAA GFS-Wave', grid: '0.16°', value: null, gap: 'the regional forecast carries no NOAA GFS-Wave samples', issuedAt: null};
  const old = {kind: 'blank', name: 'Earlier mark', region: 'morro-bay', position: {latitude: 35.1, longitude: -120.9}, positionBasis: 'Selected map position; not live GPS',
    recordedAt: '2026-11-07T18:00:00.000Z', conditions: {at: 1794506400000, retrievedAt: null, forecast: {kind: 'points', at: 1794506400000, point: 'regional',
      families: [{family: 'gfs', label: 'GFS', rows: [reading, gap]}], current: {...gap, label: 'Current', model: 'NOAA WCOFS', grid: 'unstated', gap: 'no current forecast'}}}};
  const seeded = JSON.stringify([old]);
  await page.addInitScript(([key, raw]) => { if (localStorage.getItem(key) === null) localStorage.setItem(key, raw); }, [KEY, seeded]);
  await stubLiveFeeds(page);
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: false}}));
  await v2.open('app', {...AREA, lang: 'es'});
  const log = page.getByRole('region', {name: 'Registro privado del dispositivo', exact: true});
  await expect(log.getByRole('button', {name: 'Registrar captura aquí'})).toBeVisible();
  await expect(log.getByRole('button', {name: 'Registrar sin captura aquí'})).toBeVisible();
  await expect(log).toContainText('NO USAR PARA NAVEGACIÓN.');
  await expect(log).not.toContainText('Log catch here');
  await expect(log.locator('summary')).toHaveText('Registro del dispositivo (1)');
  await log.locator('summary').click();
  const earlier = log.locator('[data-private-entry]').first();
  await expect(earlier).toContainText('Sin captura (no se registró ninguna captura) · Earlier mark');
  await expect(earlier.locator('span[lang="en"]')).toHaveText('Selected map position; not live GPS');
  await expect(earlier.locator('li[lang="en"]')).toHaveText([/^Wind: 12 kt · NOAA GFS/, /^Seas: Unavailable: the regional forecast carries no NOAA GFS-Wave samples · /, /^Current: Unavailable: no current forecast · /]);
  expect(await page.evaluate(key => localStorage.getItem(key), KEY)).toBe(seeded);
  await log.getByRole('button', {name: 'Registrar captura aquí'}).click();
  await expect(log.getByRole('status')).toHaveText('Guardado solo en este dispositivo.');
  await expect(log.locator('summary')).toHaveText('Registro del dispositivo (2)');
  const rows = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), KEY);
  expect(JSON.stringify(rows[0])).toBe(JSON.stringify(old));
  expect(rows[1].kind).toBe('catch');
  expect(rows[1].positionBasis).toBe('Selected map position; not live GPS');
  expect(Object.keys(rows[1])).toEqual(['kind', 'name', 'region', 'position', 'positionBasis', 'recordedAt', 'conditions']);
  expect(pageErrors).toEqual([]);
});
