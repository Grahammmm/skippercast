// RF2235-8: the desktop first-run keyboard handoff through the real /map application (R-P1, S5 E1).
// tests/test_first_run_keyboard.mjs mounts FirstRun with focusOnOpen=true; these cases prove the desktop
// App supplies that prop, that native Tab reaches the choices and leaves the non-modal card, and that
// Escape keeps Boat without opening the boat-entry fields. English and Spanish; no product change.
import {expect, test} from './fixtures.ts';

const PROFILES = ['boat', 'shore', 'spear', 'kayak'] as const;
const LANGS = {
  en: {title: 'How do you fish?', keep: 'Keep Boat for now'},
  es: {title: '¿Cómo pescas?', keep: 'Mantener Barco por ahora'},
} as const;

for (const lang of ['en', 'es'] as const) {
  const copy = LANGS[lang];

  test.describe(`desktop first-run keyboard (${lang})`, () => {
    test.describe.configure({timeout: 15_000});

    test(`desktop_first_run_native_tab_contract_${lang}`, async ({page, v2, isMobile}) => {
      test.skip(isMobile, 'desktop layout only: the phone sheet deliberately takes no focus on load');
      await v2.open('app', lang === 'es' ? {region: 'morro-bay', lang} : {region: 'morro-bay'});
      const card = page.locator('[data-first-run]'), heading = card.locator('#first-run-title');
      await expect(card).toBeVisible();
      await expect(heading).toHaveText(copy.title);
      await expect(card).not.toHaveAttribute('aria-modal', 'true');
      // Focus arrives on the heading without any keyboard or pointer action.
      await expect(heading).toBeFocused({timeout: 2_000});
      // Bounded idle observation: nothing else may take focus from the heading.
      await page.waitForTimeout(3_000);
      await expect(heading).toBeFocused();

      // Native Tab only: the four profiles in DOM order, then Keep Boat.
      for (const profile of PROFILES) {
        await page.keyboard.press('Tab');
        const button = card.locator(`button[data-profile="${profile}"]`);
        await expect(button).toBeFocused();
        await expect(button).toBeVisible();
      }
      await page.keyboard.press('Tab');
      const keep = card.getByRole('button', {name: copy.keep});
      await expect(keep).toBeFocused();
      await expect(keep).toBeVisible();

      // Non-modal: one more Tab leaves the card for a connected element outside it.
      await page.keyboard.press('Tab');
      const outside = await page.evaluate(() => {
        const el = document.activeElement, card = document.querySelector('[data-first-run]');
        return {connected: !!el && el.isConnected && el !== document.body, inside: !!el && !!card && card.contains(el)};
      });
      expect(outside).toEqual({connected: true, inside: false});
    });

    test(`desktop_first_run_escape_keeps_boat_${lang}`, async ({page, v2, isMobile}) => {
      test.skip(isMobile, 'desktop layout only: the phone sheet deliberately takes no focus on load');
      await v2.open('app', lang === 'es' ? {region: 'morro-bay', lang} : {region: 'morro-bay'});
      const card = page.locator('[data-first-run]'), heading = card.locator('#first-run-title');
      await expect(heading).toBeFocused({timeout: 2_000});
      await page.keyboard.press('Tab');
      await expect(card.locator('button[data-profile="boat"]')).toBeFocused();

      // A modified Escape is ignored: the card stays and no profile is chosen.
      await page.keyboard.press('Shift+Escape');
      await expect(card).toBeVisible();
      await expect(page).not.toHaveURL(/[?&]profile=/);
      expect(await page.evaluate(() => localStorage.getItem('skippercast-profile-v1'))).toBeNull();

      // Plain Escape is "Keep Boat for now": dismissed, Boat persisted, no boat-entry fields.
      await page.keyboard.press('Escape');
      await expect(card).toHaveCount(0);
      await expect(page).toHaveURL(/[?&]profile=boat/);
      expect(await page.evaluate(() => localStorage.getItem('skippercast-profile-v1'))).toContain('boat');
      await expect(page.locator('[data-first-use-boat]')).toHaveCount(0);

      // The settled URL brings back neither the chooser nor the boat-entry form.
      await page.reload();
      await expect(page).toHaveTitle(/SkipperCast/);
      await expect(card).toHaveCount(0);
      await expect(page.locator('[data-first-use-boat]')).toHaveCount(0);
    });
  });
}
