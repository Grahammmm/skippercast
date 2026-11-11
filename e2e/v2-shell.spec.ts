// The v2 app shell behind ?ui=v2 (FE-05 desktop, FE-06 mobile;
// docs/plans/front-end/dev-plan.md): at laptop width the brief column is
// 300 px (#616) beside a map stage that fills the rest; under 1,024 px the map
// fills the viewport under a top strip, one sheet with three detents moved by
// drag and keyboard, and a four-tab nav, at 390 and 320 px wide with no
// horizontal page scroll and 44 px targets. View links, the profile switch,
// the rail and the hour slider write the address without a reload; every
// control is reachable by keyboard; no horizontal page scroll at any
// viewport preset; axe is clean; the page paints within the LCP budget on
// the throttled mobile profile (FE-09, design § 13).
import {build} from 'esbuild';
import type {Page} from '@playwright/test';
import {test, expect, VIEWPORTS, LCP_BUDGET_MS, LCP_ASSERT_REARM_DATE, AERIAL_LCP_BUDGET_MS} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const TABS = 56;

// A visitor who has chosen a profile: the first-run card (FE-08, covered by
// e2e/v2-landing.spec.ts) would otherwise sit over the sheet and the rail.
test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
});

/** The sheet's visible height above the tab bar. */
async function sheetPeek(page: Page): Promise<number> {
  const box = (await page.locator('.ui-sheet').boundingBox())!;
  return Math.round(page.viewportSize()!.height - TABS - box.y);
}

test('the shell lays out the brief beside the map (laptop) or under a sheet (phone) at every viewport preset and axe is clean', async ({page, pageErrors, v2}) => {
  await v2.open('app', AREA);
  await expect(page.locator('.app-location')).toContainText('Morro Bay');
  await expect(page.locator('.ui-tile .ui-reading')).toHaveText(['—', '—', '—', '—']);
  await v2.a11y('v2-shell');
  for (const [name, viewport] of Object.entries(VIEWPORTS)) {
    await v2.open('app', AREA, name as keyof typeof VIEWPORTS);
    const brief = page.locator('aside.app-brief'), stage = page.locator('section.app-stage');
    await expect(stage).toBeVisible();
    const s = (await stage.boundingBox())!;
    if (viewport.width >= 1024) {
      await expect(brief).toBeVisible();
      const b = (await brief.boundingBox())!;
      expect(Math.round(b.width), name).toBe(300);
      expect(Math.round(s.x), name).toBe(Math.round(b.x + b.width));
      expect(Math.round(s.x + s.width), name).toBe(viewport.width);
    } else {
      await expect(brief, name).toHaveCount(0);
      expect([Math.round(s.x), Math.round(s.y), Math.round(s.width), Math.round(s.height)], name).toEqual([0, 0, viewport.width, viewport.height]);
      await expect(page.locator('.ui-sheet'), name).toHaveAttribute('data-detent', 'peek');
      await expect(page.locator('.ui-sheet h1'), name).toBeInViewport();
      await expect(page.locator('.app-tabs a'), name).toHaveCount(4);
    }
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth, `${name}: no horizontal page scroll`).toBeLessThanOrEqual(viewport.width);
  }
  expect(pageErrors).toEqual([]);
});

test('FE-52: Reports opens from the masthead (laptop) or the sheet footer (phone) as a page over the map; axe is clean', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', AREA);
  if (isMobile) {
    await page.locator('.ui-sheet-handle').focus();
    await page.keyboard.press('End');
    await page.locator('.app-reports-link').click();
  } else await page.locator('nav[aria-label="Views"] a[data-view="reports"]').click();
  await expect(page).toHaveURL(/[?&]view=reports/);
  const reports = page.locator('article.app-reports');
  await expect(reports.locator('h1')).toHaveText('Reports');
  await expect(reports.locator('a[href="/feed.xml"]')).toBeVisible();
  await expect(page.locator('section.app-stage')).toHaveCount(1);
  await v2.a11y(isMobile ? 'v2-reports-mobile' : 'v2-reports');
  const width = page.viewportSize()!.width;
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  expect(pageErrors).toEqual([]);
});

// The clock is fixed (Date held, timers still run) before the page opens, so each case is the same on every run: an
// ordinary day (Today has twelve hours left, so End is a real move) and the last hour of Pacific today (Today has one
// hour, so the Day chip must be pressed and Home is the real move).
const HOUR_CASES = [
  {name: 'ordinary day', now: '2026-10-12T19:30:00Z', lastHour: false, atEnd: false, expected: 'Today · 11 pm', hour: '2026-10-13T06:00Z', day: null},
  {name: 'last hour today', now: '2026-10-12T06:30:00Z', lastHour: true, atEnd: true, expected: 'Tomorrow · 12 am', hour: '2026-10-12T07:00Z', day: '2026-10-12'},
] as const;

for (const c of HOUR_CASES) test(`view links, the profile switch, the rail and the hour slider update the address without a reload: ${c.name}`, async ({page, pageErrors, v2, isMobile}) => {
  await page.clock.setFixedTime(new Date(c.now));
  await v2.open('app', AREA);
  await page.evaluate(() => { (window as unknown as {__v2: number}).__v2 = 1; });
  const stillLoaded = () => page.evaluate(() => (window as unknown as {__v2?: number}).__v2 === 1);
  await page.locator('nav[aria-label="Views"] a[data-view="conditions"]').click();
  await expect(page).toHaveURL(/[?&]view=conditions/);
  await expect(page.locator('a[data-view="conditions"]')).toHaveAttribute('aria-current', 'page');
  // The Conditions view (FE-32) covers the map chrome and holds the phone sheet; the brief and the rail are the map view's, so go back to it.
  await expect(page.locator('section.app-conditions')).toBeVisible();
  await page.locator('nav[aria-label="Views"] a[data-view="coast"]').click();
  await expect(page).not.toHaveURL(/[?&]view=/);
  await expect(page.locator('a[data-view="coast"]')).toHaveAttribute('aria-current', 'page');
  await page.locator('[aria-label="Profile"] button', {hasText: 'Spear'}).click();
  await expect(page).toHaveURL(/[?&]profile=spear/);
  await expect(page.locator('.app-caveat')).toContainText('In-water visibility is unverified');
  if (isMobile) {
    await page.locator('button[aria-label="Layers"]').click();
    await expect(page.locator('.ui-sheet')).toHaveAttribute('aria-label', 'Layers');
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'half');
  }
  await page.locator('.ui-rail-toggle', {hasText: 'Clouds'}).click();
  await expect(page).toHaveURL(/[?&]layers=[^&]*clouds/);
  await expect(page.locator('.app-legend')).toContainText(/Clouds|No layers/);
  if (isMobile) {
    await page.locator('.ui-sheet button', {hasText: 'Done'}).click();
    await expect(page.locator('.ui-sheet')).toHaveAttribute('aria-label', 'Brief');
    await expect(page.locator('.ui-rail')).toHaveCount(0);
  }
  const slider = page.locator('input[aria-label="Hour"]');
  // Today runs from the current hour to 11 pm (FE-12); at 11 pm Pacific it has one hour, so take tomorrow's full day.
  expect(await slider.getAttribute('max') === '0', 'Today has one hour left only in the last-hour case').toBe(c.lastHour);
  if (c.lastHour) {
    // On a phone the Day chips are in the brief sheet, which only peeks: open it as a person would, then press the chip.
    if (isMobile) {
      await page.locator('.ui-sheet-handle').focus();
      await page.keyboard.press('End');
      await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
    }
    const tomorrow = page.locator('[aria-label="Day"] button').nth(1);
    await tomorrow.click();
    await expect(tomorrow).toHaveAttribute('aria-pressed', 'true');
    // The same local hour (11 pm) on tomorrow's 24 hours: index 23.
    await expect(slider).toHaveValue('23');
    await expect(page.locator('.ui-dock-readout')).toHaveText('Tomorrow · 11 pm');
    await expect(page).toHaveURL(u => u.searchParams.get('hour') === '2026-10-13T06:00Z' && u.searchParams.get('day') === '2026-10-12');
  }
  // At the slider's end, End emits no input event, so choose the opposite endpoint.
  const max = await slider.getAttribute('max');
  expect(max, 'the slider has a numeric maximum').toMatch(/^\d+$/);
  const atEnd = await slider.inputValue() === max;
  expect(atEnd, 'the endpoint pressed is the opposite one').toBe(c.atEnd);
  const expectedValue = atEnd ? '0' : max!;
  if (!c.lastHour) expect(Number(max), 'a multi-hour Today').toBeGreaterThan(0);
  else expect(max, 'tomorrow is a full 24-hour day').toBe('23');
  await slider.focus();
  await page.keyboard.press(atEnd ? 'Home' : 'End');
  await expect(slider).toHaveValue(expectedValue);
  await expect(page).toHaveURL(/[?&]hour=\d{4}-\d{2}-\d{2}T\d{2}%3A00Z/);
  // The dock moves at once and the address settles on the chosen hour once, 100 ms after the last input (SC1407-05), so wait for it.
  await expect(page).toHaveURL(u => u.searchParams.get('hour') === c.hour);
  expect(new URL(page.url()).searchParams.get('hour'), 'the hour in the address').toBe(c.hour);
  expect(new URL(page.url()).searchParams.get('day'), 'the day in the address').toBe(c.day);
  await expect(page.locator('.ui-dock-readout')).toHaveText(c.expected);
  await expect(slider).toHaveAttribute('aria-valuetext', c.expected);
  expect(await stillLoaded(), 'no reload').toBe(true);
  // A shared link restores the same choices.
  const shared = page.url();
  await page.goto('about:blank');
  await page.goto(shared);
  await expect(page.locator('[aria-label="Profile"] button[aria-pressed="true"]')).toHaveText('Spear');
  await expect(page.locator('input[aria-label="Hour"]')).toHaveValue(expectedValue);
  await expect(page.locator('.ui-dock-readout')).toHaveText(c.expected);
  await expect(slider).toHaveAttribute('aria-valuetext', c.expected);
  expect(new URL(page.url()).searchParams.get('hour'), 'the shared hour is kept').toBe(c.hour);
  expect(pageErrors).toEqual([]);
});

// SC1722-10: actual mounted surfaces use the region calendar, including the repeated hour.
for (const lang of ['en', 'es']) test(`day-qualified dock values across fall DST: ${lang}`, async ({page, v2, pageErrors}) => {
  await page.clock.setFixedTime(new Date('2026-10-31T19:00:00Z'));
  const cases = [
    ['2026-10-31T23:00Z', 'Today · 4 pm', 'Hoy · 16'],
    ['2026-11-01T08:00Z', 'Tomorrow · 1 am', 'Mañana · 1'],
    ['2026-11-01T09:00Z', 'Tomorrow · 1 am', 'Mañana · 1'],
    ['2026-11-03T14:00Z', 'Tue · 6 am', 'mar · 6'],
    ['2026-11-07T14:00Z', 'Sat 7 · 6 am', 'sáb 7 · 6'],
  ];
  for (const [hour, en, es] of cases) {
    await v2.open('app', {...AREA, hour, lang});
    const expected = lang === 'es' ? es : en;
    await expect(page.locator('.ui-dock-readout')).toHaveText(expected);
    await expect(page.locator('input[type="range"].ui-dock-range')).toHaveAttribute('aria-valuetext', expected);
    expect(new URL(page.url()).searchParams.get('hour')).toBe(hour);
  }
  // Freeze timers after mounting: native Home changes the visible/accessibility preview,
  // while the exact UTC address remains settled until the controller's 100 ms pause.
  await page.clock.pauseAt(new Date('2026-10-31T19:00:01Z'));
  const slider = page.locator('input[type="range"].ui-dock-range');
  await slider.focus();
  await slider.press('Home');
  const preview = lang === 'es' ? 'sáb 7 · 0' : 'Sat 7 · 12 am';
  await expect(page.locator('.ui-dock-readout')).toHaveText(preview);
  await expect(slider).toHaveAttribute('aria-valuetext', preview);
  expect(new URL(page.url()).searchParams.get('hour')).toBe('2026-11-07T14:00Z');
  await page.clock.runFor(99);
  expect(new URL(page.url()).searchParams.get('hour')).toBe('2026-11-07T14:00Z');
  await page.clock.runFor(1);
  await expect(page).toHaveURL(u => u.searchParams.get('hour') === '2026-11-07T08:00Z');
  await expect(page.locator('.ui-dock-readout')).toHaveText(preview);
  await expect(slider).toHaveAttribute('aria-valuetext', preview);
  expect(pageErrors).toEqual([]);
});

test('keyboard reaches every control', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', AREA);
  const wanted = isMobile
    ? ['button[aria-label="Layers"]', '[aria-label="Profile"] button:last-child', '.ui-sheet-handle', 'input[aria-label="Hour"]', '.ui-tile:last-child summary', 'label:has-text("Target") select', 'label:has-text("Area") select', '.app-tabs a[data-view="reports"]']
    : ['nav[aria-label="Views"] a[data-view="fleet"]', '[aria-label="Profile"] button:last-child', 'label:has-text("Target") select', 'label:has-text("Area") select',
      '.ui-rail-item:last-child .ui-rail-toggle', 'input[aria-label="Hour"]', 'button[aria-label="Play"]'];
  const reached = new Set<string>();
  // #616 added the verdict basis and the Details summary to the brief column, before the rail in tab order.
  for (let i = 0; i < 96 && reached.size < wanted.length; i++) {
    await page.keyboard.press('Tab');
    for (const selector of wanted) if (!reached.has(selector) && await page.locator(selector).evaluate(el => el === document.activeElement)) reached.add(selector);
  }
  expect([...reached].sort()).toEqual([...wanted].sort());
  if (isMobile) await expect(page.locator('.ui-sheet'), 'focus inside the sheet lifts it off peek').not.toHaveAttribute('data-detent', 'peek');
  expect(pageErrors).toEqual([]);
});

test('the shell paints within the LCP budget on the throttled mobile profile', async ({page, pageErrors, v2}, info) => {
  test.skip(info.project.name !== 'phone', 'measured once, at phone size');
  // The shell on the Night base is the design § 13 budget; Morro Bay opens on Aerial, whose tiles land later (owner's call).
  // Measured until the LCP candidate list settles, not until the network goes quiet: this page has two
  // candidates (the waiting headline, then the larger verdict basis behind loadRegs' chained fetches),
  // and reading at `networkidle` reported whichever of them had painted by then. LCP_ASSERT_REARM_DATE
  // in e2e/fixtures.ts says why the comparison below is recorded rather than asserted, and when it
  // re-arms; the budget itself is unchanged.
  const paint = await v2.lcpSettled('app', {...AREA, base: 'night'});
  const over = paint.ms - LCP_BUDGET_MS;
  const w = paint.winner;
  const element = w ? `${w.tag.toLowerCase()}${w.cls.trim() ? `.${w.cls.trim().split(/\s+/).join('.')}` : ''} (${w.size} px)` : 'none recorded';
  const trail = paint.candidates.map(c => `${c.tag.toLowerCase()}@${c.ms}ms/${c.size}px`).join(' -> ') || 'none';
  const verdict = `v2 app shell LCP ${paint.ms} ms (budget ${LCP_BUDGET_MS}, design § 13): `
    + `${over > 0 ? `OVER BUDGET by ${over} ms` : `within budget by ${-over} ms`}`
    + `; largest element ${element}; candidates ${trail}`
    + `${paint.settled ? '' : ' (WARNING: the candidate list had not settled)'}`
    + `${over > 0 ? ` [recorded, not failed: report-only until ${LCP_ASSERT_REARM_DATE}]` : ''}`;
  console.log(verdict);
  info.annotations.push({type: 'lcp', description: verdict});
  // #617: the coast poster (web/map/poster.ts) is an inline path, never the LCP element; reported, and gone once the map has drawn.
  const [poster, idle] = await page.evaluate(() => ['skippercast-poster', 'skippercast-chart-idle'].map(n => performance.getEntriesByName(n)[0]?.startTime ?? null));
  const marks = `v2 app coast poster ${poster === null ? 'not shown (the map drew first)' : `${Math.round(poster)} ms`}; Chart first complete frame ${idle === null ? 'none' : `${Math.round(idle)} ms`}`;
  console.log(marks);
  info.annotations.push({type: 'lcp-marks', description: marks});
  await expect(page.locator('.app-poster')).toHaveCount(0);
  expect(paint.ms, 'Largest Contentful Paint recorded').toBeGreaterThan(0);
  // Report-only until LCP_ASSERT_REARM_DATE, then this line fails a genuine breach again.
  if (Date.now() >= Date.parse(`${LCP_ASSERT_REARM_DATE}T00:00:00Z`)) expect(paint.ms, verdict).toBeLessThanOrEqual(LCP_BUDGET_MS);
  expect(pageErrors).toEqual([]);
});

test('opening on the Aerial base paints within the budget the owner accepted for it', async ({pageErrors, v2}, info) => {
  test.skip(info.project.name !== 'phone', 'measured once, at phone size');
  const lcp = await v2.lcp('app', AREA);
  console.log(`v2 app Aerial default LCP ${Math.round(lcp)} ms (budget ${AERIAL_LCP_BUDGET_MS}, design § 13)`);
  expect(lcp, 'Largest Contentful Paint recorded').toBeGreaterThan(0);
  expect(lcp).toBeLessThanOrEqual(AERIAL_LCP_BUDGET_MS);
  expect(pageErrors).toEqual([]);
});

test.describe('phone', () => {
  test.skip(({isMobile}) => !isMobile, 'the phone project only');

  for (const width of [320, 390]) {
    test(`at ${width} px cancelled drags retain every detent and the next tap still works`, async ({page, pageErrors, v2}) => {
      await v2.open('app', AREA, width === 320 ? 'narrow' : 'phone');
      const sheet = page.locator('.ui-sheet'), handle = page.locator('.ui-sheet-handle');
      for (const [detent, dy] of [['peek', -120], ['half', -400], ['half', 120], ['full', 120], ['peek', -20], ['half', 0]] as const) {
        await handle.focus();
        await page.keyboard.press('Home');
        if (detent === 'half') await page.keyboard.press('ArrowUp');
        if (detent === 'full') await page.keyboard.press('End');
        await expect(sheet).toHaveAttribute('data-detent', detent);
        // Let the real CSS transition finish before starting the captured drag.
        await sheet.evaluate(async el => { await Promise.all(el.getAnimations().map(a => a.finished)); });
        const box = (await handle.boundingBox())!;
        const x = box.x + box.width / 2, y = box.y + box.height / 2;
        await page.mouse.move(x, y);
        await page.mouse.down();
        await page.mouse.move(x, y + dy);
        if (dy) expect(await sheet.evaluate(el => el.style.transform)).toMatch(/^translateY\(/);
        await handle.dispatchEvent('pointercancel', {pointerId: 1, clientX: x, clientY: y + dy});
        await expect(sheet, `${detent}, cancelled ${dy}px`).toHaveAttribute('data-detent', detent);
        expect(await sheet.evaluate(el => [el.style.transform, el.style.transition])).toEqual(['', '']);
        // dispatchEvent simulates cancellation; release the real mouse capture separately.
        await handle.evaluate(el => { try { el.releasePointerCapture(1); } catch { /* not captured */ } });
        await page.mouse.move(4, 4);
        await page.mouse.up();
        await handle.click();
        await expect(sheet, 'the next tap steps exactly once').toHaveAttribute('data-detent', {peek: 'half', half: 'full', full: 'peek'}[detent]);
      }
      expect(pageErrors).toEqual([]);
    });

    test(`at ${width} px the sheet peeks over the map, the detents move by drag and keyboard, and targets are 44 px`, async ({page, pageErrors, v2}) => {
      await v2.open('app', AREA, width === 320 ? 'narrow' : 'phone');
      const sheet = page.locator('.ui-sheet'), handle = page.locator('.ui-sheet-handle');
      await expect(sheet).toHaveAttribute('data-detent', 'peek');
      const peek = await sheetPeek(page);
      expect(peek).toBeGreaterThanOrEqual(160);
      expect(peek).toBeLessThanOrEqual(200);
      await expect(page.locator('.ui-sheet h1')).toBeInViewport();
      await expect(page.locator('.app-top .app-brand')).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      // Drag the handle (wherever the detent put it, once its transition has settled) by `dy` in four steps.
      const settled = async () => {
        let before = JSON.stringify(await handle.boundingBox());
        for (let i = 0; i < 20; i++) {
          await page.waitForTimeout(100);
          const after = JSON.stringify(await handle.boundingBox());
          if (after === before) return;
          before = after;
        }
      };
      const drag = async (dy: number) => {
        await settled();
        const grip = (await handle.boundingBox())!;
        const cx = grip.x + grip.width / 2, cy = grip.y + grip.height / 2;
        await page.mouse.move(cx, cy);
        await page.mouse.down();
        for (let i = 1; i <= 4; i++) await page.mouse.move(cx, cy + dy * i / 4);
        await page.mouse.up();
      };
      // Up one detent, far up to full, down one to half; a short drag snaps back.
      await drag(-120);
      await expect(sheet).toHaveAttribute('data-detent', 'half');
      expect(await sheetPeek(page)).toBeGreaterThan(peek + 100);
      await drag(-400);
      await expect(sheet).toHaveAttribute('data-detent', 'full');
      await page.locator('.app-brief-footer').scrollIntoViewIfNeeded();
      await expect(page.locator('.app-brief-footer'), 'the whole brief is reachable at full').toBeInViewport();
      await drag(120);
      await expect(sheet).toHaveAttribute('data-detent', 'half');
      await drag(20);
      await expect(sheet).toHaveAttribute('data-detent', 'half');
      // The keyboard steps and jumps; a click steps up and wraps to peek.
      await handle.focus();
      await page.keyboard.press('ArrowUp');
      await expect(sheet).toHaveAttribute('data-detent', 'full');
      await page.keyboard.press('Escape');
      await expect(sheet).toHaveAttribute('data-detent', 'peek');
      await page.keyboard.press('End');
      await expect(sheet).toHaveAttribute('data-detent', 'full');
      await page.keyboard.press('ArrowDown');
      await expect(sheet).toHaveAttribute('data-detent', 'half');
      await handle.click();
      await expect(sheet).toHaveAttribute('data-detent', 'full');
      await handle.click();
      await expect(sheet).toHaveAttribute('data-detent', 'peek');
      // A drag the browser cancels (no click follows) must not swallow the next tap.
      await settled();
      const grip = (await handle.boundingBox())!;
      const cx = grip.x + grip.width / 2, cy = grip.y + grip.height / 2;
      await page.mouse.move(cx, cy);
      await page.mouse.down();
      await page.mouse.move(cx, cy - 40);
      await handle.dispatchEvent('pointercancel', {pointerId: 1, clientX: cx, clientY: cy - 40});
      await handle.evaluate(el => { try { el.releasePointerCapture(1); } catch { /* not captured */ } });
      await page.mouse.move(4, 4);
      await page.mouse.up();
      await expect(sheet).toHaveAttribute('data-detent', 'peek');
      await handle.click();
      await expect(sheet, 'the tap after a cancelled drag still steps the sheet').toHaveAttribute('data-detent', 'half');
      await handle.click();
      await handle.click();
      await expect(sheet).toHaveAttribute('data-detent', 'peek');
      // Every visible control is at least 44 px tall and the tabs 56 px.
      const short = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>('button, a, input, select, summary')]
        .filter(el => !el.matches('.app-skip-link:not(:focus)')) // SC1722-20: a skip link is clipped to a pixel until it has focus (44 px then: e2e/v2-skip-links.spec.ts)
        .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
        .map(el => ({el: el.getAttribute('aria-label') ?? el.textContent?.trim() ?? el.tagName, h: Math.round(el.getBoundingClientRect().height)}))
        .filter(x => x.h < 44));
      expect(short).toEqual([]);
      expect(Math.round((await page.locator('.app-tabs a').first().boundingBox())!.height)).toBeGreaterThanOrEqual(TABS);
      await v2.a11y(`v2-shell-${width}`);
      expect(pageErrors).toEqual([]);
    });
  }

  test('a selected mark takes the sheet\'s peek and clearing it brings the headline back', async ({page, pageErrors, v2}) => {
    // FE-18: the link names a reef mark of the Morro Bay atlas, so the card carries its name once the atlas loads.
    await v2.open('app', {...AREA, spot: 'SC26-001'});
    const sheet = page.locator('.ui-sheet');
    await expect(sheet).toHaveAttribute('data-detent', 'peek');
    await expect(sheet.locator('.app-mark h2')).toHaveText('Southern rocky rise');
    await expect(sheet.locator('.app-mark h2')).toBeInViewport();
    await expect(sheet.locator('h1')).toHaveCount(0);
    await page.locator('button[aria-label="Clear selection"]').click();
    await expect(page).not.toHaveURL(/spot=/);
    await expect(sheet.locator('h1')).toBeInViewport();
    expect(pageErrors).toEqual([]);
  });

  // SC-N3: the Day chips scroll inside their own row, never the sheet body; the top card keeps the whole region name.
  for (const size of [{width: 390, height: 844}, {width: 360, height: 800}]) {
    test(`at ${size.width} px the full sheet never scrolls sideways and the top card names the whole region`, async ({page, pageErrors, v2}) => {
      await page.setViewportSize(size);
      await v2.open('app', {...AREA, profile: 'boat'});
      const keep = page.getByRole('button', {name: 'Keep Boat for now'});
      if (await keep.isVisible()) await keep.tap();
      const sheet = page.locator('.ui-sheet'), body = sheet.locator('.ui-sheet-body');
      await page.locator('.ui-sheet-handle').focus();
      await page.keyboard.press('End');
      await expect(sheet).toHaveAttribute('data-detent', 'full');
      const day = sheet.locator('[role="group"][aria-label="Day"]');
      await expect(day.getByRole('button').last()).toBeAttached();
      const overflow = () => body.evaluate(el => [el.scrollWidth, el.clientWidth, el.scrollLeft]);
      const [scrollWidth, clientWidth] = await overflow();
      expect(scrollWidth, 'the sheet body has no sideways overflow').toBeLessThanOrEqual(clientWidth);
      const row = (await day.boundingBox())!;
      expect(row.x + row.width, 'the Day row ends inside the screen').toBeLessThanOrEqual(size.width);
      await day.getByRole('button').last().click();
      expect((await overflow())[2], 'reaching the last Day chip scrolls its row, not the sheet').toBe(0);
      expect((await sheet.locator('.app-sheet-brief').boundingBox())!.x, 'the brief keeps its inset').toBeGreaterThanOrEqual(15);
      const location = page.locator('.app-top-card .app-location');
      await expect(location).toContainText('Morro Bay');
      await expect(location.locator('.app-location-coords')).toBeAttached();
      await expect(location.locator('.app-location-coords'), 'the coordinates leave the clipped line').toBeHidden();
      const [locWidth, locClient] = await location.evaluate(el => [el.scrollWidth, el.clientWidth]);
      expect(locWidth, 'the region name is not clipped').toBeLessThanOrEqual(locClient);
      expect(pageErrors).toEqual([]);
    });
  }

  // SC1722-09: Back to History from a peeked sheet opens it full (viewDetent); Back to another view leaves the detent as it is.
  test('SC1722-09: Back to History opens a peeked sheet full and Back to Coast leaves the detent alone', async ({page, pageErrors, v2}) => {
    await v2.open('app', AREA, 'phone');
    const sheet = page.locator('.ui-sheet'), handle = page.locator('.ui-sheet-handle');
    const tab = (view: string) => page.locator(`nav[aria-label="Views"] a[data-view="${view}"]`);
    await tab('history').click();
    await expect(page).toHaveURL(/[?&]view=history/);
    await expect(sheet).toHaveAttribute('data-detent', 'full');
    await handle.focus();
    await page.keyboard.press('Home');
    await expect(sheet).toHaveAttribute('data-detent', 'peek');
    await tab('conditions').click();
    await expect(page).toHaveURL(/[?&]view=conditions/);
    await page.goBack();
    await expect(page).toHaveURL(/[?&]view=history/);
    await expect(tab('history')).toHaveAttribute('aria-current', 'page');
    await expect(sheet).toHaveAttribute('data-detent', 'full');
    await page.goBack();
    await expect(page).not.toHaveURL(/[?&]view=/);
    expect(new URL(page.url()).pathname).toBe('/map');
    await expect(sheet).toHaveAttribute('data-detent', 'full');
    expect(pageErrors).toEqual([]);
  });
});

// SC1722-09: a press that changes the view is one history entry, a press on the shown view is none, an hour change replaces.
test('SC1722-09: Back and Forward follow the views you pressed, a repeat press adds no entry and an hour change adds none', async ({page, pageErrors, v2}) => {
  await page.clock.setFixedTime(new Date('2026-10-12T19:30:00Z'));   // an ordinary day, as HOUR_CASES: Today has hours left
  await v2.open('app', AREA);
  await page.evaluate(() => { (window as unknown as {__v2: number}).__v2 = 1; });
  const stillLoaded = () => page.evaluate(() => (window as unknown as {__v2?: number}).__v2 === 1);
  const length = () => page.evaluate(() => history.length);
  const tab = (view: string) => page.locator(`nav[aria-label="Views"] a[data-view="${view}"]`);
  const start = await length();
  await tab('coast').click();
  expect(await length(), 'a press on the shown view adds no entry').toBe(start);
  await expect(page).not.toHaveURL(/[?&]view=/);
  const slider = page.locator('input[aria-label="Hour"]');
  const max = await slider.getAttribute('max');
  expect(max, 'the slider has a numeric maximum').toMatch(/^\d+$/);
  await slider.focus();
  await page.keyboard.press(await slider.inputValue() === max ? 'Home' : 'End');
  await expect(page).toHaveURL(/[?&]hour=/);
  expect(await length(), 'an hour change adds no entry').toBe(start);
  const hour = new URL(page.url()).searchParams.get('hour');
  await tab('conditions').click();
  await expect(page).toHaveURL(/[?&]view=conditions/);
  await expect(page.locator('section.app-conditions')).toBeVisible();
  await tab('history').click();
  await expect(page).toHaveURL(/[?&]view=history/);
  await expect(tab('history')).toHaveAttribute('aria-current', 'page');
  await tab('history').click();
  expect(await length(), 'two entries for two changed views, none for the repeat').toBe(start + 2);
  await page.goBack();
  await expect(page).toHaveURL(/[?&]view=conditions/);
  await expect(tab('conditions')).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('section.app-conditions')).toBeVisible();
  await page.goBack();
  await expect(page).not.toHaveURL(/[?&]view=/);
  expect(new URL(page.url()).searchParams.get('hour'), 'the entry keeps the hour replaced into it').toBe(hour);
  expect(new URL(page.url()).pathname).toBe('/map');
  await expect(tab('coast')).toHaveAttribute('aria-current', 'page');
  await page.goForward();
  await expect(page).toHaveURL(/[?&]view=conditions/);
  await page.goForward();
  await expect(page).toHaveURL(/[?&]view=history/);
  expect(await length()).toBe(start + 2);
  expect(await stillLoaded(), 'no reload').toBe(true);
  expect(pageErrors).toEqual([]);
});

// FE-60 acceptance 3: with v2 the default, one context draws one map, one of each picker and one timeline. The
// contexts are the app at /map (Chart) and /coast, which moves to the app's 3D terrain (FE-78): the terrain lives
// inside the same stage and its in-scene place and target controls stay hidden, and no v1 map mounts.
test('FE-60: no duplicate map, picker or timeline for one context (/map and /coast)', async ({page, pageErrors, v2, isMobile}) => {
  await page.route(/\/(?:api\/coast|coast-data)\//, () => { /* never answered: the terrain stays loading, offline */ });
  // Silent means silent for the whole test: the renderer gives up on a dataset after its own 20 s timeout and the stage then
  // swaps the loading scene for Chart, so on a slow runner the checks below raced that clock (main runs 41654211025,
  // 41655615036). The give-up itself is covered by tests/test_map_stage.mjs. Long request deadlines never fire here.
  await page.addInitScript(() => {
    const timeout = AbortSignal.timeout.bind(AbortSignal);
    AbortSignal.timeout = ms => (ms >= 10_000 ? new AbortController().signal : timeout(ms));
  });
  const contexts: Array<[string, string, 'chart' | 'terrain']> = [
    ['/map', v2.url('app', {...AREA, presentation: 'chart'}), 'chart'],
    ['/coast', `/coast?${new URLSearchParams({...AREA, ui: 'v2'})}`, 'terrain'],
  ];
  for (const [name, url, surface] of contexts) {
    await page.goto(url);
    await expect(page).toHaveURL(/\/map\?/);
    await expect(page.locator('.app-location'), name).toContainText('Morro Bay');
    // Inspect the deliberately loading embed before other controls: its real
    // fetch deadline removes the scene, so this is not a stable end-of-test state.
    if (surface === 'terrain') {
      const host = page.locator('.app-terrain');
      await expect.poll(() => host.evaluate(el => !!el.shadowRoot?.getElementById('scene')), name).toBe(true);
      // The host owns place, target and time: the embed's own species picker is hidden and it draws no timeline.
      expect(await host.evaluate(el => {
        const root = el.shadowRoot!, species = root.getElementById('species') as HTMLElement | null;
        return {species: !species || species.hidden, timeline: root.querySelectorAll('input[type="range"][aria-label="Hour"], .time-dock-center').length};
      }), name).toEqual({species: true, timeline: 0});
    }
    // One map: one stage, one visible surface, at most one MapLibre canvas, no v1 map.
    await expect(page.locator('section.app-stage'), name).toHaveCount(1);
    await expect(page.locator(surface === 'chart' ? '.app-map' : '.app-terrain'), name).toBeVisible();
    await expect(page.locator(surface === 'chart' ? '.app-terrain' : '.app-map'), name).toBeHidden();
    expect(await page.locator('canvas.maplibregl-canvas').count(), `${name}: MapLibre canvases`).toBeLessThanOrEqual(1);
    await expect(page.locator('#map'), `${name}: no v1 map`).toHaveCount(0);
    // One of each picker: area and port, target, profile, presentation.
    for (const label of ['Area and port', 'Target species', 'Profile', 'Map presentation'])
      expect(await page.getByRole('group', {name: label, exact: true}).count(), `${name}: ${label}`).toBeLessThanOrEqual(1);
    expect(await page.locator('button.app-port').count(), `${name}: port button`).toBeLessThanOrEqual(1);
    await expect(page.getByRole('group', {name: 'Profile', exact: true}), name).toHaveCount(1);
    await expect(page.getByRole('group', {name: 'Map presentation', exact: true}), name).toHaveCount(1);
    if (!isMobile) await expect(page.getByRole('group', {name: 'Area and port', exact: true}), name).toHaveCount(1);
    // One timeline: one hour slider and at most one day picker.
    await expect(page.locator('input[aria-label="Hour"]'), `${name}: hour slider`).toHaveCount(1);
    expect(await page.getByRole('group', {name: 'Day', exact: true}).count(), `${name}: day picker`).toBeLessThanOrEqual(1);
  }
  expect(pageErrors).toEqual([]);
});
test('BF-graceful-gaps: render failures stay local, retry recovers or fails once, and fallback is accessible', async ({page, pageErrors, v2}) => {
  const bundle = await build({stdin: {resolveDir: process.cwd(), loader: 'tsx', contents: `
    import {render} from 'preact'; import {useState} from 'preact/hooks'; import {Guard} from './web/ui/Guard.tsx'; import './web/tokens.css';
    let attempts = 0; function Once() { if (!attempts++) throw Error('once'); return <p id="recovered">Recovered</p>; }
    function Broken() { throw Error('persistent'); } function Slot() { /* One position switching guarded views, as the shell's view ternaries do. */ const [v, set] = useState('fails'); return <><button type="button" id="switch" onClick={() => set('healthy')}>Switch view</button>{v === 'fails' ? <Guard name="fails"><Broken /></Guard> : <Guard name="healthy"><p id="healthy">Healthy</p></Guard>}</>; }
    render(<main><h1>Fixture</h1><Guard name="once"><Once /></Guard><Guard name="broken"><Broken /></Guard><Slot /><p id="sibling">Still here</p></main>, document.body);
  `}, bundle: true, format: 'iife', outfile: 'fixture.js', write: false, jsx: 'automatic', jsxImportSource: 'preact', loader: {'.woff2': 'dataurl'}});
  const logs: string[] = []; page.on('console', m => { if (m.type() === 'error' && m.text().startsWith('[guard]')) logs.push(m.text()); });
  await page.route('**/guard-fixture', route => route.fulfill({contentType: 'text/html', body: '<!doctype html><html lang="en"><title>Guard fixture</title><body></body></html>'}));
  await page.goto('/guard-fixture');
  await page.addStyleTag({content: bundle.outputFiles.find(f => f.path.endsWith('.css'))!.text});
  await page.addScriptTag({content: bundle.outputFiles.find(f => f.path.endsWith('.js'))!.text});
  await expect(page.locator('[data-guard]')).toHaveCount(3);
  await expect(page.locator('[data-guard="once"]')).toHaveAttribute('role', 'status');
  await expect(page.locator('[data-guard="once"] p')).toHaveText('This part could not load. The rest of the page still works.');
  await expect(page.locator('#sibling')).toHaveText('Still here'); expect(logs).toHaveLength(3);
  await v2.a11y('v2-guard');
  await page.locator('[data-guard="once"] button').focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#recovered')).toHaveText('Recovered'); await expect(page.locator('[data-guard="once"]')).toHaveCount(0); expect(logs).toHaveLength(3);
  for (let i = 0; i < 2; i++) {
    await page.locator('[data-guard="broken"] button').click(); await expect(page.locator('[data-guard="broken"]')).toHaveCount(1);
    await expect.poll(() => logs.length).toBe(4 + i); await expect(page.locator('#recovered')).toBeVisible(); await expect(page.locator('#sibling')).toBeVisible();
  }
  await page.locator('#switch').click(); await expect(page.locator('#healthy')).toHaveText('Healthy'); await expect(page.locator('[data-guard="fails"], [data-guard="healthy"]')).toHaveCount(0); expect(logs).toHaveLength(5); expect(pageErrors).toEqual([]);
});
test('BF-graceful-gaps: missing conditions and malformed fleet leave the shell usable', async ({page, pageErrors, v2, isMobile}) => {
  await page.route('**/feeds/conditions/regions/morro-bay/latest.json', r => r.fulfill({status: 500, body: 'failed'}));
  await page.route('**/api/forecast?*', r => r.fulfill({status: 500, body: 'failed'}));
  await page.route('**/api/om/**', r => r.fulfill({status: 500, body: 'failed'}));
  let fleetReads = 0; await page.route('**/api/session', r => r.fulfill({json: {is_admin: true}})); await page.route('**/api/fleet/**', r => { fleetReads++; return r.fulfill({contentType: 'application/json', body: '{broken'}); });
  await v2.open('app', {...AREA, layers: 'fleet'});
  await expect(page.locator(isMobile ? '.app-top' : '.app-masthead')).toBeVisible();
  await expect(page.locator('h1')).toHaveText(/Readings unavailable|Unknown|Waiting for readings/);
  await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible(); await expect(page.locator('input[aria-label="Hour"]')).toBeVisible();
  if (isMobile) { await page.locator('.ui-sheet-handle').focus(); await page.keyboard.press('End'); }
  await page.locator('.app-details summary').click();
  await expect(page.locator('.app-details')).toContainText('Conditions feeds could not be read: no buoy, tide or marine alert readings. The map, rules and trip tools still work.');
  await expect.poll(() => fleetReads).toBeGreaterThan(0); expect(pageErrors).toEqual([]);
});

// SC1922-04: direct links disclose incomplete regional coverage, not a weaker forecast verdict.
for (const lang of ['en', 'es']) {
  const label = lang === 'en' ? 'Preview' : 'Vista previa';
  const reason = lang === 'en'
    ? 'Forecasts and readings are live; habitat ranks, coastline and some layers are incomplete here.'
    : 'Los pronósticos y las lecturas están en vivo; las clasificaciones de hábitat, la costa y algunas capas están incompletas aquí.';
  test(`SC1922-04 preview disclosure visible and bounded, ${lang}`, async ({page, pageErrors, v2, isMobile}) => {
    let reads = 0;
    await page.route('**/data/home-ports.json', async route => { reads++; await route.continue(); });
    for (const size of isMobile ? [{width: 320, height: 640}, {width: 390, height: 844}] : [{width: 1280, height: 800}]) {
      await page.setViewportSize(size);
      await v2.open('app', {region: 'monterey-point-sur', lang, profile: 'shore'});
      const group = page.locator('.app-location-preview');
      await expect(group.locator('.app-region-preview-label')).toHaveText(label);
      await expect(group.locator('.app-region-preview-reason')).toHaveText(reason);
      // The day strip's chip reveal moves only the strip: the page itself stays at the top, masthead in view.
      if (!isMobile) expect(await page.evaluate(() => scrollY)).toBe(0);
      for (const el of [group, group.locator('.app-region-preview-label'), group.locator('.app-region-preview-reason')]) {
        await expect(el).toBeInViewport();
        const box = (await el.boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
        expect(await el.evaluate(e => e.scrollWidth <= e.clientWidth)).toBe(true);
      }
      if (isMobile) { await page.locator('.ui-sheet-handle').focus(); await page.keyboard.press('End'); }
      const note = page.locator('.app-where > .app-region-preview-reason');
      await note.scrollIntoViewIfNeeded();
      await expect(note).toHaveText(reason);
      await expect(note).toBeInViewport();
      expect(await note.evaluate(el => !!(el.compareDocumentPosition(el.parentElement!.querySelector('h2')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
    }
    expect(reads).toBe(isMobile ? 2 : 1); // one per page, not one per Location/brief consumer
    expect(pageErrors).toEqual([]);
  });
  for (const mode of ['active', '503', 'malformed', 'rejected']) test(`SC1922-04 ${mode} status shows no disclosure, ${lang}`, async ({page, pageErrors, v2}) => {
    let reads = 0;
    await page.route('**/data/home-ports.json', async route => {
      reads++;
      if (mode === 'active') await route.continue();
      else if (mode === '503') await route.fulfill({status: 503, body: 'offline'});
      else if (mode === 'malformed') await route.fulfill({json: {ports: []}});
      else await route.abort('failed');
    });
    await v2.open('app', {region: mode === 'active' ? 'morro-bay' : 'monterey-point-sur', lang, profile: 'shore'});
    await expect(page.locator('.app-location')).toContainText(mode === 'active' ? 'Morro Bay' : 'Monterey');
    await expect.poll(() => reads).toBe(1);
    await expect(page.locator('.app-region-preview-label, .app-region-preview-reason')).toHaveCount(0);
    await expect(page.locator('h1')).toBeAttached();
    await page.waitForTimeout(250);
    expect(reads).toBe(1);
    expect(pageErrors).toEqual([]);
  });
  test(`SC1922-04 conditions direct link reads once without opening a chooser, ${lang}`, async ({page, pageErrors, v2, isMobile}) => {
    let reads = 0;
    await page.route('**/data/home-ports.json', async route => { reads++; await route.continue(); });
    await v2.open('app', {region: 'monterey-point-sur', lang, view: 'conditions', profile: 'shore'});
    await expect(page.locator('.app-region-preview-label')).toHaveText(label);
    // Desktop retains its brief beside Conditions; phone replaces the sheet content.
    await expect(page.locator('.app-where')).toHaveCount(isMobile ? 0 : 1);
    expect(reads).toBe(1);
    expect(pageErrors).toEqual([]);
  });
}
