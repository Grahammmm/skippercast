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

test('Escape closes the open account menu after Shift+Tab returns to its trigger (FE-50)', async ({page, pageErrors, v2, isMobile}) => {
  await stubAuth(page, 'unused');
  await v2.open('app', AREA);
  const trigger = await accountButton(page, isMobile), panel = page.locator('.app-account-panel');
  await trigger.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', {name: 'Sign in or create an account'})).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(panel).toBeHidden();
  await expect(trigger).toBeFocused();
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
  // Trip alerts open in the app's dialog with the signed-out prompt, whose link opens the passkey dialog; Escape closes it.
  await page.getByRole('button', {name: 'Saved-trip alerts'}).click();
  const dialog = page.getByRole('dialog', {name: 'Trip alerts'});
  await expect(dialog).toContainText('Sign in or create an account');
  await expect(dialog.getByRole('link', {name: 'Sign in or create an account'}).first()).toHaveAttribute('href', '#account');
  await v2.a11y('v2-account-alerts');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  expect(pageErrors).toEqual([]);
});

test('controls tour can be skipped and replayed with focus restored after closing', async ({page, pageErrors, v2, isMobile}) => {
  await stubAuth(page, 'unused');
  await v2.open('app', AREA);
  const trigger = await accountButton(page, isMobile);
  await trigger.click();
  await page.getByRole('button', {name: 'Replay controls tour'}).click();
  const dialog = page.getByRole('dialog', {name: 'Controls tour'});
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', {name: 'Skip tour'}).click();
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.getByRole('button', {name: 'Replay controls tour'}).click();
  await expect(dialog.getByText('Step 1 of 4')).toBeVisible();
  await dialog.getByRole('button', {name: 'Next'}).click();
  await dialog.getByRole('button', {name: 'Next'}).click();
  await dialog.getByRole('button', {name: 'Next'}).click();
  await dialog.getByRole('button', {name: 'Finish'}).click();
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
  expect(pageErrors).toEqual([]);
});

// #602: signed in, the alerts dialog is v2's own (web/app/TripAlerts.tsx) over v1's /api/ calls:
// a saved window posts v1's body with limits from the reference boat, lists, deletes, and an
// assessment is marked read; comfort feedback posts without forecast context; deleting the
// account asks in the page first. The API is stubbed: nothing is stored.
test('signed in, saved-trip alerts save, list, delete and acknowledge through the same API', async ({page, pageErrors, v2, isMobile}) => {
  const trips: Record<string, unknown>[] = [], posted: Record<string, unknown>[] = [], comfort: Record<string, unknown>[] = [];
  let acked: unknown = null, deleted: unknown = null;
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null}}));
  await page.route('**/api/trips', async route => {
    const method = route.request().method();
    if (method === 'POST') { const body = route.request().postDataJSON() as Record<string, unknown>; posted.push(body); trips.push({id: 't1', ...body}); return route.fulfill({status: 201, json: {id: 't1'}}); }
    if (method === 'DELETE') { deleted = route.request().postDataJSON(); trips.length = 0; return route.fulfill({json: {ok: true}}); }
    return route.fulfill({json: {trips, events: [{id: 7, kind: 'day-before', status: 'pending', message: 'Wind 9 kt at 7:00.\nSeas 3 ft.'}]}});
  });
  await page.route('**/api/events/ack', route => { acked = route.request().postDataJSON(); return route.fulfill({json: {ok: true}}); });
  await page.route('**/api/comfort', route => {
    if (route.request().method() === 'POST') { comfort.push(route.request().postDataJSON() as Record<string, unknown>); return route.fulfill({status: 201, json: {ok: true}}); }
    return route.fulfill({json: {feedback: comfort.map(c => ({observed_at: '2026-10-11T20:00:00Z', rating: c.rating, context: JSON.stringify({phase: c.phase})}))}});
  });
  await v2.open('app', {...AREA, target: 'halibut'});
  await (await accountButton(page, isMobile)).click();
  await page.getByRole('button', {name: 'Saved-trip alerts'}).click();
  const dialog = page.getByRole('dialog', {name: 'Trip alerts'});
  await expect(dialog.getByRole('combobox', {name: 'Alert species'})).toHaveValue('halibut');
  await expect(dialog.getByLabel('Wind limit · kt')).toHaveValue('8');
  await expect(dialog.getByLabel('Sea limit · ft')).toHaveValue('3');
  await expect(dialog).toContainText('Limits start from the reference 23 ft boat.');
  // The pointer rests where the menu item was, so Save can be hovered when axe runs (it was, on some runs): check that state every run.
  await dialog.getByRole('button', {name: 'Save this fishing window'}).hover();
  await v2.a11y('v2-account-alerts-signed-in');
  await dialog.getByLabel('Area').selectOption('central');
  await dialog.getByLabel('Gust limit · kt').fill('14');
  await dialog.getByRole('button', {name: 'Save this fishing window'}).click();
  await expect(dialog.locator('#alert-status')).toHaveText('Trip saved. Scheduled checks run about every 30 minutes; notifications require device permission.');
  expect(posted).toHaveLength(1);
  expect(Object.keys(posted[0]!).sort()).toEqual(['date', 'end_hour', 'gust_limit', 'point', 'region', 'sea_limit', 'species', 'start_hour', 'wind_limit']);
  expect(posted[0]).toMatchObject({region: 'morro-bay', species: 'halibut', point: 'central', start_hour: 7, end_hour: 13, wind_limit: 8, gust_limit: 14, sea_limit: 3});
  // SC1537-06 (#1170): the saved trip reads by the region's names, never its raw ids.
  await expect(dialog.locator('#saved-trips')).toContainText('Estero Bay · California halibut · 7:00–13:00');
  await expect(dialog.getByRole('button', {name: /^Delete the trip on [A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2} at Estero Bay$/})).toBeVisible();
  await dialog.getByText('Recent assessments (1)').click();
  await dialog.getByRole('button', {name: 'Mark read'}).click();
  await expect.poll(() => acked).toEqual({id: 7});
  await dialog.getByRole('button', {name: /^Delete the trip on /}).click();
  await expect(dialog.locator('#saved-trips')).toHaveText('No saved trips.');
  expect(deleted).toEqual({id: 't1'});
  await dialog.getByText('How did your boat feel today?').click();
  await dialog.getByLabel('Comfort · 1 rough to 10 excellent').fill('6');
  await dialog.getByRole('button', {name: 'Save private feedback'}).click();
  await expect(dialog.locator('#comfort-history')).toContainText('1 private reports');
  expect(comfort).toEqual([{region: 'morro-bay', rating: 6, phase: 'outbound', wind: null, sea: null, period: null, heading: null, point: null}]);
  await dialog.getByText('Privacy & account data').click();
  await dialog.getByRole('button', {name: 'Delete my account and records'}).click();
  const confirm = dialog.getByRole('alertdialog');
  await expect(confirm).toContainText('This cannot be undone.');
  await expect(confirm.getByRole('button', {name: 'Cancel'})).toBeFocused();
  await confirm.getByRole('button', {name: 'Cancel'}).click();
  await expect(confirm).toBeHidden();
  await expect(dialog.getByRole('button', {name: 'Delete my account and records'}), 'Cancel keeps everything and returns focus').toBeFocused();
  expect(pageErrors).toEqual([]);
});

// SC0452-01: the passkey library (vendor/simplewebauthn-browser-14.0.0) is requested when a ceremony starts, not with the map page.
const UMD = '/vendor/simplewebauthn-browser-14.0.0/index.umd.min.js';
const UNAVAILABLE = 'Passkeys are unavailable right now. Try again when you are online.';

/** Counts the requests for the library and for the options calls that must not happen without it. */
function watchPasskeyRequests(page: Page) {
  const seen = {library: 0, loginOptions: 0, addOptions: 0};
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path === UMD) seen.library += 1;
    if (path === '/api/auth/login/options') seen.loginOptions += 1;
    if (path === '/api/auth/passkeys/options') seen.addOptions += 1;
  });
  return seen;
}

test('the map page and a signed-in account dialog request no passkey library', async ({page, pageErrors, v2}) => {
  const state = await stubAuth(page, await passkeyFixture(page));
  state.signedIn = true;
  const seen = watchPasskeyRequests(page);
  await v2.open('app', AREA);
  await expect(page.locator('.app-account-trigger')).toHaveText('Skipper');
  await page.evaluate(() => { location.hash = '#account'; });
  await expect(page.locator('#account-add')).toBeVisible();
  await expect(page.locator('#log-form')).toBeVisible();
  await page.locator('.home-port-close').click();
  await expect(page.locator('.account-card')).toHaveCount(0);
  expect(seen.library, 'no passkey library for the map, the session read or a signed-in dialog').toBe(0);
  expect(await page.evaluate(() => typeof (globalThis as {SimpleWebAuthnBrowser?: unknown}).SimpleWebAuthnBrowser)).toBe('undefined');
  expect(pageErrors).toEqual([]);
});

test('the signed-out dialog loads the library for its sign-in and Sign in completes with it', async ({page, pageErrors, v2}) => {
  const state = await stubAuth(page, await passkeyFixture(page));
  const seen = watchPasskeyRequests(page);
  await v2.open('app', AREA);
  expect(seen.library, 'the map alone requests no library').toBe(0);
  await page.evaluate(() => { location.hash = '#account'; });
  await expect(page.locator('#account-signin')).toBeEnabled();
  const reloaded = page.waitForEvent('load');
  await page.locator('#account-signin').click();
  await reloaded;
  expect(state.verified).toBe(1);
  expect(seen.library, 'one library request however many sign-in paths asked').toBe(1);
  await expect(page.locator('.app-account-trigger')).toHaveText('Skipper');
  expect(seen.library, 'the signed-in page asks for none').toBe(1);
  expect(pageErrors.filter(e => !/Failed to load resource/.test(e))).toEqual([]);
});

test('a library that will not load says passkeys are unavailable, makes no auth request, and the next try loads it', async ({page, v2}) => {
  const state = await stubAuth(page, await passkeyFixture(page));
  const seen = watchPasskeyRequests(page);
  await page.route('**/vendor/simplewebauthn-browser-14.0.0/**', route => route.abort('failed'));   // offline
  await v2.open('app', AREA);
  await page.evaluate(() => { location.hash = '#account'; });
  await expect(page.locator('#account-signin')).toBeEnabled();
  await page.locator('#account-signin').click();
  await expect(page.locator('#account-status')).toHaveText(UNAVAILABLE);
  await expect(page.locator('#account-signin')).toBeEnabled();
  await expect(page.locator('#account-create')).toBeEnabled();
  expect(seen.loginOptions, 'no options request without the library').toBe(0);

  // The right file name with other bytes: the browser refuses it on integrity, which reads the same.
  await page.unroute('**/vendor/simplewebauthn-browser-14.0.0/**');
  await page.route('**/vendor/simplewebauthn-browser-14.0.0/**', route => route.fulfill({contentType: 'text/javascript',
    body: 'globalThis.SimpleWebAuthnBrowser = {browserSupportsWebAuthn: () => true, startAuthentication: async () => ({}), startRegistration: async () => ({})};'}));
  await page.locator('#account-create').click();
  await expect(page.locator('#account-status')).toHaveText(UNAVAILABLE);
  expect(await page.evaluate(() => typeof (globalThis as {SimpleWebAuthnBrowser?: unknown}).SimpleWebAuthnBrowser), 'the tampered script never ran').toBe('undefined');
  expect(seen.loginOptions).toBe(0);

  await page.unroute('**/vendor/simplewebauthn-browser-14.0.0/**');   // back online
  const reloaded = page.waitForEvent('load');
  await page.locator('#account-signin').click();
  await reloaded;
  expect(state.verified, 'the retry loaded the real library and signed in').toBe(1);
});

test('Add a passkey loads the library when tapped; a failed load says so and a retry adds the passkey', async ({page, pageErrors, v2}) => {
  const state = await stubAuth(page, await passkeyFixture(page));
  state.signedIn = true;
  const seen = watchPasskeyRequests(page);
  const added: {response?: {id?: string}}[] = [];
  await page.route('**/api/trips', route => route.fulfill({json: {trips: [], events: []}}));   // the signed-in dialog's other reads, so none writes the status line
  await page.route('**/api/catch-log', route => route.fulfill({json: {entries: []}}));
  await page.route('**/api/spots', route => route.fulfill({json: {spots: []}}));
  await page.route('**/api/auth/passkeys/options', route => route.fulfill({json: {challenge: b64url(randomBytes(32)), rp: {name: 'SkipperCast', id: 'localhost'},
    user: {id: b64url(randomBytes(16)), name: 'Skipper', displayName: 'Skipper'}, pubKeyCredParams: [{type: 'public-key', alg: -7}], timeout: 60000,
    authenticatorSelection: {residentKey: 'required', userVerification: 'preferred'}, attestation: 'none'}}));
  await page.route('**/api/auth/passkeys', route => {
    if (route.request().method() !== 'POST') return route.fallback();
    added.push(route.request().postDataJSON() as {response?: {id?: string}});
    return route.fulfill({json: {ok: true}});
  });
  await page.route('**/vendor/simplewebauthn-browser-14.0.0/**', route => route.abort('failed'));
  await v2.open('app', AREA);
  await page.evaluate(() => { location.hash = '#account'; });
  await expect(page.locator('#account-add')).toBeVisible();
  expect(seen.library, 'opening the signed-in dialog requests nothing').toBe(0);
  await page.locator('#account-add').click();
  await expect(page.locator('#account-status')).toHaveText(UNAVAILABLE);
  expect(seen.addOptions, 'no options request without the library').toBe(0);
  expect(added).toEqual([]);

  await page.unroute('**/vendor/simplewebauthn-browser-14.0.0/**');
  await page.locator('#account-add').click();
  await expect(page.locator('#account-status')).toHaveText('Passkey added.');
  expect(seen.library).toBe(2);
  expect(seen.addOptions).toBe(1);
  expect(added).toHaveLength(1);
  expect(added[0]!.response?.id, 'the authenticator answered the registration').toBeTruthy();
  expect(pageErrors.filter(e => !/Failed to load resource/.test(e))).toEqual([]);
});

test('a tap or a close while the library is still loading keeps the late autofill from starting a sign-in', async ({page, pageErrors, v2}) => {
  const state = await stubAuth(page, await passkeyFixture(page));
  const seen = watchPasskeyRequests(page);
  let held: import('@playwright/test').Route | undefined;
  await page.route('**/vendor/simplewebauthn-browser-14.0.0/**', route => { held = route; });   // the library is on its way, not yet here
  await v2.open('app', AREA);

  // Closed while loading: the late autofill makes no options request and paints nothing.
  await page.evaluate(() => { location.hash = '#account'; });
  await expect.poll(() => held).toBeDefined();
  await page.locator('.home-port-close').click();
  await expect(page.locator('.account-card')).toHaveCount(0);
  await held!.continue(); held = undefined;
  await page.evaluate(() => { location.hash = '#guide'; });
  expect(seen.loginOptions, 'a closed dialog starts no ceremony').toBe(0);

  // Tapped while loading: only the tap's own sign-in asks for options.
  await page.unroute('**/vendor/simplewebauthn-browser-14.0.0/**');
  await page.route('**/vendor/simplewebauthn-browser-14.0.0/**', route => { held = route; });
  await page.reload();
  await page.evaluate(() => { location.hash = '#account'; });
  await expect.poll(() => held).toBeDefined();
  await page.locator('#account-signin').click();
  const reloaded = page.waitForEvent('load');
  await held!.continue();
  await reloaded;
  expect(state.verified).toBe(1);
  expect(seen.loginOptions, 'the tap asked once; the autofill that was waiting did not').toBe(1);
  expect(pageErrors.filter(e => !/Failed to load resource/.test(e))).toEqual([]);
});

// RF1925-4 (S4-40): after Create verifies, the dialog keeps a polite confirmation and a Continue button; the return/reload waits
// for an acknowledgment. Fully stubbed server; the registration itself is a Chromium virtual authenticator's synthetic credential.
async function stubCreate(page: Page, verify: 'ok' | 'refuse' = 'ok') {
  await passkeyFixture(page);
  const seen = {options: 0, verified: 0};
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: false}}));
  await page.route('**/api/auth/register/options', route => {
    seen.options += 1;
    return route.fulfill({json: {challenge: b64url(randomBytes(32)), rp: {name: 'SkipperCast', id: 'localhost'}, user: {id: b64url(randomBytes(16)), name: 'Skipper', displayName: 'Skipper'},
      pubKeyCredParams: [{type: 'public-key', alg: -7}], timeout: 60000, authenticatorSelection: {residentKey: 'required', userVerification: 'preferred'}, attestation: 'none'}});
  });
  await page.route('**/api/auth/register/verify', route => {
    seen.verified += 1;
    return verify === 'ok' ? route.fulfill({json: {ok: true}}) : route.fulfill({status: 400, json: {error: 'Verification refused'}});
  });
  return seen;
}
const CREATED = 'Account created. You\u2019re signed in. Continue to return to your screen.';

test('a created account keeps its confirmation readable until Continue, then returns once', async ({page, pageErrors, v2}) => {
  const seen = await stubCreate(page);
  await v2.open('app', AREA);
  await page.evaluate(() => { (window as unknown as {__stillHere: boolean}).__stillHere = true; location.hash = '#account'; });
  const status = page.locator('#account-status'), create = page.locator('#account-create');
  await expect(create).toBeEnabled();
  await create.click();
  await expect(status).toHaveText(CREATED);
  await expect(status).toHaveAttribute('role', 'status');
  await expect(status).toHaveAttribute('aria-live', 'polite');
  await expect(status).toHaveAttribute('aria-atomic', 'true');
  await expect(create).toHaveText('Continue');
  await expect(create).toBeEnabled();
  await expect(page.locator('#account-signin')).toBeDisabled();
  await expect(page.locator('#account-name')).toBeDisabled();
  await expect(page.locator('.account-card')).toBeVisible();
  await page.waitForTimeout(1500);   // no timer closes or reloads it
  expect(await page.evaluate(() => (window as unknown as {__stillHere?: boolean}).__stillHere), 'no reload before Continue').toBe(true);
  await expect(status).toHaveText(CREATED);
  await create.focus();
  await expect(create).toBeFocused();
  const reloaded = page.waitForEvent('load');
  await page.keyboard.press('Enter');
  await reloaded;
  expect(seen).toEqual({options: 1, verified: 1});
  expect(new URL(page.url()).searchParams.get('region')).toBe('morro-bay');
  expect(page.url(), 'the return address replaces #account').not.toContain('#account');
  expect(pageErrors).toEqual([]);
});

test('Escape on the created confirmation returns once without a second registration', async ({page, pageErrors, v2}) => {
  const seen = await stubCreate(page);
  await v2.open('app', AREA);
  await page.evaluate(() => { location.hash = '#account'; });
  await expect(page.locator('#account-create')).toBeEnabled();
  await page.locator('#account-create').click();
  await expect(page.locator('#account-status')).toHaveText(CREATED);
  const reloaded = page.waitForEvent('load');
  await page.keyboard.press('Escape');
  await reloaded;
  expect(seen).toEqual({options: 1, verified: 1});
  expect(new URL(page.url()).searchParams.get('region')).toBe('morro-bay');
  expect(pageErrors).toEqual([]);
});

test('a refused registration never shows the confirmation or Continue and can be retried', async ({page, v2}) => {
  const seen = await stubCreate(page, 'refuse');
  await v2.open('app', AREA);
  await page.evaluate(() => { (window as unknown as {__stillHere: boolean}).__stillHere = true; location.hash = '#account'; });
  await expect(page.locator('#account-create')).toBeEnabled();
  await page.locator('#account-create').click();
  await expect(page.locator('#account-status')).toContainText('Verification refused');
  await expect(page.locator('#account-create')).toBeEnabled();
  await expect(page.locator('#account-create')).toHaveText('Create account');
  await expect(page.locator('#account-status')).not.toContainText('Account created');
  await expect(page.locator('#account-name')).toBeEnabled();
  expect(seen.verified).toBe(1);
  expect(await page.evaluate(() => (window as unknown as {__stillHere?: boolean}).__stillHere), 'no reload').toBe(true);
});

test('the masthead account trigger is icon-sized at 1024-1179 px, labelled at 1180 px, and keeps its name', async ({page, v2, isMobile}) => {
  test.skip(isMobile, 'explicit desktop widths run once, under the laptop project');
  await stubAuth(page, 'unused');
  const sizes: Array<[number, number, boolean]> = [[1024, 768, true], [1179, 800, true], [1180, 820, false], [1280, 800, false]];
  for (const [width, height, compact] of sizes) {
    await page.setViewportSize({width, height});
    await v2.open('app', AREA);
    const trigger = page.locator('.app-masthead .app-account-trigger');
    await expect(trigger).toHaveAccessibleName('Sign in');
    await expect(trigger).toHaveAttribute('title', 'Sign in');
    const box = (await trigger.boundingBox())!, label = (await page.locator('.app-masthead .app-account-label').boundingBox())!;
    if (compact) {
      expect(Math.abs(box.width - (await trigger.evaluate(el => parseFloat(getComputedStyle(el).minInlineSize)))), `${width}px icon-sized`).toBeLessThan(1);
      expect(label.width).toBeLessThanOrEqual(1);
    } else expect(label.width, `${width}px keeps the label`).toBeGreaterThan(20);
  }
  await page.setViewportSize({width: 1024, height: 768});
  await v2.open('app', AREA);
  const trigger = page.locator('.app-masthead .app-account-trigger');
  await trigger.focus();
  await page.keyboard.press('Enter');
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('button', {name: 'Sign in or create an account'})).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});
