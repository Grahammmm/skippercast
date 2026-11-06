// SC1137-11: correct a catch-log entry from the account panel. Drives the real dialog (dist/account.js) in the app with synthetic rows:
// the session, passkeys, trips, spots and the paged catch log are answered here and nothing authenticates. Edit fills the one log form,
// Save sends PATCH /api/catch-log/:id with the whole form and updates the row in place, Cancel sends nothing and restores the create
// draft, a refusal shows the server's own words, and an edited older-page row keeps every loaded page and the cursor.
import type {Page, Route} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const TOKEN = (n: number) => `CURSORTOKEN${n}`;
const rowFor = (i: number): Record<string, unknown> => ({id: `e${String(i).padStart(3, '0')}`, started_at: new Date(Date.UTC(2026, 5, 1) - i * 3600_000).toISOString(), ended_at: null,
  outcome: 'blank', count: 0, trip_id: null, species: `Species ${i}`, method: null, lat: null, lon: null, note: null});
const TRIP = {id: 'trip-a', region: 'morro-bay', point: 'north', date: '2026-11-05', species: 'reef'};

interface Stub {rows: Record<string, unknown>[]; reads: (string | null)[]; patches: {url: string; body: Record<string, unknown>}[]; others: string[]; refuse?: {status: number; error: string}}

async function stubAccount(page: Page): Promise<Stub> {
  const stub: Stub = {rows: Array.from({length: 450}, (_, i) => rowFor(i)), reads: [], patches: [], others: []};
  stub.rows[1] = {...stub.rows[1]!, outcome: 'fish', count: 2, trip_id: 'gone-trip', ended_at: '2026-05-31T22:30:00.500Z', lat: 35.25, lon: -120.75, note: '<i>kept</i>', method: 'jig'};
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null}}));
  await page.route('**/api/auth/passkeys', route => route.fulfill({json: {passkeys: [{id: 'p1', created_at: '2026-10-01T00:00:00Z', last_used_at: null}]}}));
  await page.route('**/api/spots', route => route.fulfill({json: {spots: []}}));
  await page.route('**/api/trips', route => route.fulfill({json: {trips: [TRIP], events: []}}));
  await page.route(url => url.pathname === '/api/catch-log', async (route: Route) => {
    if (route.request().method() !== 'GET') { stub.others.push(route.request().method()); return route.fulfill({status: 500, json: {error: 'unexpected'}}); }
    const cursor = new URL(route.request().url()).searchParams.get('cursor');
    stub.reads.push(cursor);
    const start = cursor ? Number(cursor.replace('CURSORTOKEN', '')) : 0, more = start + 200 < stub.rows.length;
    return route.fulfill({json: {entries: stub.rows.slice(start, start + 200)}, headers: more ? {'X-SC-Catch-Log-Has-More': 'true', 'X-SC-Catch-Log-Next-Cursor': TOKEN(start + 200)} : {'X-SC-Catch-Log-Has-More': 'false'}});
  });
  await page.route(url => url.pathname.startsWith('/api/catch-log/'), async (route: Route) => {
    const request = route.request(), id = decodeURIComponent(new URL(request.url()).pathname.slice('/api/catch-log/'.length));
    if (request.method() !== 'PATCH') { stub.others.push(request.method()); return route.fulfill({status: 500, json: {error: 'unexpected'}}); }
    stub.patches.push({url: request.url(), body: request.postDataJSON() as Record<string, unknown>});
    if (stub.refuse) return route.fulfill({status: stub.refuse.status, json: {error: stub.refuse.error}});
    const i = stub.rows.findIndex(r => r.id === id), merged = {...stub.rows[i]!, ...stub.patches.at(-1)!.body, id};
    stub.rows[i] = merged;   // the page order the server would answer is not re-sorted: the panel keeps what it loaded
    return route.fulfill({json: merged});
  });
  return stub;
}

async function openAccount(page: Page, v2: {open(name: 'app', params?: Record<string, string>): Promise<void>}) {
  await v2.open('app', AREA);
  await page.evaluate(() => { location.hash = 'account'; });
  const card = page.locator('.account-card');
  await expect(card).toContainText('Signed in as Skipper');
  await expect(card.locator('#log-list li')).toHaveCount(200);
  await expect(card.locator('#log-trip option')).toHaveCount(2);
  return card;
}
const local = (page: Page, value: string) => page.evaluate(v => new Date(v).toISOString(), value);

test('edit_fills_the_log_form_and_saves_the_whole_entry_in_place', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  const card = await openAccount(page, v2);
  const items = card.locator('#log-list li');
  await items.nth(1).getByRole('button', {name: 'Edit'}).click();
  await expect(card.locator('#log-editing')).toBeVisible();
  await expect(card.locator('#log-started')).toBeFocused();
  await expect(card.getByRole('button', {name: 'Save changes'})).toBeVisible();
  await expect(items.nth(0).getByRole('button', {name: 'Edit'}), 'one correction at a time').toBeDisabled();
  // Every stored field is in the form; a trip that is not among the saved ones stays selected under its own label.
  await expect(card.locator('#log-outcome')).toHaveValue('fish');
  await expect(card.locator('#log-count')).toHaveValue('2');
  await expect(card.locator('#log-species')).toHaveValue('Species 1');
  await expect(card.locator('#log-method')).toHaveValue('jig');
  await expect(card.locator('#log-lat')).toHaveValue('35.25');
  await expect(card.locator('#log-lon')).toHaveValue('-120.75');
  await expect(card.locator('#log-note')).toHaveValue('<i>kept</i>');
  await expect(card.locator('#log-trip')).toHaveValue('gone-trip');
  await expect(card.locator('#log-trip option:checked')).toHaveText('Saved trip unavailable');
  expect(await card.locator('#log-ended').inputValue()).not.toBe('');

  // Untouched start/end/position are sent exactly as stored; edited fields change; the cleared note really clears.
  await card.locator('#log-count').fill('5');
  await card.locator('#log-species').fill('Lingcod <b>x</b>');
  await card.locator('#log-trip').selectOption('trip-a');
  await card.locator('#log-note').fill('');
  await card.getByRole('button', {name: 'Save changes'}).click();
  await expect(card.locator('#account-status')).toHaveText('Entry updated.');
  expect(stub.patches).toHaveLength(1);
  expect(stub.patches[0]!.url).toMatch(/\/api\/catch-log\/e001$/);
  expect(stub.patches[0]!.body).toEqual({started_at: stub.rows[1]!.started_at, ended_at: '2026-05-31T22:30:00.500Z', outcome: 'fish', count: 5, species: 'Lingcod <b>x</b>',
    method: 'jig', trip_id: 'trip-a', lat: 35.25, lon: -120.75, note: null});
  await expect(items).toHaveCount(200);
  await expect(items.nth(1)).toContainText('Lingcod <b>x</b>');
  await expect(items.nth(1)).toContainText('5 fish');
  await expect(items.nth(1)).toContainText('Trip: 2026-11-05');
  await expect(items.nth(1).getByRole('button', {name: 'Edit'})).toBeFocused();
  await expect(card.locator('#log-editing')).toBeHidden();
  await expect(card.getByRole('button', {name: 'Save to my log'})).toBeVisible();
  expect(stub.reads, 'saving a correction does not read the log again').toEqual([null]);
  expect(stub.others).toEqual([]);

  // Clearing the end, trip and position sends explicit nulls; a blank outcome sends count 0.
  await items.nth(1).getByRole('button', {name: 'Edit'}).click();
  await card.locator('#log-outcome').selectOption('blank');
  await card.locator('#log-ended').fill('');
  await card.locator('#log-trip').selectOption('');
  await card.locator('#log-lat').fill(''); await card.locator('#log-lon').fill('');
  await card.getByRole('button', {name: 'Save changes'}).click();
  await expect(card.locator('#account-status')).toHaveText('Entry updated.');
  expect(stub.patches[1]!.body).toEqual({started_at: stub.rows[1]!.started_at, ended_at: null, outcome: 'blank', count: 0, species: 'Lingcod <b>x</b>', method: 'jig', trip_id: null, lat: null, lon: null, note: null});
  expect(pageErrors).toEqual([]);
});

test('edit_cancel_and_escape_send_nothing_and_restore_the_create_draft', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  const card = await openAccount(page, v2);
  const items = card.locator('#log-list li');
  await card.locator('#log-species').fill('DRAFT species');
  await card.locator('#log-note').fill('draft note');
  await items.nth(1).getByRole('button', {name: 'Edit'}).click();
  await expect(card.locator('#log-species')).toHaveValue('Species 1');
  await card.locator('#log-species').fill('Changed but cancelled');
  await card.getByRole('button', {name: 'Cancel'}).click();
  await expect(card.locator('#log-editing')).toBeHidden();
  await expect(card.locator('#log-species')).toHaveValue('DRAFT species');
  await expect(card.locator('#log-note')).toHaveValue('draft note');
  await expect(items.nth(1)).toContainText('Species 1');
  await expect(items.nth(1).getByRole('button', {name: 'Edit'})).toBeFocused();

  await items.nth(1).getByRole('button', {name: 'Edit'}).click();
  await card.locator('#log-species').press('Escape');
  await expect(card.locator('#log-editing')).toBeHidden();
  await expect(page.locator('.account-card'), 'Escape in the form does not close the sheet').toBeVisible();
  await expect(card.locator('#log-species')).toHaveValue('DRAFT species');
  expect(stub.patches).toEqual([]);
  expect(stub.others).toEqual([]);
  expect(stub.reads).toEqual([null]);
  expect(pageErrors).toEqual([]);
});

test('edit_refusal_shows_the_servers_words_keeps_the_draft_and_allows_a_retry', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  stub.refuse = {status: 400, error: 'a fish entry needs a count of at least 1 <i>!'};
  const card = await openAccount(page, v2);
  const items = card.locator('#log-list li');
  await items.nth(0).getByRole('button', {name: 'Edit'}).click();
  await card.locator('#log-outcome').selectOption('fish');
  await card.locator('#log-species').fill('Draft kept');
  await card.getByRole('button', {name: 'Save changes'}).click();
  await expect(card.locator('#log-status')).toHaveText('a fish entry needs a count of at least 1 <i>!');
  await expect(card.locator('#log-species')).toHaveValue('Draft kept');
  await expect(card.locator('#log-editing')).toBeVisible();
  await expect(items.nth(0)).toContainText('Species 0');
  await expect(items.nth(0)).not.toContainText('Draft kept');

  stub.refuse = undefined;
  await card.locator('#log-count').fill('3');
  await card.getByRole('button', {name: 'Save changes'}).click();
  await expect(card.locator('#account-status')).toHaveText('Entry updated.');
  await expect(items.nth(0)).toContainText('Draft kept');
  expect(stub.patches).toHaveLength(2);
  expect(stub.others).toEqual([]);

  // A start the browser cannot read is refused here, in the page's own words, and nothing is sent.
  await items.nth(0).getByRole('button', {name: 'Edit'}).click();
  await card.locator('#log-started').fill('');
  await card.getByRole('button', {name: 'Save changes'}).click();
  await expect(card.locator('#log-status')).toHaveText('Enter a valid start and optional end time.');
  expect(stub.patches).toHaveLength(2);
  expect(pageErrors).toEqual([]);
});

test('edit_an_older_page_row_keeps_every_loaded_page_and_the_cursor', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  const card = await openAccount(page, v2);
  const items = card.locator('#log-list li'), older = card.locator('#log-older');
  await older.click();
  await expect(items).toHaveCount(400);
  await items.nth(250).getByRole('button', {name: 'Edit'}).click();
  await card.locator('#log-species').fill('EDITED-250');
  await card.locator('#log-started').fill('2030-01-01T00:00');
  await card.getByRole('button', {name: 'Save changes'}).click();
  await expect(card.locator('#account-status')).toHaveText('Entry updated.');
  // The row moved to its place by start time among the loaded rows; nothing was lost and nothing was read again.
  await expect(items).toHaveCount(400);
  await expect(items.first()).toContainText('EDITED-250');
  await expect(items.first()).toContainText('2030');
  await expect(items.filter({hasText: 'EDITED-250'})).toHaveCount(1);
  expect(stub.patches[0]!.body.started_at).toBe(await local(page, '2030-01-01T00:00'));
  expect(stub.reads).toEqual([null, TOKEN(200)]);
  await expect(older).toHaveText('Show older entries');
  await older.click();
  await expect(items).toHaveCount(450);
  expect(stub.reads, 'the next page uses the cursor it already had').toEqual([null, TOKEN(200), TOKEN(400)]);
  await expect(items.filter({hasText: 'EDITED-250'})).toHaveCount(1);
  await expect(items.first()).toContainText('EDITED-250');
  expect(stub.others).toEqual([]);
  expect(pageErrors).toEqual([]);
});
