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
