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

// Private files are answered by an exact-URL table (origin + path), so a fixture for another dataset or another origin
// answers nothing: the request lands in `unmapped` and is aborted. Contract (F25-14 / SCA-233): the log holds every
// request for a /var/ path on ANY origin, as full URLs, so a wrong origin or path is visible; it is never pre-filtered
// to the intended path. Bug it catches: a layer that asks for the wrong dataset/origin while a broad `/var/chlorophyll/**`
// fixture still answers and a "starts with /var/" check still passes.
type Fixture = {status?: number; json?: unknown; body?: string};
const SST_PATH = '/var/maplayer-sst-1/sst-preview.json', CHL_PATH = '/var/chlorophyll/central-coast/chlorophyll.json';
const fixtureTable = (origin: string): Record<string, Fixture> => ({
  [origin + SST_PATH]: {json: sstDoc()},
  [origin + CHL_PATH]: {status: 404, body: 'missing'},
});
type V2 = {open(page: 'app', params?: Record<string, string>): Promise<void>};
async function open(page: Page, v2: V2, session: Record<string, unknown>, origin: string, fixtures: Record<string, Fixture> = fixtureTable(origin)) {
  await stubLiveFeeds(page);
  await page.route('**/api/session', route => route.fulfill({json: session}));
  const requested: string[] = [], unmapped: string[] = [];
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname.startsWith('/var/')) requested.push(url.href); });
  await page.route(url => url.pathname.startsWith('/var/'), route => {
    const fixture = fixtures[route.request().url()];
    if (!fixture) { unmapped.push(route.request().url()); return route.abort(); }
    return route.fulfill(fixture.json === undefined ? {status: fixture.status, body: fixture.body} : {json: fixture.json});
  });
  await v2.open('app', AREA);
  return {requested, unmapped, since: (baseline: number) => requested.slice(baseline)};
}
const layers = async (page: Page) => { if (page.viewportSize()!.width < 1024) await page.getByRole('button', {name: 'Layers', exact: true}).click(); };

test('a visitor and a non-admin account see no private previews and make no request for them', async ({page, pageErrors, v2, baseURL}) => {
  const origin = new URL(baseURL!).origin;
  for (const session of [{signIn: '/#account', signedIn: false}, {signIn: '/#account', signedIn: true, is_admin: false, user: {id: 'u1', display_name: 'Skipper'}}]) {
    const log = await open(page, v2, session, origin);
    await layers(page);
    // The bottom sheet is also a named group "Layers" (RF1925-6), so name the rail itself.
    await expect(page.locator('.ui-rail[role="group"][aria-label="Layers"]')).toBeVisible();
    await expect(page.getByText('Private previews')).toHaveCount(0);
    await expect(page.locator('[data-preview]')).toHaveCount(0);
    expect(log.requested).toEqual([]);
    expect(log.unmapped).toEqual([]);
  }
  expect(pageErrors).toEqual([]);
});

// Owner flow: startup baseline, then each toggle must add exactly the intended full URL (origin + path), once.
async function ownerFlow(page: Page, v2: V2, origin: string, size: {width: number; height: number}, name: string, fixtures?: Record<string, Fixture>) {
  await page.setViewportSize(size);
  const log = await open(page, v2, {signIn: '/#account', signedIn: true, is_admin: true, user: {id: 'owner', display_name: 'G'}}, origin, fixtures);
  await layers(page);
  await expect(page.getByText('Private previews')).toBeVisible();
  for (const label of ['Seafloor relief (medium)', 'Wind trails', 'Surface currents (HF radar)', 'Sea-surface temperature', 'Chlorophyll (satellite)']) {
    await expect(page.getByRole('button', {name: new RegExp(`^${label.replace(/[()]/g, '\\$&')}`)}).first()).toHaveAttribute('aria-pressed', 'false');
  }
  expect(log.requested, 'nothing for these layers on first paint').toEqual([]);
  await expect(page.locator('[data-preview]')).toHaveCount(0);
  const baseline = log.requested.length;

  await page.getByRole('button', {name: /^Sea-surface temperature/}).first().click();
  const row = page.locator('[data-preview="sst"]');
  await expect(row).toHaveAttribute('data-state', 'ready');
  await expect(row).toContainText('Analysis');
  expect(log.since(baseline), 'sst toggle requests exactly its own file, once').toEqual([origin + SST_PATH]);
  const afterSst = log.requested.length;

  await page.getByRole('button', {name: /^Chlorophyll \(satellite\)/}).first().click();
  await expect(page.locator('[data-preview="chlorophyll"]')).toHaveAttribute('data-state', 'unavailable');
  await expect(page.locator('[data-preview="chlorophyll"]')).toContainText('Nothing is drawn');
  expect(log.since(afterSst), 'chlorophyll toggle requests exactly its own file, once').toEqual([origin + CHL_PATH]);
  expect(log.unmapped, 'every private request is answered by its own exact-URL fixture').toEqual([]);

  // The legend and rail stay inside the viewport with no sideways scroll.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  if (SHOTS) {
    await page.getByText('Private previews').scrollIntoViewIfNeeded();
    await page.screenshot({path: `${SHOTS}/maplive-1-${name}-rail.png`});
    await page.locator('[data-preview="sst"]').scrollIntoViewIfNeeded();
    await page.screenshot({path: `${SHOTS}/maplive-1-${name}-legend.png`});
  }

  const afterChl = log.requested.length;
  await page.getByRole('button', {name: /^Sea-surface temperature/}).first().click();
  await expect(page.locator('[data-preview="sst"]')).toHaveCount(0);
  expect(log.since(afterChl), 'switching a preview off requests nothing').toEqual([]);
}

for (const [name, size] of [['phone-375', {width: 375, height: 812}], ['tablet-820', {width: 820, height: 1180}]] as const) {
  test(`owner: every preview is off at start, loads only when switched on, and fits at ${name}`, async ({page, pageErrors, v2, baseURL}) => {
    await ownerFlow(page, v2, new URL(baseURL!).origin, size, name);
    expect(pageErrors).toEqual([]);
  });
}

// Negative controls (local synthetic, not a server authorization test): the chlorophyll fixture is mapped to another
// dataset, then to another origin. The app still asks for its intended file, which neither fixture answers, so the flow
// must fail on the unmapped request. Before SCA-233 the broad `/var/chlorophyll/**` fixture answered both and passed.
test('negative control: a chlorophyll fixture for another dataset or origin fails the flow', async ({page, v2, baseURL}) => {
  const origin = new URL(baseURL!).origin;
  const wrong: Record<string, string> = {
    'another dataset': origin + '/var/chlorophyll/north-coast/chlorophyll.json',
    'another origin': 'http://127.0.0.1:9' + CHL_PATH,
  };
  for (const [what, url] of Object.entries(wrong)) {
    const fixtures: Record<string, Fixture> = {[origin + SST_PATH]: {json: sstDoc()}, [url]: {status: 404, body: 'missing'}};
    await expect(ownerFlow(page, v2, origin, {width: 820, height: 1180}, 'negative', fixtures), what)
      .rejects.toThrow(/every private request is answered by its own exact-URL fixture/);
  }
});
