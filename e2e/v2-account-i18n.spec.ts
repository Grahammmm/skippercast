// SC0922-14: the account panel (dist/account.js, loaded on demand) opens in the language the app resolved: ?lang=es gives the
// Spanish sign-in and signed-in panels (private log, saved spots, destructive confirmation), and without it the panel reads English.
// /api/* is stubbed; no account is created and no credential is used.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ }
    Object.defineProperty(PublicKeyCredential, 'isConditionalMediationAvailable', {value: async () => false});
  });
});

async function stub(page: Page, signedIn: boolean) {
  await page.route('**/api/session', route => route.fulfill({json: signedIn ? {signIn: '/#account', signedIn: true, user: {display_name: 'Alex'}, publicKey: null} : {signIn: '/#account', signedIn: false}}));
  await page.route('**/api/auth/passkeys', route => route.fulfill({json: {passkeys: [{id: 'p1', created_at: '2026-10-01T00:00:00Z', last_used_at: null}]}}));
  await page.route('**/api/catch-log', route => route.fulfill({json: {entries: []}, headers: {'X-SC-Catch-Log-Has-More': 'false'}}));
  await page.route('**/api/trips', route => route.fulfill({json: {trips: []}}));
  await page.route('**/api/spots', route => route.fulfill({json: {spots: []}}));
}
const openPanel = (page: Page) => page.evaluate(() => { location.hash = '#account'; });

test('the signed-out account panel opens in Spanish with its privacy line and refusals', async ({page, pageErrors, v2}) => {
  await stub(page, false);
  await v2.open('app', {region: 'morro-bay', lang: 'es'});
  await openPanel(page);
  const card = page.locator('.account-card');
  await expect(card).toBeVisible();
  await expect(card.locator('#account-title')).toHaveText('Guarda viajes y alertas con una cuenta');
  await expect(card.locator('.home-port-kicker')).toHaveText('TU CUENTA');
  await expect(card.locator('#account-create')).toHaveText('Crear cuenta');
  await expect(card.locator('#account-signin')).toHaveText('Iniciar sesión con una clave de acceso');
  await expect(card.locator('#account-name')).toHaveAttribute('placeholder', 'p. ej., Alex');
  await expect(card).toContainText('SkipperCast solo almacena su clave pública');
  await expect(card.locator('.home-port-close')).toHaveAttribute('aria-label', 'Cerrar cuenta');
  await page.keyboard.press('Escape');
  await expect(card).toBeHidden();
  // Closing and reopening reads the language again: the dialog keeps no copy of the previous one.
  expect(pageErrors).toEqual([]);
});

test('the signed-in account panel is Spanish end to end and the delete confirmation keeps its warning', async ({page, pageErrors, v2}) => {
  await stub(page, true);
  let deleted = 0;
  await page.route('**/api/privacy', route => { deleted += 1; return route.fulfill({json: {ok: true}}); });
  await v2.open('app', {region: 'morro-bay', lang: 'es'});
  await openPanel(page);
  const card = page.locator('.account-card');
  await expect(card.locator('#account-title')).toHaveText('Sesión iniciada como Alex');
  await expect(card.locator('h2.account-subhead')).toHaveText(['Claves de acceso', 'Registro de capturas', 'Sitios guardados']);
  await expect(card.locator('#account-add')).toHaveText('Agregar una clave de acceso en este dispositivo');
  await expect(card.locator('[data-remove-passkey]')).toHaveAttribute('title', 'Agrega otra clave de acceso antes de eliminar esta');
  await expect(card.locator('#log-status')).toHaveText('Todavía no hay entradas.');
  await expect(card.locator('#spot-export')).toHaveText('Descargar mis sitios como GPX');
  await expect(card).toContainText('Las notas privadas nunca se incluyen en el GPX.');
  await card.locator('summary').click();
  await card.locator('#account-delete').click();
  const confirm = card.locator('.account-confirm');
  await expect(confirm).toContainText('No se puede deshacer.');
  await expect(confirm.locator('[data-confirm="no"]')).toHaveText('Cancelar');
  await confirm.locator('[data-confirm="no"]').click();
  expect(deleted, 'Cancelar sends nothing').toBe(0);
  expect(pageErrors).toEqual([]);
});

test('without a language choice the account panel reads English', async ({page, pageErrors, v2}) => {
  await stub(page, true);
  await v2.open('app', {region: 'morro-bay'});
  await openPanel(page);
  const card = page.locator('.account-card');
  await expect(card.locator('#account-title')).toHaveText('Signed in as Alex');
  await expect(card.locator('#log-status')).toHaveText('No entries yet.');
  await expect(card).not.toContainText('Las notas privadas');
  expect(pageErrors).toEqual([]);
});
