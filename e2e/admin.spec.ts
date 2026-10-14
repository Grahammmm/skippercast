// The Text Advisor admin (TA-W2, docs/plans/text-advisor/08-website.md § Admin):
// a passkey account (a Chromium virtual authenticator) gets 404
// at /admin.html until the admin role is granted the way
// scripts/advisor/grant-admin.mjs does it, here through e2e/d1.ts (SQL on the
// running Worker's own local D1, served by e2e/worker.mjs). A seeded photo review is
// then approved from the keyboard (a) and the row checked in D1; axe runs on
// the queue and the Health view. TA-S1: the approved angler share is a social
// draft, opened in the Posts view (axe). e2e/serve.mjs sets TEXT_ADVISOR_ENABLED=true.
import {createHash} from 'node:crypto';
import {test, expect, checkA11y} from './fixtures.ts';
import {d1} from './d1.ts';

const word = (s: string): string => s.replace(/[^\w-]/g, '');

test('an admin signs in, sees the queue and approves a photo review with the keyboard', async ({page, pageErrors}, info) => {
  test.setTimeout(120_000);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
    hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  // FE-61: the app's #account link opens the account dialog (web/account.ts), as the v1 Guide's button did;
  // a chosen profile keeps the first-run card from covering it.
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  // The dialog also starts a passkey-autofill sign-in (dist/account.js). Clicking Create while that request's
  // options are still loading lets its ceremony start after the registration and abort or answer it (#579), so
  // wait for them first (bounded: a browser without autofill never asks).
  const autofill = page.waitForResponse(r => r.url().endsWith('/api/auth/login/options'), {timeout: 15_000}).catch(() => undefined);
  await page.goto('/map?region=morro-bay#account');
  await expect(page.locator('.account-card')).toBeVisible({timeout: 30_000});
  await autofill;
  const reloaded = page.waitForEvent('load');   // the app reloads signed in
  await page.locator('#account-create').click();
  await reloaded;
  await expect.poll(async () => (await (await page.request.get('/api/session')).json()).signedIn).toBe(true);
  const session = await (await page.request.get('/api/session')).json();
  expect(session.is_admin).toBe(false);
  const userId = word(session.user.id);

  // Not an admin yet: the page and the API answer as if they did not exist.
  expect((await page.request.get('/admin.html')).status()).toBe(404);
  expect((await page.request.get('/api/admin/reviews')).status()).toBe(404);

  // Grant the role, and seed a contact, a photo and its review (ids unique per project and attempt, so a retry or
  // --repeat-each run seeds fresh rows instead of failing on the last attempt's).
  const tag = word(`${info.project.name}-${info.repeatEachIndex}-${info.retry}`), contact = `e2e-contact-${tag}`, media = `e2e-photo-${tag}`;
  const review = createHash('sha256').update(`e2e:${tag}`).digest('hex').slice(0, 32);
  const now = new Date().toISOString();
  await d1(`UPDATE users SET role='admin' WHERE id='${userId}';`
    + `INSERT INTO advisor_contacts(id,channel,role,language,status,last_seen_at,created_at,updated_at) VALUES('${contact}','web','angler','en','active','${now}','${now}','${now}');`
    + `INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,exif_stripped,has_person,publish_state,credit,created_at) VALUES('${media}','${contact}','image','image/jpeg',1000,'','',0,1,'queued','E2E angler','${now}');`
    + `INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES('${review}','media','${media}','angler_photo','open','${now}');`);
  expect((await (await page.request.get('/api/session')).json()).is_admin).toBe(true);

  await page.goto('/admin');
  await expect(page).toHaveURL(/\/admin\.html$/);
  await expect(page.getByRole('heading', {level: 1, name: 'Review queue'})).toBeVisible();
  const card = page.locator(`#review-${review}`);
  await expect(card).toBeVisible();
  await expect(card.getByRole('checkbox', {name: 'Person in photo'})).toBeChecked();
  await expect(card).toContainText('E2E angler');
  await checkA11y(page, 'admin-queue', info.project.name);

  await card.focus();
  await page.keyboard.press('a');
  await expect(page.getByRole('status').filter({hasText: 'Marked approved.'})).toBeVisible();
  await expect(card).toHaveCount(0);
  expect(await d1(`SELECT publish_state FROM advisor_media WHERE id='${media}'`)).toEqual([{publish_state: 'approved'}]);
  expect(await d1(`SELECT status,decided_by FROM advisor_reviews WHERE id='${review}'`)).toEqual([{status: 'approved', decided_by: userId}]);

  // TA-S1: the approved angler share became a social draft (fixed caption line: no model in the browser tests); the
  // Posts view lists it with its caption and the surfaces, and the editor opens on it.
  const post = await d1(`SELECT id,status,caption FROM advisor_posts WHERE media_json='["${media}"]'`);
  expect(post).toHaveLength(1);
  expect(post[0]!.status).toBe('draft');
  expect(String(post[0]!.caption)).toContain('Photo: E2E angler');
  await page.getByRole('link', {name: 'Posts'}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Posts'})).toBeVisible();
  // The draft's card is its post review (contacts.ts reviewId: sha256('post:<post id>:social_draft')[:32]); both projects seed one.
  const draft = page.locator(`#review-${createHash('sha256').update(`post:${String(post[0]!.id)}:social_draft`).digest('hex').slice(0, 32)}`);
  await expect(draft).toBeVisible();
  await expect(draft).toContainText('Instagram feed, Facebook Page');
  await draft.getByRole('button', {name: 'Edit'}).click();
  await expect(draft.getByRole('checkbox', {name: 'Facebook Page'})).toBeChecked();
  await expect(draft.getByLabel('Caption')).toHaveValue(/Photo: E2E angler/);
  await checkA11y(page, 'admin-posts', info.project.name);
  await draft.getByRole('button', {name: 'Cancel'}).click();

  await page.getByRole('link', {name: 'Health', exact: true}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Health'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Mac relay'})).toBeVisible();
  await checkA11y(page, 'admin-health', info.project.name);

  // TA-W3: the Skippers view (a seeded pending boat owned by the contact) and that contact, opened by id.
  const boat = `e2e-boat-${tag}`;
  await d1(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,created_at,updated_at) VALUES('${boat}','${boat}','E2E Boat ${tag}','morro-bay','morro-bay','${contact}','pending','${now}','${now}');`);
  await page.getByRole('link', {name: 'Skippers'}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Skippers'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Invite a skipper'})).toBeVisible();
  const boatCard = page.getByRole('article', {name: new RegExp(`E2E Boat ${tag}`)});
  await expect(boatCard).toBeVisible();
  await checkA11y(page, 'admin-skippers', info.project.name);
  await boatCard.getByRole('link', {name: 'Unnamed contact'}).click();
  await expect(page).toHaveURL(new RegExp(`#contact/${contact}$`));
  await expect(page.getByRole('heading', {level: 1, name: 'Contact'})).toBeVisible();
  await expect(page.getByRole('link', {name: 'Export this contact’s data'})).toBeVisible();
  await checkA11y(page, 'admin-contact', info.project.name);

  // TA-W4: the Funnel (D1 counts; Analytics Engine is not configured in the browser tests).
  await page.getByRole('link', {name: 'Funnel'}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Funnel'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'New contacts by day and source'})).toBeVisible();
  await expect(page.getByText('Analytics Engine is not connected', {exact: false})).toBeVisible();
  await page.getByLabel('Window').selectOption('30');
  await expect(page.getByRole('heading', {name: 'Engagement'})).toBeVisible();
  await checkA11y(page, 'admin-funnel', info.project.name);

  // TA-A4: the Rules view on one jurisdiction (e2e/seed/advisor-pages.sql: lingcod active, rockfish in review). Read only:
  // the seeded rows also feed e2e/advisor-pages.spec.ts.
  await page.goto('/admin.html#rules?jurisdiction=california-central');
  await expect(page.getByRole('heading', {level: 1, name: 'Rules'})).toBeVisible();
  const rockfish = page.getByRole('row', {name: /Rockfish \(RCG complex\)/});
  await expect(rockfish).toContainText('Due');
  await expect(rockfish.getByRole('link', {name: 'CDFW Groundfish Summary'})).toBeVisible();
  await expect(page.getByRole('row', {name: /^Lingcod/})).not.toContainText('Due');
  await checkA11y(page, 'admin-rules', info.project.name);
  expect(pageErrors).toEqual([]);
});
