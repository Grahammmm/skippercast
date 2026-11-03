// BF-deep-links: Share copies one canonical link (region, port, absolute day, profile); opening it elsewhere shows that port and
// profile without touching the saved home; a bad ?port= is cleaned; a dismissed sheet does nothing; no clipboard shows the link.
import type {BrowserContext, Page} from '@playwright/test';
import {expect, test} from './fixtures.ts';
const PORT_KEY = 'skippercast-home-port-v1', PROFILE_KEY = 'skippercast-profile-v1', SOCAL = 'southern-california';
const portButton = (page: Page) => page.locator('button.app-port');
const share = (page: Page) => page.getByRole('button', {name: 'Share this view'});
const status = (page: Page) => page.locator('.app-share-status');
/** On a phone the control sits low in the brief sheet, below the fold: dispatch the press rather than scroll the sheet. */
const press = (page: Page) => share(page).dispatchEvent('click');
/** navigator.share (none, or rejecting with `reject`) and a clipboard (recording, or absent); window.prompt is recorded. */
const stubShare = (context: BrowserContext, {reject = null as string | null, sheet = false, clipboard = true} = {}) => context.addInitScript(([reject, sheet, clipboard]) => {
  const w = window as unknown as {copies: string[]; shares: unknown[]; prompts: number};
  w.copies = []; w.shares = []; w.prompts = 0;
  window.prompt = () => { w.prompts++; return null; };
  Object.defineProperty(navigator, 'share', {configurable: true, value: sheet ? async (data: unknown) => { w.shares.push(data); if (reject) throw new DOMException('x', reject as string); } : undefined});
  Object.defineProperty(navigator, 'clipboard', {configurable: true, value: clipboard ? {writeText: async (text: string) => { w.copies.push(text); }} : undefined});
}, [reject, sheet, clipboard] as const);
const copies = (page: Page) => page.evaluate(() => (window as unknown as {copies: string[]}).copies);
const saved = (page: Page) => page.evaluate(key => localStorage.getItem(key), PORT_KEY);
const storage = (context: BrowserContext, port: string, profile: string) => context.addInitScript(([k1, v1, k2, v2]) => {
  if (!sessionStorage.getItem('seeded')) { localStorage.setItem(k1, v1); localStorage.setItem(k2, v2); sessionStorage.setItem('seeded', '1'); }
}, [PORT_KEY, port, PROFILE_KEY, profile]);

test('round trip: a link made at San Diego opens San Diego, today and Kayak for someone saved at Santa Barbara', async ({page, context, browser, baseURL, pageErrors, v2}) => {
  await stubShare(context);
  await storage(context, 'san-diego', 'kayak');
  await v2.open('app', {region: SOCAL, utm_source: 'x', diagnostics: '1'});
  await press(page);
  await expect(status(page)).toHaveText('Link copied');
  await press(page);
  await expect(status(page)).toHaveCount(1);
  const [link, again] = await copies(page);
  expect(again, 'a second press gives the same link').toBe(link);
  const url = new URL(link!);
  expect([...url.searchParams.keys()]).toEqual(['region', 'port', 'profile', 'day']);
  expect(url.searchParams.get('port')).toBe('san-diego');
  expect(url.searchParams.get('profile')).toBe('kayak');

  const other = await browser.newContext({baseURL});
  await other.route(u => u.origin !== new URL(baseURL!).origin, route => route.abort('blockedbyclient'));
  await other.route('**/feeds/**', route => route.fulfill({status: 404, json: {}}));
  await other.route('**/api/**', route => route.fulfill({status: 503, json: {}}));
  await other.addInitScript(() => localStorage.setItem('skippercast-first-run-v1', 'done'));
  await storage(other, 'santa-barbara', 'boat');
  const them = await other.newPage();
  const errors: string[] = [];
  them.on('pageerror', e => errors.push(String(e)));
  await them.goto(url.pathname + url.search + '&ui=v2');
  await expect(portButton(them)).toHaveAttribute('aria-label', 'Change port (San Diego)');
  await expect(them.locator('[aria-label="Profile"] [aria-pressed="true"]')).toHaveText('Kayak');
  await expect(them.locator('.app-window, [aria-label="Day"] [aria-pressed="true"]').first()).toContainText('Today');
  expect(await saved(them), 'the recipient\'s home is untouched').toBe('santa-barbara');
  expect(new URL(them.url()).searchParams.get('port')).toBe('san-diego');
  expect(errors).toEqual([]);
  await other.close();
});

test('an invalid, foreign, repeated or empty port falls back to the saved port and is removed from the address', async ({page, context, pageErrors}) => {
  await storage(context, 'ventura', 'boat');
  const consoleErrors: string[] = [];
  page.on('console', m => { if (m.type() === 'error' && /port/i.test(m.text())) consoleErrors.push(m.text()); });
  for (const query of [`region=${SOCAL}&port=nowhere`, `region=${SOCAL}&port=A..B`, `region=${SOCAL}&port=${'x'.repeat(200)}`, `region=${SOCAL}&port=%3Cscript%3E`,
    `region=${SOCAL}&port=san-diego&port=san-diego`, `region=${SOCAL}&port=`, 'region=monterey-point-sur&port=morro-bay']) {
    await page.goto(`/map?ui=v2&${query}`);
    await expect(page, query).not.toHaveURL(/[?&]port=/);
    await expect(portButton(page)).toHaveAttribute('aria-label', query.startsWith('region=monterey') ? /^Change port \(Monterey/ : /^Change port \(Ventura/);
    expect(await saved(page), query).toBe('ventura');
  }
  expect(consoleErrors).toEqual([]);
});

test('a directory that fails to load keeps the port in the address and the control renders', async ({page, pageErrors}) => {
  await page.route('**/data/home-ports.json', route => route.fulfill({status: 500, body: ''}));
  await page.goto(`/map?ui=v2&region=${SOCAL}&port=san-diego`);
  await expect(portButton(page)).toHaveAttribute('aria-label', 'Choose port');
  await expect(share(page)).toBeVisible();
  expect(new URL(page.url()).searchParams.get('port')).toBe('san-diego');
});

test('a dismissed share sheet does nothing; a refused one falls through to the clipboard', async ({page, context, pageErrors}) => {
  await stubShare(context, {sheet: true, reject: 'AbortError'});
  await page.goto(`/map?ui=v2&region=${SOCAL}&port=san-diego`);
  await press(page);
  await expect.poll(() => page.evaluate(() => (window as unknown as {shares: unknown[]}).shares.length)).toBe(1);
  expect(await copies(page)).toEqual([]);
  await expect(status(page)).toHaveText('');
  await expect(page.getByLabel('Link to copy')).toHaveCount(0);
  await page.evaluate(() => Object.defineProperty(navigator, 'share', {value: async () => { throw new DOMException('x', 'NotAllowedError'); }}));
  await press(page);
  await expect(status(page)).toHaveText('Link copied');
  expect((await copies(page)).length).toBe(1);
});

test('without a clipboard the link opens selected in a field; Escape closes it and returns to Share; no prompt', async ({page, context, pageErrors}) => {
  await stubShare(context, {clipboard: false});
  await page.goto(`/map?ui=v2&region=${SOCAL}&port=san-diego`);
  await press(page);
  const field = page.getByLabel('Link to copy');
  await expect(field).toBeFocused();
  expect(new URL(await field.inputValue()).searchParams.get('port')).toBe('san-diego');
  expect(await field.evaluate((el: HTMLInputElement) => el.selectionEnd! - el.selectionStart! === el.value.length)).toBe(true);
  await expect(status(page)).toHaveText('');
  await field.press('Escape');
  await expect(field).toHaveCount(0);
  await expect(share(page)).toBeFocused();
  expect(await page.evaluate(() => (window as unknown as {prompts: number}).prompts)).toBe(0);
});
