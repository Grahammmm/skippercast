// #597: the account dialog (dist/account.js) starts a passkey-autofill sign-in that asks the Worker for its
// options first. A person who taps Create before those options return must still get their account: the late
// autofill request must not start a ceremony that aborts the registration through the shared abort service.
// The options request is held until Create has started, then released. Real Worker, real passkey (a Chromium
// virtual authenticator), as e2e/admin.spec.ts.
import type {Route} from '@playwright/test';
import {test, expect} from './fixtures.ts';

/** Records every passkey-autofill ceremony (conditional get) and whether Create had already been tapped; it survives the reload. */
const recordAutofill = () => {
  const get = navigator.credentials.get.bind(navigator.credentials);
  navigator.credentials.get = (options?: CredentialRequestOptions) => {
    if (options?.mediation === 'conditional') {
      const log = JSON.parse(sessionStorage.getItem('autofill-log') ?? '[]');
      log.push({afterCreate: sessionStorage.getItem('create-tapped') === '1'});
      sessionStorage.setItem('autofill-log', JSON.stringify(log));
    }
    return get(options);
  };
};
const autofillAfterCreate = async (page: import('@playwright/test').Page) =>
  (JSON.parse(await page.evaluate(() => sessionStorage.getItem('autofill-log') ?? '[]')) as {afterCreate: boolean}[]).filter(e => e.afterCreate).length;

test('Create tapped before the autofill options return still creates the account', async ({page, pageErrors}) => {
  test.setTimeout(120_000);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
    hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.addInitScript(recordAutofill);

  let held: Route | undefined;
  const asked = new Promise<void>(resolve => {
    void page.route('**/api/auth/login/options', route => { held = route; resolve(); });
  });
  await page.goto('/map?region=morro-bay#account');
  await expect(page.locator('.account-card')).toBeVisible({timeout: 30_000});
  await asked;   // the autofill sign-in has asked for its options, and they are held
  expect(held, 'the dialog started a passkey-autofill request').toBeDefined();

  const registering = page.waitForRequest(r => r.url().endsWith('/api/auth/register/options'));
  const reloaded = page.waitForEvent('load');   // the app reloads signed in
  await page.evaluate(() => sessionStorage.setItem('create-tapped', '1'));
  await page.locator('#account-create').click();
  await registering;
  await held!.continue();                       // the autofill options arrive after Create began
  await page.unroute('**/api/auth/login/options');

  await reloaded;
  await expect.poll(async () => (await (await page.request.get('/api/session')).json()).signedIn).toBe(true);
  expect(await autofillAfterCreate(page), 'no passkey-autofill ceremony starts once Create was tapped').toBe(0);
  expect(pageErrors).toEqual([]);
});

test('a closed dialog\'s late autofill cannot abort Create in the dialog that replaced it', async ({page, pageErrors}) => {
  test.setTimeout(120_000);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
    hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.addInitScript(recordAutofill);

  // Hold only the first dialog's autofill options; any later request goes through.
  let first: Route | undefined;
  const asked = new Promise<void>(resolve => {
    void page.route('**/api/auth/login/options', route => { if (first) return route.continue(); first = route; resolve(); });
  });
  await page.goto('/map?region=morro-bay#account');
  await expect(page.locator('.account-card')).toBeVisible({timeout: 30_000});
  await asked;
  await page.locator('.home-port-close').click();          // close dialog A while its autofill is held
  await expect(page.locator('.account-card')).toHaveCount(0);
  await page.evaluate(() => { location.hash = '#account'; });   // dialog B
  await expect(page.locator('#account-create')).toBeEnabled({timeout: 30_000});

  const registering = page.waitForRequest(r => r.url().endsWith('/api/auth/register/options'));
  const reloaded = page.waitForEvent('load');
  await page.evaluate(() => sessionStorage.setItem('create-tapped', '1'));
  await page.locator('#account-create').click();
  await registering;
  await first!.continue();                                  // dialog A's options arrive after B's Create began
  await page.unroute('**/api/auth/login/options');

  await reloaded;
  await expect.poll(async () => (await (await page.request.get('/api/session')).json()).signedIn).toBe(true);
  expect(await autofillAfterCreate(page), 'no passkey-autofill ceremony starts once Create was tapped').toBe(0);
  expect(pageErrors).toEqual([]);
});

