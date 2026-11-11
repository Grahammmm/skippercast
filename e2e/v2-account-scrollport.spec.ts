// RF2135-6 (audit S4-32): the real account dialog with long synthetic rows keeps its whole border box in the viewport, is the only
// scrollport, reaches its last content, and shows scroll-edge cues only where there is more to scroll. Nothing authenticates.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const SIZES = [[1440, 900], [390, 844], [360, 640], [844, 390]] as const;
const long = 'Long synthetic note '.repeat(12);
const rows = Array.from({length: 40}, (_, i) => ({id: `e${i}`, started_at: new Date(Date.UTC(2026, 5, 1) - i * 3600_000).toISOString(), ended_at: null,
  outcome: 'blank', count: 0, trip_id: null, species: `Species ${i}`, method: null, lat: null, lon: null, note: long}));
const spots = Array.from({length: 20}, (_, i) => ({id: `s${i}`, name: `Spot ${i}`, lat: 35.2, lon: -120.8, note: long}));

async function stub(page: Page, signedIn: boolean) {
  await page.route('**/api/session', route => route.fulfill({json: signedIn
    ? {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null} : {signIn: '/#account', signedIn: false}}));
  await page.route('**/api/auth/passkeys', route => route.fulfill({json: {passkeys: [{id: 'p1', created_at: '2026-10-01T00:00:00Z', last_used_at: null}]}}));
  await page.route('**/api/spots', route => route.fulfill({json: {spots}}));
  await page.route('**/api/trips', route => route.fulfill({json: {trips: [], events: []}}));
  await page.route(url => url.pathname === '/api/catch-log', route => route.fulfill({json: {entries: rows}, headers: {'X-SC-Catch-Log-Has-More': 'false'}}));
}
const open = async (page: Page, v2: {open(n: 'app', p?: Record<string, string>): Promise<void>}) => {
  await v2.open('app', AREA);
  await page.evaluate(() => { location.hash = 'account'; });
};
const cues = (page: Page) => page.locator('.account-card').evaluate(el => ({top: el.scrollTop, max: el.scrollHeight - el.clientHeight}));

for (const [w, h] of SIZES) {
  test(`account_initial_border_box_inside_viewport_${w}x${h}`, async ({page, v2}) => {
    await page.setViewportSize({width: w, height: h});
    await stub(page, true);
    await open(page, v2);
    const card = page.locator('.account-card');
    await expect(card).toContainText('Signed in as Skipper');
    const box = await card.evaluate(el => { const r = el.getBoundingClientRect(); return {t: r.top, b: r.bottom, l: r.left, r: r.right, vw: innerWidth, vh: innerHeight, sw: document.documentElement.scrollWidth}; });
    expect(box.t).toBeGreaterThanOrEqual(0); expect(box.l).toBeGreaterThanOrEqual(0);
    expect(box.b).toBeLessThanOrEqual(box.vh); expect(box.r).toBeLessThanOrEqual(box.vw);
    expect(box.sw).toBeLessThanOrEqual(box.vw);
  });
}

test('account_card_is_only_scrollport_and_reaches_end', async ({page, v2}) => {
  await page.setViewportSize({width: 390, height: 640});
  await stub(page, true);
  await open(page, v2);
  const card = page.locator('.account-card');
  await expect(card).toContainText('Signed in as Skipper');
  const s = await cues(page);
  expect(s.top).toBe(0); expect(s.max).toBeGreaterThan(0);
  expect(await page.locator('#account-body').evaluate(el => el.scrollHeight <= el.clientHeight + 1 || getComputedStyle(el).overflowY === 'visible')).toBe(true);
  await card.evaluate(el => { el.scrollTop = el.scrollHeight; });
  // The close button is the card's absolutely-positioned last child (top-right); focusing it scrolls back to the top, so take the last visible control in the body (the closed delete <details> hides its button; its summary is the last reachable control).
  const last = page.locator('#account-body').locator('button, summary, input, a').locator('visible=true').last();
  await last.focus();
  await expect(last).toBeFocused();
  expect((await cues(page)).top).toBeGreaterThan(0);
});

test('account_scroll_cues_short_content_has_none', async ({page, v2}) => {
  await page.setViewportSize({width: 1440, height: 1200});
  await stub(page, false);
  await open(page, v2);
  await expect(page.locator('.account-card')).toBeVisible();
  const s = await cues(page);
  expect(s.max).toBeLessThanOrEqual(0);
});

test('account_keyboard_escape_still_closes', async ({page, v2}) => {
  await page.setViewportSize({width: 390, height: 640});
  await stub(page, true);
  await open(page, v2);
  await expect(page.locator('.account-card')).toContainText('Signed in as Skipper');
  await page.keyboard.press('Escape');
  await expect(page.locator('.account-card')).toHaveCount(0);
});
