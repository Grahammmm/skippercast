// SC1722-13 (UX audit S4-16, S4-17): on /map?lang=es the Shore profile is Orilla and the Coast view is Costa, so no two
// different controls share a visible name, and the target field's hint is the short Busca especie. Synthetic feeds only.
import {test, expect} from './fixtures.ts';

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'shore'); } catch { /* storage blocked */ } });
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: false}}));
});

test('es_distinct_actions: Orilla names the Shore profile, Costa only the Coast view, and the target hint is Busca especie', async ({page, pageErrors, v2, isMobile}) => {
  // On the phone the target field lives on the Plan view; the profile switch and the tabs are on every view.
  await v2.open('app', {region: 'morro-bay', lang: 'es', ...(isMobile ? {view: 'plan'} : {})});
  const profile = page.getByRole('group', {name: 'Perfil'}).first().locator('button:visible');
  const views = page.getByRole('navigation', {name: 'Vistas'}).locator('a:visible');
  await expect(profile).toHaveText(['Barco', 'Orilla', 'Pesca submarina', 'Kayak']);
  await expect(views.first()).toHaveText('Costa');
  const names = [...await profile.allInnerTexts(), ...await views.allInnerTexts()].map(s => s.trim());
  expect(names.filter(n => n === 'Costa'), `visible names: ${names}`).toHaveLength(1);
  // The Shore profile is still the chosen one: only its words changed.
  await expect(profile.nth(1)).toHaveAttribute('aria-pressed', 'true');
  await expect(views.first()).toHaveAttribute('data-view', 'coast');
  const find = page.locator('.app-target-search:visible');
  await expect(find).toHaveAttribute('placeholder', 'Busca especie');
  await expect(find).toHaveAttribute('aria-label', 'Busca especie');
  expect(pageErrors).toEqual([]);
});
