// #646 (walkthrough slice 6, owner decision B): the Chart flyover.
// 1. A first Chart view over the home framing flies, then settles north up
//    and flat with `?view=` untouched, and does not fly again in the session.
// 2. A tap mid-flight stops it.
// 3. Under prefers-reduced-motion, or for a link that names a view, it never flies.
import {test, expect} from './fixtures.ts';

const FLYOVER_KEY = 'skippercast-flyover-v1';
const TIMING = process.env.E2E_TIMING === '1';

type JourneyEvent = {name: string; startTime: number; duration: number};
type JourneyWindow = Window & {__journeyEvents: JourneyEvent[]};

test('SCB-02 phone journey: first tap, day chip and dock step stay under 100ms with the automatic tour suppressed', async ({page, v2, isMobile, pageErrors}) => {
  // Absolute latency at 4x CPU is local timing proof, not a gate on shared runners (main red 7 times).
  // Run it on a quiet machine: E2E_TIMING=1 pnpm e2e e2e/v2-flyover.spec.ts --project=phone
  test.skip(!TIMING, 'timing journey runs with E2E_TIMING=1');
  test.skip(!isMobile, 'phone journey');
  await page.emulateMedia({reducedMotion: 'no-preference'});
  // The SCB-02 journey's 4x CPU profile and Event Timing measurement, over
  // the offline fixtures. No session flag or skip-flyover override is set.
  await page.addInitScript(() => {
    const events: JourneyEvent[] = [];
    (window as unknown as JourneyWindow).__journeyEvents = events;
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) events.push({name: entry.name, startTime: entry.startTime, duration: entry.duration});
    }).observe({type: 'event', durationThreshold: 16, buffered: true} as PerformanceObserverInit);
  });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', {rate: 4});
  try {
    await v2.open('app', {region: 'morro-bay', profile: 'boat', 'boat-entry': 'ask', diagnostics: '1'});
    const chart = page.locator('.app-chart');
    await expect(chart).toHaveAttribute('data-mpa-drawn', /\d/);
    // #2224 suppresses the automatic tour on phones; prove that before any
    // input, rather than letting an input stop a mistakenly running tour.
    await expect(chart).not.toHaveAttribute('data-flyover', /./);
    expect(await page.evaluate(key => sessionStorage.getItem(key), FLYOVER_KEY)).toBeNull();
    expect(await page.evaluate(() => PerformanceObserver.supportedEntryTypes.includes('event'))).toBe(true);
    const measure = async (name: string, action: () => Promise<void>) => {
      // First map idle is not the end of lazy startup requests or their paint.
      // Keep setup/previous interaction work outside this interaction's window.
      await page.waitForLoadState('networkidle');
      await page.evaluate(async () => {
        await document.fonts.ready;
        await new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done())));
      });
      const since = await page.evaluate(() => performance.now());
      await action();
      await page.waitForTimeout(1200); // Event Timing delivers after the next paint.
      const events = await page.evaluate(since => (window as unknown as JourneyWindow).__journeyEvents.filter(e => e.startTime >= since && /^(click|keydown|keyup|pointerdown|pointerup)$/.test(e.name)), since);
      // No entry means the interaction was below Event Timing's 16ms floor.
      const maxMs = Math.max(0, ...events.map(e => e.duration));
      console.log(`SCB-02 ${name}: ${maxMs || '<16'}ms`, JSON.stringify(events));
      expect(maxMs, name).toBeLessThan(100);
    };
    const entry = page.locator('[data-first-use-boat]');
    await measure('first tap (Not now)', async () => {
      await entry.getByRole('button', {name: 'Not now'}).tap();
      await expect(entry).toHaveCount(0);
    });
    const dock = page.locator('.app-sheet-hour');
    const day = dock.locator('button[aria-pressed="false"]').first();
    const dayText = await day.textContent();
    await measure('day chip', async () => {
      await day.tap();
      await expect(dock.locator('button[aria-pressed="true"]')).toHaveText(dayText!);
    });
    const slider = dock.getByRole('slider');
    await slider.focus();
    const before = await slider.inputValue();
    await measure('dock hour step', async () => {
      await page.keyboard.press('ArrowRight');
      await expect(slider).not.toHaveValue(before);
    });
    await expect(page.locator('.app-chart')).not.toHaveAttribute('data-flyover', /./);
    expect(await page.evaluate(key => sessionStorage.getItem(key), FLYOVER_KEY)).toBeNull();
    expect(pageErrors).toEqual([]);
  } finally {
    await cdp.send('Emulation.setCPUThrottlingRate', {rate: 1});
    await cdp.detach();
  }
});

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
  await page.setViewportSize({width: 1024, height: 768});
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
  await page.setViewportSize({width: 1280, height: 800});
  await v2.open('app', {region: 'morro-bay', profile: 'boat', diagnostics: '1'});
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-flyover', 'flying');
  await chart.locator('canvas').first().dispatchEvent('pointerdown');
  await expect(chart).toHaveAttribute('data-flyover', 'stopped');
  expect(pageErrors).toEqual([]);
});

test('acceptance 3: reduced motion and a linked view never fly', async ({page, pageErrors, v2}) => {
  await page.setViewportSize({width: 1280, height: 800});
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

for (const width of [390, 844, 1023]) {
  test(`small screen ${width}px: a fresh session never starts the camera tour`, async ({page, pageErrors, v2}) => {
    await page.setViewportSize({width, height: width === 844 ? 390 : 844});
    await page.emulateMedia({reducedMotion: 'no-preference'});
    await v2.open('app', {region: 'morro-bay', profile: 'boat', diagnostics: '1'});
    const chart = page.locator('.app-chart');
    await expect(chart).toHaveAttribute('data-mpa-drawn', /\d/);
    await expect(chart).not.toHaveAttribute('data-flyover', /./);
    expect(await page.evaluate(key => sessionStorage.getItem(key), FLYOVER_KEY)).toBeNull();
    // Suppression must not consume the session's one desktop tour.
    await page.setViewportSize({width: 1024, height: 768});
    await page.reload();
    await expect(chart).toHaveAttribute('data-flyover', 'flying');
    expect(pageErrors).toEqual([]);
  });
}
