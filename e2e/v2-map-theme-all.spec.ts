// THEME-D3 part 1 of 2 — not full-map acceptance.
// Covered: observed Chart paints with night/ENC bases, seafloor, contours,
// stations, condition selection and admin fleet; marks admission and terrain
// registry output (not rendered marks).
// DEFERRED (web/map/ unless otherwise specified): bottom relief/survey detail
// (bottom-relief.ts, survey-detail.ts); nearshore rings (nearshore.ts, swell.ts);
// public charter/AIS (charter-grounds.ts, commercial-ais.ts); shore/reach/route
// (shore.ts, reach.ts, planning-route.ts); study previews (preview-layers.ts,
// preview/); current particles (currents.ts, flow.ts); built-app marks rendering
// and drape (marks.ts, stage.ts); 3D material/camera parity (stage.ts,
// packages/coast/src/coast3d/viewer.ts).
// DEFERRED: not mountable offline — aerial (aerial.ts, web/app/MapStage.tsx).
import process from 'node:process';
import {expect, test} from '@playwright/test';
import {bindThemeFixture, FIRST, NEXT, NOW, serveThemeApp, snapshot, type Theme} from './theme-d3-fixture.ts';
import {buildMarksProbe, marksManifest, qualifyMarksInputs, serveMarksArm, type MarksArm} from './theme-d3-marks.ts';

declare global {
  interface Window {
    d3Marks: () => {verdict: string | null; targets: number; drape: number; errors: number};
  }
}

// A parser that accepts a same-path, wrong-byte atlas can leak marks through
// the terrain registry. Exercise the real gate in isolated browser instances.
const marksArms: MarksArm[] = ['startup', '4a-i', '4a-ii', '4b'];
for (const arm of marksArms) {
  test(`marks fixture qualification ${arm}`, async ({}, info) => {
    test.skip(info.project.name !== 'laptop', 'The digest/fallback contract is viewport independent');
    const inputs = await qualifyMarksInputs();
    const server = await serveMarksArm(inputs, arm, await buildMarksProbe());
    try {
      const {chromium} = await import('@playwright/test');
      const local = await chromium.launch(info.project.use.launchOptions);
      try {
        const context = await local.newContext({serviceWorkers: 'block'});
        await server.fence(context);
        const page = await context.newPage();
        await page.goto(`${server.origin}/map?region=${FIRST}&profile=boat&target=reef`);
        const admitted = arm === 'startup' || arm === '4a-i';
        const expected = admitted ? {verdict: 'ready', targets: 132, drape: expect.any(Number), errors: 0} : {verdict: 'failed', targets: 0, drape: 0, errors: 1};
        await expect.poll(() => page.evaluate(() => window.d3Marks?.())).toEqual(expected);
        const observed = await page.evaluate(() => window.d3Marks());
        if (admitted) expect(observed.drape).toBeGreaterThan(0);
        expect(server.atlasPaths()).toEqual(server.expectedAtlasPaths);
        console.log(`marks ${arm}: ${JSON.stringify(observed)}`);
      } finally { await local.close(); }
    } finally {
      await server.close();
      expect(server.violations).toEqual([]);
    }
  });
}

// A wrong digest with the correct Git blob must still refuse qualification.
test('marks fixture manifest refuses a wrong digest before launch', async ({}, info) => {
  test.skip(info.project.name !== 'laptop', 'The manifest contract is viewport independent');
  const path = 'web/map/marks.ts';
  const files = {...marksManifest.files, [path]: [marksManifest.files[path][0], '0'.repeat(64)] as const};
  await expect(qualifyMarksInputs({...marksManifest, files})).rejects.toThrow(`Marks fixture not qualified: ${path} drift`);
});

// The provider unit oracles cannot detect a provider omitted by the real app,
// or a theme switch rebuilding sources instead of updating the mounted map.
const other = (theme: Theme): Theme => theme === 'light' ? 'dark' : 'light';
const view = '35.38000,-120.88000,12';
const link = (region: string, layers: string, base: string, camera: string) => `/map?ui=v2&region=${region}&profile=boat&base=${base}&view=${camera}&presentation=chart&layers=${layers}&diagnostics=1`;
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
const rendered = (page: import('@playwright/test').Page, source: string) => page.evaluate(id =>
  window.d3Chart.queryRenderedFeatures().filter(feature => feature.source === id).length, source);
const frameBoundary = (page: import('@playwright/test').Page) => page.evaluate(() =>
  new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));

for (const starting of ['dark', 'light'] as const) {
  test(`mounted map stays in place and matches fresh ${other(starting)} paint (starts ${starting})`, async ({browser}, info) => {
    // Eight paired full-page journeys plus the held-region transition share
    // this deadline; individual readiness and request assertions stay bounded.
    test.setTimeout(180_000);
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

      const plan = [{layers: choices[0]!, base: 'chart', camera: '35.16889,-120.75417,12'},
        ...choices.map(layers => ({layers, base: 'night', camera: view}))];
      for (const {layers, base, camera} of plan) {
        await test.step(`${base}/${layers}`, async () => {
          const loadBoundary = data.requests.length;
          await live.emulateMedia({colorScheme: starting});
          const url = server.origin + link(FIRST, layers, base, camera);
          await Promise.all([live, fresh].map(page => page.goto(url)));
          await Promise.all([live, fresh].map(page => page.waitForFunction(() => window.d3Chart?.isStyleLoaded() && window.d3Chart?.areTilesLoaded(), null, {timeout: 10_000})));
          await Promise.all([live, fresh].map(page => enableFleet(page, phone)));

          await Promise.all([live, fresh].map(settled));
          await Promise.all([live, fresh].map(page => page.waitForLoadState('networkidle')));
          if (base === 'chart' || base === 'night' && layers === choices[0]) {
            const source = base === 'chart' ? 'stations' : 'depth-contours';
            for (const page of [live, fresh]) {
              await expect.poll(() => rendered(page, source), `${source} draws actual features`).toBeGreaterThan(0);
            }
          }
          const before = await snapshot(live), target = await snapshot(fresh);
          console.log(`${info.project.name}/${starting}/${layers}: ${before.layers.length} Chart layers, sources ${before.sources.join(', ')}`);
          expect(before.theme).toBe(starting);
          expect(target.theme).toBe(other(starting));
          expect(before.layers.length).toBeGreaterThan(0);
          expect(before.layers).not.toEqual(target.layers);
          expect(before.sources).toEqual(expect.arrayContaining(['fleet-heat', 'fleet-tracks', 'fleet-events']));
          if (base === 'chart') expect(await live.evaluate(() => window.d3Chart.getLayoutProperty('chart-enc', 'visibility'))).toBe('visible');
          expect([...ids(before)].sort()).toEqual([...ids(target)].sort());
          expect(data.requests.slice(loadBoundary).some(path => path.endsWith('.pmtiles'))).toBe(true);
          if (!process.env.CI && layers === choices[0] && base === 'night') {
            await live.screenshot({path: info.outputPath(`${starting}.png`)});
          }
          const boundary = data.requests.length;
          for (let i = 0; i < 10; i++) {
            const next = i % 2 === 0 ? other(starting) : starting;
            await live.emulateMedia({colorScheme: next});
            await live.waitForFunction(theme => (document.documentElement.dataset.theme ?? 'dark') === theme, next);
          }
          await frameBoundary(live);
          const afterTen = await snapshot(live);
          expect.soft(data.requests.slice(boundary), 'new requests after ten switches').toEqual([]);
          expect.soft(afterTen).toEqual(before);
          await live.emulateMedia({colorScheme: other(starting)});
          await live.waitForFunction(theme => (document.documentElement.dataset.theme ?? 'dark') === theme, other(starting));
          await frameBoundary(live);
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
      // Trigger the same real popstate transition in the switched and fresh
      // documents, but keep both response bodies held until after comparison.
      await live.emulateMedia({colorScheme: starting});
      await live.waitForFunction(theme => (document.documentElement.dataset.theme ?? 'dark') === theme, starting);
      await Promise.all([live, fresh].map(page => page.evaluate(region => {
        const url = new URL(location.href);
        url.searchParams.set('region', region);
        history.pushState({}, '', url);
        dispatchEvent(new PopStateEvent('popstate'));
      }, NEXT)));
      await expect.poll(() => [data, reference].every(fixture => fixture.seen.includes(`/regions/${NEXT}/region.json`))).toBe(true);
      // Region selection itself starts independent readers. Drain those (apart
      // from the gated definition) before taking a theme-only request baseline.
      await expect.poll(async () => {
        const count = data.requests.length;
        await live.waitForFunction(() => window.d3Chart?.loaded());
        await frameBoundary(live);
        return data.requests.length - count;
      }).toBe(0);
      const pendingBefore = await snapshot(live), pendingBoundary = data.requests.length;
      await live.emulateMedia({colorScheme: other(starting)});
      await live.waitForFunction(theme => (document.documentElement.dataset.theme ?? 'dark') === theme, other(starting));
      await frameBoundary(live);
      const pendingAfter = await snapshot(live);
      const pendingFresh = await snapshot(fresh);
      expect.soft(data.requests.slice(pendingBoundary), 'new requests with next region held').toEqual([]);
      expect.soft(ids(pendingAfter)).toEqual(ids(pendingBefore));
      expect.soft([...ids(pendingAfter)].sort()).toEqual([...ids(pendingFresh)].sort());
      expect.soft(pendingAfter.camera).toEqual(pendingBefore.camera);
      expect.soft(pendingAfter.images).toEqual(pendingBefore.images);
      expect.soft(pendingAfter.duplicates).toEqual([]);
      expect.soft(stalePaint(pendingAfter, pendingFresh), 'stale paint with next region held').toEqual([]);
      data.release();
      reference.release();
    } finally {
      await Promise.all(contexts.map(context => context.close()));
      server.close();
    }
  });
}
