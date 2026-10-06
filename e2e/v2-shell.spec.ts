// The v2 app shell behind ?ui=v2 (FE-05 desktop, FE-06 mobile;
// docs/plans/front-end/dev-plan.md): at laptop width the brief column is
// 332 px beside a map stage that fills the rest; under 1,024 px the map
// fills the viewport under a top strip, one sheet with three detents moved by
// drag and keyboard, and a four-tab nav, at 390 and 320 px wide with no
// horizontal page scroll and 44 px targets. View links, the profile switch,
// the rail and the hour slider write the address without a reload; every
// control is reachable by keyboard; no horizontal page scroll at any
// viewport preset; axe is clean; the page paints within the LCP budget on
// the throttled mobile profile (FE-09, design § 13).
import type {Page} from '@playwright/test';
import {test, expect, VIEWPORTS, LCP_BUDGET_MS} from './fixtures.ts';

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
      expect(Math.round(b.width), name).toBe(332);
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

test('view links, the profile switch, the rail and the hour slider update the address without a reload', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', AREA);
  await page.evaluate(() => { (window as unknown as {__v2: number}).__v2 = 1; });
  const stillLoaded = () => page.evaluate(() => (window as unknown as {__v2?: number}).__v2 === 1);
  await page.locator('nav[aria-label="Views"] a[data-view="conditions"]').click();
  await expect(page).toHaveURL(/[?&]view=conditions/);
  await expect(page.locator('a[data-view="conditions"]')).toHaveAttribute('aria-current', 'page');
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
  await slider.focus();
  await page.keyboard.press('End');
  await expect(page).toHaveURL(/[?&]hour=\d{4}-\d{2}-\d{2}T\d{2}%3A00Z/);
  await expect(page.locator('.ui-dock-readout')).toHaveText('11 pm');
  expect(await stillLoaded(), 'no reload').toBe(true);
  // A shared link restores the same choices.
  const shared = page.url();
  await page.goto('about:blank');
  await page.goto(shared);
  await expect(page.locator('[aria-label="Profile"] button[aria-pressed="true"]')).toHaveText('Spear');
  await expect(page.locator('.ui-dock-readout')).toHaveText('11 pm');
  expect(pageErrors).toEqual([]);
});

test('keyboard reaches every control', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', AREA);
  const wanted = isMobile
    ? ['button[aria-label="Layers"]', '[aria-label="Profile"] button:last-child', '.ui-sheet-handle', 'input[aria-label="Hour"]', '.ui-tile:last-child summary', 'label:has-text("Target") select', 'label:has-text("Area") select', '.app-tabs a[data-view="fleet"]']
    : ['nav[aria-label="Views"] a[data-view="fleet"]', '[aria-label="Profile"] button:last-child', 'label:has-text("Target") select', 'label:has-text("Area") select',
      '.ui-rail-item:last-child .ui-rail-toggle', 'input[aria-label="Hour"]', 'button[aria-label="Play"]'];
  const reached = new Set<string>();
  for (let i = 0; i < 60 && reached.size < wanted.length; i++) {
    await page.keyboard.press('Tab');
    for (const selector of wanted) if (!reached.has(selector) && await page.locator(selector).evaluate(el => el === document.activeElement)) reached.add(selector);
  }
  expect([...reached].sort()).toEqual([...wanted].sort());
  if (isMobile) await expect(page.locator('.ui-sheet'), 'focus inside the sheet lifts it off peek').not.toHaveAttribute('data-detent', 'peek');
  expect(pageErrors).toEqual([]);
});

test('the shell paints within the LCP budget on the throttled mobile profile', async ({pageErrors, v2}, info) => {
  test.skip(info.project.name !== 'phone', 'measured once, at phone size');
  const lcp = await v2.lcp('app', AREA);
  console.log(`v2 app shell LCP ${Math.round(lcp)} ms (budget ${LCP_BUDGET_MS}, design § 13)`);
  expect(lcp, 'Largest Contentful Paint recorded').toBeGreaterThan(0);
  expect(lcp).toBeLessThanOrEqual(LCP_BUDGET_MS);
  expect(pageErrors).toEqual([]);
});

test.describe('phone', () => {
  test.skip(({isMobile}) => !isMobile, 'the phone project only');

  for (const width of [320, 390]) {
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
    await v2.open('app', {...AREA, spot: 'r12'});
    const sheet = page.locator('.ui-sheet');
    await expect(sheet).toHaveAttribute('data-detent', 'peek');
    await expect(sheet.locator('.app-mark h2')).toHaveText('r12');
    await expect(sheet.locator('.app-mark h2')).toBeInViewport();
    await expect(sheet.locator('h1')).toHaveCount(0);
    await page.locator('button[aria-label="Clear selection"]').click();
    await expect(page).not.toHaveURL(/spot=/);
    await expect(sheet.locator('h1')).toBeInViewport();
    expect(pageErrors).toEqual([]);
  });
});
