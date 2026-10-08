// The v2 entry flow behind ?ui=v2 (FE-08, docs/plans/front-end/dev-plan.md):
// /map with no area opens the saved port or the landing; the command bar's
// port chooser matches by name and Enter navigates in place, saving the port
// under the key v1 reads; a refused location leaves a message with the input
// focused; the first-run profile choice shows once and never with ?profile=
// in the address. On the phone (FE-06) the port and locate controls sit in
// the sheet's area group, so the sheet opens to full first. FE-83: a /coast
// home opens in v2, Forget clears it everywhere, and denied storage still
// navigates. The landing itself (FE-07): the readout with source, age and
// stale state from stubbed feeds at a fixed clock, the saved-port redirect,
// the port input with a profile pill, the layer dots, axe, no map engine
// request, and LCP on the throttled mobile profile.
import type {Page} from '@playwright/test';
import {test, expect, checkA11y, LCP_BUDGET_MS} from './fixtures.ts';

const SHELL = '/map?region=morro-bay&ui=v2';
const PORT_KEY = 'skippercast-home-port-v1';
const PROFILE_KEY = 'skippercast-profile-v1';
const PLACE_KEY = 'skippercast-home-place-v1';
const stay = (page: Page) => page.evaluate(() => { (window as unknown as {__v2: number}).__v2 = 1; });
const stayed = (page: Page) => page.evaluate(() => (window as unknown as {__v2?: number}).__v2 === 1);
/** The brief: the desktop column, or the phone's sheet. */
const brief = (page: Page, isMobile: boolean) => page.locator(isMobile ? '.ui-sheet' : 'aside.app-brief');
/** Reach the area group's controls: on the phone they are in the sheet at full. */
async function openMenus(page: Page, isMobile: boolean): Promise<void> {
  if (!isMobile) return;
  await page.locator('.ui-sheet-handle').focus();
  await page.keyboard.press('End');
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
}
/** A visitor who chose a profile already, so the first-run card does not cover the controls. */
const withProfile = (page: Page) => page.addInitScript(key => { try { localStorage.setItem(key, 'boat'); } catch { /* storage blocked */ } }, PROFILE_KEY);

test('/map with no area opens the landing without a saved port, and the saved port with one', async ({page, context, pageErrors}) => {
  await page.goto('/map?ui=v2');
  await expect(page).toHaveURL(/\/\?ui=v2$/);
  await expect(page.locator('h1')).toContainText('Know the water');
  await context.addInitScript(key => { try { localStorage.setItem(key, 'san-diego'); } catch { /* storage blocked */ } }, PORT_KEY);
  await page.goto('/map?ui=v2');
  await expect(page).toHaveURL(/\/map\?[^#]*region=southern-california/);
  await expect(page).toHaveURL(/[?&]ui=v2/);
  await expect(page.locator('.app-location')).toContainText(/Southern California/i);
  expect(pageErrors).toEqual([]);
});

test('the port chooser matches by name, Enter navigates in place, and v1 reads the saved port', async ({page, pageErrors, isMobile}, info) => {
  await withProfile(page);
  await page.goto(SHELL);
  await stay(page);
  await openMenus(page, isMobile);
  await page.locator('.app-port').click();
  const dialog = page.locator('dialog.port-dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[data-port]')).toHaveCount(6);   // the featured ports before a query
  await checkA11y(page, 'v2-port-chooser', info.project.name);
  const input = dialog.locator('input[type="search"]');
  await expect(input).toBeFocused();
  await input.fill('san d');
  await expect(dialog.locator('[data-port]')).toHaveText([/San Diego/]);
  await input.press('Enter');
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/[?&]region=southern-california/);
  await expect(page).toHaveURL(/[?&]ui=v2/);
  await expect(page).toHaveURL(/[?&]profile=boat/);   // the choice carries the profile (§ 7)
  expect(await stayed(page), 'no reload').toBe(true);
  expect(await page.evaluate(key => localStorage.getItem(key), PORT_KEY)).toBe('san-diego');
  await expect(page.locator('.app-port')).toContainText('San Diego');
  // v1 (shared key): a bare visit opens the port v2 saved instead of its chooser.
  await page.goto('/?ui=v1');
  await expect(page).toHaveURL(/[?&]region=southern-california/);
  await expect(page.locator('.home-port-card')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('a refused location leaves a message and the input focused; Explore the coast opens the central coast', async ({page, context, pageErrors, isMobile}) => {
  await withProfile(page);
  // The browser refuses: the error callback fires with PERMISSION_DENIED (a pending prompt would hang the test).
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'geolocation', {value: {getCurrentPosition: (_ok: unknown, fail: (e: {code: number; message: string}) => void) => fail({code: 1, message: 'denied'})}});
  });
  await page.goto(SHELL);
  await openMenus(page, isMobile);
  await page.locator('button[aria-label="Use my location"]').click();
  const dialog = page.locator('dialog.port-dialog');
  await expect(dialog.locator('[role="status"]')).toHaveText('Location was unavailable. Search for a port instead.');
  await expect(dialog.locator('input[type="search"]')).toBeFocused();
  await expect(dialog).toContainText('Your choice stays in this browser.');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await page.locator('.app-port').click();
  await dialog.getByRole('button', {name: 'Explore the coast'}).click();
  await expect(page).toHaveURL(/[?&]coast=central/);
  await expect(page).not.toHaveURL(/region=/);
  expect(pageErrors).toEqual([]);
});

test('a home saved on /coast opens in v2, and Forget clears it for v1 and /coast too (FE-83)', async ({page, context, baseURL, pageErrors, isMobile}) => {
  const home = {v: 1, place: 'cambria', mode: 'spear'};
  await context.addCookies([{name: 'skippercast_home', value: encodeURIComponent(JSON.stringify(home)), url: baseURL!}]);
  // Seed once per tab, so the forget below is not undone by the next navigation.
  await context.addInitScript(([key, value]) => {
    try { if (sessionStorage.getItem('fe83')) return; sessionStorage.setItem('fe83', '1'); localStorage.setItem(key, value); } catch { /* storage blocked */ }
  }, [PLACE_KEY, JSON.stringify(home)]);
  await page.goto('/map?ui=v2');
  await expect(page).toHaveURL(/[?&]place=cambria/);
  await expect(page.locator('.app-location')).toHaveAttribute('data-region', 'cambria-san-simeon');
  await expect(page.locator('[aria-label="Profile"] button[aria-pressed="true"]')).toHaveText('Spear');
  await expect(page.locator('.app-firstrun')).toHaveCount(0);   // the /coast home already chose the mode
  await openMenus(page, isMobile);
  await page.locator('.app-port').click();
  const dialog = page.locator('dialog.port-dialog');
  await dialog.getByRole('button', {name: 'Forget saved home'}).click();
  await expect(dialog.locator('[role="status"]')).toHaveText('Saved home removed. This visit stays at the current selection.');
  await expect(dialog.getByRole('button', {name: 'Forget saved home'})).toHaveCount(0);
  expect(await page.evaluate(keys => keys.map(k => localStorage.getItem(k)), [PORT_KEY, PLACE_KEY, PROFILE_KEY])).toEqual([null, null, null]);
  expect((await context.cookies()).some(c => c.name === 'skippercast_home')).toBe(false);
  await expect(page).toHaveURL(/[?&]place=cambria/);   // this visit stays where it is
  await page.goto('/?ui=v1');
  await expect(page.locator('.home-port-card')).toBeVisible();   // v1 has no home either
  expect(pageErrors).toEqual([]);
});

test('with storage denied the chooser still navigates', async ({page, pageErrors, isMobile}) => {
  await page.addInitScript(() => {
    for (const name of ['getItem', 'setItem', 'removeItem'] as const) Object.defineProperty(Storage.prototype, name, {value() { throw new DOMException('denied', 'SecurityError'); }});
  });
  await page.goto(SHELL + '&profile=boat');
  await stay(page);
  await openMenus(page, isMobile);
  await page.locator('.app-port').click();
  const dialog = page.locator('dialog.port-dialog');
  await expect(dialog.getByRole('button', {name: 'Forget saved home'})).toHaveCount(0);
  const input = dialog.locator('input[type="search"]');
  await input.fill('san d');
  await input.press('Enter');
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/[?&]region=southern-california/);
  expect(await stayed(page), 'no reload').toBe(true);
  expect(pageErrors).toEqual([]);
});

test('first run asks for the profile once and never when the address names one', async ({page, pageErrors, isMobile}) => {
  await page.goto(SHELL);
  const card = page.locator('.app-firstrun');
  await expect(card).toBeVisible();
  await expect(card).not.toHaveAttribute('aria-modal', 'true');
  await expect(brief(page, isMobile)).toBeVisible();   // the map and brief are never blocked
  await card.locator('button[data-profile="shore"]').click();
  await expect(card).toHaveCount(0);
  await expect(page).toHaveURL(/[?&]profile=shore/);
  await expect(page.locator('[aria-label="Profile"] button[aria-pressed="true"]')).toHaveText('Shore');
  await page.goto(SHELL);
  await expect(brief(page, isMobile)).toBeVisible();
  await expect(card).toHaveCount(0);
  await expect(page.locator('[aria-label="Profile"] button[aria-pressed="true"]')).toHaveText('Shore', {timeout: 5_000});
  await page.evaluate(() => localStorage.clear());
  await page.goto(SHELL + '&profile=boat');
  await expect(brief(page, isMobile)).toBeVisible();
  await expect(card).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

// FE-07: synthetic feeds at a fixed clock (no test reads the real time or a live service).
const NOW = Date.parse('2026-10-07T20:00:00Z');
const ago = (min: number) => new Date(NOW - min * 60000).toISOString();
const buoy = (name: string, station: string, units: Record<string, string>, row: Record<string, unknown>) =>
  ({name, status: 'ok', max_age_hours: 2, data: {station, units, observations: [row]}});
const FEED = {schema_version: 1, region_id: 'morro-bay', generated_at: ago(12), sources: {
  offshore: buoy('Cape San Martin offshore', '46028', {WDIR: 'degT', WSPD: 'm/s', GST: 'm/s'}, {time: ago(20), WDIR: 320, WSPD: 7, GST: 9}),
  'diablo-spectrum': buoy('Diablo Canyon swell and wind waves', '46215', {SwH: 'm', SwP: 'sec', SwD: '-'}, {time: ago(34), SwH: 0.7, SwP: 10.5, SwD: 'WNW'}),
  diablo: buoy('Diablo Canyon', '46215', {WTMP: 'degC'}, {time: ago(200), WTMP: 14.5}),
}};
const coops = (min: number, v: string) => ({t: new Date(NOW - min * 60000).toISOString().slice(0, 16).replace('T', ' '), v});
const TIDE = {metadata: {id: '9412110', name: 'Port San Luis'}, data: [coops(114, '2.10'), coops(6, '3.04')]};
/** Fix the clock and answer the conditions feed and the CO-OPS water level (page routes win over the fixture's block). */
async function landingFeeds(page: Page, feed: unknown = FEED, tide: unknown = TIDE): Promise<void> {
  await page.clock.setFixedTime(NOW);
  await page.route('**/feeds/conditions/regions/morro-bay/latest.json', route => feed ? route.fulfill({json: feed}) : route.fulfill({status: 404, json: {}}));
  await page.route('https://api.tidesandcurrents.noaa.gov/**', route => tide ? route.fulfill({json: tide}) : route.abort('failed'));
}
const ENGINE = /maplibre|pmtiles|three|coast3d|coast-workspace/i;

test('the landing shows the hero and every reading with its source and age; a stale reading says stale; no map engine loads', async ({page, pageErrors, v2}, info) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await landingFeeds(page);
  await v2.open('landing');
  await expect(page.locator('h1')).toHaveText('Know the water before you leave the dock.');
  await expect(page.locator('.landing-shore path')).toHaveCount(2);
  const tiles = page.locator('.landing-tiles li[data-reading]');
  await expect(tiles).toHaveCount(4);
  await expect(page.locator('[data-reading="wind"] .ui-tile-reading')).toHaveText('14kt');
  await expect(page.locator('[data-reading="wind"] .ui-tile-source')).toHaveText('NDBC 46028 · 20 min');
  await expect(page.locator('[data-reading="swell"] .ui-tile-source')).toHaveText('NDBC 46215 · 34 min');
  await expect(page.locator('[data-reading="tide"] .ui-tile-source')).toHaveText('NOAA 9412110 · 6 min');
  await expect(page.locator('[data-reading="water"] .ui-tile')).toHaveAttribute('data-state', 'stale');
  await expect(page.locator('[data-reading="water"] .ui-tile-source')).toHaveText('NDBC 46215 · 3 hstale');
  await expect(page.locator('.landing-fresh')).toHaveText('Buoy feed updated 12 min ago');
  await expect(page.locator('[data-fleet]')).toHaveCount(0);
  await expect(page.locator('.landing-dots a[data-layer]')).toHaveCount(6);
  await expect(page.locator('.landing-dots a[data-layer="currents"]')).toHaveAttribute('href', /\/map\?region=morro-bay&layers=currents&ui=v2$/);
  await page.locator('[data-reading="tide"] summary').click();
  await expect(page.locator('[data-reading="tide"] .ui-popover-body')).toContainText('mean lower low water');
  await checkA11y(page, 'v2-landing', info.project.name);
  expect(requests.filter(url => ENGINE.test(new URL(url).pathname)), 'no MapLibre or three request').toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('with the feeds unavailable every tile still names its source, says unavailable and shows stale', async ({page, pageErrors, v2}) => {
  await landingFeeds(page, null, null);
  await v2.open('landing');
  const sources = page.locator('.landing-tiles .ui-tile-source');
  await expect(sources).toHaveText(['NDBC 46028 · unavailablestale', 'NDBC 46215 · unavailablestale', 'NDBC 46215 · unavailablestale', 'NOAA 9412110 · unavailablestale']);
  await expect(page.locator('.landing-tiles .ui-tile[data-state="stale"]')).toHaveCount(4);
  await expect(page.locator('.landing-fresh')).toHaveText('Buoy feed unavailable');
  expect(pageErrors).toEqual([]);
});

test('a saved port and no parameters open the app there with the stored profile; any other parameter keeps the landing', async ({page, context, pageErrors}) => {
  await context.addInitScript(([port, profile]) => { try { localStorage.setItem(port, 'morro-bay'); localStorage.setItem(profile, 'spear'); } catch { /* storage blocked */ } }, [PORT_KEY, PROFILE_KEY]);
  await page.goto('/?ui=v2&from=newsletter');
  await expect(page.locator('h1')).toHaveText('Know the water before you leave the dock.');
  await expect(page.locator('[data-profile="spear"]')).toHaveAttribute('aria-pressed', 'true');
  await page.goto('/?ui=v2');
  await expect(page).toHaveURL(/\/map\?/);
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({ui: 'v2', region: 'morro-bay', profile: 'spear'});
  expect(pageErrors).toEqual([]);
});

test('a profile pill and a port from the landing input open the app with both and save the port', async ({page, pageErrors, v2}) => {
  await landingFeeds(page);
  await v2.open('landing');
  await page.locator('.landing-pills [data-profile="shore"]').click();
  await expect(page.locator('.landing-pills [data-profile="shore"]')).toHaveAttribute('aria-pressed', 'true');
  const input = page.getByLabel('Where are you launching?');
  await input.fill('morro');
  await expect(page.locator('.landing [data-port]')).toHaveText([/Morro Bay/]);
  await input.press('Enter');
  await expect(page).toHaveURL(/\/map\?/);
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({ui: 'v2', region: 'morro-bay', profile: 'shore'});
  expect(await page.evaluate(key => localStorage.getItem(key), PORT_KEY)).toBe('morro-bay');
  await expect(page.locator('.app-firstrun')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('the landing paints within the LCP budget on the throttled mobile profile', async ({pageErrors, v2}, info) => {
  test.skip(info.project.name !== 'phone', 'measured once, at phone size');
  const lcp = await v2.lcp('landing');
  console.log(`v2 landing LCP ${Math.round(lcp)} ms (budget ${LCP_BUDGET_MS}, design § 13)`);
  expect(lcp, 'Largest Contentful Paint recorded').toBeGreaterThan(0);
  expect(lcp).toBeLessThanOrEqual(LCP_BUDGET_MS);
  expect(pageErrors).toEqual([]);
});
