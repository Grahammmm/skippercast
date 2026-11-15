// RF1935-4: viewport emulation, not evidence from a physical keyboard.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay', profile: 'boat', target: 'lingcod'};
test.beforeEach(async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('skippercast-profile-v1', 'boat'));
});

async function geometry(page: Page) {
  return page.locator('.app-sheet .app-target-search').evaluate(el => {
    const r = el.getBoundingClientRect(), body = el.closest('.ui-sheet-body')!;
    const b = body.getBoundingClientRect();
    return {input: r.toJSON(), body: b.toJSON(), viewport: {width: innerWidth, height: innerHeight},
      visible: r.width > 0 && r.height > 0 && r.left >= 0 && r.right <= innerWidth && r.top >= Math.max(0, b.top + body.clientTop)
        && r.bottom <= Math.min(innerHeight, b.top + body.clientTop + body.clientHeight),
      hit: document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === el,
      overflow: document.documentElement.scrollWidth > innerWidth};
  });
}
async function editingVisible(page: Page) {
  await expect.poll(async () => {
    const g = await geometry(page); return g.visible && g.hit && !g.overflow;
  }).toBe(true);
}

for (const lang of ['en', 'es']) for (const detent of ['full', 'half', 'peek']) {
  test(`emulated short viewport preserves focus, filtering and blur: ${lang}, ${detent}`, async ({page, v2, isMobile}, info) => {
    test.skip(!isMobile, 'phone editing layout');
    await page.setViewportSize({width: 844, height: 390});
    await v2.open('app', {...AREA, lang, query: 'retained'});
    const sheet = page.locator('.app-sheet'), handle = page.locator('.ui-sheet-handle');
    const search = sheet.locator('.app-target-search'), select = sheet.locator('.app-target select');
    const tabs = page.locator('.app-tabs');
    const reservations = () => page.locator('.app-mobile').evaluate(el => ['--app-tabs', '--app-strip'].map(p => getComputedStyle(el).getPropertyValue(p)));
    const ordinary = await reservations();
    await expect(tabs.locator('a')).toHaveCount(4);
    await handle.focus();
    await page.keyboard.press(detent === 'full' ? 'End' : 'Home');
    if (detent === 'half') await page.keyboard.press('ArrowUp');
    await expect(sheet).toHaveAttribute('data-detent', detent);
    await sheet.evaluate(async el => { await Promise.all(el.getAnimations().map(a => a.finished)); });
    const url = page.url(), selected = await select.inputValue();
    // Real sequential keyboard reach, including native focus expansion from peek.
    for (let n = 0; n < 90 && !await search.evaluate(el => el === document.activeElement); n++) await page.keyboard.press('Tab');
    await expect(search).toBeFocused();
    const identity = await search.elementHandle();
    const stored = await sheet.getAttribute('data-detent');
    expect(stored).toBe(detent === 'peek' ? 'half' : detent);
    const before = await geometry(page);
    console.log('RF1935-4 before resize', JSON.stringify(before));
    await expect(tabs).toHaveCSS('display', 'none');
    expect(await reservations()).not.toEqual(ordinary);
    expect(page.url()).toBe(url);
    await expect(select).toHaveValue(selected);
    await expect(sheet.locator('.ui-sheet-body')).toHaveCSS('overflow', 'auto');
    await expect(sheet).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)');
    await search.fill('salm');
    await expect(select.locator('option:not([disabled])')).toHaveCount(2);
    await expect(select.locator('option[value="salmon"]')).toHaveCount(1);
    await expect(select).toHaveValue(selected);
    for (const size of [{width: 844, height: 220}, {width: 844, height: 260}, {width: 390, height: 844}, {width: 390, height: 420}, {width: 844, height: 220}, {width: 390, height: 844}, {width: 844, height: 390}]) {
      await page.setViewportSize(size);
      await editingVisible(page);
      const after = await geometry(page);
      console.log('RF1935-4 after resize', JSON.stringify(after));
      await info.attach(`emulated-${size.width}x${size.height}`, {body: JSON.stringify({before, after}), contentType: 'application/json'});
      await expect(search).toBeFocused();
      await expect(search).toHaveValue('salm');
      expect(await search.evaluate((el, original) => el === original, identity)).toBe(true);
      expect(page.url()).toBe(url);
    }
    await page.keyboard.press('Escape');
    await expect(search).toBeFocused(); // native Escape is not a custom blur/trap
    await search.fill('no-synthetic-match');
    await expect(select.locator('option:not([disabled])')).toHaveCount(1); // selected target survives a miss
    await search.fill('');
    await expect(select.locator('option:not([disabled])')).toHaveCount(10);
    await page.keyboard.press('Tab');
    await expect(select).toBeFocused();
    await expect(tabs).toBeVisible();
    expect(await reservations()).toEqual(ordinary);
    await expect(sheet).toHaveAttribute('data-detent', stored!);
    await select.selectOption('salmon');
    await expect(page).toHaveURL(/target=salmon/);
    // A second focus/blur cycle cannot leave stale presentation state.
    await search.focus();
    await expect(tabs).toBeHidden();
    await page.keyboard.press('Shift+Tab');
    await expect(search).not.toBeFocused();
    await expect(tabs).toBeVisible();
    expect(await reservations()).toEqual(ordinary);
  });
}

test('visual-only resize and scroll are bounded, duplicate events and cancelled focus leave no stale styles', async ({page, v2, isMobile}) => {
  test.skip(!isMobile, 'phone visual viewport');
  await page.setViewportSize({width: 390, height: 844});
  await v2.open('app', AREA);
  const sheet = page.locator('.app-sheet'), search = sheet.locator('.app-target-search');
  await page.locator('.ui-sheet-handle').press('End');
  await search.focus();
  // Synthetic visual-only keyboard shrink: layout viewport deliberately stays tall.
  await page.evaluate(() => {
    const viewport = window.visualViewport!;
    Object.defineProperty(viewport, 'height', {configurable: true, value: 220});
    Object.defineProperty(viewport, 'offsetTop', {configurable: true, value: 40});
    viewport.dispatchEvent(new Event('resize'));
    viewport.dispatchEvent(new Event('resize'));
    viewport.dispatchEvent(new Event('scroll'));
  });
  await editingVisible(page);
  await expect.poll(() => search.evaluate(el => {
    const r = el.getBoundingClientRect(), v = window.visualViewport!;
    return r.top >= v.offsetTop && r.bottom <= v.offsetTop + v.height;
  })).toBe(true);
  await expect(sheet).toHaveCSS('max-height', '220px');
  // Cancel a pending reveal with blur; late viewport events must not reapply it.
  await search.evaluate(el => {
    window.visualViewport!.dispatchEvent(new Event('scroll'));
    el.blur();
  });
  await page.evaluate(() => window.visualViewport!.dispatchEvent(new Event('resize')));
  await expect(page.locator('.app-tabs')).toBeVisible();
  await expect.poll(() => sheet.evaluate(el => el.style.maxHeight + el.style.bottom)).toBe('');
  await search.focus();
  await expect(sheet).toHaveCSS('max-height', '220px');
  await page.setViewportSize({width: 1280, height: 800});
  await expect(page.locator('.app-mobile')).toHaveCount(0);
  await page.evaluate(() => window.visualViewport!.dispatchEvent(new Event('scroll')));
  await expect(page.locator('.app-target-search')).toHaveCount(1);
});

test('non-target controls, separate Plan search and desktop keep their ordinary layout', async ({page, v2, isMobile}) => {
  await v2.open('app', AREA);
  if (!isMobile) {
    // The source guard reveals the first answer above the map after startup.
    // Measure the ordinary layout only once that answer is visible.
    await expect(page.locator('.app-first-answer')).toBeVisible();
    const search = page.locator('.app-target-search');
    const before = await page.locator('.app-stage').boundingBox();
    await search.fill('salm');
    expect(await page.locator('.app-stage').boundingBox()).toEqual(before);
    await expect(page.locator('.app-target select option[value="salmon"]')).toHaveCount(1);
    await expect(page.locator('.app-mobile')).toHaveCount(0);
    return;
  }
  await page.locator('.ui-sheet-handle').press('End');
  for (const selector of ['[aria-label="Day"] button', 'input[type="range"]', '.app-sheet a', '.app-target select']) {
    await page.locator(selector).first().focus();
    await expect(page.locator('.app-tabs')).toBeVisible();
    await expect(page.locator('.app-mobile')).not.toHaveCSS('--app-tabs', '0px');
  }
  await v2.open('app', {...AREA, view: 'plan'});
  await page.locator('.app-mobile-page .app-target-search').focus();
  await expect(page.locator('.app-tabs')).toBeVisible();
  await page.locator('.app-limits-trigger').click();
  await page.locator('.app-limits-dialog input').first().focus();
  await expect(page.locator('.app-tabs')).toBeVisible();
});
