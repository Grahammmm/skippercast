// Main flows at phone and laptop size (P4-09a): map, species, forecast and
// meteogram, regulations summary, GPX export, port change without reload,
// offline save, and passkey accounts. axe runs on each screen.
import {readFile} from 'node:fs/promises';
import {test, expect, openMap, checkA11y} from './fixtures.ts';

test('the map loads survey markers and the header', async ({page, pageErrors}, info) => {
  await openMap(page);
  await expect(page).toHaveTitle(/SkipperCast/);
  await expect(page.locator('#coast-select')).toBeEnabled();
  await expect(page.locator('#species-select')).toBeEnabled();
  await checkA11y(page, 'map', info.project.name);
  expect(pageErrors).toEqual([]);
});

test('picking a species updates the address and the rules badge', async ({page, pageErrors}) => {
  await openMap(page);
  const select = page.locator('#species-select');
  await expect(select.locator('option[value="halibut"]')).toHaveCount(1);
  await select.selectOption('halibut');
  await expect(page).toHaveURL(/[?&]target=halibut/);
  await expect(page.locator('#species-regulations summary .reg-badge')).not.toHaveText('');
  expect(pageErrors).toEqual([]);
});

test('the regulations summary row shows status, limits and the official source', async ({page, pageErrors}, info) => {
  await openMap(page);
  const rules = page.locator('#species-regulations');
  await rules.locator('summary').first().click();
  const row = rules.locator('.reg-summary-row').first();
  await expect(row).toBeVisible();
  await expect(row.locator('.reg-badge')).not.toHaveText('');
  await expect(row.locator('a[href^="https://"]').first()).toHaveAttribute('target', '_blank');
  await expect(row.locator('.reg-verified')).toContainText(/Verified|Needs recheck|Not verified/);
  await checkA11y(page, 'rules', info.project.name);
  expect(pageErrors).toEqual([]);
});

test('the forecast opens with the meteogram, and picking an hour is kept in the address', async ({page, pageErrors}, info) => {
  await openMap(page);
  await page.locator('[data-nav="forecast"]').click();
  await expect(page).toHaveURL(/#forecast$/);
  const plot = page.locator('#meteogram .meteogram-plot');
  await expect(plot.locator('svg')).toBeVisible({timeout: 30_000});
  await expect(page.locator('#best-day-banner strong')).not.toHaveText('Checking…');
  await plot.focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('#detail-hour')).toHaveValue('2');
  await expect(page).toHaveURL(/[?&]hour=\d{4}-\d{2}-\d{2}T\d{2}%3A00Z/);
  await checkA11y(page, 'forecast', info.project.name);
  // A shared link opens the same hour.
  const shared = page.url();
  await page.goto('about:blank');
  await page.goto(shared);
  await expect(page.locator('#meteogram .meteogram-plot svg')).toBeVisible({timeout: 30_000});
  await expect(page.locator('#detail-hour')).toHaveValue('2');
  expect(pageErrors).toEqual([]);
});

test('a port in the same region moves the map without reloading and keeps the forecast state', async ({page, pageErrors}) => {
  await page.addInitScript(() => { try { sessionStorage.setItem('loads', String(Number(sessionStorage.getItem('loads') || 0) + 1)); } catch { /* blocked */ } });
  await openMap(page, '/?region=morro-bay&view=35.36000,-120.94000,10&target=halibut#forecast');
  await expect(page.locator('#meteogram .meteogram-plot svg')).toBeVisible({timeout: 30_000});
  await page.locator('#meteogram .meteogram-plot').focus();
  for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight');
  await expect(page.locator('#detail-hour')).toHaveValue('5');
  await page.locator('#home-port-button').click();
  await page.locator('#home-port-search').fill('Port San Luis');
  await page.getByRole('button', {name: /Port San Luis/}).click();
  await expect(page).toHaveURL(/[?&]view=35\.\d+%2C-120\.\d+%2C10/);
  await expect(page.locator('#location-caption')).toContainText('Avila');
  await expect(page.locator('#detail-hour')).toHaveValue('5');
  await expect(page.locator('#species-select')).toHaveValue('halibut');
  expect(await page.evaluate(() => sessionStorage.getItem('loads'))).toBe('1');
  expect(pageErrors).toEqual([]);
});

test('export downloads a GPX file of the chosen spots', async ({page, pageErrors}, info) => {
  await openMap(page);
  await page.locator('[data-nav="export"]').click();
  await expect(page).toHaveURL(/#export$/);
  const download = page.locator('#export-download');
  await expect(download).toBeVisible({timeout: 30_000});
  await checkA11y(page, 'export', info.project.name);
  if (await download.isDisabled()) await page.locator('#export-content input[type="checkbox"]').first().check();
  await expect(download).toBeEnabled();
  const [file] = await Promise.all([page.waitForEvent('download'), download.click()]);
  expect(file.suggestedFilename()).toMatch(/\.gpx$/);
  const gpx = await readFile(await file.path(), 'utf8');
  expect(gpx).toMatch(/^<\?xml[^>]*\?>\s*<gpx[\s>]/);
  expect(gpx).toMatch(/<wpt |<trk>/);
  expect(pageErrors).toEqual([]);
});

test.describe('offline', () => {
  test.use({serviceWorkers: 'allow'});
  test('a saved region opens offline with the freshness banner', async ({page, context, pageErrors}, info) => {
    await openMap(page, '/?region=morro-bay#guide');
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.locator('#offline-pack-topic > summary').click();
    const save = page.locator('#offline-pack-save');
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.locator('#offline-pack')).toContainText(/Saved Morro Bay/, {timeout: 90_000});
    await checkA11y(page, 'guide', info.project.name);
    await page.waitForFunction(() => !!navigator.serviceWorker.controller);
    await context.setOffline(true);
    await page.goto('/?region=morro-bay#map');
    await expect(page.locator('#map .leaflet-marker-icon').first()).toBeVisible({timeout: 30_000});
    await expect(page.locator('#offline-banner')).toBeVisible();
    await expect(page.locator('#offline-banner span')).toHaveText(/^Offline — /);
    await context.setOffline(false);
    expect(pageErrors).toEqual([]);
  });
});

test('a passkey account can be created, used and signed out of', async ({page, pageErrors}, info) => {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
    hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  await openMap(page, '/?region=morro-bay#guide');
  const entry = page.locator('#account-entry');
  await expect(entry).toBeVisible();
  await entry.click();
  await expect(page.locator('#account-create')).toBeVisible();
  await checkA11y(page, 'account', info.project.name);
  await page.locator('#account-create').click();
  // Creating an account reloads the page signed in; open the account again.
  await expect(page.locator('#map .leaflet-marker-icon').first()).toBeAttached({timeout: 30_000});
  await page.locator('#account-entry').click();
  await expect(page.locator('#account-signout')).toBeVisible();
  expect((await (await page.request.get('/api/session')).json()).signedIn).toBe(true);
  await page.locator('#account-signout').click();
  await expect(page.locator('#map .leaflet-marker-icon').first()).toBeAttached({timeout: 30_000});
  await expect.poll(async () => (await (await page.request.get('/api/session')).json()).signedIn).toBe(false);
  expect(pageErrors).toEqual([]);
});

// The same UI must handle unavailable data honestly, not render calm values.
test('a model outage leaves the forecast explicitly unavailable', async ({page, pageErrors}) => {
  await page.route('**/api/om/**', route => route.fulfill({status: 503, json: {error: 'Simulated model outage'}}));
  await openMap(page, '/?region=morro-bay#forecast');
  await expect(page.locator('#meteogram')).toContainText('Forecast graph unavailable', {timeout: 30_000});
  await expect(page.locator('#meteogram .meteogram-plot svg')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});
