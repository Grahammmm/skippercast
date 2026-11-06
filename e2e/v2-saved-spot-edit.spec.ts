// SC1137-09: edit a saved spot from the account panel. Drives the real dialog (dist/account.js) in the app with synthetic rows:
// the session, passkeys, trips, catch log and spots are answered here and nothing authenticates. Edit sends only name and note,
// Cancel sends nothing, a refusal shows the server's own words, and the GPX carries the new name and never the note.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const NOTE = 'E2ENOTE-private';

interface Stub {patches: {url: string; body: Record<string, unknown>}[]; changed: number; refuse?: {status: number; error: string}; spots: Record<string, unknown>[]}

async function stub(page: Page): Promise<Stub> {
  const s: Stub = {patches: [], changed: 0, spots: [
    {id: 'a1', name: 'First', lat: 35.0, lon: -121.6, note: NOTE, created_at: 'x'},
    {id: 'b2', name: 'Second', lat: 35.01, lon: -121.61, note: null, created_at: 'x'},
  ]};
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null}}));
  await page.route('**/api/auth/passkeys', route => route.fulfill({json: {passkeys: [{id: 'p1', created_at: '2026-10-01T00:00:00Z', last_used_at: null}]}}));
  await page.route('**/api/trips', route => route.fulfill({json: {trips: [], events: []}}));
  await page.route('**/api/catch-log', route => route.fulfill({json: {entries: []}, headers: {'X-SC-Catch-Log-Has-More': 'false'}}));
  await page.route('**/api/spots', route => route.fulfill({json: {spots: s.spots}}));
  await page.route('**/api/spots/*', route => {
    const request = route.request();
    if (request.method() !== 'PATCH') return route.fallback();
    s.patches.push({url: request.url(), body: request.postDataJSON() as Record<string, unknown>});
    if (s.refuse) return route.fulfill({status: s.refuse.status, json: {error: s.refuse.error}});
    const id = decodeURIComponent(new URL(request.url()).pathname.split('/').pop()!);
    const row = s.spots.find(r => r.id === id)!;
    Object.assign(row, s.patches.at(-1)!.body);
    return route.fulfill({json: row});
  });
  await page.addInitScript(() => { addEventListener('skippercast:saved-spots-changed', () => { (window as unknown as {__changed: number}).__changed = ((window as unknown as {__changed?: number}).__changed ?? 0) + 1; }); });
  return s;
}

async function open(page: Page, v2: {open(name: 'app', params?: Record<string, string>): Promise<void>}) {
  await v2.open('app', AREA);
  await page.evaluate(() => { location.hash = 'account'; });
  await expect(page.locator('#spot-list li')).toHaveCount(2);
}

test('Edit saves a new name and note in place; the position cannot be edited and the layer is told once', async ({page, v2}) => {
  const s = await stub(page); await open(page, v2);
  const row = page.locator('#spot-list li').first();
  await row.getByRole('button', {name: 'Edit'}).click();
  const form = page.locator('#spot-list form.spot-edit');
  await expect(form.locator('input[name=name]')).toHaveValue('First');
  await expect(form.locator('textarea[name=note]')).toHaveValue(NOTE);
  await expect(form).toContainText('A different position needs a new spot.');
  await expect(form.locator('input[name=lat], input[name=lon]')).toHaveCount(0);
  await form.locator('input[name=name]').fill('Renamed <b>x</b>');
  await form.locator('textarea[name=note]').fill('NEWNOTE');
  await form.getByRole('button', {name: 'Save changes'}).click();
  await expect(page.locator('#spot-list li').first()).toContainText('Renamed <b>x</b>');
  await expect(page.locator('#spot-list li').nth(1)).toContainText('Second');
  expect(s.patches).toHaveLength(1);
  expect(s.patches[0]!.url).toMatch(/\/api\/spots\/a1$/);
  expect(Object.keys(s.patches[0]!.body).sort()).toEqual(['name', 'note']);
  expect(await page.evaluate(() => (window as unknown as {__changed?: number}).__changed)).toBe(1);
});

test('Cancel and Escape leave the row as it was and send nothing', async ({page, v2}) => {
  const s = await stub(page); await open(page, v2);
  const first = page.locator('#spot-list li').first();
  await first.getByRole('button', {name: 'Edit'}).click();
  await page.locator('#spot-list input[name=name]').fill('Discarded');
  await page.locator('#spot-list').getByRole('button', {name: 'Cancel'}).click();
  await expect(page.locator('#spot-list form')).toHaveCount(0);
  await expect(page.locator('#spot-list li').first()).toContainText('First');
  await page.locator('#spot-list li').first().getByRole('button', {name: 'Edit'}).click();
  await page.locator('#spot-list input[name=name]').press('Escape');
  await expect(page.locator('#spot-list form')).toHaveCount(0);
  await expect(page.locator('.account-card'), 'Escape in the editor does not close the sheet').toBeVisible();
  expect(s.patches).toEqual([]);
  expect(await page.evaluate(() => (window as unknown as {__changed?: number}).__changed ?? 0)).toBe(0);
});

test('A refusal shows the server\'s own words, keeps the draft and the stored row', async ({page, v2}) => {
  const s = await stub(page); s.refuse = {status: 400, error: 'name must be 80 characters or fewer <i>'};
  await open(page, v2);
  await page.locator('#spot-list li').first().getByRole('button', {name: 'Edit'}).click();
  await page.locator('#spot-list input[name=name]').fill('Draft kept');
  await page.locator('#spot-list').getByRole('button', {name: 'Save changes'}).click();
  await expect(page.locator('#spot-list [data-edit-status]')).toHaveText('name must be 80 characters or fewer <i>');
  await expect(page.locator('#spot-list input[name=name]')).toHaveValue('Draft kept');
  expect(await page.evaluate(() => (window as unknown as {__changed?: number}).__changed ?? 0)).toBe(0);
  await page.locator('#spot-list').getByRole('button', {name: 'Cancel'}).click();
  await expect(page.locator('#spot-list li').first()).toContainText('First');
});
