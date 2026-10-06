// Shared fixtures for the browser tests: only the local site is reachable
// (every other origin is aborted, so NWS, NOAA and map tiles never decide a
// result), uncaught page errors fail the test, and axe checks are recorded.
import {mkdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {forecastFixture} from './forecast-fixture.ts';
import AxeBuilder from '@axe-core/playwright';
import {test as base, expect, type Page} from '@playwright/test';
import {stubBoundaryChecks} from './boundary-fixture.ts';

export const AXE_DIR = join(import.meta.dirname, '..', 'test-results', 'axe');
const BLOCKING = new Set(['serious', 'critical']);

// FE-09: the v2 pages (docs/plans/front-end/design.md § 13). Viewport presets
// cover the narrowest phone, the phone project, the desktop breakpoint (§ 6:
// 1,024 px) and a wide display.
export const VIEWPORTS = {
  narrow: {width: 320, height: 568}, phone: {width: 390, height: 844}, laptop: {width: 1024, height: 768}, desktop: {width: 1440, height: 900},
} as const;
export type ViewportName = keyof typeof VIEWPORTS;
export type V2Page = 'app' | 'landing';
/** Lighthouse's mobile profile: 4× slower CPU, 1.6 Mb/s down, 750 kb/s up, 150 ms round trip. */
export const THROTTLED_MOBILE = {cpu: 4, latency: 150, downloadThroughput: 1.6e6 / 8, uploadThroughput: 750e3 / 8};
export const LCP_BUDGET_MS = 2500;

export interface V2 {
  /** Path of a v2 page with `ui=v2`: the app at `/map` and the landing at `/` (design § 14). */
  url(page: V2Page, params?: Record<string, string>): string;
  /** Open a v2 page, at a viewport preset when given. `/feeds/` answers 404 unless `feed` stubbed the path; `/api/` keeps the shared stubs above. */
  open(page: V2Page, params?: Record<string, string>, viewport?: ViewportName): Promise<void>;
  /** Answer a feed or API path (a glob such as `**\/feeds/data/regions/morro-bay/latest.json`) with a JSON body; call before `open`. */
  feed(pattern: string, body: unknown, status?: number): Promise<void>;
  /** Largest Contentful Paint in milliseconds for a fresh load on the throttled mobile profile. */
  lcp(page: V2Page, params?: Record<string, string>): Promise<number>;
  /** axe on the page as it is now (serious and critical fail; the rest are reported). */
  a11y(name: string): Promise<void>;
}

export const test = base.extend<{pageErrors: string[]; v2: V2}>({
  context: async ({context, baseURL}, use) => {
    const origin = new URL(baseURL!).origin;
    await context.route(url => url.origin !== origin && url.protocol !== 'data:' && url.protocol !== 'blob:', route => route.abort('blockedbyclient'));
    // Block the shared live feed too: browser-origin blocking cannot stop the
    // local Worker from fetching remote models. Exercise the direct fallback
    // with synthetic, unit-checked hourly responses instead of live services.
    await context.route('**/api/forecast?*', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
    const fixtureNow = Date.now();
    await context.route('**/api/om/**', route => route.fulfill({json: forecastFixture(new URL(route.request().url()), fixtureNow)}));
    // A stale committed snapshot must not make UI checks depend on today's
    // upstream MPA feed. The real fail-closed checks still run on these polygons.
    await stubBoundaryChecks(context);
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
  v2: async ({page}, use, info) => {
    const url: V2['url'] = (name, params = {}) => {
      const search = new URLSearchParams({...params, ui: 'v2'});
      return `${name === 'app' ? '/map' : '/'}?${search}`;
    };
    // The local Worker proxies /feeds/ to upstream; a v2 page never reaches it (tests stay offline).
    await page.route('**/feeds/**', route => route.fulfill({status: 404, json: {error: 'No feed stub (e2e/fixtures.ts v2.feed)'}}));
    await page.addInitScript(() => {
      const w = window as unknown as {__lcp: number};
      w.__lcp = 0;
      new PerformanceObserver(list => { for (const entry of list.getEntries()) w.__lcp = entry.startTime; }).observe({type: 'largest-contentful-paint', buffered: true});
    });
    const v2: V2 = {
      url,
      async feed(pattern, body, status = 200) { await page.route(pattern, route => route.fulfill({status, json: body})); },
      async open(name, params, viewport) {
        if (viewport) await page.setViewportSize(VIEWPORTS[viewport]);
        await page.goto(url(name, params));
        await expect(page).toHaveTitle(/SkipperCast/);
      },
      async lcp(name, params) {
        const cdp = await page.context().newCDPSession(page);
        await cdp.send('Network.enable');
        await cdp.send('Network.emulateNetworkConditions', {offline: false, ...THROTTLED_MOBILE});
        await cdp.send('Emulation.setCPUThrottlingRate', {rate: THROTTLED_MOBILE.cpu});
        try {
          await page.goto(url(name, params), {waitUntil: 'networkidle'});
          // The LCP candidate stops changing once the network is quiet; the observer saw every earlier one.
          return await page.evaluate(() => (window as unknown as {__lcp: number}).__lcp);
        } finally {
          await cdp.send('Emulation.setCPUThrottlingRate', {rate: 1});
          await cdp.detach();
        }
      },
      a11y: name => checkA11y(page, name, info.project.name),
    };
    await use(v2);
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
