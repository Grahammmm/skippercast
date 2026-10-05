// The charter fleet admin (CF-31, docs/plans/charter-fleet/design.md § 13): an admin
// decides a seeded class review in #fleet-review, opens the vessel in #fleet-vessel/<id>,
// edits a field and sees it pinned, each checked in D1 (admin fact, pinned_json).
// e2e/serve.mjs sets FLEET_ENABLED=true; a second test answers the fleet API with 404
// (the flag off) and checks the fleet tabs and routes are gone. Synthetic data only:
// the vessels are invented names in a per-project region, never registry rows.
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import type {Page} from '@playwright/test';
import {test, expect, openMap, checkA11y} from './fixtures.ts';

const ROOT = resolve(import.meta.dirname, '..');
const WRANGLER = ['--yes', 'wrangler@4.142.0'];   // the pin e2e/serve.mjs uses
const CONFIG = resolve(ROOT, 'wrangler.e2e.local.jsonc'), STATE = resolve(ROOT, '.wrangler/e2e-state');

/**
 * Run SQL against the local D1 the dev server uses; the parsed rows of the last statement.
 * The running Worker and the other project's test share the SQLite file, so a busy database is retried.
 */
function d1(sql: string): Record<string, unknown>[] {
  for (let attempt = 1; ; attempt++) {
    try {
      const out = execFileSync('npx', [...WRANGLER, 'd1', 'execute', 'skippercast', '--local', '--persist-to', STATE, '--config', CONFIG, '--json', '--command', sql],
        {cwd: ROOT, encoding: 'utf8', env: {...process.env, WRANGLER_SEND_METRICS: 'false'}, stdio: ['ignore', 'pipe', 'pipe']});
      const parsed = JSON.parse(out) as {results: Record<string, unknown>[]}[];
      return parsed.at(-1)?.results ?? [];
    } catch (e) {
      if (attempt >= 5 || !/SQLITE_BUSY/.test(String((e as {stderr?: unknown}).stderr ?? e))) throw e;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500 * attempt);
    }
  }
}
const word = (s: string): string => s.replace(/[^\w-]/g, '');
const hex = (s: string): string => createHash('sha256').update(s).digest('hex').slice(0, 32);

/** Create a passkey account (the virtual authenticator e2e/admin.spec.ts uses) and make it an admin; its user id. */
async function signInAsAdmin(page: Page): Promise<string> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
    hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true}});
  await openMap(page, '/?region=morro-bay#guide');
  await page.locator('#account-entry').click();
  await page.locator('#account-create').click();
  await expect(page.locator('#map .leaflet-marker-icon').first()).toBeAttached({timeout: 30_000});
  await expect.poll(async () => (await (await page.request.get('/api/session')).json()).signedIn).toBe(true);
  const userId = word((await (await page.request.get('/api/session')).json()).user.id);
  d1(`UPDATE users SET role='admin' WHERE id='${userId}';`);
  expect((await (await page.request.get('/api/session')).json()).is_admin).toBe(true);
  return userId;
}

test('an admin decides a fleet review, edits a vessel field and sees it pinned', async ({page, pageErrors}, info) => {
  test.setTimeout(120_000);
  const userId = await signInAsAdmin(page);
  const tag = word(info.project.name), region = `e2e-${tag}`;
  const vessel = hex(`e2e-fleet-vessel:${tag}`), review = hex(`e2e-fleet-review:${tag}`), name = `E2E Osprey ${tag}`;
  const now = new Date().toISOString();
  d1(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at)
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
  expect(d1(`SELECT status,decided_by,json_extract(decision_json,'$.vessel_class') AS cls FROM fleet_reviews WHERE id='${review}'`))
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
  expect(d1(`SELECT passengers_max,json_type(pinned_json,'$.passengers_max') AS pin FROM fleet_vessels WHERE id='${vessel}'`))
    .toEqual([{passengers_max: 6, pin: 'object'}]);
  expect(d1(`SELECT value_json,method,source_url FROM fleet_vessel_facts WHERE vessel_id='${vessel}' AND field='passengers_max' AND superseded_at IS NULL`))
    .toEqual([{value_json: '6', method: 'admin', source_url: `admin:${userId}`}]);

  // Unpin releases the pin and keeps the value.
  await passengers.getByRole('button', {name: 'Unpin Passengers (max)'}).click();
  await expect(page.getByRole('status').filter({hasText: 'Passengers (max) unpinned'})).toBeVisible();
  await expect(passengers).not.toContainText('Pinned');
  expect(d1(`SELECT passengers_max,json_type(pinned_json,'$.passengers_max') AS pin FROM fleet_vessels WHERE id='${vessel}'`))
    .toEqual([{passengers_max: 6, pin: null}]);
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
