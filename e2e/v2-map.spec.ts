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
