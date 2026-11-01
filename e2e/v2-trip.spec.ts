// The v2 trip planner, GPX export and offline pack (FE-51, docs/plans/front-end/dev-plan.md).
// The planner (web/planner.ts, #602) keeps v1's controls and ids, so the ranked-export flow of
// e2e/ranked-export.spec.ts runs here against the v2 app with the same synthetic reefs, pin 01
// on the Chart included (#495); the same selection downloads the same GPX bytes from both shells (only the creation time
// differs); a mark card adds its spot; and a region saved from v2 opens offline from the
// pack, the app's page and files included.
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {readFile} from 'node:fs/promises';
import type {Page} from '@playwright/test';
import {chartCentre, test, expect} from './fixtures.ts';
import {stubLiveFeeds} from '../scripts/measure_startup.mjs';

const AREA = {region: 'morro-bay', presentation: 'chart'};
const NAME = 'Morro Bay & Avila';
// A returning visitor with a profile: the first-run choice never covers the map.
test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
});
type Feature = {type: 'Feature'; geometry: unknown; properties: {terrain: {score: number}} & Record<string, unknown>};

/** e2e/ranked-export.spec.ts's 25 screened reefs as the seafloor publication's export; `change` edits one and republishes. */
async function rankedReefs(page: Page) {
  await stubLiveFeeds(page);
  const expires_at = new Date(Date.now() + 86400000).toISOString();
  const features: Feature[] = Array.from({length: 25}, (_, i) => {
    const x = -121.17 + i * .007, y = 35.43;
    return {type: 'Feature', geometry: {type: 'Polygon', coordinates: [[[x, y], [x + .002, y], [x + .002, y + .002], [x, y + .002], [x, y]]]},
      properties: {id: 'test-reef-' + String(i).padStart(2, '0'), region: 'morro-bay', tier: 2, status: 'habitat', exportable: true, screen: {status: 'pass'},
        waypoint: {longitude: x + .001, latitude: y + .001}, source_ids: ['synthetic-fixture'], source_year: 2008, resolution_m: 2,
        metric_support_fraction: .96, interpolation_mask: 'unknown', substrate: {known_fraction: 1, independent_confirmation: false},
        independent_evidence: [], depth_min_ft: 90, depth_max_ft: 120, terrain: {score: 90 - i, grade: 'A', relief_210m_m: 12}, fit: {lingcod: 3, 'rockfish-reef': 3}, area_ha: 2}};
  });
  let bytes = JSON.stringify({type: 'FeatureCollection', region: 'morro-bay', expires_at, features});
  const manifest = () => ({region: 'morro-bay', status: 'ready', archive_sha256: 'a'.repeat(64), expires_at, export_file: 'habitat-export.geojson.gz',
    export_sha256: createHash('sha256').update(gzipSync(bytes)).digest('hex'), export_bytes: gzipSync(bytes).length, export_decoded_bytes: Buffer.byteLength(bytes)});
  await page.route('**/feeds/tiles/seafloor/manifest-morro-bay.json', r => r.fulfill({json: manifest()}));
  // CI6-01B: the planner ranks only places the land/water check (web/land-water.ts) confirms as water. Most of these
  // synthetic reefs lie offshore in zoom-12 tiles NOAA did not serve, which the check leaves unknown and withholds, so
  // the committed index is extended with those tiles as clean water. The check itself is covered by
  // e2e/land-water.spec.ts and tests/test_land_water.mjs; served tiles keep their committed cells.
  await page.route('**/regions/morro-bay/land-water.json', async route => {
    const response = await route.fetch(), index = await response.json(), n = 2 ** index.constants.tile_zoom;
    for (let i = 0; i < 25; i++) {
      const lon = -121.17 + i * .007 + .001, lat = 35.431;
      const key = `${index.constants.tile_zoom}/${Math.floor((lon + 180) / 360 * n)}/${Math.floor((1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * n)}`;
      index.tiles[key] ??= `w${index.constants.grid ** 2}`;
    }
    await route.fulfill({response, json: index});
  });
  const gate = {hold: false, release: () => {}, started: () => {}};
  await page.route('**/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz', async r => {
    if (gate.hold) { gate.hold = false; gate.started(); await new Promise<void>(resolve => { gate.release = resolve; }); }
    return r.fulfill({contentType: 'application/gzip', body: gzipSync(bytes)});
  });
  return {gate, change() { features[0]!.properties.terrain.score = 89; bytes = JSON.stringify({type: 'FeatureCollection', region: 'morro-bay', expires_at, features}); }};
}

/** Click where a point draws on the Chart, from `?view=` (Web Mercator, 256 px tiles at that zoom, offset from where the Chart draws its centre: fixtures.ts `chartCentre`). */
async function clickChart(page: Page, at: {latitude: number; longitude: number}) {
  const [lat, lon, zoom] = new URL(page.url()).searchParams.get('view')!.split(',').map(Number) as [number, number, number];
  const world = 256 * 2 ** zoom, x = (l: number) => (l + 180) / 360 * world;
  const y = (l: number) => { const s = Math.sin(l * Math.PI / 180); return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * world; };
  const centre = await chartCentre(page);
  await page.mouse.click(centre.x + x(at.longitude) - x(lon), centre.y + y(at.latitude) - y(lat));
}

/** The account button: in the masthead, or (phone) in the sheet's footer with the sheet lifted to full (e2e/v2-account.spec.ts). */
async function accountMenu(page: Page, isMobile: boolean) {
  if (isMobile) {
    await page.locator('.ui-sheet-handle').focus();
    await page.keyboard.press('End');
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
  }
  const trigger = page.locator('.app-account-trigger');
  await trigger.scrollIntoViewIfNeeded();
  await trigger.click();
  return page.locator('.app-account-panel');
}
async function openPlan(page: Page, isMobile: boolean) {
  await (await accountMenu(page, isMobile)).getByRole('button', {name: /^Trip plan and GPX/}).click();
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeVisible();
  await expect(page.locator('#export-heading')).toBeFocused();
  expect(new URL(page.url()).hash).toBe('#export');
}
async function download(page: Page): Promise<string> {
  const [file] = await Promise.all([page.waitForEvent('download'), page.locator('#export-download').click()]);
  return readFile(await file.path(), 'utf8');
}
/**
 * The planner opens ready (SCJ-8): the 20 best reefs already chosen and today's date. Then Best available, as
 * ranked-export.spec.ts runs it: a cleared selection while loading wins, then the ranked set.
 */
async function rankBest(page: Page, gate: {hold: boolean; release: () => void; started: () => void}) {
  await expect(page.locator('#export-selection-count')).toHaveText('20 selected');
  await expect(page.locator('#export-scope-status')).toContainText('20 distinct reef spots');
  const today = await page.evaluate(() => new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date()));
  await expect(page.locator('#export-date')).toHaveValue(today);
  await expect(page.locator('#export-map')).toBeEnabled();
  gate.hold = true;
  const pending = new Promise<void>(resolve => { gate.started = resolve; });
  await page.locator('#export-best').click(); await pending;
  await page.locator('[data-scope="none"]').click(); gate.release();
  await expect(page.locator('#export-best')).toBeEnabled();
  await expect(page.locator('#export-selection-count')).toHaveText('0 selected');
  await expect(page.locator('#export-map')).toBeDisabled();
  await page.locator('#export-best').click();
  await expect(page.locator('#export-scope-status')).toContainText('20 distinct reef spots');
  await expect(page.locator('#export-selection-count')).toHaveText('20 selected');
  await expect(page.locator('#export-date')).toHaveValue(today);
}

test('the ranked export runs in v2: best reefs, complete outlines, a restored plan, and changed data require reranking', async ({page, pageErrors, v2, isMobile}, info) => {
  const reefs = await rankedReefs(page);
  await v2.open('app', {...AREA, diagnostics: '1'});
  await openPlan(page, isMobile);
  await rankBest(page, reefs.gate);
  await expect(page.locator('#export-spot-list')).toContainText('#1 · Strong · 90% confidence');
  await expect(page.locator('[data-layer="outlines"]')).toBeChecked();
  await expect(page.locator('[data-layer="alignments"]')).not.toBeChecked();
  await expect(page.locator('[data-layer="exclusions"]')).not.toBeChecked();
  const size = (await page.locator('#export-download').boundingBox())!;
  expect(size.height, 'a 44 px download button').toBeGreaterThanOrEqual(44);
  await v2.a11y('v2-trip');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: `test-results/${info.project.name}-v2-trip.png`});
  const gpx = await download(page);
  expect(gpx.match(/<wpt /g)).toHaveLength(20);
  expect(gpx.match(/<trk>/g)).toHaveLength(20);
  expect(gpx).toContain('<name>01 LR H3 C90% 90-120ft</name>');
  expect(gpx).toContain('lat="35.43" lon="-121.17"');
  expect(gpx).not.toContain('<rte>');
  await page.locator('#export-spot-list [data-spot]').first().uncheck();
  await page.locator('#export-search').fill('test-reef');
  await expect(page.locator('#export-spot-list [data-spot]')).toHaveCount(20);
  await page.locator('#export-spot-list [data-spot]').first().check();
  // The plan follows #export: a reload reopens it and restores the ranked reefs from the current publication.
  await page.reload();
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeVisible();
  await expect(page.locator('#export-scope-status')).toContainText('Saved ranked reefs restored');
  await expect(page.locator('#export-selection-count')).toHaveText('20 selected');
  // "Show ranked spots on map" closes the plan, moves the Chart to the ranked reefs and draws them as numbered pins (#495).
  await page.locator('#export-map').click();
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeHidden();
  await expect.poll(() => new URL(page.url()).searchParams.get('view')).toMatch(/^35\.43\d*,-121\.1\d*,1[01](?:\.\d+)?$/);
  expect(new URL(page.url()).hash).toBe('');
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-ranked', '20');
  await expect(chart, 'MapLibre drew the pins in view').toHaveAttribute('data-ranked-drawn', /^[1-9]\d*$/);
  // Pin 01, as ranked-export.spec.ts clicks it: a pin holding nearby spots zooms in until 01 stands alone and opens its card.
  const card = page.getByRole('region', {name: 'Selected mark'});
  await expect(async () => {
    await clickChart(page, {latitude: 35.431, longitude: -121.169});
    await expect(card.getByRole('heading')).toHaveText('#1 · 01 LR H3 C90% 90-120ft', {timeout: 1000});
  }).toPass({timeout: 30_000, intervals: [1000]});  // a second apart, never a double-click zoom
  await expect(card.locator('.ui-reading')).toHaveText('Habitat 3/3 · 90% evidence confidence');
  await v2.a11y('v2-trip-ranked');
  await card.getByRole('button', {name: 'Review & export'}).click();
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeVisible();
  await expect(page.locator('#export-heading')).toBeFocused();
  expect(new URL(page.url()).hash).toBe('#export');
  reefs.change();
  await page.locator('#export-download').click();
  await expect(page.locator('#export-action-status')).toHaveText('Reef data changed. Select Best available again before exporting.');
  // Escape closes the plan and drops #export.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeHidden();
  await expect.poll(() => new URL(page.url()).hash, 'the dialog\'s close event drops the hash').toBe('');
  expect(pageErrors).toEqual([]);
});

// FE-61: v1's planner, which this compared byte for byte, is gone; the v2 file keeps v1's 20 ranked reef spots.
test('the ranked selection downloads a GPX of the 20 ranked reef spots', async ({page, pageErrors, v2, isMobile}) => {
  const reefs = await rankedReefs(page);
  await v2.open('app', AREA);
  await openPlan(page, isMobile);
  await rankBest(page, reefs.gate);
  const fromV2 = await download(page);
  expect(fromV2).toMatch(/<time>[^<]+<\/time>/);
  expect(fromV2.match(/<wpt\b/g)?.length).toBe(20);
  expect(pageErrors).toEqual([]);
});

test('a reef mark joins the trip from its card, and GPX opens the plan with it', async ({page, pageErrors, v2, isMobile}) => {
  await stubLiveFeeds(page);
  await v2.open('app', {...AREA, spot: 'SC26-001'});
  const card = page.getByRole('region', {name: 'Selected mark'});
  await expect(card.getByRole('heading')).toHaveText('Southern rocky rise');
  // Morro Bay's atlas marks are research coordinates, so the card says what it saves (v1's wording).
  await card.getByRole('button', {name: 'Save research reference'}).click();
  await expect(card.getByRole('button', {name: 'Added to trip'})).toBeVisible();
  await expect((await accountMenu(page, isMobile)).getByRole('button', {name: 'Trip plan and GPX · 1 saved'})).toBeVisible();
  await page.keyboard.press('Escape');
  await card.getByRole('button', {name: 'GPX'}).click();
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeVisible();
  await expect(page.locator('#export-selection-count')).toHaveText('1 selected');
  await expect(page.locator('#export-validation')).toContainText('Research coordinates need explicit opt-in');
  await page.getByRole('button', {name: 'Close the trip plan'}).click();
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeHidden();
  expect(pageErrors).toEqual([]);
});

test('a Chart click saves a categorized user waypoint, restores it and exports standard GPX type', async ({page, pageErrors, v2, isMobile}) => {
  await stubLiveFeeds(page);
  const writes: string[] = [];
  page.on('request', request => { if (request.method() !== 'GET' && request.method() !== 'HEAD') writes.push(new URL(request.url()).pathname); });
  await v2.open('app', {...AREA, view: '35.43,-121.17,12'});
  await openPlan(page, isMobile);
  await page.locator('#waypoint-place').click();
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeHidden();
  await expect(page.getByRole('button', {name: 'Cancel waypoint'})).toBeVisible();
  if (isMobile) await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'peek');
  // Pick exposed Chart space, not a fixed geography that may be under mobile chrome.
  const canvas = page.locator('.app-chart canvas.maplibregl-canvas');
  const chart = (await canvas.boundingBox())!;
  if (isMobile) await canvas.click({position: {x: chart.width / 4, y: chart.height / 3}});
  else await clickChart(page, {latitude: 35.43, longitude: -121.17});
  const dialog = page.getByRole('dialog', {name: 'Trip plan and GPX'});
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Waypoint name').fill('Synthetic user marker');
  await dialog.getByLabel('Category', {exact: true}).selectOption('wreck');
  await dialog.getByRole('button', {name: 'Save waypoint', exact: true}).click();
  const points = dialog.getByRole('region', {name: 'Your waypoints'});
  await expect(points).toContainText('Synthetic user marker · wreck');
  await expect(page.locator('#export-research')).not.toBeChecked();
  await expect(page.locator('#export-download')).toBeEnabled();
  expect(await download(page)).toContain('<type>wreck</type>');
  await page.reload();
  await expect(points).toContainText('Synthetic user marker · wreck');
  const restored = await download(page);
  expect(restored).toContain('<name>Synthetic user marker</name>');
  expect(restored).toContain('<type>wreck</type>');
  await v2.a11y('v2-user-waypoint');
  await points.getByRole('button', {name: 'Remove waypoint Synthetic user marker'}).click();
  await expect(points).not.toContainText('Synthetic user marker');
  await expect(page.locator('#export-download')).toBeDisabled();
  expect(writes.filter(path => path.startsWith('/api/') && path !== '/api/telemetry')).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test.describe('offline', () => {
  test.use({serviceWorkers: 'allow'});
  test('a region saved from v2 opens offline from its pack, the app included', async ({page, context, pageErrors, v2, isMobile}) => {
    await stubLiveFeeds(page);
    const tideId = '9000002';
    await page.addInitScript(id => localStorage.setItem('skippercast-tide-station-v1.morro-bay', id), tideId);
    await page.route('**/mdapi/prod/webapi/stations.json?*', route => route.fulfill({json: {stations: [
      {id: tideId, name: 'Offline fixture station', lat: 35.36, lng: -120.85, type: 'R'},
    ]}}));
    await page.route('**/api/prod/datagetter?*', route => route.fulfill({json: {predictions: [
      {t: '2026-10-08 21:00', v: '2.3', type: 'H'}, {t: '2026-10-08 22:00', v: '1.2'},
    ]}}));
    await v2.open('app', AREA);
    await (await accountMenu(page, isMobile)).getByRole('button', {name: 'Save for offline'}).click();
    const dialog = page.getByRole('dialog', {name: 'Save for offline'});
    await expect(dialog.getByText('Nothing saved on this device yet.')).toBeVisible();
    await expect(dialog.getByRole('button', {name: 'Save coastal readings'})).toBeVisible();
    await v2.a11y('v2-offline');
    await dialog.getByRole('button', {name: `Save ${NAME} for offline`}).click();
    await expect(dialog.getByRole('status').first()).toContainText(`Saved ${NAME} · `, {timeout: 90_000});
    const tideKeys = await page.evaluate(async id => {
      const cacheName = (await caches.keys()).find(name => name.startsWith('sc-pack-morro-bay-'));
      if (!cacheName) return [];
      return (await (await caches.open(cacheName)).keys()).map(request => request.url)
        .filter(url => new URL(url).hostname === 'api.tidesandcurrents.noaa.gov' && new URL(url).pathname.endsWith('/datagetter'))
        .map(url => new URL(url).searchParams).filter(params => params.get('station') === id)
        .map(params => params.get('interval')).sort();
    }, tideId);
    expect(tideKeys).toEqual(['6', 'hilo']);
    await expect(dialog.locator('.app-offline-list li').first()).toContainText(new RegExp(`^${NAME}Saved (just now|\\d+ min ago) · `));
    await expect(dialog.locator('.app-offline-list li').first()).toContainText(/of 95 chart tiles · \d+ of 95 base map tiles \(zoom 8–12\)/);
    // The save registered the worker; once it controls the page, the pack answers offline.
    await page.waitForFunction(() => !!navigator.serviceWorker?.controller, null, {timeout: 30_000});
    await context.setOffline(true);
    await page.goto(v2.url('app', AREA));
    await expect(page).toHaveTitle(/SkipperCast/);
    await expect(page.locator('.app-stage')).toBeAttached({timeout: 30_000});
    await context.setOffline(false);
    expect(pageErrors).toEqual([]);
  });

  test('a region saved without a tide-station choice adds no NOAA predictions to its pack', async ({page, v2, isMobile}) => {
    await stubLiveFeeds(page);
    await page.route('**/mdapi/prod/webapi/stations.json?*', route => route.fulfill({json: {stations: []}}));
    await page.route('**/api/prod/datagetter?*', route => route.fulfill({json: {predictions: [{t: '2026-10-08 21:00', v: '2.3', type: 'H'}]}}));
    await v2.open('app', AREA);
    await (await accountMenu(page, isMobile)).getByRole('button', {name: 'Save for offline'}).click();
    const dialog = page.getByRole('dialog', {name: 'Save for offline'});
    await dialog.getByRole('button', {name: `Save ${NAME} for offline`}).click();
    await expect(dialog.getByRole('status').first()).toContainText(`Saved ${NAME} · `, {timeout: 90_000});

    const tidePackStations = await page.evaluate(async () => {
      const cacheName = (await caches.keys()).find(name => name.startsWith('sc-pack-morro-bay-'));
      if (!cacheName) return [];
      return (await (await caches.open(cacheName)).keys()).map(request => request.url)
        .filter(url => new URL(url).hostname === 'api.tidesandcurrents.noaa.gov' && new URL(url).pathname.endsWith('/datagetter'))
        .map(url => new URL(url).searchParams.get('station'));
    });
    expect([...new Set(tidePackStations)].sort()).toEqual(['9412110']);
  });
});
