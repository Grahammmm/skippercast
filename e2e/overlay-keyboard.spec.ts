// UXFIX-01 / R-P1 (S4-02 re-test per S5 E3): one table-driven keyboard contract for every blocking overlay.
// Opened from the keyboard: focus lands inside within 1 s; for modal overlays Tab and Shift+Tab never leave;
// Escape closes it and focus returns to the opener (never body); a click on the scrim closes it likewise.
// Not in the table: the desktop first-run card (non-modal, RF2235-8 / e2e/first-run-keyboard.spec.ts) and the basis popover (RF0834-7).
// The account dialog signed in is driven against stubbed /api/session and /api/auth/passkeys: nothing is stored, no passkey ceremony runs.
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const read = (file: string) => JSON.parse(readFileSync(join(import.meta.dirname, '..', 'web', file), 'utf8'));
const english = read('strings.en.generated.json') as Record<string, {en: string}>, spanish = read('strings.es.generated.json') as Record<string, string>;
const copy = (id: string, lang: string) => (lang === 'es' ? spanish[id] : english[id]?.en) ?? english[id]!.en;

/** Focus the opener and press Enter, as a keyboard user does. */
async function activate(page: Page, selector: string) {
  const opener = page.locator(selector).first();
  await opener.focus();
  await page.keyboard.press('Enter');
  return opener;
}
/** The account menu's trigger opens the menu; the named entry opens the overlay, and the menu's trigger is its opener. */
async function viaMenu(page: Page, id: string, lang: string) {
  const opener = await activate(page, '.app-account-trigger');
  const entry = page.locator('.app-account-panel').getByRole('button', {name: copy(id, lang), exact: true});
  await expect(entry).toBeEnabled();
  await entry.focus();
  await page.keyboard.press('Enter');
  return opener;
}

type Case = {name: string; overlay: string; modal: boolean; scrim: boolean; signedIn?: boolean; open: (page: Page, lang: string) => Promise<ReturnType<Page['locator']>>};
// Share has no scrim and is not modal: it is a popover the person can leave by Tab, closed by Escape (web/app/CommandBar.tsx).
const CASES: readonly Case[] = [
  {name: 'account signed out', overlay: '.account-card', modal: true, scrim: true, open: (page, lang) => viaMenu(page, 'accountMenu.signInCreate', lang)},
  {name: 'account signed in', overlay: '.account-card', modal: true, scrim: true, signedIn: true, open: (page, lang) => viaMenu(page, 'accountMenu.manage', lang)},
  {name: 'limits', overlay: 'dialog.app-limits-dialog:modal', modal: true, scrim: true, open: page => activate(page, '.app-limits-trigger')},
  {name: 'choose port', overlay: 'dialog.port-dialog:modal', modal: true, scrim: true, open: page => activate(page, 'button.app-port')},
  {name: 'save for offline', overlay: 'dialog.port-dialog:modal', modal: true, scrim: true, open: (page, lang) => viaMenu(page, 'accountMenu.offline', lang)},
  {name: 'trip plan', overlay: 'dialog.app-trip:modal', modal: true, scrim: true, open: (page, lang) => viaMenu(page, 'accountMenu.trip', lang)},
  // The plan's own link to Save for offline: the opener closes with the plan, so focus falls back to the masthead trigger.
  {name: 'save for offline from the trip plan', overlay: 'dialog.port-dialog:modal', modal: true, scrim: true, open: async (page, lang) => {
    const opener = await viaMenu(page, 'accountMenu.trip', lang);
    await page.locator('dialog.app-trip').getByRole('button', {name: copy('trip.legal.open', lang), exact: true}).focus();
    await page.keyboard.press('Enter');
    return opener;
  }},
  {name: 'trip alerts', overlay: 'dialog.port-dialog:modal', modal: true, scrim: true, open: (page, lang) => viaMenu(page, 'accountMenu.alertsAction', lang)},
  {name: 'share', overlay: '.app-share-popover', modal: false, scrim: false, open: page => activate(page, '.app-share button')},
];

test.describe('overlay keyboard contract (R-P1)', () => {
  test.beforeEach(async ({page, isMobile}) => {
    test.skip(isMobile, 'laptop project only: the phone layout opens these from the sheet (e2e/v2-dialog-fit.spec.ts)');
    await page.addInitScript(() => {
      try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ }
      Object.defineProperty(PublicKeyCredential, 'isConditionalMediationAvailable', {value: async () => false});
    });
    // The share link falls back to the manual field when the clipboard is unavailable, which is the overlay under test.
    await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', {value: undefined}));
  });

  for (const lang of ['en', 'es']) {
    for (const c of CASES) {
      test(`${c.name} (${lang})`, async ({page, pageErrors, v2}) => {
        const signedIn = c.signedIn === true;
        await page.route('**/api/session', route => route.fulfill({json: signedIn
          ? {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null} : {signIn: '/#account', signedIn: false}}));
        await page.route('**/api/auth/passkeys', route => route.fulfill({json: {passkeys: [{id: 'p1', created_at: '2026-10-01T00:00:00Z', last_used_at: null}]}}));
        await page.route(/\/api\/(trips|spots|catch-log)$/, route => route.fulfill({json: {trips: [], spots: [], entries: []}}));
        await v2.open('app', {region: 'morro-bay', lang});
        const overlay = page.locator(c.overlay).first();
        const inside = () => overlay.evaluate(el => el.contains(document.activeElement));
        // A native modal dialog hands Tab to the browser's own UI (activeElement is body) and keeps the page behind it inert;
        // that is the platform trap. Every other overlay keeps focus on an element of its own.
        const trapped = async () => (await inside()) || (c.overlay.startsWith('dialog') && await page.evaluate(() => document.activeElement === document.body));
        const opener = await c.open(page, lang);
        await expect(overlay).toBeVisible();
        // Every overlay moves focus in as it opens (showModal, or the account card's own focus call), so the check is immediate, inside 1 s.
        expect(await inside(), 'focus moved into the overlay').toBe(true);
        if (c.modal) {
          for (let i = 0; i < 10; i++) { await page.keyboard.press('Tab'); expect(await trapped(), `Tab ${i + 1} stays inside`).toBe(true); }
          for (let i = 0; i < 3; i++) { await page.keyboard.press('Shift+Tab'); expect(await trapped(), `Shift+Tab ${i + 1} stays inside`).toBe(true); }
        }
        await page.keyboard.press('Escape');
        await expect(overlay).toBeHidden();
        await expect(opener, 'focus returns to the opener').toBeFocused();
        if (c.scrim) {
          await c.open(page, lang);
          await expect(overlay).toBeVisible();
          await page.mouse.click(4, 4);
          await expect(overlay, 'a scrim click closes it').toBeHidden();
          await expect(opener, 'focus returns to the opener after a scrim click').toBeFocused();
        }
        expect(pageErrors).toEqual([]);
      });
    }
  }
});
