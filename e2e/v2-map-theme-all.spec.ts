import {expect, test} from '@playwright/test';
import {bindThemeFixture, FIRST, NEXT, NOW, serveThemeApp, snapshot, type Theme} from './theme-d3-fixture.ts';
import {syntheticTerrain} from './terrain-keyboard-fixture.ts';

// The provider unit oracles cannot detect a provider omitted by the real app,
// or a theme switch rebuilding sources instead of updating the mounted map.
const other = (theme: Theme): Theme => theme === 'light' ? 'dark' : 'light';
const view = '35.38000,-120.88000,12';
const link = (region: string, layers: string, presentation = 'chart') => `/map?ui=v2&region=${region}&profile=boat&base=night&view=${view}&presentation=${presentation}&layers=${layers}&diagnostics=1`;
const ids = (shot: Awaited<ReturnType<typeof snapshot>>) => shot.layers.map(({id}) => id);
type Shot = Awaited<ReturnType<typeof snapshot>>;
function stalePaint(live: Shot, fresh: Shot) {
  const expected = new Map(fresh.layers.map(({id, paint}) => [id, paint]));
  return live.layers.flatMap(({id, paint}) => {
    const want = expected.get(id);
    return want ? [...new Set([...Object.keys(paint), ...Object.keys(want)])].filter(key =>
      JSON.stringify(paint[key as keyof typeof paint]) !== JSON.stringify(want[key as keyof typeof want])).map(key => `${id}/${key}`) : [`${id} missing on fresh page`];
  });
}
async function enableFleet(page: import('@playwright/test').Page, phone: boolean) {
  if (phone) await page.getByRole('button', {name: 'Layers', exact: true}).click();
  const admin = page.locator('label.app-rail-option').filter({hasText: /· admin$/}).getByRole('checkbox');
  await expect(admin).toHaveCount(3);
  // Toggle the real app controls, even if offscreen in the sheet.
  for (const option of await admin.all()) await option.evaluate((element: HTMLInputElement) => { if (!element.checked) element.click(); });
  if (phone) await page.getByRole('button', {name: 'Done', exact: true}).click();
}
const choices = ['seafloor,currents,fleet,stations', 'swell,fleet,stations', 'water-temp,fleet,stations', 'sst-contrast,fleet,stations', 'sst-fronts,fleet,stations', 'chlorophyll,fleet,stations', 'clouds,fleet,stations'];
const settled = (page: import('@playwright/test').Page) => page.waitForFunction(() => window.d3Chart?.loaded() && window.d3Chart?.areTilesLoaded(), null, {timeout: 10_000});

for (const starting of ['dark', 'light'] as const) {
  test(`mounted map stays in place and matches fresh ${other(starting)} paint (starts ${starting})`, async ({browser}, info) => {
    const phone = info.project.name === 'phone';
    const viewport = phone ? {width: 390, height: 844} : {width: 1200, height: 800};
    const server = await serveThemeApp();
    const contexts = await Promise.all([starting, other(starting)].map(colorScheme => browser.newContext({viewport, colorScheme,
      hasTouch: phone, isMobile: phone, reducedMotion: 'reduce', serviceWorkers: 'block'})));
    try {
      const [live, fresh] = await Promise.all(contexts.map(context => context.newPage()));
      await Promise.all([live, fresh].map(page => page.clock.setFixedTime(NOW)));
      const data = await bindThemeFixture(contexts[0], server.origin, starting, process.env.D3_STALE_PAINT === '1');
      const reference = await bindThemeFixture(contexts[1], server.origin, other(starting));
      reference.release();
      for (const layers of choices) {
        await test.step(layers, async () => {
          await live.emulateMedia({colorScheme: starting});
          const url = server.origin + link(FIRST, layers);
          await Promise.all([live, fresh].map(page => page.goto(url)));
          await Promise.all([live, fresh].map(page => page.waitForFunction(() => window.d3Chart?.isStyleLoaded() && window.d3Chart?.areTilesLoaded(), null, {timeout: 10_000})));
          await Promise.all([live, fresh].map(page => enableFleet(page, phone)));
          await Promise.all([live, fresh].map(settled));
          await Promise.all([live, fresh].map(page => page.waitForLoadState('networkidle')));
          const before = await snapshot(live), target = await snapshot(fresh);
          console.log(`${info.project.name}/${starting}/${layers}: ${before.layers.length} Chart layers, sources ${before.sources.join(', ')}`);
          expect(before.theme).toBe(starting);
          expect(target.theme).toBe(other(starting));
          expect(before.layers.length).toBeGreaterThan(0);
          expect(before.layers).not.toEqual(target.layers);
          expect(before.sources).toEqual(expect.arrayContaining(['fleet-heat', 'fleet-tracks', 'fleet-events']));
          expect([...ids(before)].sort()).toEqual([...ids(target)].sort());
          expect(data.requests.some(path => path.endsWith('.pmtiles'))).toBe(true);
          if (layers === choices[0]) await live.screenshot({path: info.outputPath(`${starting}.png`)});
          const boundary = data.requests.length;
          for (let i = 0; i < 10; i++) {
            const next = i % 2 === 0 ? other(starting) : starting;
            await live.emulateMedia({colorScheme: next});
            await live.waitForFunction(theme => (document.documentElement.dataset.theme ?? 'dark') === theme, next);
          }
          const afterTen = await snapshot(live);
          expect.soft(data.requests.slice(boundary), 'new requests after ten switches').toEqual([]);
          expect.soft(afterTen).toEqual(before);
          await live.emulateMedia({colorScheme: other(starting)});
          await live.waitForFunction(theme => (document.documentElement.dataset.theme ?? 'dark') === theme, other(starting));
          const switched = await snapshot(live);
          expect.soft(data.requests.slice(boundary), 'new requests after final switch').toEqual([]);
          expect.soft(switched.camera).toEqual(before.camera);
          expect.soft(switched.sources).toEqual(before.sources);
          expect.soft(ids(switched)).toEqual(ids(before));
          expect.soft(switched.images).toEqual(before.images);
          expect.soft(switched.duplicates).toEqual([]);
          expect.soft(stalePaint(switched, target), 'stale paint vs fresh page').toEqual([]);
        });
      }
      // Trigger the real popstate region load without changing the document.
      const pending = live.waitForRequest(url => url.url().includes(`/regions/${NEXT}/region.json`));
      await live.evaluate(region => {
        const url = new URL(location.href);
        url.searchParams.set('region', region);
        history.pushState({}, '', url);
        dispatchEvent(new PopStateEvent('popstate'));
      }, NEXT);
      await pending;
      await expect.poll(() => data.seen.includes(`/regions/${NEXT}/region.json`)).toBe(true);
      // Region selection itself starts independent readers. Drain those (apart
      // from the gated definition) before taking a theme-only request baseline.
      await expect.poll(async () => {
        const count = data.requests.length;
        await live.waitForFunction(() => window.d3Chart?.loaded());
        await live.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
        return data.requests.length - count;
      }).toBe(0);
      const pendingBefore = await snapshot(live), pendingBoundary = data.requests.length;
      await live.emulateMedia({colorScheme: starting});
      await live.waitForFunction(theme => (document.documentElement.dataset.theme ?? 'dark') === theme, starting);
      const pendingAfter = await snapshot(live);
      expect.soft(data.requests.slice(pendingBoundary), 'new requests with next region held').toEqual([]);
      expect.soft(ids(pendingAfter)).toEqual(ids(pendingBefore));
      expect.soft(pendingAfter.camera).toEqual(pendingBefore.camera);
      expect.soft(pendingAfter.duplicates).toEqual([]);
      data.release();
      const terrain = await syntheticTerrain(live);
      terrain.release();
      await live.goto(server.origin + link(FIRST, choices[0], '3d'));
      await expect(live.locator('.app-terrain')).toBeVisible();
      await expect(live.locator('.app-terrain #scene')).toHaveAttribute('data-perspective', '3d');
    } finally {
      await Promise.all(contexts.map(context => context.close()));
      server.close();
    }
  });
}
