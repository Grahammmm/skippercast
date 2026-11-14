// SC1722-14: computed CSS precondition only; real iOS focus zoom is unconfirmed.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

async function census(page: Page, surface: string, families: string[]) {
  await page.evaluate(() => document.fonts.ready);
  const fields = await page.locator('input:visible, select:visible, textarea:visible').evaluateAll(els => els.map(el => {
    const s = getComputedStyle(el), b = el.getBoundingClientRect();
    return {label: el.getAttribute('aria-label'), id: el.id, cls: el.className,
      family: el.tagName === 'INPUT' ? el.getAttribute('type') || 'text' : el.tagName.toLowerCase(),
      fontSize: parseFloat(s.fontSize), box: {x: b.x, y: b.y, width: b.width, height: b.height}};
  }));
  console.log(surface, JSON.stringify(fields));
  expect(fields.length, surface).toBeGreaterThan(0);
  for (const family of families) expect(fields.some(f => f.family === family), `${surface}: ${family}`).toBe(true);
  for (const f of fields) {
    expect(Number.isFinite(f.fontSize) && f.fontSize >= 16, `${surface}: ${JSON.stringify(f)}`).toBe(true);
    expect(f.box.x, `${surface}: left edge ${f.cls}`).toBeGreaterThanOrEqual(0);
    expect(f.box.x + f.box.width, `${surface}: right edge ${f.cls}`).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth), surface).toBeLessThanOrEqual(page.viewportSize()!.width);
}

// Compare fixed-state layout with the shared rule removed, then restored. Intrinsic
// select widths may change; only the granted search widening is allowed.
async function targetGeometry(page: Page) {
  return page.evaluate(() => {
    const el = document.querySelector<HTMLInputElement>('.app-target-search:where(:not([hidden]))')!;
    const snapshot = () => {
      const s = getComputedStyle(el), b = el.getBoundingClientRect();
      const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d')!;
      ctx.font = `${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
      return {font: s.font, family: s.fontFamily, weight: s.fontWeight, width: b.width, height: b.height, text: ctx.measureText(el.placeholder).width,
        client: el.clientWidth, scroll: el.scrollWidth, content: b.width - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight) - parseFloat(s.borderLeftWidth) - parseFloat(s.borderRightWidth)};
    };
    const sheet = [...document.styleSheets].find(s => [...s.cssRules].some(r => r instanceof CSSStyleRule && r.selectorText === 'input, select, textarea'))!;
    const index = [...sheet.cssRules].findIndex(r => r instanceof CSSStyleRule && r.selectorText === 'input, select, textarea');
    const rule = sheet.cssRules[index].cssText, after = snapshot();
    sheet.deleteRule(index);
    const before = snapshot();
    sheet.insertRule(rule, index);
    return {before, after};
  });
}

for (const lang of ['en', 'es']) test(`all visible fields, dialogs and interactions at 16px (${lang})`, async ({page, v2, isMobile, pageErrors}) => {
  await page.addInitScript(() => localStorage.setItem('skippercast-profile-v1', 'shore'));
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: false}}));
  await v2.open('landing', {lang});
  await expect(page.locator('input[type="search"]:visible').first()).toBeVisible();
  await census(page, 'landing', ['search']);
  const landingSearch = page.locator('input[type="search"]:visible').first();
  await landingSearch.fill('san d');
  await expect(landingSearch).toHaveValue('san d');
  await landingSearch.fill('');

  await v2.open('app', {region: 'morro-bay', profile: 'shore', view: 'plan', lang});
  // The Plan view is the active phone surface and has no coast-sheet handle.
  const find = page.locator('.app-target-search:visible');
  await expect(find).toHaveAttribute('placeholder', lang === 'es' ? 'Busca especie' : 'Find a target');
  await census(page, 'map', ['search', 'select']);
  const geometry = await targetGeometry(page);
  console.log('target before/after', lang, JSON.stringify(geometry));
  expect(geometry.after.width).toBe(133);
  expect(geometry.after.scroll).toBeLessThanOrEqual(geometry.after.client);
  expect(geometry.after.text).toBeLessThanOrEqual(geometry.after.content);
  expect(geometry.after.height).toBeGreaterThanOrEqual(44);
  const select = page.locator('.app-target select:visible');
  const choices = await select.locator('option').evaluateAll(els => els.map(el => ({value: (el as HTMLOptionElement).value, label: el.textContent!})));
  const choice = choices.find(c => c.value !== '')!;
  await select.selectOption(choice.value);
  await expect(select).toHaveValue(choice.value);
  await find.fill('zzzz-no-target');
  await expect(select.locator('option')).toHaveCount(1); // selected target survives a nonmatch
  await expect(select).toHaveValue(choice.value);
  await find.fill('');
  expect(await select.locator('option').count()).toBeGreaterThan(1);
  await find.focus();
  await expect(find).toBeFocused();
  expect(await find.evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe('none');

  const limits = page.locator('dialog.app-limits-dialog');
  await expect(limits).toBeHidden();
  await page.locator('.app-limits-trigger:visible').click();
  await expect(limits).toBeVisible();
  await expect(limits.locator('input[type="number"]').first()).toBeVisible();
  await census(page, 'Limits', ['number', 'select']);
  const number = limits.locator('input[type="number"]').first();
  await number.fill('6');
  await expect(number).toHaveValue('6');
  await page.keyboard.press('Escape'); // cancel, no limit save
  await expect(limits).toBeHidden();
  expect(await page.evaluate(() => localStorage.getItem('skippercast-limits-v1'))).toBeNull();
  if (isMobile) {
    await v2.open('app', {region: 'morro-bay', profile: 'shore', view: 'coast', lang});
    await page.locator('.ui-sheet-handle').press('End');
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
    await census(page, 'expanded coast sheet', ['search', 'select']);
  }
  await page.locator('.app-port:visible').click();
  const port = page.locator('dialog.port-dialog');
  await expect(port).toBeVisible();
  await census(page, 'port', ['search']);
  await port.locator('input[type="search"]').fill('san d');
  await expect(port.locator('[data-port]')).toHaveCount(1);
  await port.locator('input[type="search"]').fill('');
  await expect(port.locator('[data-port]')).toHaveCount(6);
  await page.keyboard.press('Escape');
  await expect(port).toBeHidden();

  // Fixture coverage, not a discovered production textarea. Include disabled
  // visible fields and hidden fields to guard against a vacuous census.
  await page.evaluate(() => {
    const fixture = document.createElement('div');
    fixture.id = 'input-size-fixture'; fixture.style.fontSize = '13px';
    fixture.style.display = 'flex'; fixture.style.flexWrap = 'wrap';
    fixture.innerHTML = '<textarea aria-label="Font fixture"></textarea><input disabled aria-label="Disabled fixture"><input type="hidden">';
    document.body.append(fixture);
  });
  for (const theme of ['dark', 'light']) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
    await census(page, `${theme} + textarea fixture`, ['textarea', 'text']);
  }
  expect(pageErrors).toEqual([]);
});
