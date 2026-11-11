// RF2135-5 (UX audit S4-08, top-chrome slice): on ordinary landscape phones the top card/controls row and the profile
// switch sit side by side, so the header is short and the map keeps a band above the peek sheet. Rectangles are
// measured as the page sits, before any test action can scroll it.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const SHELL = '/map?region=morro-bay&ui=v2';
const SIZES = [[844, 390], [667, 375], [640, 360]] as const;

async function open(page: Page, width: number, height: number, lang = 'en'): Promise<void> {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: false}}));
  await page.setViewportSize({width, height});
  await page.goto(`${SHELL}${lang === 'es' ? '&lang=es' : ''}`);
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'peek');
  await expect.poll(() => page.locator('.ui-sheet').evaluate(el => el.getBoundingClientRect().top)).toBeGreaterThan(0);
}

const measure = (page: Page) => page.evaluate(() => {
  const r = (el: Element | null) => { const b = el?.getBoundingClientRect(); return b ? {top: b.top, bottom: b.bottom, left: b.left, right: b.right, width: b.width, height: b.height} : null; };
  const controls = [...document.querySelectorAll('.app-top button, .app-top a, .app-top .ui-chip')].map(el => r(el)!);
  return {
    header: r(document.querySelector('.app-top')), sheet: r(document.querySelector('.ui-sheet')), controls,
    profile: r(document.querySelector('.app-profile')), row: r(document.querySelector('.app-top-row')),
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
});

for (const lang of ['en', 'es']) {
  for (const [w, h] of SIZES) {
    test(`landscape_top_chrome_geometry ${w}x${h} ${lang}: short header, whole controls, 44px targets`, async ({page}) => {
      await open(page, w, h, lang);
      const m = await measure(page);
      expect(m.header!.bottom).toBeLessThanOrEqual(80);
      expect(m.header!.bottom).toBeLessThanOrEqual(m.sheet!.top);
      expect(m.overflow).toBeLessThanOrEqual(0);
      expect(m.profile!.top).toBeLessThan(m.row!.bottom); // beside, not below
      expect(m.controls.length).toBeGreaterThanOrEqual(5);
      for (const c of m.controls) {
        expect(c.left).toBeGreaterThanOrEqual(0); expect(c.right).toBeLessThanOrEqual(w);
        expect(c.top).toBeGreaterThanOrEqual(0); expect(c.bottom).toBeLessThanOrEqual(m.sheet!.top);
        expect(c.height).toBeGreaterThanOrEqual(43.5);
      }
    });
  }
}

test('landscape_boundaries: portrait and 500/501 px heights keep the stacked header', async ({page}) => {
  await open(page, 700, 501);
  const tall = await measure(page);
  expect(tall.profile!.top).toBeGreaterThanOrEqual(tall.row!.bottom - 1);
  await page.setViewportSize({width: 700, height: 500});
  await expect.poll(async () => { const m = await measure(page); return m.profile!.top < m.row!.bottom; }).toBe(true);
  await page.setViewportSize({width: 390, height: 844});
  await expect.poll(async () => { const m = await measure(page); return m.profile!.top >= m.row!.bottom - 1; }).toBe(true);
});

test('landscape_controls_and_detents_still_work', async ({page}) => {
  await open(page, 667, 375);
  await page.locator('.ui-sheet-handle').focus();
  await page.keyboard.press('End');
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
  await page.keyboard.press('Home');
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'peek');
  const chips = page.locator('.app-profile .ui-chip');
  await chips.nth(1).click();
  await expect(chips.nth(1)).toHaveAttribute('aria-pressed', 'true');
});
