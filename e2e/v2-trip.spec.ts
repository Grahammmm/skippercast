// The v2 trip planner, GPX export and offline pack (FE-51, docs/plans/front-end/dev-plan.md).
// The planner is v1's (web/trip.ts wraps dist/export-ui.js), so the ranked-export flow of
// e2e/ranked-export.spec.ts runs here against the v2 app with the same synthetic reefs; the
// same selection downloads the same GPX bytes from both shells (only the creation time
// differs); a mark card adds its spot; and a region saved from v2 opens offline from the
// pack, the app's page and files included.
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {readFile} from 'node:fs/promises';
import type {Page} from '@playwright/test';
import {test, expect, openMap} from './fixtures.ts';
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
  const gate = {hold: false, release: () => {}, started: () => {}};
  await page.route('**/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz', async r => {
    if (gate.hold) { gate.hold = false; gate.started(); await new Promise<void>(resolve => { gate.release = resolve; }); }
    return r.fulfill({contentType: 'application/gzip', body: gzipSync(bytes)});
  });
  return {gate, change() { features[0]!.properties.terrain.score = 89; bytes = JSON.stringify({type: 'FeatureCollection', region: 'morro-bay', expires_at, features}); }};
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
/** Best available, as ranked-export.spec.ts runs it: a cleared selection while loading wins, then the ranked set. */
async function rankBest(page: Page, gate: {hold: boolean; release: () => void; started: () => void}) {
  await expect(page.locator('#export-map')).toBeDisabled();
  gate.hold = true;
  const pending = new Promise<void>(resolve => { gate.started = resolve; });
  await page.locator('#export-best').click(); await pending;
  await page.locator('[data-scope="none"]').click(); gate.release();
  await expect(page.locator('#export-best')).toBeEnabled();
  await expect(page.locator('#export-selection-count')).toHaveText('0 selected');
  await page.locator('#export-best').click();
  await expect(page.locator('#export-scope-status')).toContainText('20 distinct reef spots');
  await expect(page.locator('#export-selection-count')).toHaveText('20 selected');
}

test('the ranked export runs in v2: best reefs, complete outlines, a restored plan, and changed data require reranking', async ({page, pageErrors, v2, isMobile}, info) => {
  const reefs = await rankedReefs(page);
  await v2.open('app', AREA);
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
  // "Show ranked spots on map" closes the plan and moves the Chart to the ranked reefs.
  await page.locator('#export-map').click();
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeHidden();
  await expect.poll(() => new URL(page.url()).searchParams.get('view')).toMatch(/^35\.43\d*,-121\.1\d*,1[01](?:\.\d+)?$/);
  expect(new URL(page.url()).hash).toBe('');
  await openPlan(page, isMobile);
  reefs.change();
  await page.locator('#export-download').click();
  await expect(page.locator('#export-action-status')).toHaveText('Reef data changed. Select Best available again before exporting.');
  // Escape closes the plan and drops #export.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', {name: 'Trip plan and GPX'})).toBeHidden();
  await expect.poll(() => new URL(page.url()).hash, 'the dialog\'s close event drops the hash').toBe('');
  expect(pageErrors).toEqual([]);
});

test('the same ranked selection downloads the same GPX bytes from v2 and v1', async ({page, pageErrors, v2, isMobile}) => {
  const reefs = await rankedReefs(page);
  await v2.open('app', AREA);
  await openPlan(page, isMobile);
  await rankBest(page, reefs.gate);
  const fromV2 = await download(page);
  // v1 reads the same draft (one per region in this browser), restores it, and ranks the same reefs again.
  await openMap(page, '/?ui=v1&region=morro-bay#export');
  await expect(page.locator('#export-scope-status')).toContainText('Saved ranked reefs restored');
  await page.locator('#export-best').click();
  await expect(page.locator('#export-scope-status')).toContainText('20 distinct reef spots');
  const fromV1 = await download(page);
  const created = /<time>[^<]+<\/time>/;
  expect(fromV2).toMatch(created);
  expect(fromV2.replace(created, '')).toBe(fromV1.replace(created, ''));
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

test.describe('offline', () => {
  test.use({serviceWorkers: 'allow'});
  test('a region saved from v2 opens offline from its pack, the app included', async ({page, context, pageErrors, v2, isMobile}) => {
    await stubLiveFeeds(page);
    await v2.open('app', AREA);
    await (await accountMenu(page, isMobile)).getByRole('button', {name: 'Save for offline'}).click();
    const dialog = page.getByRole('dialog', {name: 'Save for offline'});
    await expect(dialog.getByText('Nothing saved on this device yet.')).toBeVisible();
    await expect(dialog.getByRole('button', {name: 'Save coastal readings'})).toBeVisible();
    await v2.a11y('v2-offline');
    await dialog.getByRole('button', {name: `Save ${NAME} for offline`}).click();
    await expect(dialog.getByRole('status').first()).toContainText(`Saved ${NAME} · `, {timeout: 90_000});
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
});
