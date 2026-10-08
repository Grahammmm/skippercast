// The v2 account menu (FE-50, docs/plans/front-end/dev-plan.md): the
// masthead's (phone: the sheet footer's) account button opens one menu that
// is keyboard operable (aria-expanded, focus moves in, arrows move, Escape
// closes and returns focus); sign in runs v1's passkey dialog to completion;
// a boat preset saves as first-run.js does; trip alerts open in the app's
// dialog. The auth endpoints are stubbed and the passkey is a Chromium
// virtual authenticator's synthetic credential: no account is created.
// Passkey autofill is reported unavailable so the explicit "Sign in with a
// passkey" button runs the ceremony (the virtual authenticator would answer
// account.js's conditional request on its own).
import {generateKeyPairSync, randomBytes} from 'node:crypto';
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const b64url = (b: Buffer) => b.toString('base64url');

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ }
    Object.defineProperty(PublicKeyCredential, 'isConditionalMediationAvailable', {value: async () => false});
  });
});

/** The account button: in the masthead, or (phone) in the sheet's footer with the sheet lifted to full. */
async function accountButton(page: Page, isMobile: boolean) {
  const trigger = page.locator('.app-account-trigger');
  if (isMobile) {
    await page.locator('.ui-sheet-handle').focus();
    await page.keyboard.press('End');
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
    await trigger.scrollIntoViewIfNeeded();
  }
  return trigger;
}

/** Stub /api/session (and the login endpoints); `signedIn` flips when the login is verified. */
async function stubAuth(page: Page, credentialId: string) {
  const state = {signedIn: false, verified: 0};
  await page.route('**/api/session', route => route.fulfill({json: state.signedIn
    ? {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null}
    : {signIn: '/#account', signedIn: false}}));
  await page.route('**/api/auth/login/options', route => route.fulfill({json: {challenge: b64url(randomBytes(32)), rpId: 'localhost', allowCredentials: [], userVerification: 'preferred', timeout: 60000}}));
  await page.route('**/api/auth/login/verify', async route => {
    const body = route.request().postDataJSON() as {response?: {id?: string; type?: string}};
    expect(body.response?.id, 'the authenticator answered with the fixture credential').toBe(credentialId);
    state.signedIn = true; state.verified += 1;
    await route.fulfill({json: {ok: true}});
  });
  await page.route('**/api/auth/passkeys', route => route.fulfill({json: {passkeys: [{id: 'p1', created_at: '2026-10-01T00:00:00Z', last_used_at: null}]}}));
  return state;
}

/** A virtual platform authenticator holding one synthetic resident credential for localhost. */
async function passkeyFixture(page: Page): Promise<string> {
  const id = randomBytes(16);
  const {privateKey} = generateKeyPairSync('ec', {namedCurve: 'P-256'});
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  const {authenticatorId} = await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
    hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  await cdp.send('WebAuthn.addCredential', {authenticatorId, credential: {credentialId: id.toString('base64'), isResidentCredential: true, rpId: 'localhost',
    privateKey: privateKey.export({type: 'pkcs8', format: 'der'}).toString('base64'), userHandle: randomBytes(16).toString('base64'), signCount: 0}});
  return b64url(id);
}

test('signing in from the account menu completes the passkey flow and keeps the place', async ({page, pageErrors, v2, isMobile}) => {
  const state = await stubAuth(page, await passkeyFixture(page));
  await v2.open('app', AREA);
  const trigger = await accountButton(page, isMobile);
  await expect(trigger).toHaveText('Sign in');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.app-account-panel [data-preset]')).toHaveCount(4);
  await v2.a11y('v2-account-menu');
  await page.getByRole('button', {name: 'Sign in or create an account'}).click();
  await expect(page.locator('.account-card')).toBeVisible();
  await expect(trigger, 'the menu closes before the dialog opens').toHaveAttribute('aria-expanded', 'false');
  await v2.a11y('v2-account-dialog');
  const reloaded = page.waitForEvent('load');
  await page.locator('#account-signin').click();
  await reloaded;
  expect(state.verified).toBe(1);
  await expect(trigger).toHaveText('Skipper');
  expect(new URL(page.url()).searchParams.get('region')).toBe('morro-bay');
  expect(page.url(), 'no hash left behind').not.toContain('#');
  await (await accountButton(page, isMobile)).click();
  await expect(page.locator('.app-account-panel')).toContainText('Signed in as Skipper');
  expect(pageErrors).toEqual([]);
});

test('the menu is keyboard operable and Escape returns focus to its button', async ({page, pageErrors, v2, isMobile}) => {
  await stubAuth(page, 'unused');
  await v2.open('app', AREA);
  const trigger = await accountButton(page, isMobile), panel = page.locator('.app-account-panel');
  await trigger.focus();
  await page.keyboard.press('Enter');
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('button', {name: 'Sign in or create an account'})).toBeFocused();
  await expect(panel.locator('[data-preset]')).toHaveCount(4);
  await page.keyboard.press('ArrowDown');
  await expect(panel.locator('[data-preset]').first()).toBeFocused();
  await page.keyboard.press('End');
  await expect(panel.locator('a').last()).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('button', {name: 'Sign in or create an account'}), 'arrows wrap').toBeFocused();
  await page.keyboard.press('Escape');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(panel).toBeHidden();
  await expect(trigger).toBeFocused();
  // A boat preset saves as first-run.js does and the page reloads with it.
  await trigger.click();
  const reloaded = page.waitForEvent('load');
  await panel.locator('[data-preset="console"]').click();
  await reloaded;
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('skippercast-boat-v1') ?? 'null')?.preset)).toBe('console');
  await (await accountButton(page, isMobile)).click();
  await expect(panel.locator('[data-preset="console"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(panel).toContainText('Ratings use Center console (20–24 ft).');
  // Trip alerts open in the app's dialog with v1's signed-out prompt; Escape closes it.
  await page.getByRole('button', {name: 'Saved-trip alerts'}).click();
  const dialog = page.getByRole('dialog', {name: 'Trip alerts'});
  await expect(dialog).toContainText('Sign in or create an account');
  await expect(dialog.locator('#species-select option')).not.toHaveCount(0);
  await v2.a11y('v2-account-alerts');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  expect(pageErrors).toEqual([]);
});
