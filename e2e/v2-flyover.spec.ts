// #646 (walkthrough slice 6, owner decision B): the Chart flyover.
// 1. A first Chart view over the home framing flies, then settles north up
//    and flat with `?view=` untouched, and does not fly again in the session.
// 2. A tap mid-flight stops it.
// 3. Under prefers-reduced-motion, or for a link that names a view, it never flies.
import {test, expect} from './fixtures.ts';

const FLYOVER_KEY = 'skippercast-flyover-v1';

test.beforeEach(async ({page}) => {
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
  // The shared fixture marks the flyover as seen unless `e2e-flyover-fresh` is set; this spec sets it, and clears the
  // flyover key once (a reload keeps the session), whichever init script runs first.
  await page.addInitScript(key => {
    try { if (sessionStorage.getItem('e2e-flyover-fresh') !== 'cleared') { sessionStorage.setItem('e2e-flyover-fresh', 'cleared'); sessionStorage.removeItem(key); } } catch { /* storage blocked */ }
  }, FLYOVER_KEY);
});

test('acceptance 1: the first Chart view flies once and ends where it started', async ({page, pageErrors, v2}) => {
  test.setTimeout(60_000);
  await v2.open('app', {region: 'morro-bay', profile: 'boat', diagnostics: '1'});
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-flyover', 'flying');
  const start = await chart.getAttribute('data-view');
  await expect(chart).toHaveAttribute('data-flyover', 'done', {timeout: 30_000});
  expect(await chart.getAttribute('data-view')).toBe(start);
  expect(new URL(page.url()).searchParams.has('view'), 'the tour writes no ?view=').toBe(false);
  expect(await page.evaluate(key => sessionStorage.getItem(key), FLYOVER_KEY)).toBe('1');
  await page.reload();
  await expect(chart).toHaveAttribute('data-mpa-drawn', /\d/);
  await expect(chart).not.toHaveAttribute('data-flyover', /./);
  expect(pageErrors).toEqual([]);
});

test('acceptance 2: a tap mid-flight stops it', async ({page, pageErrors, v2}) => {
  await v2.open('app', {region: 'morro-bay', profile: 'boat', diagnostics: '1'});
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-flyover', 'flying');
  await chart.locator('canvas').first().dispatchEvent('pointerdown');
  await expect(chart).toHaveAttribute('data-flyover', 'stopped');
  expect(pageErrors).toEqual([]);
});

test('acceptance 3: reduced motion and a linked view never fly', async ({page, pageErrors, v2}) => {
  await page.emulateMedia({reducedMotion: 'reduce'});
  await v2.open('app', {region: 'morro-bay', profile: 'boat', diagnostics: '1'});
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-mpa-drawn', /\d/);
  await expect(chart).not.toHaveAttribute('data-flyover', /./);
  await page.emulateMedia({reducedMotion: 'no-preference'});
  await page.evaluate(() => sessionStorage.removeItem('e2e-flyover-fresh'));  // the next load starts unseen again
  await v2.open('app', {region: 'morro-bay', profile: 'boat', view: '35.38000,-120.88000,11', diagnostics: '1'});
  await expect(chart).toHaveAttribute('data-mpa-drawn', /\d/);
  await expect(chart).not.toHaveAttribute('data-flyover', /./);
  expect(pageErrors).toEqual([]);
});
