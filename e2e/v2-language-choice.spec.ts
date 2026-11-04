// SC0452-08: the app menu's English / Español choice (web/app/LanguageChoice.tsx, web/i18n.ts setLanguage).
// The real /map shell on the local server; every other origin is blocked (e2e/fixtures.ts) and the session
// is a synthetic signed-out answer. A choice changes the page at once, with no reload, and survives one.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const KEY = 'skippercast-language-v1';
// brief.planning, a covered line the brief shows in each language.
const PLANNING = {en: 'Planning aid · not a navigation chart.', es: 'Ayuda de planificación · no es una carta náutica.'};

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: false}}));
});

/** The account button: in the masthead, or (phone) in the sheet's footer with the sheet lifted to full. */
async function openMenu(page: Page, isMobile: boolean) {
  const trigger = page.locator('.app-account-trigger');
  if (isMobile) {
    await page.locator('.ui-sheet-handle').focus();
    await page.keyboard.press('End');
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
    await trigger.scrollIntoViewIfNeeded();
  }
  await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  const panel = page.locator('.app-account-panel');
  return {trigger, panel, english: panel.getByRole('button', {name: 'English'}), spanish: panel.getByRole('button', {name: 'Español'})};
}
const htmlLang = (page: Page) => page.evaluate(() => document.documentElement.lang);
/** A marker on the window: a navigation or reload would lose it. */
const mark = (page: Page) => page.evaluate(() => { (window as unknown as {__kept: boolean}).__kept = true; });
const kept = (page: Page) => page.evaluate(() => (window as unknown as {__kept?: boolean}).__kept === true);

test('language_choice_both_directions: an English browser chooses Español and back, with no reload and focus kept', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', AREA);
  expect(await htmlLang(page)).toBe('en');
  const {trigger, panel, english, spanish} = await openMenu(page, isMobile);
  await expect(english).toHaveAttribute('aria-pressed', 'true');
  await expect(spanish).toHaveAttribute('aria-pressed', 'false');
  await expect(spanish).toHaveAttribute('lang', 'es');
  await expect(english).toHaveAttribute('lang', 'en');
  await expect(page.getByText(PLANNING.en).first()).toBeAttached();
  await mark(page);

  await spanish.click();
  await expect(spanish).toHaveAttribute('aria-pressed', 'true');
  await expect(english).toHaveAttribute('aria-pressed', 'false');
  expect(await htmlLang(page)).toBe('es');
  await expect(panel.getByRole('heading', {name: 'Idioma'})).toBeVisible();
  await expect(page.getByText(PLANNING.es).first()).toBeAttached();
  await expect(english, 'each language is labelled in itself, in either language').toHaveText('English');
  await expect(spanish).toBeFocused();
  await expect(trigger, 'the menu stays open').toHaveAttribute('aria-expanded', 'true');
  expect(await page.evaluate(k => localStorage.getItem(k), KEY)).toBe('es');
  expect(await kept(page), 'no reload').toBe(true);

  await english.click();
  await expect(english).toHaveAttribute('aria-pressed', 'true');
  await expect(spanish).toHaveAttribute('aria-pressed', 'false');
  expect(await htmlLang(page)).toBe('en');
  await expect(panel.getByRole('heading', {name: 'Language'})).toBeVisible();
  await expect(page.getByText(PLANNING.en).first()).toBeAttached();
  await expect(english).toBeFocused();
  expect(await page.evaluate(k => localStorage.getItem(k), KEY)).toBe('en');
  expect(await kept(page), 'no reload').toBe(true);
  expect(pageErrors).toEqual([]);
});

test('language_choice_reload_and_opposing_link: the choice survives a reload, also over the address\'s own ?lang=', async ({page, pageErrors, v2, isMobile}) => {
  // No ?lang= in the address: the choice is stored and the address is left alone.
  await v2.open('app', AREA);
  let menu = await openMenu(page, isMobile);
  const address = page.url();
  await menu.spanish.click();
  expect(page.url(), 'the address is untouched').toBe(address);
  await page.reload();
  expect(await htmlLang(page)).toBe('es');
  await expect(page.getByText(PLANNING.es).first()).toBeAttached();
  menu = await openMenu(page, isMobile);
  await expect(menu.spanish).toHaveAttribute('aria-pressed', 'true');

  // ?lang=en in the address, then Español: only that value changes, and the reload reads Español.
  await page.evaluate(k => localStorage.removeItem(k), KEY);
  await v2.open('app', {...AREA, lang: 'en'});
  expect(await htmlLang(page)).toBe('en');
  const before = page.url();
  await mark(page);
  menu = await openMenu(page, isMobile);
  await menu.spanish.click();
  expect(page.url()).toBe(before.replace('lang=en', 'lang=es'));
  expect(await kept(page), 'no reload and no new document').toBe(true);
  await page.reload();
  expect(await htmlLang(page)).toBe('es');

  // The inverse, from an address that says Español.
  menu = await openMenu(page, isMobile);
  await menu.english.click();
  expect(page.url()).toBe(before);
  await page.reload();
  expect(await htmlLang(page)).toBe('en');
  expect(pageErrors).toEqual([]);
});

test.describe('storage blocked', () => {
  test.beforeEach(async ({page}) => {
    await page.addInitScript(() => {
      // Every read and write refuses, as a browser that blocks site data does. (A getter that throws on access is covered
      // in tests/test_i18n.mjs; other modules of the shell read the bare global unguarded, which is not this card's.)
      const refuse = () => { throw new DOMException('denied', 'QuotaExceededError'); };
      Object.defineProperty(window, 'localStorage', {configurable: true, value: {getItem: refuse, setItem: refuse, removeItem: refuse, clear: refuse, key: refuse, length: 0}});
    });
  });

  test('language_choice_storage_unavailable: the choice works for the visit and nothing is thrown', async ({page, pageErrors, v2, isMobile}) => {
    await v2.open('app', AREA);
    expect(await htmlLang(page)).toBe('en');
    const {spanish, english} = await openMenu(page, isMobile);
    await mark(page);
    await spanish.click();
    expect(await htmlLang(page)).toBe('es');
    await expect(spanish).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText(PLANNING.es).first()).toBeAttached();
    await english.click();
    expect(await htmlLang(page)).toBe('en');
    await expect(english).toHaveAttribute('aria-pressed', 'true');
    expect(await kept(page)).toBe(true);
    expect(pageErrors).toEqual([]);
  });
});

test('language_choice_keyboard: Enter and Space choose, the arrows and Escape work as before', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', AREA);
  const {trigger, panel, english, spanish} = await openMenu(page, isMobile);
  await spanish.focus();
  await page.keyboard.press('Enter');
  await expect(spanish).toHaveAttribute('aria-pressed', 'true');
  await expect(spanish).toBeFocused();
  await english.focus();
  await page.keyboard.press('Space');
  await expect(english).toHaveAttribute('aria-pressed', 'true');
  expect(await htmlLang(page)).toBe('en');
  await expect(english).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(spanish, 'the arrows still step through the menu').toBeFocused();
  await page.keyboard.press('Home');
  await expect(panel.getByRole('button', {name: 'Sign in or create an account'})).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(trigger).toBeFocused();
  expect(pageErrors).toEqual([]);
});
