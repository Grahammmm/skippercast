// The v2 map stage (FE-71, docs/plans/front-end/design.md § 3A.2): one stage,
// three presentations. The terrain is packages/coast's renderer mounted in the
// stage's shadow root by dynamic import; Chart stays the MapLibre placeholder
// until FE-11. The Fish Worker bridge (/api/coast, /coast-data) never answers
// here: either it is held open, so the terrain stays mounted and loading, or it
// fails, so the stage must return to Chart with v1's message.
import type {Page} from '@playwright/test';
import {expect, test} from './fixtures.ts';

const UNAVAILABLE = 'Coastal graphics are unavailable. The chart, forecasts and trip tools remain usable.';
const PLACE = {region: 'morro-bay', profile: 'spear', target: 'rockfish', hour: '2030-01-02T03:00Z', habitat: 'reef:r1', view: '35.38000,-120.88000,12'};

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
});

/** Hold every coast data request open: the renderer mounts and waits for its terrain. */
const holdCoastData = (page: Page) => page.route(/\/(?:api\/coast|coast-data)\//, () => { /* never answered */ });
const failCoastData = (page: Page) => page.route(/\/(?:api\/coast|coast-data)\//, route => route.fulfill({status: 503, json: {error: 'Offline map test'}}));
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
