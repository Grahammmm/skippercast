// The v2 map stage (FE-71, docs/plans/front-end/design.md § 3A.2): one stage,
// three presentations. The terrain is packages/coast's renderer mounted in the
// stage's shadow root by dynamic import; Chart is MapLibre (FE-11) over the
// synthetic basemap fixture (tests/fixtures/basemap/tiny.pmtiles, served by
// range here, since the published archive lives on R2) and the region's
// committed shoreline. The Fish Worker bridge (/api/coast, /coast-data) never answers
// here: either it is held open, so the terrain stays mounted and loading, or it
// fails, so the stage must return to Chart with v1's message.
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {inflateSync} from 'node:zlib';
import type {Page, Route} from '@playwright/test';
import {expect, test} from './fixtures.ts';

const UNAVAILABLE = 'Coastal graphics are unavailable. The chart, forecasts and trip tools remain usable.';
const PLACE = {region: 'morro-bay', profile: 'spear', target: 'rockfish', hour: '2030-01-02T03:00Z', habitat: 'reef:r1', view: '35.38000,-120.88000,12'};

// `v2` first: its catch-all /feeds/ stub is registered before the basemap routes, which take precedence.
test.beforeEach(async ({page, v2: _v2}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await serveBasemap(page);
});

/** Hold every coast data request open: the renderer mounts and waits for its terrain. */
const holdCoastData = (page: Page) => page.route(/\/(?:api\/coast|coast-data)\//, () => { /* never answered */ });
const failCoastData = (page: Page) => page.route(/\/(?:api\/coast|coast-data)\//, route => route.fulfill({status: 503, json: {error: 'Offline map test'}}));
const TINY = readFileSync(new URL('../tests/fixtures/basemap/tiny.pmtiles', import.meta.url));
const ARCHIVE = 'tiles/basemap/ca-coast-fixture.pmtiles';
/** FE-10's manifest and archive, answered by byte range as R2 answers the PMTiles reader. */
async function serveBasemap(page: Page) {
  await page.route('**/feeds/tiles/basemap/manifest.json', route => route.fulfill({json: {schema_version: 1, key: ARCHIVE}}));
  await page.route(`**/feeds/${ARCHIVE}`, route => {
    const range = /bytes=(\d+)-(\d+)/.exec(route.request().headers().range ?? '');
    if (!range) return route.fulfill({body: TINY, headers: {'Accept-Ranges': 'bytes'}});
    const start = Number(range[1]), end = Math.min(Number(range[2]), TINY.length - 1);
    return route.fulfill({status: 206, body: TINY.subarray(start, end + 1),
      headers: {'Content-Range': `bytes ${start}-${end}/${TINY.length}`, 'Accept-Ranges': 'bytes', 'Content-Type': 'application/octet-stream'}});
  });
}
const viewOf = (value: string | null) => { const [latitude, longitude, zoom] = (value ?? '').split(',').map(Number); return {latitude, longitude, zoom}; };
const toggle = (page: Page, name: string) => page.getByRole('group', {name: 'Map presentation'}).getByRole('button', {name, exact: true});
const params = (page: Page) => Object.fromEntries(new URL(page.url()).searchParams);

test('3D shows the terrain; switching to 2D keeps place, target, profile, hour and selection', async ({page, pageErrors, v2}) => {
  const three: string[] = [];
  page.on('request', request => { if (/\/assets\/(?:viewer|embed|terrain)\./.test(request.url())) three.push(request.url()); });
  await holdCoastData(page);
  await v2.open('app', {...PLACE, presentation: 'chart'});
  await expect(page.locator('.app-map')).toBeVisible();
  expect(three, 'Chart loads no renderer').toEqual([]);

  await toggle(page, '3D').click();
  const host = page.locator('.app-terrain');
  await expect(host).toBeVisible();
  await expect(host).toHaveAttribute('data-coast-theme', 'tokens');
  // The managed renderer marks its scene with the perspective it draws.
  const perspective = () => host.evaluate(el => el.shadowRoot?.getElementById('scene')?.dataset.perspective ?? null);
  await expect.poll(perspective).toBe('3d');
  await expect(toggle(page, '3D')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.app-map')).toBeHidden();
  expect(three.length, 'the renderer loads on the first terrain choice').toBeGreaterThan(0);
  expect(params(page)).toMatchObject({...PLACE, presentation: '3d'});

  await toggle(page, '2D').click();
  await expect.poll(perspective).toBe('2d');
  expect(params(page)).toMatchObject({...PLACE, presentation: '2d'});
  await page.goBack();
  await expect.poll(perspective).toBe('3d');
  await toggle(page, 'Chart').click();
  await expect(host).toBeHidden();
  await expect(page.locator('.app-map')).toBeVisible();
  expect(params(page)).toMatchObject({...PLACE, presentation: 'chart'});
  await v2.a11y('v2-map-chart');
  expect(pageErrors).toEqual([]);
});

test('the terrain chrome sits clear of the stage chrome and axe is clean', async ({page, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {...PLACE, presentation: '3d'});
  await expect.poll(() => page.locator('.app-terrain').evaluate(el => [...(el.shadowRoot?.querySelectorAll('link') ?? [])].every(l => !!(l as HTMLLinkElement).sheet) && !!el.shadowRoot?.getElementById('scene'))).toBe(true);
  await expect(page.locator('.app-stage-note')).toBeEmpty();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width, 'no horizontal page scroll').toBeLessThanOrEqual(page.viewportSize()!.width);
  await v2.a11y('v2-map-terrain');
});

test('with WebGL disabled the stage shows Chart and v1\'s message, and axe is clean', async ({page, v2}) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
      return /webgl/i.test(kind) ? null : (original as (...a: unknown[]) => unknown).call(this, kind, ...rest);
    } as typeof original;
  });
  await holdCoastData(page);
  await v2.open('app', {...PLACE, presentation: '3d'});
  await expect(page.getByRole('status').filter({hasText: UNAVAILABLE})).toBeVisible();
  await expect(page.locator('.app-map')).toBeVisible();
  await expect(page.locator('.app-terrain')).toBeHidden();
  await expect(toggle(page, 'Chart')).toHaveAttribute('aria-pressed', 'true');
  await expect(toggle(page, '3D')).toBeDisabled();
  expect(params(page).presentation, 'the link keeps the request').toBe('3d');
  await v2.a11y('v2-map-no-webgl');
});

test('unavailable terrain data returns the stage to Chart with v1\'s message', async ({page, v2}) => {
  await failCoastData(page);
  await v2.open('app', {...PLACE, presentation: '2d'});
  await expect(page.getByRole('status').filter({hasText: UNAVAILABLE})).toBeVisible();
  await expect(page.locator('.app-map')).toBeVisible();
  await expect(toggle(page, '2D')).toBeDisabled();
});

test('a region without terrain offers Chart only and says why', async ({page, v2}) => {
  await v2.open('app', {region: 'santa-cruz-monterey-bay', presentation: '3d'});
  await expect(page.locator('.app-stage-note')).toHaveText('No reviewed coastal terrain covers this region yet.');
  await expect(toggle(page, 'Chart')).toHaveAttribute('aria-pressed', 'true');
  for (const name of ['2D', '3D']) {
    await expect(toggle(page, name)).toBeDisabled();
    await expect(toggle(page, name)).toHaveAttribute('aria-describedby', 'app-stage-note');
  }
});

// The time dock (FE-12): the horizon is the 169 whole hours from now; the dock's hour reaches the renderer.
const HOUR_MS = 3_600_000;
const hourParam = (ms: number) => new Date(ms).toISOString().slice(0, 16) + 'Z';
const horizonStart = () => Math.floor(Date.now() / HOUR_MS) * HOUR_MS;
const urlHour = (page: Page) => new URL(page.url()).searchParams.get('hour');

test('the terrain receives the dock\'s hour', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: '3d'});
  const host = page.locator('.app-terrain');
  await expect(host).toHaveAttribute('data-hour', /^\d{4}-\d{2}-\d{2}T\d{2}:00:00\.000Z$/);
  // Tomorrow is a full day: its chip, then the slider's first or last hour.
  await page.getByRole('group', {name: 'Day'}).getByRole('button').nth(1).evaluate(b => (b as HTMLButtonElement).click());
  await expect.poll(() => urlHour(page)).not.toBeNull();
  const slider = page.locator('input[aria-label="Hour"]');
  const atStart = await slider.inputValue() === '0';
  await slider.focus();
  await page.keyboard.press(atStart ? 'End' : 'Home');
  await expect(page.locator('.ui-dock-readout')).toHaveText(atStart ? '11 pm' : '12 am');
  const chosen = urlHour(page)!;
  await expect(host).toHaveAttribute('data-hour', chosen.replace('Z', ':00.000Z'));
  expect(pageErrors).toEqual([]);
});

test('play steps hours, stops at the end of the horizon and pauses when the page is hidden', async ({page, pageErrors, v2, isMobile}) => {
  test.skip(isMobile, 'the play button is the desktop dock\'s');
  const end = horizonStart() + 168 * HOUR_MS;
  await v2.open('app', {region: 'morro-bay', hour: hourParam(end - 2 * HOUR_MS)});
  await page.getByRole('button', {name: 'Play'}).click();
  await expect(page.getByRole('button', {name: 'Pause'})).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', {name: 'Play'})).toBeVisible({timeout: 10_000});
  expect(Date.parse(urlHour(page)!), 'stopped on the horizon\'s last hour').toBeGreaterThanOrEqual(end);
  await page.waitForTimeout(1500);
  expect(Date.parse(urlHour(page)!)).toBeLessThanOrEqual(horizonStart() + 168 * HOUR_MS);

  await page.goto(v2.url('app', {region: 'morro-bay', hour: hourParam(horizonStart())}));
  await page.getByRole('button', {name: 'Play'}).click();
  await expect.poll(() => urlHour(page)).not.toBe(hourParam(horizonStart()));
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.getByRole('button', {name: 'Play'})).toHaveAttribute('aria-pressed', 'false');
  const paused = urlHour(page);
  await page.waitForTimeout(2500);
  expect(urlHour(page), 'no step while hidden').toBe(paused);
  expect(pageErrors).toEqual([]);
});

test('prefers-reduced-motion never auto-plays: the button steps one hour per press', async ({page, pageErrors, v2, isMobile}) => {
  test.skip(isMobile, 'the step button is the desktop dock\'s');
  await page.emulateMedia({reducedMotion: 'reduce'});
  const start = horizonStart();
  await v2.open('app', {region: 'morro-bay', hour: hourParam(start)});
  await expect(page.getByRole('button', {name: 'Play'})).toHaveCount(0);
  await page.getByRole('button', {name: 'Next hour'}).click();
  await expect.poll(() => urlHour(page)).toBe(hourParam(start + HOUR_MS));
  await page.waitForTimeout(2500);
  expect(urlHour(page), 'one press, one hour').toBe(hourParam(start + HOUR_MS));
  await v2.a11y('v2-dock-reduced-motion');
  expect(pageErrors).toEqual([]);
});

test('the Chart draws the basemap and the Morro Bay coastline with their attribution', async ({page, pageErrors, v2}) => {
  const fetched: string[] = [];
  page.on('response', response => { if (/ca-coast-fixture\.pmtiles|shoreline\.geojson/.test(response.url())) fetched.push(`${response.status()} ${new URL(response.url()).pathname}`); });
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', view: '35.38000,-120.88000,11'});
  const chart = page.locator('.app-chart');
  await expect(chart.locator('canvas.maplibregl-canvas')).toBeVisible();
  await expect(chart.locator('.maplibregl-ctrl-attrib')).toContainText('© OpenStreetMap contributors, © Protomaps');
  await expect(chart.locator('.maplibregl-ctrl-attrib')).toContainText('NOAA NGS · CUSP shoreline');
  await expect(chart.locator('.maplibregl-ctrl-scale')).toHaveText(/nm|ft/);
  await expect.poll(() => fetched.some(f => f.startsWith('206 /feeds/tiles/basemap/')), {message: 'the basemap is read by range'}).toBe(true);
  await expect.poll(() => fetched).toContain('200 /regions/morro-bay/shoreline.geojson');
  await expect(chart).toHaveAttribute('data-view', '35.38000,-120.88000,11');
  await expect(page.locator('[data-unavailable]')).toHaveCount(0);
  await v2.a11y('v2-map-chart-engine');
  expect(pageErrors).toEqual([]);
});

test('a failing coastline marks only its layer unavailable; the basemap keeps drawing', async ({page, v2}) => {
  await page.route('**/regions/morro-bay/shoreline.geojson', route => route.fulfill({status: 503, body: 'Offline map test'}));
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart'});
  if (page.viewportSize()!.width < 1024) await page.getByRole('button', {name: 'Layers'}).click();
  await expect(page.locator('[data-unavailable="coastline"]')).toHaveText('Coastline unavailable.');
  await expect(page.locator('[data-unavailable]')).toHaveCount(1);
  await expect(page.locator('.app-chart .maplibregl-ctrl-attrib')).toContainText('© OpenStreetMap contributors, © Protomaps');
  await expect(page.locator('.app-chart canvas.maplibregl-canvas')).toBeVisible();
});

test('Chart → 3D → Chart keeps the centre within one zoom step', async ({page, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {...PLACE, presentation: 'chart'});
  const chart = page.locator('.app-chart');
  await expect(chart.locator('canvas.maplibregl-canvas')).toBeVisible();
  const before = viewOf(await chart.getAttribute('data-view'));
  await toggle(page, '3D').click();
  await expect(page.locator('.app-terrain')).toBeVisible();
  await toggle(page, 'Chart').click();
  await expect(chart).toBeVisible();
  const after = viewOf(await chart.getAttribute('data-view'));
  expect(Math.abs(after.latitude - before.latitude)).toBeLessThan(0.01);
  expect(Math.abs(after.longitude - before.longitude)).toBeLessThan(0.01);
  expect(Math.abs(after.zoom - before.zoom)).toBeLessThanOrEqual(1);
  expect(viewOf(params(page).view).zoom, 'the link keeps the place').toBeCloseTo(before.zoom, 0);
});

// Seafloor (FE-14): a synthetic publication (tests/fixtures/seafloor/chart.pmtiles, built by
// build-chart.mjs) with its manifest and the regional ledger whose SHA-256 the manifest names,
// answered as the Worker answers them. Candidate A covers the view's centre, offshore.
const SEAFLOOR = readFileSync(new URL('../tests/fixtures/seafloor/chart.pmtiles', import.meta.url));
const SEAFLOOR_LEDGER = JSON.stringify({region: 'morro-bay', reaches: [
  {id: 'morro-bay-fx1', region: 'morro-bay', status: 'habitat-screened'}, {id: 'morro-bay-fx2', region: 'morro-bay', status: 'habitat-held-for-screen'}]});
const SEAFLOOR_PLACE = {region: 'morro-bay', presentation: 'chart', view: '35.35300,-120.94800,13', target: 'lingcod'};
const HELD = 'Seafloor habitat is held for screening review';
const EXPIRED = 'Seafloor screening has expired and is being refreshed';
const byRange = (route: Route, bytes: Buffer) => {
  const range = /bytes=(\d+)-(\d+)/.exec(route.request().headers().range ?? '');
  if (!range) return route.fulfill({body: bytes, headers: {'Accept-Ranges': 'bytes'}});
  const start = Number(range[1]), end = Math.min(Number(range[2]), bytes.length - 1);
  return route.fulfill({status: 206, body: bytes.subarray(start, end + 1),
    headers: {'Content-Range': `bytes ${start}-${end}/${bytes.length}`, 'Accept-Ranges': 'bytes', 'Content-Type': 'application/octet-stream'}});
};
async function serveSeafloor(page: Page, manifest: Record<string, unknown> = {}): Promise<string[]> {
  const archive: string[] = [], expires = new Date(Date.now() + 86_400_000).toISOString();
  await page.route('**/feeds/tiles/seafloor/manifest-morro-bay.json', route => route.fulfill({headers: {'Cache-Control': 'no-store'}, json: {
    schema_version: 1, region: 'morro-bay', status: 'ready', expires_at: expires, archive_sha256: 'f'.repeat(64),
    ledger_sha256: createHash('sha256').update(SEAFLOOR_LEDGER).digest('hex'), source_attribution: ['Fixture Survey Lab'],
    source_use_notice: 'Retain source-specific terms and credits.', planning_notice: 'Planning only. Not a navigation chart. Check current CDFW regulations.', ...manifest}}));
  await page.route('**/feeds/tiles/seafloor/regions/morro-bay/ledger.json', route => route.fulfill({body: SEAFLOOR_LEDGER, contentType: 'application/json'}));
  await page.route('**/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles', route => { archive.push(route.request().url()); return byRange(route, SEAFLOOR); });
  return archive;
}
const narrow = (page: Page) => page.viewportSize()!.width < 1024;
/** The rail and legend: on a phone they are the sheet's Layers panel. */
const showLayers = async (page: Page) => { if (narrow(page)) await page.getByRole('button', {name: 'Layers', exact: true}).click(); };
const hideLayers = async (page: Page) => { if (narrow(page)) await page.getByRole('button', {name: 'Done'}).click(); };
const clickCentre = async (page: Page) => {
  const box = (await page.locator('.app-chart canvas.maplibregl-canvas').boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
};

test('Seafloor draws screened candidates and cells in Chart, names its surveys, and toggling removes its layers', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  const archive = await serveSeafloor(page);
  await v2.open('app', {...SEAFLOOR_PLACE, layers: 'seafloor'});
  await expect(page.locator('.app-chart canvas.maplibregl-canvas')).toBeVisible();
  await expect.poll(() => archive.length, {message: 'the archive is read by range once the publication is admitted'}).toBeGreaterThan(0);
  // The candidate under the centre opens the card: nominal depth, survey and year, then basis, datum and credits.
  await expect(async () => {
    await clickCentre(page);
    await expect(page.locator('.app-mark h2')).toHaveText('Habitat candidate, unverified', {timeout: 1000});
  }).toPass();
  await expect(page.locator('.app-mark-kind')).toHaveText('Terrain grade A · fits lingcod habitat 3 of 3');
  await expect(page.locator('.app-mark .ui-reading')).toHaveText('41–90 ft nominal');
  await expect(page.locator('.app-mark-source')).toHaveText('Survey fixture-survey-2m · 2010 · 2 m grid');
  const basis = page.locator('.app-mark .ui-popover-body');
  await expect(basis).toContainText('Habitat candidate, unverified. Nominal depth (NAVD88); verify on your sounder.');
  await expect(basis).toContainText('Fixture Survey Lab Synthetic test credit; never survey data.');

  await showLayers(page);
  const row = page.locator('.app-legend-seafloor');
  await expect(row.locator('[data-surveys="seafloor"]')).toHaveText('Surveys fixture-survey-2m (2010), fixture-survey-2m (unknown)');
  await expect(row.locator('[data-reason="seafloor"]')).toHaveText('2 candidates · 2 unranked in view');
  await expect(row.locator('.app-legend-title')).toHaveText('Physical habitat fit, not catch probability');
  await expect(row.locator('.app-key')).toHaveCount(7);
  await row.getByRole('group', {name: 'Colour seafloor by'}).getByRole('button', {name: 'Terrain grade'}).click();
  await expect(row.locator('.app-legend-title')).toHaveText('Terrain grade');
  await expect(row.locator('.app-key').first()).toHaveAttribute('data-tone', 'strong');
  await expect(row).toContainText('A · most rugged terrain');
  await v2.a11y('v2-map-seafloor');

  // Off: its layers leave the map, the card that showed one of its candidates closes, and the same click finds nothing.
  await page.locator('.ui-rail-item', {hasText: 'Seafloor'}).getByRole('button', {name: /Seafloor/}).click();
  await expect.poll(() => params(page).layers).not.toContain('seafloor');
  await expect(row).toHaveCount(0);
  await expect(page.locator('.app-mark')).toHaveCount(0);
  await hideLayers(page);
  await clickCentre(page);
  await page.waitForTimeout(300);
  await expect(page.locator('.app-mark')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('A held seafloor publication draws nothing and says why', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  const archive = await serveSeafloor(page, {status: 'held'});
  await v2.open('app', {...SEAFLOOR_PLACE, layers: 'seafloor'});
  await showLayers(page);
  await expect(page.locator('[data-reason="seafloor"]')).toHaveText(HELD);
  await expect(page.locator('.app-legend-seafloor .app-key')).toHaveCount(0);
  expect(archive, 'a held publication never opens its archive').toEqual([]);
  await v2.a11y('v2-map-seafloor-held');
  expect(pageErrors).toEqual([]);
});

test('A seafloor publication that expires while drawn hides its candidates with v1\'s message', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await serveSeafloor(page, {expires_at: new Date(Date.now() + 20_000).toISOString()});
  await v2.open('app', {...SEAFLOOR_PLACE, layers: 'seafloor'});
  await expect(page.locator('.app-chart canvas.maplibregl-canvas')).toBeVisible();
  await expect(async () => {
    await clickCentre(page);
    await expect(page.locator('.app-mark h2')).toHaveText('Habitat candidate, unverified', {timeout: 1000});
  }).toPass();
  // At expiry the layer hides before it asks for a fresh publication; the card that showed a candidate closes.
  await expect(page.locator('.app-mark')).toHaveCount(0, {timeout: 30_000});
  await showLayers(page);
  await expect(page.locator('[data-reason="seafloor"]')).toHaveText(EXPIRED);
  await expect(page.locator('.app-legend-seafloor .app-key')).toHaveCount(0);
  await hideLayers(page);
  await clickCentre(page);
  await page.waitForTimeout(300);
  await expect(page.locator('.app-mark')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

// Protected areas (FE-19): the committed region files, always drawn on the Chart. BUCHON is a
// point well inside Point Buchon SMR (about 1 km from its edges), so a click at the canvas centre lands in it.
const BUCHON = '35.24178,-120.91053';
const mapAttr = async (page: Page, name: string) => Number(await page.locator('.app-chart').getAttribute(name));

test('protected areas draw with the ds582 credit, are named from zoom 11 and open their card with the official rules page', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', layers: 'none', view: `${BUCHON},10`});
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-mpa', 'complete');
  await expect.poll(() => mapAttr(page, 'data-mpa-drawn'), {message: 'outlines drawn in view'}).toBeGreaterThan(0);
  await expect(chart).toHaveAttribute('data-mpa-labels', '0');
  await expect(chart.locator('.maplibregl-ctrl-attrib')).toContainText('CDFW ds582 · CC BY 4.0');

  await page.goto(v2.url('app', {region: 'morro-bay', presentation: 'chart', layers: 'none', view: `${BUCHON},11`}));
  await expect.poll(() => mapAttr(page, 'data-mpa-labels'), {message: 'names placed at zoom 11'}).toBeGreaterThan(0);
  const box = (await chart.locator('canvas.maplibregl-canvas').boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  const card = page.locator('.app-mark');
  await expect(card.locator('h2')).toHaveText('Point Buchon State Marine Reserve');
  await expect(card.locator('.app-mark-kind')).toHaveText('State Marine Reserve');
  await expect(card.locator('.ui-reading')).toHaveText('CCR Title 14, Section 632 (b) (93)');
  await expect(card.locator('.app-mark-source')).toHaveText('CDFW ds582 · checked 2026-09-21');
  await expect(card.getByRole('link', {name: /^Regulations/})).toHaveAttribute('href', 'https://wildlife.ca.gov/Conservation/Marine/MPAs');

  await showLayers(page);
  const row = page.locator('.app-legend-mpa');
  await expect(row.locator('.app-mpa-note')).toHaveText('CDFW ds582 snapshot for this region, checked 2026-09-21.');
  await expect(row.getByRole('link', {name: 'Official rules and boundaries (CDFW)'})).toHaveAttribute('href', 'https://wildlife.ca.gov/Conservation/Marine/MPAs');
  await v2.a11y('v2-map-mpas');
  expect(pageErrors).toEqual([]);
});

test('a region its snapshot does not cover, or boundaries that fail to load, say an area without an outline may still be protected', async ({page, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {region: 'bodega-point-reyes', presentation: 'chart', layers: 'none'});
  await expect(page.locator('.app-chart')).toHaveAttribute('data-mpa', 'incomplete');
  await showLayers(page);
  await expect(page.locator('.app-legend-mpa .app-mpa-note')).toHaveText('The boundary snapshot is incomplete for this region; an area without an outline may still be protected.');

  await page.route('**/data/protected-areas.geojson', route => route.fulfill({status: 503, body: 'Offline map test'}));
  await page.goto(v2.url('app', {region: 'morro-bay', presentation: 'chart', layers: 'none'}));
  await expect(page.locator('.app-chart')).toHaveAttribute('data-mpa', 'unavailable');
  await showLayers(page);
  await expect(page.locator('.app-legend-mpa .app-mpa-note')).toHaveText('Boundaries did not load, so none are drawn; an area without an outline may still be protected.');
  await expect(page.locator('[data-unavailable="mpas"]'), 'the row speaks for the layer').toHaveCount(0);
});

// FE-18: atlas reef marks on the Chart and the one mark card. SC26-001 sits alone (the next mark is
// 750 m away), so a click at the chart's centre, with the view on it, picks it.
const MARK = {id: 'SC26-001', name: 'Southern rocky rise', view: '35.164314,-120.843179,14'};

test('clicking a reef mark sets ?spot=, drops ?habitat= and opens its card; closing returns focus to the chart', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', profile: 'boat', target: 'lingcod', habitat: 'reef:r1', view: MARK.view});
  const chart = page.locator('.app-chart');
  await expect(chart.locator('canvas.maplibregl-canvas')).toBeVisible();
  await expect(chart).toHaveAttribute('data-marks', /^[1-9]\d*$/);
  const box = (await chart.boundingBox())!;
  await expect(async () => {
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    expect(params(page).spot).toBe(MARK.id);
  }).toPass({timeout: 20_000, intervals: [1000]});  // a second apart, never a double-click zoom
  expect(params(page).habitat, 'one selection at a time').toBeUndefined();
  const card = page.getByRole('region', {name: 'Selected mark'});
  const heading = card.getByRole('heading', {name: MARK.name});
  await expect(heading).toBeFocused();
  await expect(card.locator('.app-mark-kind')).toHaveText('Reef mark · grade A · ~135–184 ft');
  await expect(card.locator('.ui-reading')).toHaveText('Fits lingcod habitat 3 of 3');
  await expect(card.locator('.app-mark-source')).toHaveText('Avila / Point Buchon · surveyed 2008 · atlas 2026-09-27');
  await expect(card.locator('.app-mark-rules')).toHaveText('Screened against protected areas with 2992 m clearance in the atlas of 2026-09-27; check current rules before you fish. CDFW ocean fishing regulations');
  await expect(card.locator('.app-mark-rules').getByRole('link', {name: /^CDFW ocean fishing regulations/})).toHaveAttribute('href', 'https://wildlife.ca.gov/Fishing/Ocean/Regulations');
  const close = card.getByRole('button', {name: 'Clear selection'});
  const size = (await close.boundingBox())!;
  expect(Math.min(size.width, size.height), 'a 44 px close button').toBeGreaterThanOrEqual(44);
  await v2.a11y('v2-map-mark-card');
  await close.click();
  await expect(card).toHaveCount(0);
  expect(params(page).spot).toBeUndefined();
  await expect(chart.locator('canvas.maplibregl-canvas')).toBeFocused();
  expect(pageErrors).toEqual([]);
});

test('a shared ?spot= names its mark in the terrain too, and Escape clears it', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: '3d', target: 'lingcod', spot: MARK.id});
  const card = page.getByRole('region', {name: 'Selected mark'});
  await expect(card.getByRole('heading')).toHaveText(MARK.name);
  await expect(card.locator('.ui-reading')).toHaveText('Fits lingcod habitat 3 of 3');
  await expect(card.getByRole('heading')).not.toBeFocused();
  await card.getByRole('button', {name: 'Clear selection'}).focus();
  await page.keyboard.press('Escape');
  await expect(card).toHaveCount(0);
  expect(params(page).spot).toBeUndefined();
  expect(pageErrors).toEqual([]);
});

// Currents (FE-15): a synthetic WCOFS packet on a 0.04° grid off Morro Bay, three-hourly native
// frames around now, answered for the bound place's ocean snapshot; the rest of the bridge is held.
const CURRENT_VIEW = '35.32000,-120.90000,11';
async function serveOcean(page: Page) {
  const now = Date.now(), three = 3 * HOUR_MS, first = Math.floor(now / three) * three - three, iso = (ms: number) => new Date(ms).toISOString();
  const cells = [];
  // Seventeen columns reach -120.60, over the basemap fixture's land (its tile's east half, east of -120.76).
  for (let j = 0; j < 9; j++) for (let i = 0; i < 17; i++) {
    const lon = +(-121.24 + i * 0.04).toFixed(6), lat = +(35.16 + j * 0.04).toFixed(6), uMs = 0.15 + i * 0.03, vMs = 0.12 - j * 0.02;
    cells.push({lat, lon, uMs, vMs, speedKnots: Math.hypot(uMs, vMs) * 1.943844492, towardDeg: (Math.atan2(uMs, vMs) * 180 / Math.PI + 360) % 360});
  }
  const wcofs = {id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS surface forecast', url: 'https://example.test/wcofs', fetchedAt: iso(now - 600_000),
    issuedAt: iso(now - three), sampleAt: null, nativeResolutionKm: 4, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true,
    attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Surface only.', frames: [0, 1, 2, 3].map(k => ({validAt: iso(first + k * three), cells}))};
  await page.route('**/api/coast/ocean', route => route.fulfill({json: {schemaVersion: 1, countyId: 'slo', generatedAt: iso(now - 300_000), currents: [wcofs], cloud: null, sources: []}}));
}
const flow = (page: Page) => page.locator('.app-chart canvas.chart-flow--dash');
/** Drawn pixels of the still canvas inside and outside the fixture's land (lon > -120.76, lat 35.18–35.47), 8 px kept clear of its edge. */
const flowOnLand = (page: Page, view: string) => page.evaluate(view => {
  const [lat0, lon0, zoom] = view.split(',').map(Number) as [number, number, number];
  const c = document.querySelector<HTMLCanvasElement>('canvas.chart-flow--base')!, w = c.width, h = c.height, world = 512 * 2 ** (zoom - 1);
  const mercator = (lat: number) => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
  const x = (lon: number) => w / 2 + (lon - lon0) / 360 * world, y = (lat: number) => h / 2 - (mercator(lat) - mercator(lat0)) / (2 * Math.PI) * world;
  const [east, top, bottom] = [x(-120.76) + 8, y(35.47) + 8, y(35.18) - 8], data = c.getContext('2d')!.getImageData(0, 0, w, h).data;
  let land = 0, water = 0;
  for (let py = 0; py < h; py++) for (let px = 0; px < w; px++) if (data[(py * w + px) * 4 + 3]) { if (px > east && py > top && py < bottom) land++; else water++; }
  return {land, water};
}, view);
const openLayers = async (page: Page) => { if (page.viewportSize()!.width < 1024) await page.getByRole('button', {name: 'Layers'}).click(); };
const baseSelect = (page: Page) => page.locator('.app-rail-base').getByRole('combobox', {name: 'Base'});

test('Currents draw the bound forecast as animated streamlines, read on click and follow ?current=', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await serveOcean(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', view: CURRENT_VIEW, current: 'wcofs'});
  await expect(flow(page)).toHaveAttribute('data-motion', 'animated');
  expect(Number(await flow(page).getAttribute('data-paths')), 'streamlines over the field').toBeGreaterThan(10);
  const drawn = await flowOnLand(page, CURRENT_VIEW);
  expect(drawn.land, 'the land mask clips paths, arrowheads and source dots').toBe(0);
  expect(drawn.water).toBeGreaterThan(1000);
  // A click on open water inside the field reads the blended current.
  const box = (await page.locator('.app-chart canvas.maplibregl-canvas').boundingBox())!;
  // Left of the desktop rail, above the mobile sheet's peek.
  await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.4);
  await expect(page.locator('.app-mark h2')).toHaveText('Surface current');
  await expect(page.locator('.app-mark .ui-reading')).toHaveText(/^\d\.\d\d kt toward \d{1,3}° true$/);
  await expect(page.locator('.app-mark-source')).toHaveText('NOAA WCOFS surface forecast · issued 3 h ago');

  await openLayers(page);
  const entry = page.locator('.ui-rail-item', {hasText: 'Currents'});
  await expect(entry.locator('.ui-rail-note')).toHaveText(/^forecast \w{3} \d{1,2} [ap]m$/);
  await expect(page.locator('.app-legend-currents .ui-popover-body')).toHaveText(/^NOAA WCOFS surface forecast, about 4 km, issued 3 h ago; arrows follow the toward-bearing and their motion is illustrative\.$/);
  await v2.a11y('v2-map-currents');

  const source = entry.getByRole('combobox', {name: 'Source'});
  await source.selectOption('hfr-6');
  await expect.poll(() => params(page).current).toBe('hfr-6');
  await expect(flow(page)).toHaveAttribute('data-paths', '0');
  await expect(page.locator('[data-reason="currents"]')).toHaveText('Currents unavailable: no fresh Observed HF radar · 6 km frame for this hour.');
  await source.selectOption('off');
  await expect.poll(() => params(page).current).toBe('off');
  await expect(entry.getByRole('button', {name: /Currents/})).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('.app-legend-currents')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('Currents stand still under reduced motion and pause while the page is hidden', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await serveOcean(page);
  await page.emulateMedia({reducedMotion: 'reduce'});
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', view: CURRENT_VIEW, current: 'wcofs'});
  await expect(flow(page)).toHaveAttribute('data-motion', 'still');
  expect(Number(await flow(page).getAttribute('data-paths'))).toBeGreaterThan(10);
  await page.emulateMedia({reducedMotion: 'no-preference'});
  await expect(flow(page)).toHaveAttribute('data-motion', 'animated');
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(flow(page)).toHaveAttribute('data-motion', 'paused');
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', {configurable: true, get: () => false});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(flow(page)).toHaveAttribute('data-motion', 'animated');
  expect(pageErrors).toEqual([]);
});

test('Currents in a region no packet covers draw nothing and say so', async ({page, v2}) => {
  await v2.open('app', {region: 'santa-cruz-monterey-bay', presentation: 'chart', current: 'wcofs'});
  await openLayers(page);
  await expect(page.locator('.ui-rail-item', {hasText: 'Currents'}).locator('.ui-rail-note')).toHaveText('no packet for this region');
  await expect(page.locator('[data-reason="currents"]')).toHaveText('Currents unavailable: no local surface-current packet covers this region yet.');
  await expect(page.locator('canvas.chart-flow')).toHaveCount(0);
});

// FE-22: the cloud loop over a synthetic GOES index (goes-times.json's shape, times relative to now).
// nowCOAST answers with a 1×1 PNG; the CSP must let MapLibre fetch it, and only listed times are asked for.
const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
test('Clouds loops over the listed GOES frames only, each labelled with its time and age', async ({page, pageErrors, v2}) => {
  const MIN = 60_000, newest = Math.floor(Date.now() / MIN) * MIN - 7 * MIN;
  const times = Array.from({length: 24}, (_, i) => new Date(newest - (23 - i) * 5 * MIN).toISOString());
  await v2.feed('**/feeds/conditions/goes-times.json', {id: 'goes-longwave', kind: 'observation', observedAt: times.at(-1), fetchedAt: new Date(newest).toISOString(),
    availableTimes: times, layer: 'goes_longwave_imagery', url: 'https://nowcoast.noaa.gov/', attribution: 'NOAA / NESDIS · GOES', license: 'public-domain-us-gov', limitations: 'Observed frames only.'});
  const requested: string[] = [], blocked: string[] = [];
  await page.route('https://nowcoast.noaa.gov/**', route => {
    requested.push(new URL(route.request().url()).searchParams.get('time') ?? 'none');
    return route.fulfill({body: PIXEL, contentType: 'image/png', headers: {'Access-Control-Allow-Origin': '*'}});
  });
  page.on('console', message => { if (/Content Security Policy/i.test(message.text())) blocked.push(message.text()); });
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', layers: 'clouds', view: '35.38000,-120.88000,9'});
  if (page.viewportSize()!.width < 1024) {
    // The phone's rail and legend are the sheet's layers panel; the full sheet shows both.
    await page.getByRole('button', {name: 'Layers'}).click();
    await page.locator('.ui-sheet-handle').focus();
    await page.keyboard.press('End');
  }
  await expect.poll(() => requested.length, {message: 'MapLibre fetches the frames'}).toBeGreaterThan(0);
  expect(blocked, 'the CSP allows nowCOAST for MapLibre').toEqual([]);
  const note = page.locator('.app-legend-note');
  await expect(note).toHaveText(/^observed \d{1,2}:\d{2} [ap]m · (?:under 1|\d+) min ago$/);
  const first = await note.textContent();
  await expect(note, 'the loop steps').not.toHaveText(first!, {timeout: 10_000});
  await expect(page.locator('.ui-rail-item', {hasText: 'Clouds'}).locator('.ui-rail-note')).toHaveText(/^observed \d{1,2}:\d{2} [ap]m · \d+ min ago$/);
  await v2.a11y('v2-map-clouds');
  await page.getByRole('button', {name: 'Cloud loop'}).click();
  await expect(page.getByRole('button', {name: 'Cloud loop'})).toHaveAttribute('aria-pressed', 'false');
  const held = await note.textContent();
  await page.waitForTimeout(1500);
  await expect(note, 'held').toHaveText(held!);
  expect([...new Set(requested)].every(at => times.includes(at)), `only listed times: ${[...new Set(requested)].join(', ')}`).toBe(true);
  await page.locator('.ui-rail-item', {hasText: 'Clouds'}).locator('.ui-rail-toggle').click();
  await expect(note).toHaveCount(0);
  const count = requested.length;
  await page.waitForTimeout(1500);
  expect(requested.length, 'no frame is requested once Clouds is off').toBe(count);
  expect(pageErrors).toEqual([]);
});

// FE-23: the aerial base where the region's package offers it (region.json basemap.aerial). USGS answers with
// the 1×1 PNG; the CSP must let MapLibre fetch it, only the fixed NAIP service is asked, and only while it is on.
test('Aerial draws NAIP tiles from the fixed USGS service only while chosen, labelled with its dates', async ({page, pageErrors, v2}) => {
  const requested: string[] = [], blocked: string[] = [];
  await page.route('https://imagery.nationalmap.gov/**', route => {
    requested.push(route.request().url());
    return route.fulfill({body: PIXEL, contentType: 'image/png', headers: {'Access-Control-Allow-Origin': '*'}});
  });
  page.on('console', message => { if (/Content Security Policy/i.test(message.text())) blocked.push(message.text()); });
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', view: '35.38000,-120.88000,12'});
  await expect(page.locator('.app-chart canvas.maplibregl-canvas')).toBeVisible();
  await openLayers(page);
  // FE-20: the rail's one base select; Aerial is listed where the region's package offers it.
  const select = baseSelect(page);
  await expect(select.locator('option')).toHaveText(['Night', 'Chart detail', 'Aerial']);
  await page.waitForTimeout(1000);
  expect(requested, 'nothing is requested before Aerial is chosen').toEqual([]);

  await select.selectOption('aerial');
  await expect(page.locator('#app-rail-base-note')).toHaveText('flown 13–29 May 2022');
  await expect.poll(() => params(page).base).toBe('aerial');
  await expect.poll(() => requested.length, {message: 'MapLibre fetches the tiles'}).toBeGreaterThan(0);
  expect(blocked, 'the CSP allows the USGS host for MapLibre').toEqual([]);
  expect(requested.every(url => url.startsWith('https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?')),
    'the one NAIP service packages/coast names').toBe(true);
  await expect(page.locator('.app-chart .maplibregl-ctrl-attrib')).toContainText('USGS / USDA · NAIP aerial imagery (dated mosaic) · flown 13–29 May 2022');
  await v2.a11y('v2-map-aerial');

  await select.selectOption('night');
  await expect.poll(() => params(page).base).toBe('night');
  await expect(page.locator('.app-chart .maplibregl-ctrl-attrib')).not.toContainText('NAIP');
  const count = requested.length;
  await page.waitForTimeout(1500);
  expect(requested.length, 'no tile is requested once Aerial is off').toBe(count);
  expect(pageErrors).toEqual([]);
});

// FE-21: inside the Pecho Rock outline, 352 m from the nearest reef mark (45 px at zoom 14, clear of its 44 px target).
const PECHO_VIEW = '35.17586,-120.82186,14';
test('Charter fleet draws the charter grounds from the committed file, opens a ground\'s card, offers commercial AIS 2024 and leaves when off', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', profile: 'boat', target: 'lingcod', view: PECHO_VIEW, layers: 'fleet'});
  const chart = page.locator('.app-chart'), row = page.locator('.app-legend-fleet'), attribution = page.locator('.app-chart .maplibregl-ctrl-attrib');
  await expect(chart.locator('canvas.maplibregl-canvas')).toBeVisible();
  const card = page.getByRole('region', {name: 'Selected mark'});
  await expect(async () => {
    await clickCentre(page);
    await expect(card.getByRole('heading', {name: 'Pecho Rock'})).toBeVisible({timeout: 1000});
  }).toPass({timeout: 20_000, intervals: [1000]});
  await expect(card.locator('.app-mark-kind')).toHaveText('Charter-reported ground · Named landmark vicinity');
  await card.getByRole('button', {name: 'Clear selection'}).click();

  // The phone's rail and legend are the sheet's layers panel; the full sheet shows both.
  await showLayers(page);
  if (narrow(page)) { await page.locator('.ui-sheet-handle').focus(); await page.keyboard.press('End'); }
  await expect(row.locator('[data-stamp="charter-grounds"]')).toHaveText('2 named vicinities · no verified charter AIS');
  await expect(row.locator('.app-swatch[data-layer="charter-grounds"]')).toHaveCount(1);
  const option = page.getByRole('checkbox', {name: 'Commercial AIS 2024'});
  await expect(option).not.toBeChecked();
  await expect(page.getByRole('checkbox', {name: /· admin$/}), 'FE-24: no activity layers for a visitor').toHaveCount(0);
  await expect(attribution).not.toContainText('Global Fishing Watch');
  await option.check();
  await expect(row.locator('[data-reason="commercial-ais"]')).toHaveText('3 historical grid cells · Jul & Sep 2024 · depth unknown');
  await expect(attribution).toContainText('Global Fishing Watch · CC BY-NC 4.0');
  await v2.a11y('v2-map-fleet');

  await page.getByRole('button', {name: /^Charter fleet/}).click();
  await expect.poll(() => params(page).layers ?? '').not.toContain('fleet');
  await expect(row).toHaveCount(0);
  await expect(attribution).not.toContainText('Global Fishing Watch');
  expect(pageErrors).toEqual([]);
});

// FE-24: v1's access check answered as for an admin with both fleet flags on; one synthetic stop at the view's centre.
test('an admin gets the fleet activity layers under Charter fleet; a stop opens a card that says it is inferred from movement', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  const asked: string[] = [];
  await page.route('**/api/session', route => route.fulfill({json: {signedIn: true, is_admin: true}}));
  await page.route('**/api/fleet/map/**', route => {
    const url = new URL(route.request().url());
    asked.push(url.pathname);
    if (url.pathname.endsWith('/filters')) return route.fulfill({json: {region: url.searchParams.get('region')}});
    const [lat, lon] = PECHO_VIEW.split(',').map(Number);
    const features = url.pathname.endsWith('/events') ? [{type: 'Feature', id: 'ev-1', geometry: {type: 'Point', coordinates: [lon, lat]}, properties: {
      layer: 'event', id: 'ev-1', vessel_name: 'Test Boat', kind: 'drift-anchor', dwell_min: 49, local_date: '2026-09-01', started_at: '2026-09-01T16:00:00Z',
      ended_at: '2026-09-01T16:49:00Z', port_id: 'morro-bay', basis: 'inferred-from-movement', rights: 'internal', planning_only: false}}] : [];
    return route.fulfill({json: {type: 'FeatureCollection', features, meta: {next: null, trips: 0, ignored: []}}});
  });
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', profile: 'boat', target: 'lingcod', view: PECHO_VIEW, layers: 'fleet'});
  await expect(page.locator('.app-chart canvas.maplibregl-canvas')).toBeVisible();
  await showLayers(page);
  if (narrow(page)) { await page.locator('.ui-sheet-handle').focus(); await page.keyboard.press('End'); }
  const events = page.getByRole('checkbox', {name: 'Fleet events · admin'});
  await expect(events).not.toBeChecked();
  await expect(page.getByRole('checkbox', {name: /· admin$/})).toHaveCount(3);
  expect(asked, 'no layer loads until one is on').toEqual(['/api/fleet/map/filters']);
  await events.check();
  const row = page.locator('.app-legend-fleet');
  await expect(row.locator('[data-reason="fleet-activity"]')).toHaveText('1 stops · inferred from movement.');
  await expect(row.locator('.app-swatch[data-layer="fleet-events"]')).toHaveCount(1);
  await v2.a11y('v2-map-fleet-admin');
  await hideLayers(page);
  if (narrow(page)) { await page.locator('.ui-sheet-handle').focus(); await page.keyboard.press('Home'); }
  const card = page.getByRole('region', {name: 'Selected mark'});
  await expect(async () => {
    await clickCentre(page);
    await expect(card.getByRole('heading', {name: 'Test Boat'})).toBeVisible({timeout: 1000});
  }).toPass({timeout: 20_000, intervals: [1000]});
  await expect(card).toContainText('Inferred from movement (speed and track shape). Not a confirmed fishing stop or catch.');
  await card.getByRole('button', {name: 'Clear selection'}).click();
  await showLayers(page);
  await events.uncheck();
  await expect(row.locator('[data-reason="fleet-activity"]')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('a region without basemap.aerial offers no Aerial base, whatever ?base= says', async ({page, v2}) => {
  const requested: string[] = [];
  await page.route('https://imagery.nationalmap.gov/**', route => { requested.push(route.request().url()); return route.abort(); });
  await v2.open('app', {region: 'santa-cruz-monterey-bay', presentation: 'chart', base: 'aerial'});
  await expect(page.locator('.app-chart canvas.maplibregl-canvas')).toBeVisible();
  await openLayers(page);
  await expect(page.locator('.ui-rail-item', {hasText: 'Currents'})).toBeVisible();
  await expect(baseSelect(page).locator('option')).toHaveText(['Night', 'Chart detail']);
  await expect(baseSelect(page), 'what draws: the basemap alone').toHaveValue('night');
  await page.waitForTimeout(1000);
  expect(requested).toEqual([]);
});

// FE-20: the rail, the legend, ?layers= and the profile defaults; the base select (FE-23 review) and "Chart only" in the terrain.
const railToggle = (page: Page, name: string) => page.locator('.ui-rail-item', {hasText: name}).locator('.ui-rail-toggle');
const pressedEntries = (page: Page) => page.locator('.ui-rail-toggle[aria-pressed="true"] .ui-rail-label').allTextContents();

test('?layers= restores the rail, a Fish ?layer= opens its entry, and a profile switch applies that profile\'s layers', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', layers: 'seafloor,currents'});
  await showLayers(page);
  await expect.poll(() => pressedEntries(page)).toEqual(['Seafloor', 'Currents']);
  expect(params(page).current, 'the link names no source: its list turns on the forecast (#482)').toBeUndefined();
  await expect(page.locator('.app-legend-seafloor')).toBeVisible();
  await expect(page.locator('.app-legend-currents')).toBeVisible();
  await expect(page.locator('.app-legend .app-swatch:not([data-layer="mpas"])'), 'no colour key until a layer draws').toHaveCount(0);

  await page.locator('[aria-label="Profile"] button', {hasText: 'Shore'}).click();
  await expect.poll(() => params(page).profile).toBe('shore');
  expect(params(page).layers, 'a switch drops the link\'s list').toBeUndefined();
  await expect.poll(() => pressedEntries(page)).toEqual(['Water temp', 'Swell']);
  await page.locator('[aria-label="Profile"] button', {hasText: 'Boat'}).click();
  await expect.poll(() => pressedEntries(page), 'Boat\'s own list comes back').toEqual(['Seafloor', 'Currents']);

  await v2.open('app', {place: 'morro', layer: 'temperature'});
  await showLayers(page);
  await expect.poll(() => pressedEntries(page), 'Fish\'s layer=temperature').toEqual(['Water temp']);
  await expect(page.locator('.app-location')).toHaveAttribute('data-region', 'morro-bay');
  expect(pageErrors).toEqual([]);
});

test('in 3D the Chart\'s entries and the base read "Chart only" and never toggle hidden layers', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: '3d', layers: 'seafloor', view: PLACE.view});
  await expect(page.locator('.app-terrain')).toBeVisible();
  await showLayers(page);
  for (const name of ['Seafloor', 'Water temp', 'Swell', 'Clouds']) {
    await expect(railToggle(page, name), name).toBeDisabled();
    await expect(page.locator('.ui-rail-item', {hasText: name}).locator('.ui-rail-note'), name).toHaveText('Chart only');
  }
  await expect(railToggle(page, 'Currents'), 'Currents draw in the terrain too').toBeEnabled();
  await expect(railToggle(page, 'Charter fleet'), 'FE-82: the charter grounds drape on the terrain').toBeEnabled();
  await expect(page.locator('.app-legend-mpa'), 'FE-82: the protected areas drape on the terrain').toBeVisible();
  await expect(baseSelect(page)).toBeDisabled();
  await expect(page.locator('#app-rail-base-note')).toHaveText('Chart only');
  await expect(page.locator('.app-legend [data-reason="seafloor"]')).toHaveText('Chart only');
  await railToggle(page, 'Water temp').click({force: true});
  await page.waitForTimeout(300);
  expect(params(page).layers, 'a disabled entry changes nothing').toBe('seafloor');
  await v2.a11y('v2-map-terrain-rail');

  await hideLayers(page);
  await toggle(page, 'Chart').click();
  await showLayers(page);
  await expect(railToggle(page, 'Water temp')).toBeEnabled();
  await expect(railToggle(page, 'Seafloor')).toHaveAttribute('aria-pressed', 'true');
  await expect(baseSelect(page)).toBeEnabled();
  expect(pageErrors).toEqual([]);
});

test('a link\'s ?base=chart shows Chart detail in the base select, which can be chosen again after another base', async ({page, pageErrors, v2}) => {
  const enc: string[] = [];
  await page.route('https://gis.charttools.noaa.gov/**', route => { enc.push(route.request().url()); return route.fulfill({body: PIXEL, contentType: 'image/png', headers: {'Access-Control-Allow-Origin': '*'}}); });
  await page.route('https://imagery.nationalmap.gov/**', route => route.fulfill({body: PIXEL, contentType: 'image/png', headers: {'Access-Control-Allow-Origin': '*'}}));
  await holdCoastData(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', base: 'chart', view: '35.38000,-120.88000,12'});
  await expect(page.locator('.app-chart canvas.maplibregl-canvas')).toBeVisible();
  await showLayers(page);
  const select = baseSelect(page);
  await expect(select).toHaveValue('chart');
  await expect(page.locator('#app-rail-base-note')).toHaveText('from zoom 10');
  await expect.poll(() => enc.length, {message: 'the ENC display draws'}).toBeGreaterThan(0);
  await select.selectOption('aerial');
  await expect.poll(() => params(page).base).toBe('aerial');
  await select.selectOption('chart');
  await expect.poll(() => params(page).base).toBe('chart');
  await expect(page.locator('.app-chart .maplibregl-ctrl-attrib')).toContainText('NOAA ENC display');
  await v2.a11y('v2-map-base');
  expect(pageErrors).toEqual([]);
});

// FE-16: a synthetic coast report whose surface-temperature analysis covers the water off Morro Bay on
// a 0.02° grid (57.3 to 64.1 °F, so the legend reads 57–65 °F), analysed 30 hours ago and named by its
// own source status, as the bridge serves it; the rest of the bridge is held.
async function serveReport(page: Page, sst: Record<string, unknown> = {}) {
  const now = Date.now(), iso = (ms: number) => new Date(ms).toISOString(), points = [];
  for (let j = 0; j < 21; j++) for (let i = 0; i < 26; i++) {
    points.push({lon: +(-121.30 + i * 0.02).toFixed(6), lat: +(35.10 + j * 0.02).toFixed(6), tempF: +(57.3 + i * 0.2 + j * 0.09).toFixed(2), errorF: 0.6});
  }
  const source = {id: 'mur-surface-temperature', label: 'NASA JPL MUR · surface temperature analysis', url: 'https://example.test/mur', kind: 'analysis', outcome: 'ok', fetchedAt: iso(now - HOUR_MS)};
  await page.route('**/api/coast/report', route => route.fulfill({json: {schemaVersion: 1, countyId: 'slo', generatedAt: iso(now - 600_000),
    forecasts: [], observations: [], tides: [], tideEvents: [], alerts: [], catches: [], catchStatus: '', habitatStatus: '', sources: [source],
    visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null},
    spatial: {surfaceTemperature: {sourceId: source.id, analysedAt: iso(now - 30 * HOUR_MS), fetchedAt: source.fetchedAt, nativeResolutionDeg: 0.01,
      sampleSpacingDeg: 0.02, points, url: source.url, kind: 'analysis', ...sst}}}}));
}
/** The colour at a page point: a 1×1 screenshot, whose first PNG pixel is raw under every row filter. */
async function pixel(page: Page, x: number, y: number): Promise<number[]> {
  const png = await page.screenshot({clip: {x, y, width: 1, height: 1}}), data: Buffer[] = [];
  for (let at = 8; at < png.length; at += 12 + png.readUInt32BE(at)) if (png.toString('ascii', at + 4, at + 8) === 'IDAT') data.push(png.subarray(at + 8, at + 8 + png.readUInt32BE(at)));
  return [...inflateSync(Buffer.concat(data)).subarray(1, 4)];
}
const apart = (a: number[], b: number[]) => a.reduce((n, v, i) => n + Math.abs(v - b[i]!), 0);

test('Water temp draws the bound analysis as a field with contours, names it, reads it on click and leaves when off', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await serveReport(page);
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', view: CURRENT_VIEW, layers: 'none'});
  const box = (await page.locator('.app-chart canvas.maplibregl-canvas').boundingBox())!, x = box.x + box.width * 0.3, y = box.y + box.height * 0.35;
  // Open water before the layer is on, once the chart has settled.
  let water: number[] = [];
  await expect.poll(async () => { const a = await pixel(page, x, y); await page.waitForTimeout(400); water = await pixel(page, x, y); return apart(a, water); }).toBe(0);

  await openLayers(page);
  const entry = page.locator('.ui-rail-item', {hasText: 'Water temp'});
  await entry.getByRole('button', {name: /Water temp/}).click();
  await expect.poll(() => params(page).layers).toBe('water-temp');
  const row = page.locator('.app-legend-water-temp');
  await expect(row.locator('[data-range="water-temp"]')).toHaveText('57–65 °F');
  await expect(row.locator('[data-stamp="water-temp"]')).toHaveText(/^NASA JPL MUR · analysis \w{3} \d{1,2} · 30 h old$/);
  await expect(row.locator('.ui-popover-body')).toHaveText(/^NASA JPL MUR daily analysis on a 0\.01° grid sampled every 0\.02°, for \w{3} \d{1,2} \(30 h old\), with an analysis error of 0\.6 °F\. Surface water only, neither bottom temperature nor a forecast; masked land and missing cells stay blank\.$/);
  await expect(entry.locator('.ui-rail-note')).toHaveText(/^analysis \w{3} \d{1,2} · 30 h old$/);
  await expect(page.locator('[data-unavailable="water-temp"]')).toHaveCount(0);
  await v2.a11y('v2-map-water-temp');
  if (narrow(page)) await page.getByRole('button', {name: 'Done'}).click();
  await expect.poll(async () => apart(await pixel(page, x, y), water), {message: 'the field is drawn over the water'}).toBeGreaterThan(60);

  // A click on the field reads the analysis there, with its error, date and product.
  await page.mouse.click(x, y);
  await expect(page.locator('.app-mark h2')).toHaveText('Surface temperature');
  await expect(page.locator('.app-mark .ui-reading')).toHaveText(/^(?:5[7-9]|6[0-5])\.\d °F · analysis error 0\.6 °F$/);
  await expect(page.locator('.app-mark-source')).toHaveText(/^NASA JPL MUR · analysis \w{3} \d{1,2} · 30 h old$/);

  // Off: the field, its contours and the reading of it go.
  await openLayers(page);
  await entry.getByRole('button', {name: /Water temp/}).click();
  await expect.poll(() => params(page).layers).toBe('none');
  await expect(row).toHaveCount(0);
  await expect(page.locator('.app-mark')).toHaveCount(0);
  if (narrow(page)) await page.getByRole('button', {name: 'Done'}).click();
  // The phone's sheet may rest at another height now, and its shadow tints the water by a few levels.
  await expect.poll(async () => apart(await pixel(page, x, y), water), {message: 'the water shows again'}).toBeLessThan(12);
  expect(pageErrors).toEqual([]);
});

test('Water temp draws nothing for a stale analysis or a region no report covers, and says why', async ({page, v2}) => {
  await holdCoastData(page);
  await serveReport(page, {analysedAt: new Date(Date.now() - 80 * HOUR_MS).toISOString()});
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', view: CURRENT_VIEW, layers: 'water-temp'});
  await openLayers(page);
  await expect(page.locator('.ui-rail-item', {hasText: 'Water temp'}).locator('.ui-rail-note')).toHaveText(/^no fresh analysis · last \w{3} \d{1,2}$/);
  await expect(page.locator('[data-reason="water-temp"]')).toHaveText(/^Water temp unavailable: the latest NASA JPL MUR analysis, for \w{3} \d{1,2}, is past its 72-hour age limit\.$/);
  await expect(page.locator('[data-range="water-temp"]')).toHaveCount(0);

  await page.goto(v2.url('app', {region: 'santa-cruz-monterey-bay', presentation: 'chart', layers: 'water-temp'}));
  await openLayers(page);
  await expect(page.locator('.ui-rail-item', {hasText: 'Water temp'}).locator('.ui-rail-note')).toHaveText('no analysis for this region');
  await expect(page.locator('[data-reason="water-temp"]')).toHaveText('Water temp unavailable: no local surface-temperature analysis covers this region yet.');
});

// FE-17: a synthetic regional forecast feed whose NOAA GFS-Wave grid (3 × 3 points 0.2° apart) lies over the
// water in CURRENT_VIEW, from a run issued six hours before the current hour. The primary swell alternates
// between about 3 and 7 ft from hour to hour, its period crosses 12 and 13 s, and it comes from the west-northwest.
async function serveForecast(page: Page, {region = 'morro-bay', issuedHoursAgo = 6, points = 'grid'}: {region?: string; issuedHoursAgo?: number; points?: 'grid' | 'scattered'} = {}) {
  const now = Date.now(), issued = horizonStart() - issuedHoursAgo * HOUR_MS, times = Array.from({length: 60}, (_, k) => issued / 1000 + k * 3600);
  const requested: [string, number, number][] = [], data: unknown[] = [];
  for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) {
    requested.push([`p-${j}-${i}`, +(35.10 + j * 0.2 + (points === 'scattered' ? i * 0.01 : 0)).toFixed(2), +(-121.30 + i * 0.2).toFixed(2)]);
    data.push({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', swell_wave_height: 'ft', swell_wave_period: 's', swell_wave_direction: '°'},
      hourly: {time: times, swell_wave_height: times.map((t, k) => 3 + (k % 2) * 4 + i * 0.3 + j * 0.2), swell_wave_period: times.map(() => 11.5 + i), swell_wave_direction: times.map(() => 285 + j * 5)}});
  }
  await page.route(new RegExp(`/api/forecast\\?region=${region}$`), route => route.fulfill({json: {region_id: region, requested_points: requested, retrieved: now - 600_000,
    models: {ncep_gfswave016: {data, meta: {last_run_initialisation_time: issued / 1000, data_end_time: times.at(-1)}}}}}));
}

test('Swell draws the model grid as a field with period lines and strokes, names the run, follows the hour and leaves when off', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  await serveForecast(page);
  // Tomorrow has all 24 hours, so the slider can always step.
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', view: CURRENT_VIEW, layers: 'none', hour: hourParam(horizonStart() + 24 * HOUR_MS)});
  // Inside the grid and clear of the legend, which grows over the chart's lower left while Swell is on.
  const box = (await page.locator('.app-chart canvas.maplibregl-canvas').boundingBox())!, x = box.x + box.width * 0.3, y = box.y + box.height * 0.25;
  let water: number[] = [];
  await expect.poll(async () => { const a = await pixel(page, x, y); await page.waitForTimeout(400); water = await pixel(page, x, y); return apart(a, water); }).toBe(0);

  await openLayers(page);
  const entry = page.locator('.ui-rail-item', {hasText: 'Swell'});
  await entry.getByRole('button', {name: /Swell/}).click();
  await expect.poll(() => params(page).layers).toBe('swell');
  const row = page.locator('.app-legend-swell'), stamp = row.locator('[data-stamp="swell"]');
  await expect(row.locator('[data-range="swell"]')).toHaveText(/^\d\.\d–\d\.\d ft · 11\.5–13\.5 s · from WNW$/);
  await expect(row.locator('[data-scale="swell"]')).toHaveText('0 ft to 15+ ft');
  await expect(stamp).toHaveText(/^NOAA GFS-Wave model forecast · run \w{3} \d{1,2}, \d{1,2} [ap]m · 6 h old · valid \w{3} \w{3} \d{1,2}, \d{1,2} [ap]m$/);
  await expect(row.locator('.ui-popover-body')).toContainText('A model forecast, not a buoy observation.');
  await expect(entry.locator('.ui-rail-note')).toHaveText(/^valid \w{3} \d{1,2} [ap]m · run 6 h old$/);
  await expect(page.locator('[data-unavailable="swell"]')).toHaveCount(0);
  await v2.a11y('v2-map-swell');
  const before = await stamp.textContent();
  if (narrow(page)) await page.getByRole('button', {name: 'Done'}).click();
  let drawn: number[] = [];
  await expect.poll(async () => apart(drawn = await pixel(page, x, y), water), {message: 'the field is drawn over the water'}).toBeGreaterThan(40);

  // The next (or previous) hour: about 4 ft apart, so new pixels and a new valid hour.
  const slider = page.locator('input[aria-label="Hour"]');
  await slider.focus();
  await page.keyboard.press(await slider.inputValue() === await slider.getAttribute('max') ? 'ArrowLeft' : 'ArrowRight');
  await expect.poll(async () => apart(await pixel(page, x, y), drawn), {message: 'the texture follows the hour'}).toBeGreaterThan(30);
  await openLayers(page);
  await expect(stamp).not.toHaveText(before!);
  if (narrow(page)) await page.getByRole('button', {name: 'Done'}).click();

  // A click on the field reads the model there (on a phone, south-west of the reef marks the probe sits among).
  await page.mouse.click(...(narrow(page) ? [box.x + box.width * 0.12, box.y + box.height * 0.36] : [x, y]) as [number, number]);
  await expect(page.locator('.app-mark h2')).toHaveText('Primary swell');
  await expect(page.locator('.app-mark .ui-reading')).toHaveText(/^\d\.\d ft · 1[123]\.\d s · from WNW \d{3}°$/);
  await expect(page.locator('.app-mark-source')).toHaveText(/^NOAA GFS-Wave · run \w{3} \d{1,2}, \d{1,2} [ap]m · 6 h old · valid /);

  await openLayers(page);
  await entry.getByRole('button', {name: /Swell/}).click();
  await expect.poll(() => params(page).layers).toBe('none');
  await expect(row).toHaveCount(0);
  await expect(page.locator('.app-mark')).toHaveCount(0);
  if (narrow(page)) await page.getByRole('button', {name: 'Done'}).click();
  await expect.poll(async () => apart(await pixel(page, x, y), water), {message: 'the water shows again'}).toBeLessThan(12);
  expect(pageErrors).toEqual([]);
});

test('Swell draws nothing for a stale run or points that form no grid, and says why', async ({page, v2}) => {
  await holdCoastData(page);
  await serveForecast(page, {issuedHoursAgo: 40});
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', view: CURRENT_VIEW, layers: 'swell'});
  await openLayers(page);
  await expect(page.locator('.ui-rail-item', {hasText: 'Swell'}).locator('.ui-rail-note')).toHaveText(/^no fresh forecast · run \w{3} \d{1,2}, \d{1,2} [ap]m$/);
  await expect(page.locator('[data-reason="swell"]')).toHaveText(/^Swell unavailable: the latest NOAA GFS-Wave run, of \w{3} \d{1,2}, \d{1,2} [ap]m, is past its 36-hour age limit\.$/);
  await expect(page.locator('[data-range="swell"]')).toHaveCount(0);

  await serveForecast(page, {region: 'santa-cruz-monterey-bay', points: 'scattered'});
  await page.goto(v2.url('app', {region: 'santa-cruz-monterey-bay', presentation: 'chart', layers: 'swell'}));
  await openLayers(page);
  await expect(page.locator('.ui-rail-item', {hasText: 'Swell'}).locator('.ui-rail-note')).toHaveText('no forecast grid for this region');
  await expect(page.locator('[data-reason="swell"]')).toHaveText('Swell unavailable: this region\'s forecast points do not form a grid, so no field is drawn.');
});
