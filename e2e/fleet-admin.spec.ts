// The charter fleet admin (CF-31, docs/plans/charter-fleet/design.md § 13): an admin
// decides a seeded class review in #fleet-review, opens the vessel in #fleet-vessel/<id>,
// edits a field and sees it pinned, each checked in D1 (admin fact, pinned_json).
// e2e/serve.mjs sets FLEET_ENABLED=true; a second test answers the fleet API with 404
// (the flag off) and checks the fleet tabs and routes are gone. Synthetic data only:
// the vessels are invented names in a per-project region, never registry rows.
import {createHash} from 'node:crypto';
import type {Page} from '@playwright/test';
import {test, expect, checkA11y} from './fixtures.ts';
import {d1} from './d1.ts';

const word = (s: string): string => s.replace(/[^\w-]/g, '');
const hex = (s: string): string => createHash('sha256').update(s).digest('hex').slice(0, 32);

/** Create a passkey account (the virtual authenticator e2e/admin.spec.ts uses) and make it an admin; its user id. */
async function signInAsAdmin(page: Page): Promise<string> {
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
  const userId = word((await (await page.request.get('/api/session')).json()).user.id);
  await d1(`UPDATE users SET role='admin' WHERE id='${userId}';`);
  expect((await (await page.request.get('/api/session')).json()).is_admin).toBe(true);
  return userId;
}

test('an admin decides a fleet review, edits a vessel field and sees it pinned', async ({page, pageErrors}, info) => {
  test.setTimeout(120_000);
  const userId = await signInAsAdmin(page);
  // Unique per project and attempt: a retry or --repeat-each run seeds fresh rows instead of failing on the last attempt's.
  const tag = word(`${info.project.name}-${info.repeatEachIndex}-${info.retry}`), region = `e2e-${tag}`;
  const vessel = hex(`e2e-fleet-vessel:${tag}`), review = hex(`e2e-fleet-review:${tag}`), name = `E2E Osprey ${tag}`;
  const now = new Date().toISOString();
  await d1(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at)
      VALUES('${vessel}','${region}','e2e-osprey-${tag}','${name}','E2EOSPREY${tag.toUpperCase()}','morro-bay','active','hidden','${now}','${now}','${now}','${now}');`
    + `INSERT INTO fleet_reviews(id,region,kind,subject_id,candidate_json,proposal_json,score,status,opened_at)
      VALUES('${review}','${region}','class','${vessel}','{"values":[{"source_id":"e2e-a","value":"six-pack","confidence":0.8},{"source_id":"e2e-b","value":"inspected-party","confidence":0.7}]}',
        '{"vessel_id":"${vessel}","vessel_class":"six-pack"}',NULL,'open','${now}');`);

  await page.goto(`/admin.html#fleet-review?region=${region}`);
  await expect(page.getByRole('heading', {level: 1, name: 'Fleet review'})).toBeVisible();
  await expect(page.getByRole('link', {name: 'Vessels', exact: true})).toBeVisible();
  const card = page.locator(`#fleet-review-${review}`);
  await expect(card).toBeVisible();
  await expect(card.getByRole('link', {name})).toBeVisible();
  await checkA11y(page, 'fleet-review', info.project.name);

  // Decide: set the class the proposal names. The card leaves the open list and D1 holds the decision, the column and its pin.
  await card.getByLabel('Class').selectOption('inspected-party');
  await card.getByRole('button', {name: 'Set class'}).click();
  await expect(page.getByRole('status').filter({hasText: 'Decided: Set class.'})).toBeVisible();
  await expect(card).toHaveCount(0);
  expect(await d1(`SELECT status,decided_by,json_extract(decision_json,'$.vessel_class') AS cls FROM fleet_reviews WHERE id='${review}'`))
    .toEqual([{status: 'decided', decided_by: userId, cls: 'inspected-party'}]);

  // The vessel: listed with the class pinned, then a field edited from its detail.
  await page.getByRole('link', {name: 'Vessels', exact: true}).click();
  await expect(page.getByRole('heading', {level: 1, name: 'Vessels'})).toBeVisible();
  await page.goto(`/admin.html#fleet-vessels?region=${region}`);
  const row = page.getByRole('row', {name: new RegExp(name)});
  await expect(row).toContainText('Inspected party boat');
  await expect(row).toContainText('Class');
  await checkA11y(page, 'fleet-vessels', info.project.name);
  await row.getByRole('link', {name}).click();
  await expect(page).toHaveURL(new RegExp(`#fleet-vessel/${vessel}$`));
  await expect(page.getByRole('heading', {level: 1, name})).toBeVisible();
  await expect(page.locator('#fleet-field-vessel_class')).toContainText('Pinned');
  const passengers = page.locator('#fleet-field-passengers_max');
  await expect(passengers).not.toContainText('Pinned');
  await passengers.getByRole('button', {name: 'Edit Passengers (max)'}).click();
  await passengers.getByLabel('Passengers (max)', {exact: true}).fill('6');
  await passengers.getByRole('button', {name: 'Save and pin'}).click();
  await expect(page.getByRole('status').filter({hasText: 'Passengers (max) saved and pinned.'})).toBeVisible();
  await expect(passengers).toContainText('6');
  await expect(passengers).toContainText('Pinned');
  await expect(passengers).toContainText('Admin edit');
  await checkA11y(page, 'fleet-vessel', info.project.name);
  expect(await d1(`SELECT passengers_max,json_type(pinned_json,'$.passengers_max') AS pin FROM fleet_vessels WHERE id='${vessel}'`))
    .toEqual([{passengers_max: 6, pin: 'object'}]);
  expect(await d1(`SELECT value_json,method,source_url FROM fleet_vessel_facts WHERE vessel_id='${vessel}' AND field='passengers_max' AND superseded_at IS NULL`))
    .toEqual([{value_json: '6', method: 'admin', source_url: `admin:${userId}`}]);

  // Unpin releases the pin and keeps the value.
  await passengers.getByRole('button', {name: 'Unpin Passengers (max)'}).click();
  await expect(page.getByRole('status').filter({hasText: 'Passengers (max) unpinned'})).toBeVisible();
  await expect(passengers).not.toContainText('Pinned');
  expect(await d1(`SELECT passengers_max,json_type(pinned_json,'$.passengers_max') AS pin FROM fleet_vessels WHERE id='${vessel}'`))
    .toEqual([{passengers_max: 6, pin: null}]);
  expect(pageErrors).toEqual([]);
});

test('the fleet trip detail fits a phone screen without horizontal page scroll', async ({page, pageErrors}, info) => {
  test.setTimeout(120_000);
  const userId = await signInAsAdmin(page);
  // Unique per project and attempt, like the review test above.
  const tag = word(`${info.project.name}-${info.repeatEachIndex}-${info.retry}`), region = `e2e-${tag}`;
  const trip = hex(`e2e-fleet-trip:${tag}`), vessel = hex(`e2e-fleet-trip-vessel:${tag}`), name = `E2E Tern ${tag}`;
  const segment = hex(`e2e-fleet-trip-seg:${tag}`), label = hex(`e2e-fleet-trip-label:${tag}`);
  const now = new Date().toISOString();
  const departed = new Date(Date.now() - 3 * 3600_000).toISOString();   // inside the trip's window
  const returned = new Date(Date.now() - 1 * 3600_000).toISOString();
  await d1(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at)
      VALUES('${vessel}','${region}','e2e-tern-${tag}','${name}','E2ETERN${tag.toUpperCase()}','morro-bay','active','hidden','${now}','${now}','${now}','${now}');`
    + `INSERT INTO fleet_trips(id,region,vessel_id,mmsi,departed_at,returned_at,local_date,season,status,distance_nm,max_offshore_nm,fishing_min,source,rights,classifier_version,computed_at)
      VALUES('${trip}','${region}','${vessel}','366000000','${departed}','${returned}','${departed.slice(0, 10)}','2026','closed',12,4,90,'synthetic','public','e2e','${now}');`
    + `INSERT INTO fleet_segments(id,trip_id,seq,kind,started_at,ended_at,mean_sog,straightness,heading_var)
      VALUES('${segment}','${trip}',1,'drift-anchor','${departed}','${returned}',1.2,0.9,10);`
    + `INSERT INTO fleet_segment_labels(id,trip_id,started_at,ended_at,label,labeller,basis,created_at)
      VALUES('${label}','${trip}','${departed}','${returned}','drift-anchor','${userId}','synthetic e2e label','${now}');`);

  // The trip detail renders the labels and segments tables; their "Delete"/"Use range" headers are
  // visually-hidden (position: absolute), and at phone width those escape an unpositioned .admin-scroll
  // and widen the page. Assert the page itself never scrolls horizontally at phone width.
  await page.setViewportSize({width: 375, height: 812});
  await page.goto(`/admin.html#fleet-trip/${trip}`);
  await expect(page.getByRole('heading', {level: 1, name: new RegExp(name)})).toBeVisible();
  await expect(page.getByRole('table').first()).toBeVisible();
  const widths = await page.evaluate(() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth}));
  expect(widths.scroll, `the trip detail overflows horizontally at phone width (page ${widths.scroll}px, viewport ${widths.client}px)`).toBeLessThanOrEqual(widths.client);
  expect(pageErrors).toEqual([]);
});

test('the fleet tabs and routes are hidden while the fleet is off', async ({page, pageErrors}) => {
  test.setTimeout(120_000);
  await signInAsAdmin(page);
  // FLEET_ENABLED off: every /api/admin/fleet/* path answers 404 (server/routes/fleet.ts fleetGate).
  await page.route('**/api/admin/fleet/**', route => route.fulfill({status: 404, json: {error: 'Not found'}}));
  await page.goto('/admin.html#fleet-review');
  await expect(page.getByRole('heading', {level: 1, name: 'Review queue'})).toBeVisible();
  const nav = page.getByRole('navigation', {name: 'Admin views'});
  await expect(nav.getByRole('link', {name: 'Health'})).toBeVisible();
  await expect(nav.getByRole('link', {name: 'Fleet review'})).toHaveCount(0);
  await expect(nav.getByRole('link', {name: 'Vessels', exact: true})).toHaveCount(0);
  await page.goto(`/admin.html#fleet-vessel/${hex('e2e-fleet-off')}`);
  await expect(page.getByRole('heading', {level: 1, name: 'Review queue'})).toBeVisible();
  expect(pageErrors).toEqual([]);
});
