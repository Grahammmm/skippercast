// #597: the account dialog (dist/account.js) starts a passkey-autofill sign-in that asks the Worker for its
// options first. A person who taps Create before those options return must still get their account: the late
// autofill request must not start a ceremony that aborts the registration through the shared abort service.
// The options request is held until Create has started, then released. Real Worker, real passkey (a Chromium
// virtual authenticator), as e2e/admin.spec.ts.
import type {Route} from '@playwright/test';
import {test, expect} from './fixtures.ts';

test('Create tapped before the autofill options return still creates the account', async ({page, pageErrors}) => {
  test.setTimeout(120_000);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
    hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });

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
  await page.locator('#account-create').click();
  await registering;
  await held!.continue();                       // the autofill options arrive after Create began
  await page.unroute('**/api/auth/login/options');

  await reloaded;
  await expect.poll(async () => (await (await page.request.get('/api/session')).json()).signedIn).toBe(true);
  expect(pageErrors).toEqual([]);
});
