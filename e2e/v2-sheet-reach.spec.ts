// SC1722-07 (UX audit S4-06): the phone sheet is moved down by its detent's transform, so at half height the last
// stretch of its scrolling body sat below the screen and the footer's Sign in, the only sign-in entry on the phone,
// could be reached only by dragging the sheet to full. The body now carries bottom padding equal to its detent's
// hidden offset plus the tab bar. These tests scroll ONLY the body to its end and measure Sign in before any
// focus, click or scrollIntoView could move it.
import type {Locator, Page} from '@playwright/test';
import {test, expect, setSize, wideViewport} from './fixtures.ts';

const SHELL = '/map?region=morro-bay&ui=v2';
const SIZES = [[390, 844], [375, 667], [360, 640]] as const;
const DETENTS = ['half', 'full'] as const;
type Detent = (typeof DETENTS)[number];
/** UXFIX-12: at 844x390 (nightly `phone-land`) the half-height sheet starts Sign in above the visible body. Landscape layout waits for the map decision, so these cases are fixme until it lands. */
const landscapeHalf = () => wideViewport() !== null && test.info().project.name === 'phone-land';

/** A signed-out visitor who already chose a profile, so the first-run card does not replace the brief. */
async function openSignedOut(page: Page, width: number, height: number): Promise<void> {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: false}}));
  await setSize(page, {width, height});
  await page.goto(SHELL);
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'peek');
  await expect(signIn(page)).toHaveText(/Sign in/);
}

const signIn = (page: Page): Locator => page.locator('.ui-sheet-body .app-brief-footer .app-account-trigger');

/** Move the sheet with the real handle's keys, then wait until its transition has settled. */
async function goTo(page: Page, detent: 'peek' | Detent): Promise<void> {
  await page.locator('.ui-sheet-handle').focus();
  await page.keyboard.press(detent === 'peek' ? 'Home' : detent === 'full' ? 'End' : 'Home');
  if (detent === 'half') await page.keyboard.press('ArrowUp');
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', detent);
  await settled(page);
}

/** The sheet's top and its pinned edge's height have stopped moving (two frames apart, three samples). */
async function settled(page: Page): Promise<void> {
  await expect.poll(() => page.locator('.ui-sheet').evaluate(async el => {
    const tops: number[] = [];
    for (let i = 0; i < 3; i += 1) { tops.push(el.getBoundingClientRect().top + el.querySelector('.ui-sheet-edge')!.getBoundingClientRect().height / 1000); await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }
    return tops.every(t => t === tops[0]);
  }), {message: 'the sheet transition has settled'}).toBe(true);
}

/** Make the brief taller than any phone sheet (the footer moves to the end of a long body), or hide all but the footer. */
async function shapeContent(page: Page, shape: 'long' | 'short'): Promise<void> {
  // A constructed stylesheet: the page's CSP forbids injected <style> elements.
  await page.evaluate(css => {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(css);
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  }, shape === 'long'
    ? '.app-sheet-brief .app-brief-footer { margin-top: 1400px !important; }'
    : '.app-sheet-brief > :not(.app-brief-footer) { display: none !important; }');
}

const scrollBodyToEnd = (page: Page) => page.locator('.ui-sheet-body').evaluate(el => { el.scrollTop = el.scrollHeight; return {top: el.scrollTop, max: el.scrollHeight - el.clientHeight}; });

/** Sign in and the footer's last row, measured as they sit, against the visible part of the body and the tab bar. */
async function reach(page: Page) {
  return page.evaluate(() => {
    const rect = (sel: string) => document.querySelector(sel)!.getBoundingClientRect();
    const link = rect('.ui-sheet-body .app-brief-footer .app-account-trigger'), footer = rect('.ui-sheet-body .app-brief-footer');
    const body = rect('.ui-sheet-body'), tabs = rect('.app-tabs');
    const scroller = document.querySelector('.ui-sheet-body')!;
    return {link, footer, body, tabs, vw: innerWidth, scrollTop: scroller.scrollTop, scrollable: scroller.scrollHeight > scroller.clientHeight};
  });
}

for (const [width, height] of SIZES) {
  for (const detent of DETENTS) {
    for (const shape of ['long', 'short'] as const) {
      test(`sheet_footer_reachable_half_and_full: Sign in is whole above the tab bar at ${detent}, ${width}x${height}, ${shape} content`, async ({page, pageErrors, isMobile}) => {
        test.skip(!isMobile, 'phone layout only');
        test.skip(!!wideViewport() && width !== SIZES[0][0], 'a nightly project runs one size, its own');
        test.fixme(detent === 'half' && landscapeHalf(), 'landscape sheet layout waits for the map decision (UXFIX-12 finding)');
        await openSignedOut(page, width, height);
        await shapeContent(page, shape);
        await goTo(page, detent);
        if (shape === 'long') {
          const end = await scrollBodyToEnd(page);
          expect(end.max, 'the body truly overflows').toBeGreaterThan(200);
          expect(end.top, 'the body is at its maximum scroll').toBeGreaterThanOrEqual(end.max - 1);
        }
        const m = await reach(page);
        await expect(page.locator('.ui-sheet'), 'the sheet was not silently expanded').toHaveAttribute('data-detent', detent);
        // Sign in is whole inside the visible body; the footer's last row ends above the tab bar (the whole footer can be taller than
        // the 360x640 half-height window, so only its end is required to be visible).
        for (const [name, box] of [['Sign in', m.link], ['the footer', m.footer]] as const) {
          if (name === 'Sign in') expect(box.top, `${name} starts inside the visible body`).toBeGreaterThanOrEqual(Math.max(0, m.body.top) - 0.5);
          expect(box.bottom, `${name} ends above the tab bar`).toBeLessThanOrEqual(m.tabs.top + 0.5);
          expect(box.left, `${name} is inside the screen`).toBeGreaterThanOrEqual(0);
          expect(box.right, `${name} is inside the screen`).toBeLessThanOrEqual(m.vw);
        }
        // It is the real, unobstructed control: a hit test at its centre lands on it.
        const hit = await signIn(page).evaluate(el => { const b = el.getBoundingClientRect(); return document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2)?.closest('.app-account-trigger') === el; });
        expect(hit, 'nothing covers Sign in').toBe(true);
        await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', detent);
        expect(pageErrors).toEqual([]);
      });
    }
  }
}

test('sheet_reach_survives_resize_and_full_half_return: the end stays reachable after full, and across resizes', async ({page, pageErrors, isMobile}) => {
  test.skip(!isMobile, 'phone layout only');
  test.fixme(landscapeHalf(), 'landscape sheet layout waits for the map decision (UXFIX-12 finding)');
  await openSignedOut(page, 390, 844);
  await shapeContent(page, 'long');
  const reached = async (label: string) => {
    await scrollBodyToEnd(page);
    const m = await reach(page);
    expect(m.link.bottom, `${label}: Sign in above the tab bar`).toBeLessThanOrEqual(m.tabs.top + 0.5);
    expect(m.link.top, `${label}: Sign in inside the body`).toBeGreaterThanOrEqual(Math.max(0, m.body.top) - 0.5);
  };
  await goTo(page, 'half'); await reached('half');
  await goTo(page, 'full'); await reached('full');
  await goTo(page, 'half'); await reached('half again (stale scroll position)');
  for (const [width, height] of [[360, 640], [375, 667], [390, 844]] as const) {
    await setSize(page, {width, height});
    await settled(page);
    await reached(`half after resize to ${width}x${height}`);
  }
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'half');
  expect(pageErrors).toEqual([]);
});

test('sheet_padding_does_not_relayout_drag_or_change_peek_policy: height and edge stay put, overscroll is contained on the body only', async ({page, pageErrors, isMobile}) => {
  test.skip(!isMobile, 'phone layout only');
  await openSignedOut(page, 390, 844);
  const sizes = () => page.evaluate(() => {
    const sheet = document.querySelector<HTMLElement>('.ui-sheet')!, edge = document.querySelector<HTMLElement>('.ui-sheet-edge')!, body = document.querySelector<HTMLElement>('.ui-sheet-body')!;
    return {sheet: sheet.offsetHeight, edge: edge.offsetHeight, body: body.offsetHeight, bodyPad: getComputedStyle(body).paddingBottom};
  });
  const peek = await sizes();
  await goTo(page, 'half'); const half = await sizes();
  await goTo(page, 'full'); const full = await sizes();
  expect([half.sheet, full.sheet], 'sheet height does not change with the detent').toEqual([peek.sheet, peek.sheet]);
  // UXFIX-11: the day chips join the edge from half up (one chip row, at most 52 px); the edge is the same at half and full.
  expect(half.edge, 'the pinned edge keeps its height from half to full').toBe(full.edge);
  expect(half.edge - peek.edge, 'the edge grows by at most one chip row').toBeLessThanOrEqual(52);
  expect(half.edge - peek.edge, 'the edge grows by the chip row').toBeGreaterThanOrEqual(44);
  expect(half.body, 'the body keeps its height from half to full').toBe(full.body);
  expect(peek.body - half.body, 'the body gives up only the chip row').toBe(half.edge - peek.edge);
  expect(parseFloat(half.bodyPad), 'half pads for its hidden offset').toBeGreaterThan(parseFloat(full.bodyPad));
  // A sampled drag: pointer moves change only the transform, never any height or padding.
  await goTo(page, 'half');
  const handle = (await page.locator('.ui-sheet-handle').boundingBox())!;
  const x = handle.x + handle.width / 2, y = handle.y + handle.height / 2;
  await page.mouse.move(x, y); await page.mouse.down();
  for (const dy of [-20, -60, -100]) {
    await page.mouse.move(x, y + dy);
    const during = await sizes();
    expect(during.sheet, `sheet height during the drag at ${dy}`).toBe(peek.sheet);
    expect(during.body, `body height during the drag at ${dy}`).toBe(half.body);
    expect(during.bodyPad, `body padding during the drag at ${dy}`).toBe(half.bodyPad);
  }
  await page.mouse.up();
  // Keys keep their meanings; peek still clips its body.
  await goTo(page, 'full');
  await page.keyboard.press('ArrowDown'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'half');
  await page.keyboard.press('Escape'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'peek');
  expect(await page.locator('.ui-sheet-body').evaluate(el => getComputedStyle(el).overflowY)).toBe('hidden');
  // Containment is on the sheet body only.
  const contain = await page.evaluate(() => ({
    body: getComputedStyle(document.querySelector('.ui-sheet-body')!).overscrollBehaviorY,
    html: getComputedStyle(document.documentElement).overscrollBehaviorY,
    page: getComputedStyle(document.body).overscrollBehaviorY,
  }));
  expect(contain).toEqual({body: 'contain', html: 'auto', page: 'auto'});
  expect(pageErrors).toEqual([]);
});

// UXFIX-11 (UX audit S4-07, change plan C2): the day chips sit in the pinned hour strip beside the slider, so "What about Saturday?" is
// one tap at the top of the sheet. One day control on the page, in the edge and not in the scrolling body; at peek it stays hidden so
// the first-run card and verdict keep the peek's height and the readout names the day.
for (const [width, height] of SIZES) {
  test(`day_chips_pinned_in_hour_strip: ${width}x${height} one control, in view at half and full, a tap changes the day and not the scroll`, async ({page, pageErrors, isMobile}) => {
    test.skip(!isMobile, 'phone layout only');
    await openSignedOut(page, width, height);
    const days = page.locator('[role="group"][aria-label="Day"]');
    await expect(days, 'exactly one day control on the phone page').toHaveCount(1);
    expect(await days.evaluate(el => !!el.closest('.ui-sheet-edge') && !el.closest('.ui-sheet-body')), 'the chips are in the pinned edge, not the body').toBe(true);
    await expect(days, 'peek keeps its height: the readout names the day instead').toBeHidden();
    await shapeContent(page, 'long');
    for (const detent of DETENTS) {
      await goTo(page, detent);
      await expect(days, `the chips are in the viewport at ${detent} without scrolling`).toBeInViewport({ratio: 1});
      const chip = days.getByRole('button').first();
      expect((await chip.boundingBox())!.height, 'chips are at least 44 px tall').toBeGreaterThanOrEqual(44);
    }
    await goTo(page, 'full');
    const body = page.locator('.ui-sheet-body');
    const top = await body.evaluate(el => { el.scrollTop = 300; return el.scrollTop; });
    expect(top, 'the body is scrolled before the tap').toBeGreaterThan(100);
    const tomorrow = days.getByRole('button').nth(1);
    await tomorrow.click();
    await expect(tomorrow).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.ui-dock-readout'), 'the slider label names the day').toContainText('Tomorrow');
    await expect(page, 'the verdict day settles into the address').toHaveURL(url => url.searchParams.has('hour') || url.searchParams.has('day'));
    const weekday = (await tomorrow.innerText()).trim().split(/\s/)[0]!;
    await expect(page.locator('.app-sheet-brief .app-sheet-head .ui-eyebrow'), 'the verdict heading names the same day').toContainText(weekday);
    expect(await body.evaluate(el => el.scrollTop), 'the tap does not move the sheet body').toBe(top);
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
    expect(pageErrors).toEqual([]);
  });
}
