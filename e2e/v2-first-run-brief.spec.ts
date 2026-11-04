import {test, expect, THROTTLED_MOBILE} from './fixtures.ts';
import type {Page} from '@playwright/test';
import {stubLiveFeeds, stubForecast} from '../scripts/measure_startup.mjs';
import {readFileSync} from 'node:fs';
import {forecastFixture} from './forecast-fixture.ts';
import {regionWarmList} from '../web/landing/region-warm.ts';

const FUNNEL_BUDGET_MS = 30_000;
const PORT_KEY = 'skippercast-home-port-v1';
const cells = [['morro', 'morro-bay', 'boat'], ['morro', 'morro-bay', 'shore'],
  ['morro', 'morro-bay', 'spear'], ['morro', 'morro-bay', 'kayak'], ['monterey', 'monterey-point-sur', 'boat']];
async function prepare(page: Page, region = 'morro-bay') {
  await stubLiveFeeds(page, {id: region});
  // Startup's byte-budget stand-in omits units; use the unit-checked calm UI fixture.
  const definition = JSON.parse(readFileSync(new URL(`../dist/regions/${region}/region.json`, import.meta.url), 'utf8'));
  await page.route('**/api/forecast?*', route => {
    const feed = stubForecast(definition);
    for (const model of Object.values(feed.models)) model.data = model.data.map(point => {
      const url = new URL('https://fixture.invalid/forecast');
      url.search = new URLSearchParams({latitude: String(point.latitude), longitude: String(point.longitude),
        hourly: Object.keys(point.hourly).filter(key => key !== 'time').join(',')}).toString();
      return forecastFixture(url);
    });
    return route.fulfill({json: feed});
  });
  await page.addInitScript(() => {
    if (!sessionStorage.getItem('funnel-started')) {
      localStorage.clear(); sessionStorage.setItem('funnel-started', '1');
      sessionStorage.setItem('funnel-actions', '[]'); sessionStorage.setItem('funnel-writes', '0');
    }
    localStorage.removeItem('skippercast-first-run-v1');
    const set = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (this === localStorage && key === 'skippercast-home-port-v1')
        set.call(sessionStorage, 'funnel-writes', String(Number(sessionStorage.getItem('funnel-writes')) + 1));
      return set.call(this, key, value);
    };
    for (const type of ['input', 'keydown', 'click']) document.addEventListener(type, event => {
      const actions = JSON.parse(sessionStorage.getItem('funnel-actions') || '[]');
      // Enter dispatches a native submit-button click, not another user action.
      if (type === 'click' && (event as MouseEvent).detail === 0 && actions.at(-1) === 'Enter'
        && (event.target as HTMLElement).matches('button[type="submit"]')) return;
      actions.push(type === 'keydown' ? (event as KeyboardEvent).key : type);
      sessionStorage.setItem('funnel-actions', JSON.stringify(actions));
    }, true);
  });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', {offline: false, ...THROTTLED_MOBILE});
  await cdp.send('Emulation.setCPUThrottlingRate', {rate: THROTTLED_MOBILE.cpu});
  return cdp;
}
async function port(page: Page, query: string) {
  const input = page.getByLabel('Where are you launching?');
  await input.fill(query); await input.press('Enter');
  await expect(page.locator('.landing-step[data-step="profile"]')).toBeVisible();
}
async function verdict(page: Page, started: number, label: string) {
  const word = page.locator('.app-verdict .app-verdict-word');
  await expect(word).toBeVisible({timeout: FUNNEL_BUDGET_MS});
  const elapsed = Date.now() - started;
  console.log(`FUNNEL ${label}: ${elapsed} ms`);
  expect(elapsed).toBeLessThanOrEqual(FUNNEL_BUDGET_MS);
  await expect(word).toHaveText(/^(Comfortable|Marginal|Rough)$/);
  await expect(page.locator('.app-verdict-limit')).toHaveText(/\.$/);
  await expect(page.locator('.app-verdict')).not.toContainText(/\b(?:Confidence|High|Low|Go)\b/);
  await expect(page.locator('dialog[open], [role="dialog"]:visible, .app-firstrun, .port-dialog[open]')).toHaveCount(0);
  await expect(page.getByText(/sign in to continue|create (an )?account|passkey|take a tour|welcome to/i).filter({visible: true})).toHaveCount(0);
}
for (const [query, region, profile] of cells) test(`${query} → ${profile} → useful brief`, async ({page, pageErrors}, info) => {
  const cdp = await prepare(page, region);
  try {
    const started = Date.now(); await page.goto('/?ui=v2');
    await port(page, query); await page.locator(`[data-profile="${profile}"]`).click();
    await expect(page).toHaveURL(/\/map\?/);
    expect(new URL(page.url()).searchParams.get('region')).toBe(region);
    expect(new URL(page.url()).searchParams.get('profile')).toBe(profile);
    await verdict(page, started, `${info.project.name}/${query}/${profile}`);
    expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('funnel-actions')!))).toEqual(['input', 'Enter', 'click']);
    if (query === 'morro' && profile === 'boat') {
      await page.evaluate(() => sessionStorage.setItem('funnel-actions', '[]'));
      const returning = Date.now(); await page.goto('/'); await page.reload();
      await expect(page).toHaveURL(/\/map\?/);
      await verdict(page, returning, `${info.project.name}/returning`);
      expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('funnel-actions')!))).toEqual([]);
    }
    expect(pageErrors).toEqual([]);
  } finally { await cdp.send('Emulation.setCPUThrottlingRate', {rate: 1}); await cdp.detach(); }
});

test('cancelled port and late warm-up cannot replace the second choice', async ({page, pageErrors}) => {
  const cdp = await prepare(page, 'monterey-point-sur');
  let release!: () => void; const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/regions/morro-bay/region.json', async route => { await held; await route.continue(); });
  try {
    await page.goto('/?ui=v2'); await port(page, 'morro');
    await page.getByRole('button', {name: 'Change port'}).click();
    expect(await page.evaluate(key => localStorage.getItem(key), PORT_KEY)).toBeNull();
    await port(page, 'monterey');
    await expect(page.locator('.landing-step [role="status"]')).toHaveText('Monterey map files ready.');
    // What the cancelled port's warm-up (web/landing/region-warm.ts) reads after its region.json: the
    // files that must not be fetched once that port is left. Its own regions/morro-bay/region.json is
    // the request the route above holds, and the regional forecast is what the landing's own verdict
    // reads for the default region -- which is morro-bay as well -- so neither path names the warm-up
    // alone; the warm-up asks for them in the same batch as the files below, so leaving them out of the
    // watch costs no coverage. The landing's hero readout and verdict go on reading the default region
    // whatever port is chosen, and that traffic is not what this guarantee is about.
    const morro = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8'));
    const cancelledWarmUp = new Set(regionWarmList('morro-bay', morro)
      .filter(path => !path.endsWith('/region.json') && !path.startsWith('/api/'))
      .map(path => new URL(path, page.url()).href));
    expect([...cancelledWarmUp].map(href => new URL(href).pathname).sort()).toEqual([
      '/data/protected-areas.geojson', '/regions/morro-bay/atlas-marks.json', '/regions/morro-bay/coverage.json',
      '/regions/morro-bay/poster.svg', '/regions/morro-bay/search-plan-index.json', '/regions/morro-bay/shoreline-overview.geojson']);
    const late: string[] = []; page.on('request', r => { if (cancelledWarmUp.has(r.url())) late.push(r.url()); });
    release();
    await expect(page.locator('.landing-step [role="status"]')).toHaveText('Monterey map files ready.');
    await page.locator('[data-profile="boat"]').click();
    await expect(page).toHaveURL(/region=monterey-point-sur/); expect(late).toEqual([]); expect(pageErrors).toEqual([]);
  } finally { release(); await cdp.detach(); }
});

test('duplicate profile activation saves and navigates once without waiting for warm-up', async ({page, pageErrors}) => {
  const cdp = await prepare(page);
  await page.route('**/regions/morro-bay/atlas-marks.json', route => route.abort());
  let navigations = 0; page.on('framenavigated', frame => { if (frame === page.mainFrame() && new URL(frame.url()).pathname === '/map') navigations++; });
  try {
    const started = Date.now(); await page.goto('/?ui=v2'); await port(page, 'morro');
    await page.locator('[data-profile="boat"]').evaluate(button => { (button as HTMLElement).click(); (button as HTMLElement).click(); });
    await expect(page).toHaveURL(/\/map\?/); await verdict(page, started, 'duplicate');
    expect(navigations).toBe(1);
    expect(await page.evaluate(() => Number(sessionStorage.getItem('funnel-writes')))).toBe(1); expect(pageErrors).toEqual([]);
  } finally { await cdp.detach(); }
});
// Spec edge 8 (Explore → default-region verdict) is voided by the t_d0a5b151 disposition of 2026-11-02:
// Explore deliberately opens coast=central with no region (e2e/v2-landing.spec.ts), so it has no brief.
test('Save-Data skips warm-up and reaches a brief', async ({page, pageErrors}) => {
  const cdp = await prepare(page);
  await page.addInitScript(() => Object.defineProperty(navigator, 'connection', {value: {saveData: true}}));
  const requests: string[] = []; page.on('request', r => requests.push(r.url()));
  try {
    const started = Date.now(); await page.goto('/?ui=v2');
    await port(page, 'morro');
    await expect(page.locator('.landing-step [role="status"]')).toHaveText('');
    expect(requests.filter(p => /atlas-marks|search-plan-index|poster\.svg|\/api\/forecast/.test(p))).toEqual([]);
    await page.locator('[data-profile="boat"]').click(); await expect(page).toHaveURL(/profile=boat/);
    await verdict(page, started, 'Save-Data'); expect(pageErrors).toEqual([]);
  } finally { await cdp.detach(); }
});
test('failed feeds give an honest unavailable lead instead of waiting forever', async ({page, pageErrors}) => {
  const cdp = await prepare(page);
  await page.route(/\/(?:api\/(?:forecast|daily|om\/)|feeds\/)/, route => route.fulfill({status: 503, json: {error: 'Synthetic unavailable'}}));
  try {
    const started = Date.now(); await page.goto('/?ui=v2'); await port(page, 'morro');
    await page.locator('[data-profile="boat"]').click(); await expect(page).toHaveURL(/\/map\?/);
    await expect(page.locator('.app-verdict-word').or(page.getByText('Readings unavailable.', {exact: true}))).toBeVisible({timeout: FUNNEL_BUDGET_MS});
    expect(Date.now() - started).toBeLessThanOrEqual(FUNNEL_BUDGET_MS);
    if (await page.locator('.app-verdict-word').count()) {
      await expect(page.locator('.app-verdict-word')).toHaveText('Unknown'); await expect(page.locator('.app-verdict-limit')).toHaveText(/\.$/);
    }
    expect(pageErrors).toEqual([]);
  } finally { await cdp.detach(); }
});
