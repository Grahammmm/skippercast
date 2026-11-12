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

// RF1925-1: actual clicks in the real scroll context, with a deterministic fleet neighbour.
async function revealShare(page: Page) {
  const handle = page.locator('.ui-sheet-handle');
  if (await handle.isVisible()) {
    await handle.press('End');
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
  }
  await page.locator('.app-share button').scrollIntoViewIfNeeded();
}
async function fallbackGeometry(page: Page, manual: boolean) {
  const geometry = await page.evaluate(manual => {
    const wrap = document.querySelector('.app-share')!;
    const rect = (el: Element) => el.getBoundingClientRect();
    const w = rect(wrap);
    const pieces = manual ? [wrap.querySelector('button')!, wrap.querySelector('summary')!, wrap.querySelector('input')!] :
      [wrap.querySelector('button')!, wrap.querySelector('[role=status]')!];
    const visible = (el: Element) => rect(el).width > 0 && rect(el).height > 0;
    const neighbours = [...document.querySelectorAll('.app-brief-links, .app-share ~ *, .app-area > button, .app-area > label')].filter(visible);
    const overlap = (a: DOMRect, b: DOMRect) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
      Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
    const boxes = pieces.map(rect);
    const scrolls = [document.documentElement, ...document.querySelectorAll('.ui-sheet, .ui-sheet-body')];
    return {
      contained: boxes.every(b => b.left >= w.left - 1 && b.right <= w.right + 1 && b.top >= w.top - 1 && b.bottom <= w.bottom + 1),
      overlaps: boxes.flatMap((a, i) => [...boxes.slice(i + 1), ...neighbours.map(rect)].map(b => overlap(a, b))),
      following: [...document.querySelectorAll('.app-brief-links')].filter(visible).every(el => rect(el).top >= w.bottom),
      overflow: scrolls.map(el => el.scrollWidth - el.clientWidth),
      offenders: [...document.querySelectorAll('body *')].filter(el => rect(el).right > document.documentElement.clientWidth + 1).slice(0, 15).map(el => ({cls: el.className, right: rect(el).right, width: rect(el).width})),
    };
  }, manual);
  expect(geometry.contained, 'feedback contributes to the reserved share area').toBe(true);
  expect(geometry.overlaps.every(n => n === 0), 'feedback never covers other controls or fleet text').toBe(true);
  expect(geometry.following, 'fleet text follows the reserved area').toBe(true);
  expect(geometry.overflow, JSON.stringify(geometry.offenders)).toEqual(geometry.overflow.map(() => 0));
}

for (const lang of ['en', 'es'] as const) for (const narrow of [false, true]) {
  test(`fallback geometry ${lang} ${narrow ? '320px enlarged text' : 'project viewport'}`, async ({page, context, v2, pageErrors}) => {
    if (narrow) await page.setViewportSize({width: 320, height: 844});
    await stubShare(context);
    await storage(context, 'morro-bay', 'boat');
    const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date());
    await v2.feed('**/feeds/data/regions/morro-bay/latest.json', {
      schema_version: 1, generated_at: new Date().toISOString(), region_id: 'morro-bay', sources: {}, landing_names: ['Morro Bay'],
      reports: ['Gull', 'Tern', 'Finch', 'Swan', 'Lark'].map(boat => ({boat: `Fixture ${boat}`, port: 'Morro Bay', date: today})),
    });
    await page.route('**/api/coast/report*', r => r.fulfill({status: 503, json: {}}));
    await v2.open('app', {region: 'morro-bay', port: 'morro-bay', lang});
    await expect(page.locator('.app-brief-links')).toContainText('5 boats reported');
    if (narrow) {
      await page.route('**/share-text-fixture.css', r => r.fulfill({contentType: 'text/css', body: '.app-share { font-size: 200%; } .app-share-status, .app-share-popover input { font-size: inherit; }'}));
      await page.addStyleTag({url: '/share-text-fixture.css'});
    }
    await revealShare(page);
    const button = page.locator('.app-share button');
    const idleHeight = await page.locator('.app-share').evaluate(el => el.getBoundingClientRect().height);

    await button.click();
    await expect(status(page)).toHaveText(lang === 'es' ? 'Enlace copiado' : 'Link copied');
    expect((await copies(page)).length).toBe(1);
    await fallbackGeometry(page, false);
    await button.click();
    expect((await copies(page)).length).toBe(2);
    const [first, second] = await copies(page);
    expect(second).toBe(first);
    expect([...new URL(first!).searchParams.keys()]).toEqual(['region', 'port', 'profile', 'day']);
    await fallbackGeometry(page, false);
    await expect(status(page)).toBeEmpty({timeout: 5000});
    expect(await page.locator('.app-share').evaluate(el => el.getBoundingClientRect().height)).toBe(idleHeight);

    for (const mode of ['missing', 'rejected', 'native-rejected']) {
      await page.evaluate(mode => {
        Object.defineProperty(navigator, 'clipboard', {configurable: true, value: mode === 'missing' ? undefined : {writeText: async () => { throw new Error('Synthetic refusal'); }}});
        Object.defineProperty(navigator, 'share', {configurable: true, value: mode === 'native-rejected' ? async () => { throw new DOMException('Synthetic refusal', 'NotAllowedError'); } : undefined});
      }, mode);
      await button.click();
      const details = page.locator('.app-share-popover'), field = details.locator('input');
      await expect(details).toHaveAttribute('open', '');
      await expect(details.locator('summary')).toHaveText(lang === 'es' ? 'Enlace' : 'Link', {ignoreCase: true});
      await expect(field).toBeFocused();
      await expect(field).toHaveAttribute('readonly', '');
      expect(await field.inputValue()).toBe(first);
      expect(await field.evaluate((el: HTMLInputElement) => el.selectionStart === 0 && el.selectionEnd === el.value.length)).toBe(true);
      await expect(status(page)).toBeEmpty();
      await fallbackGeometry(page, true);
      // A long synthetic URL must scroll inside the field, not widen the disclosure/page.
      await field.evaluate((el: HTMLInputElement) => { el.value += `&fixture=${'x'.repeat(2000)}`; el.select(); });
      await fallbackGeometry(page, true);
      await details.locator('summary').click();
      await expect(details).not.toHaveAttribute('open', '');
      await expect(field).not.toBeVisible();
      await details.locator('summary').click();
      await expect(field).toBeVisible();
      await button.click();
      await expect(details.locator('input')).toHaveCount(1);
      await field.press('Escape');
      await expect(details).toHaveCount(0);
      await expect(button).toBeFocused();
      expect(await page.locator('.app-share').evaluate(el => el.getBoundingClientRect().height)).toBe(idleHeight);
    }
    expect(await page.evaluate(() => (window as unknown as {prompts: number}).prompts)).toBe(0);
    expect(pageErrors).toEqual([]);
  });
}

// SC1922-02: with no share sheet and no clipboard at all, the manual-copy panel takes its own space: inside the viewport, clear of the
// next visible text block (the fleet line), wide enough to show the start of the link, and Escape gives the space back and focuses Share.
async function openManualPanel(page: Page, context: BrowserContext, size: {width: number; height: number}, theme: 'dark' | 'light') {
  await page.setViewportSize(size);
  await stubShare(context, {clipboard: false});
  await storage(context, 'morro-bay', 'boat');
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date());
  await page.route('**/feeds/data/regions/morro-bay/latest.json', r => r.fulfill({json: {
    schema_version: 1, generated_at: new Date().toISOString(), region_id: 'morro-bay', sources: {}, landing_names: ['Morro Bay'],
    reports: ['Gull', 'Tern', 'Finch', 'Swan', 'Lark'].map(boat => ({boat: `Fixture ${boat}`, port: 'Morro Bay', date: today})),
  }}));
  await page.route('**/api/coast/report*', r => r.fulfill({status: 503, json: {}}));
  await page.goto('/map?ui=v2&region=morro-bay&port=morro-bay');
  await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
  const fleet = page.locator('.app-brief-links').first();
  await expect(fleet).toContainText('5 boats reported');
  await revealShare(page);
  const gap = () => fleet.evaluate(el => el.getBoundingClientRect().top - document.querySelector('.app-share button')!.getBoundingClientRect().top);
  const idleGap = await gap();
  await share(page).click();
  return {fleet, idleGap, gap};
}
const phoneSizes = [{width: 390, height: 844}, {width: 320, height: 640}, {width: 412, height: 844}];
for (const size of phoneSizes) for (const theme of (size.width === 390 ? ['dark', 'light'] : ['dark']) as ('dark' | 'light')[]) {
  test(`manual share panel ${size.width}x${size.height} ${theme}: inside the viewport, clear of the next text, Escape returns to Share`, async ({page, context, pageErrors}) => {
    const {fleet, idleGap, gap} = await openManualPanel(page, context, size, theme);
    const panel = page.locator('.app-share-popover'), field = panel.locator('input');
    await expect(field).toBeFocused();
    await expect(field).toHaveAttribute('readonly', '');
    expect(await field.evaluate((el: HTMLInputElement) => el.selectionStart === 0 && el.selectionEnd === el.value.length)).toBe(true);
    expect(new URL(await field.inputValue()).searchParams.get('port')).toBe('morro-bay');
    await expect(status(page)).toHaveText('');
    await fleet.scrollIntoViewIfNeeded();
    await expect(fleet).toBeInViewport();
    await expect(panel).toBeInViewport();
    const g = await page.evaluate(() => {
      const box = (el: Element) => { const r = el.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height}; };
      const panel = document.querySelector('.app-share-popover')!, fleet = document.querySelector('.app-brief-links')!;
      const parts = [panel, panel.querySelector('summary'), panel.querySelector('.ui-popover-body'), panel.querySelector('input')];
      const input = panel.querySelector('input')!, style = getComputedStyle(input);
      return {
        parts: parts.map(el => el ? box(el) : null), fleet: box(fleet),
        vw: document.documentElement.clientWidth, vh: window.innerHeight,
        content: input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
        bg: getComputedStyle(panel.querySelector('.ui-popover-body')!).backgroundColor,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });
    expect(g.parts.every(p => p && p.w > 0 && p.h > 0), 'panel, summary, body and input all have boxes').toBe(true);
    for (const p of g.parts) {
      expect(p!.l, 'left edge').toBeGreaterThanOrEqual(-1); expect(p!.r, 'right edge').toBeLessThanOrEqual(g.vw + 1);
      expect(p!.t, 'top edge').toBeGreaterThanOrEqual(-1); expect(p!.b, 'bottom edge').toBeLessThanOrEqual(g.vh + 1);
    }
    const p = g.parts[0]!, f = g.fleet;
    expect(f.w > 0 && f.h > 0, 'the fleet line is rendered').toBe(true);
    const apart = p.r <= f.l || f.r <= p.l || p.b <= f.t || f.b <= p.t;
    expect(apart, `panel ${JSON.stringify(p)} must not intersect the fleet line ${JSON.stringify(f)}`).toBe(true);
    expect(f.t, 'the fleet line sits below the panel, not painted over it').toBeGreaterThanOrEqual(p.b - 1);
    expect(g.content, 'the field shows the start of the link').toBeGreaterThanOrEqual(160);
    expect(g.bg, 'opaque panel').not.toMatch(/rgba\(.*, 0\)$|transparent/);
    expect(g.overflow, 'no horizontal scroll').toBeLessThanOrEqual(0);

    await field.press('Escape');
    await expect(panel).toHaveCount(0);
    await expect(share(page)).toBeFocused();
    expect(Math.abs(await gap() - idleGap), 'the added row is released').toBeLessThanOrEqual(1);
    await share(page).click();
    await expect(panel).toHaveCount(1);
    await expect(field).toBeFocused();
    expect(await page.evaluate(() => (window as unknown as {prompts: number}).prompts)).toBe(0);
    expect(pageErrors).toEqual([]);
  });
}
