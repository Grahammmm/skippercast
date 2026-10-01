// Shared fixtures for the browser tests: only the local site is reachable
// (every other origin is aborted, so NWS, NOAA and map tiles never decide a
// result), uncaught page errors fail the test, and axe checks are recorded.
import {mkdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {forecastFixture} from './forecast-fixture.ts';
import AxeBuilder from '@axe-core/playwright';
import {test as base, expect, type Page} from '@playwright/test';

export const AXE_DIR = join(import.meta.dirname, '..', 'test-results', 'axe');
const BLOCKING = new Set(['serious', 'critical']);

export const test = base.extend<{pageErrors: string[]}>({
  context: async ({context, baseURL}, use) => {
    const origin = new URL(baseURL!).origin;
    await context.route(url => url.origin !== origin && url.protocol !== 'data:' && url.protocol !== 'blob:', route => route.abort('blockedbyclient'));
    // Block the shared live feed too: browser-origin blocking cannot stop the
    // local Worker from fetching remote models. Exercise the direct fallback
    // with synthetic, unit-checked hourly responses instead of live services.
    await context.route('**/api/forecast?*', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
    const fixtureNow = Date.now();
    await context.route('**/api/om/**', route => route.fulfill({json: forecastFixture(new URL(route.request().url()), fixtureNow)}));
    // A returning visitor who finished the first-run steps; tests open area links.
    await context.addInitScript(() => { try { localStorage.setItem('skippercast-first-run-v1', 'done'); } catch { /* storage blocked */ } });
    await use(context);
  },
  pageErrors: async ({page}, use) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(String(error)));
    await use(errors);
    expect(errors, 'uncaught page errors').toEqual([]);
  },
});
export {expect};

/** Open an area link and wait until the app has drawn the survey markers (visible on the map view). */
export async function openMap(page: Page, path = '/?region=morro-bay#map'): Promise<void> {
  await page.goto(path);
  const marker = page.locator('#map .leaflet-marker-icon').first();
  if (new URL(path, 'http://x').hash === '#map') await expect(marker).toBeVisible({timeout: 30_000});
  else await expect(marker).toBeAttached({timeout: 30_000});
}

/** Run axe on the page as it is now; fail on serious or critical violations only (for now). */
export async function checkA11y(page: Page, name: string, project: string): Promise<void> {
  const results = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']).analyze();
  const brief = (list: typeof results.violations) => list.map(v => ({id: v.id, impact: v.impact ?? null, nodes: v.nodes.length, help: v.help}));
  const summary = brief(results.violations);
  mkdirSync(AXE_DIR, {recursive: true});
  // "incomplete" is axe's needs-review list (for example contrast over map imagery it cannot measure).
  writeFileSync(join(AXE_DIR, `${project}-${name}.json`), JSON.stringify({page: name, project, url: page.url(), violations: summary, incomplete: brief(results.incomplete)}, null, 1));
  const blocking = summary.filter(v => BLOCKING.has(String(v.impact)));
  expect(blocking, `serious or critical axe violations on ${name}`).toEqual([]);
}
