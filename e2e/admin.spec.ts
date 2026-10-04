// The Text Advisor admin (TA-W2, docs/plans/text-advisor/08-website.md § Admin):
// a passkey account (the virtual authenticator e2e/app.spec.ts uses) gets 404
// at /admin.html until the admin role is granted the way
// scripts/advisor/grant-admin.mjs does it, here with `wrangler d1 execute
// --local` against the state e2e/serve.mjs runs on. A seeded photo review is
// then approved from the keyboard (a) and the row checked in D1; axe runs on
// the queue and the Health view. e2e/serve.mjs sets TEXT_ADVISOR_ENABLED=true.
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {test, expect, openMap, checkA11y} from './fixtures.ts';

const ROOT = resolve(import.meta.dirname, '..');
const WRANGLER = ['--yes', 'wrangler@4.142.0'];   // the pin e2e/serve.mjs uses
const CONFIG = resolve(ROOT, 'wrangler.e2e.local.jsonc'), STATE = resolve(ROOT, '.wrangler/e2e-state');

/** Run SQL against the local D1 the dev server uses; the parsed rows of the last statement. */
function d1(sql: string): Record<string, unknown>[] {
  const out = execFileSync('npx', [...WRANGLER, 'd1', 'execute', 'skippercast', '--local', '--persist-to', STATE, '--config', CONFIG, '--json', '--command', sql],
    {cwd: ROOT, encoding: 'utf8', env: {...process.env, WRANGLER_SEND_METRICS: 'false'}, stdio: ['ignore', 'pipe', 'pipe']});
  const parsed = JSON.parse(out) as {results: Record<string, unknown>[]}[];
  return parsed.at(-1)?.results ?? [];
}
const word = (s: string): string => s.replace(/[^\w-]/g, '');

test('an admin signs in, sees the queue and approves a photo review with the keyboard', async ({page, pageErrors}, info) => {
  test.setTimeout(120_000);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
    hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  await openMap(page, '/?region=morro-bay#guide');
  await page.locator('#account-entry').click();
  await page.locator('#account-create').click();
  await expect(page.locator('#map .leaflet-marker-icon').first()).toBeAttached({timeout: 30_000});
  await expect.poll(async () => (await (await page.request.get('/api/session')).json()).signedIn).toBe(true);
  const session = await (await page.request.get('/api/session')).json();
  expect(session.is_admin).toBe(false);
  const userId = word(session.user.id);

  // Not an admin yet: the page and the API answer as if they did not exist.
  expect((await page.request.get('/admin.html')).status()).toBe(404);
  expect((await page.request.get('/api/admin/reviews')).status()).toBe(404);

  // Grant the role, and seed a contact, a photo and its review (ids unique per project).
  const tag = word(info.project.name), contact = `e2e-contact-${tag}`, media = `e2e-photo-${tag}`;
  const review = createHash('sha256').update(`e2e:${tag}`).digest('hex').slice(0, 32);
  const now = new Date().toISOString();
  d1(`UPDATE users SET role='admin' WHERE id='${userId}';`
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
  expect(d1(`SELECT publish_state FROM advisor_media WHERE id='${media}'`)).toEqual([{publish_state: 'approved'}]);
  expect(d1(`SELECT status,decided_by FROM advisor_reviews WHERE id='${review}'`)).toEqual([{status: 'approved', decided_by: userId}]);

  await page.getByRole('link', {name: 'Health'}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Health'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Mac relay'})).toBeVisible();
  await checkA11y(page, 'admin-health', info.project.name);

  // TA-W3: the Skippers view (a seeded pending boat owned by the contact) and that contact, opened by id.
  const boat = `e2e-boat-${tag}`;
  d1(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,created_at,updated_at) VALUES('${boat}','${boat}','E2E Boat ${tag}','morro-bay','morro-bay','${contact}','pending','${now}','${now}');`);
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
