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
// the port input with a profile pill, the layer dots, axe, no three request,
// and LCP on the throttled mobile profile. FE-25: the live night map after
// first paint over the synthetic basemap fixture and a synthetic WCOFS packet
// (the coast bridge is otherwise held), its credit and Currents preview,
// motion standing still under reduced motion, and the shoreline SVG alone
// with WebGL disabled.
import {readFileSync} from 'node:fs';
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
/** The terrain renderer and three (FE-25 acceptance 4: the landing never requests them); MapLibre may load, after first paint. */
const THREE = /three|coast3d|coast-workspace|\/assets\/(?:viewer|embed|terrain)\./i;

test('the landing shows the hero and every reading with its source and age; a stale reading says stale; no three loads', async ({page, pageErrors, v2}, info) => {
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
  await expect(page.locator('#landing-readout-title')).toHaveText('Latest readings · Morro Bay & Avila area');
  await expect(page.locator('[data-fleet]')).toHaveCount(0);
  await expect(page.locator('.landing-dots a[data-layer]')).toHaveCount(6);
  await expect(page.locator('.landing-dots a[data-layer="currents"]')).toHaveAttribute('href', /\/map\?region=morro-bay&layers=currents&ui=v2$/);
  await page.locator('[data-reading="tide"] summary').click();
  await expect(page.locator('[data-reading="tide"] .ui-popover-body')).toContainText('mean lower low water');
  await expect(page.locator('[data-reading="tide"] .ui-popover-body')).toContainText('not a Morro Bay bar-current prediction');
  await page.locator('[data-reading="wind"] summary').click();
  await expect(page.locator('[data-reading="wind"] .ui-popover-body')).toContainText('about 56 nm WNW of Morro Bay harbor, out at sea: not a harbor or launch reading');
  await expect(page.locator('.landing-credit')).toHaveText('Shoreline: NOAA National Geodetic Survey · CUSP shoreline, surveyed 1994–2010.');
  await checkA11y(page, 'v2-landing', info.project.name);
  expect(requests.filter(url => THREE.test(new URL(url).pathname)), 'no three request').toEqual([]);
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

test('the landing paints within the LCP budget on the throttled mobile profile, with the night map loading after it', async ({page, pageErrors, v2}, info) => {
  test.skip(info.project.name !== 'phone', 'measured once, at phone size');
  await nightFixtures(page);
  const lcp = await v2.lcp('landing');
  console.log(`v2 landing LCP ${Math.round(lcp)} ms (budget ${LCP_BUDGET_MS}, design § 13)`);
  expect(lcp, 'Largest Contentful Paint recorded').toBeGreaterThan(0);
  expect(lcp).toBeLessThanOrEqual(LCP_BUDGET_MS);
  await expect(page.locator('.landing-night')).toHaveAttribute('data-state', 'ready');   // the map drew in the same load
  expect(pageErrors).toEqual([]);
});

// FE-25: the night map over e2e/v2-map.spec.ts's fixtures: the synthetic basemap (one tile, served by range) and a WCOFS
// packet on a 0.04° grid off Morro Bay with three-hourly frames around now; every other coast bridge request is held.
const TINY = readFileSync(new URL('../tests/fixtures/basemap/tiny.pmtiles', import.meta.url));
const ARCHIVE = 'tiles/basemap/ca-coast-fixture.pmtiles';
const HOUR_MS = 3_600_000;
async function nightFixtures(page: Page): Promise<void> {
  await page.route(/\/(?:api\/coast|coast-data)\//, () => { /* never answered */ });
  await page.route('**/feeds/tiles/basemap/manifest.json', route => route.fulfill({json: {schema_version: 1, key: ARCHIVE}}));
  await page.route(`**/feeds/${ARCHIVE}`, route => {
    const range = /bytes=(\d+)-(\d+)/.exec(route.request().headers().range ?? '');
    if (!range) return route.fulfill({body: TINY, headers: {'Accept-Ranges': 'bytes'}});
    const start = Number(range[1]), end = Math.min(Number(range[2]), TINY.length - 1);
    return route.fulfill({status: 206, body: TINY.subarray(start, end + 1),
      headers: {'Content-Range': `bytes ${start}-${end}/${TINY.length}`, 'Accept-Ranges': 'bytes', 'Content-Type': 'application/octet-stream'}});
  });
  const now = Date.now(), three = 3 * HOUR_MS, first = Math.floor(now / three) * three - three, iso = (ms: number) => new Date(ms).toISOString();
  const cells = [];
  for (let j = 0; j < 9; j++) for (let i = 0; i < 17; i++) {
    const lon = +(-121.24 + i * 0.04).toFixed(6), lat = +(35.16 + j * 0.04).toFixed(6), uMs = 0.15 + i * 0.03, vMs = 0.12 - j * 0.02;
    cells.push({lat, lon, uMs, vMs, speedKnots: Math.hypot(uMs, vMs) * 1.943844492, towardDeg: (Math.atan2(uMs, vMs) * 180 / Math.PI + 360) % 360});
  }
  const wcofs = {id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS surface forecast', url: 'https://example.test/wcofs', fetchedAt: iso(now - 600_000),
    issuedAt: iso(now - three), sampleAt: null, nativeResolutionKm: 4, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true,
    attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Surface only.', frames: [0, 1, 2, 3].map(k => ({validAt: iso(first + k * three), cells}))};
  await page.route('**/api/coast/ocean', route => route.fulfill({json: {schemaVersion: 1, countyId: 'slo', generatedAt: iso(now - 300_000), currents: [wcofs], cloud: null, sources: []}}));
}
const flow = (page: Page) => page.locator('.landing-night canvas.chart-flow--dash');

test('after first paint the night map draws the coastline and animated currents behind the hero, credits them and loads no three', async ({page, pageErrors, v2}, info) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await nightFixtures(page);
  await v2.open('landing');
  await expect(page.locator('.landing-night')).toHaveAttribute('data-state', 'ready');
  await expect(page.locator('.landing')).toHaveAttribute('data-night', 'ready');
  await expect(page.locator('.landing-night canvas.maplibregl-canvas')).toHaveAttribute('tabindex', '-1');   // still: never in the tab order
  await expect(page.locator('.landing-night .maplibregl-control-container a, .landing-night button')).toHaveCount(0);
  await expect(flow(page)).toHaveAttribute('data-motion', 'animated');
  expect(Number(await flow(page).getAttribute('data-paths')), 'streamlines over the field').toBeGreaterThan(10);
  // The SVG stays as the fallback, faded out under the drawn map.
  await expect(page.locator('.landing-shore path')).toHaveCount(2);
  await expect.poll(() => page.locator('.landing-shore').evaluate(el => getComputedStyle(el).opacity)).toBe('0');
  await expect(page.locator('[data-credit="basemap"]')).toHaveText('Basemap: © OpenStreetMap contributors, © Protomaps.');
  await expect(page.locator('[data-credit="currents"]')).toHaveText(/^Currents: NOAA WCOFS surface forecast, about 4 km, issued 3 h ago; arrows follow the toward-bearing and their motion is illustrative\.$/);
  // MapLibre is fetched only after the first paint and the load event (design § 13).
  const timing = await page.evaluate(() => ({
    paint: performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? NaN,
    load: performance.getEntriesByType('navigation').map(e => (e as PerformanceNavigationTiming).loadEventEnd)[0] ?? NaN,
    maplibre: performance.getEntriesByType('resource').find(e => /\/assets\/maplibre\.[0-9a-f]+\.js$/.test(e.name))?.startTime ?? NaN,
  }));
  expect(timing.maplibre, 'MapLibre after first paint').toBeGreaterThan(timing.paint);
  expect(timing.maplibre, 'MapLibre after the load event').toBeGreaterThanOrEqual(timing.load);
  expect(requests.some(url => new URL(url).pathname === `/feeds/${ARCHIVE}`), 'the basemap is read').toBe(true);
  // A Currents dot previews the streamlines; leaving it ends the preview.
  const dot = page.locator('.landing-dots a[data-layer="currents"]');
  await dot.focus();
  await expect(page.locator('.landing')).toHaveAttribute('data-preview', 'currents');
  await dot.blur();
  await expect(page.locator('.landing')).not.toHaveAttribute('data-preview', /./);
  await checkA11y(page, 'v2-landing-night', info.project.name);
  expect(requests.filter(url => THREE.test(new URL(url).pathname)), 'no three request').toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('under prefers-reduced-motion the night map\'s currents stand still', async ({page, pageErrors, v2}) => {
  await nightFixtures(page);
  await page.emulateMedia({reducedMotion: 'reduce'});
  await v2.open('landing');
  await expect(page.locator('.landing-night')).toHaveAttribute('data-state', 'ready');
  await expect(flow(page)).toHaveAttribute('data-motion', 'still');
  expect(Number(await flow(page).getAttribute('data-paths'))).toBeGreaterThan(10);
  expect(pageErrors).toEqual([]);
});

test('with WebGL disabled the landing keeps the shoreline SVG, never fetches MapLibre, and axe is clean', async ({page, pageErrors, v2}, info) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
      return /webgl/i.test(kind) ? null : (original as (...a: unknown[]) => unknown).call(this, kind, ...rest);
    } as typeof original;
  });
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await nightFixtures(page);
  await v2.open('landing');
  await page.waitForLoadState('load');
  // The night map's start runs a frame after the load event; give it that frame and one more task.
  await page.evaluate(() => new Promise(done => requestAnimationFrame(() => setTimeout(done, 100))));
  await expect(page.locator('.landing-shore path')).toHaveCount(2);
  await expect(page.locator('.landing-shore')).toBeVisible();
  expect(await page.locator('.landing-shore').evaluate(el => getComputedStyle(el).opacity)).not.toBe('0');
  await expect(page.locator('.landing-night')).toHaveCount(0);
  await expect(page.locator('.landing')).not.toHaveAttribute('data-night', /./);
  expect(requests.filter(url => /\/assets\/(?:maplibre|NightMap)\./.test(new URL(url).pathname)), 'no MapLibre or night map request').toEqual([]);
  await checkA11y(page, 'v2-landing-no-webgl', info.project.name);
  expect(pageErrors).toEqual([]);
});
