// SC0922-03: the account sheet's catch log reaches every stored entry. The route sends 200 rows a page and says in two response
// headers whether older rows exist; the sheet offers "Show older entries", appends the next page, and removes any entry singly.
// Drives the real account dialog (dist/account.js) in the app. Fully stubbed with synthetic rows: the session, passkeys, trips,
// spots and catch log are answered here, non-local traffic is aborted by the shared fixtures, nothing authenticates.
import type {Page, Route} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const TOKEN = (id: string) => `CURSORTOKEN-${id}`;
const PAGE_SIZE = 200;
// Newest first, IDs ascending within each timestamp. Rows 199/200 and 399/400 tie across page boundaries.
const rowFor = (i: number) => ({id: `e${String(i).padStart(3, '0')}`, started_at: new Date(Date.UTC(2026, 5, 1) - Math.floor((i + 1) / 2) * 3600_000).toISOString(), outcome: 'blank', count: 0, trip_id: null, species: `Species ${i}`, note: i === 449 ? '<b>oldest</b>' : null});
const ROWS = Array.from({length: 450}, (_, i) => rowFor(i));
type Row = (typeof ROWS)[number];
const compareKeys = (a: Row, b: Row) => b.started_at.localeCompare(a.started_at) || a.id.localeCompare(b.id);

interface Stub {reads: (string | null)[]; deletes: string[]; failNextOlderRead?: boolean; failDelete?: boolean; failFirst?: boolean; gate?: Promise<void>; removed: Set<string>}

/** Session, passkeys, spots and trips, plus a catch log with opaque tokens for the last key returned. */
async function stubAccount(page: Page): Promise<Stub> {
  const stub: Stub = {reads: [], deletes: [], removed: new Set()};
  const cursors = new Map<string, Row>();
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null}}));
  await page.route('**/api/auth/passkeys', route => route.fulfill({json: {passkeys: [{id: 'p1', created_at: '2026-10-01T00:00:00Z', last_used_at: null}]}}));
  await page.route('**/api/spots', route => route.fulfill({json: {spots: []}}));
  await page.route('**/api/trips', route => route.fulfill({json: {trips: [], events: []}}));
  await page.route(url => url.pathname === '/api/catch-log', async (route: Route) => {
    const cursor = new URL(route.request().url()).searchParams.get('cursor');
    stub.reads.push(cursor);
    if (cursor && stub.gate) await stub.gate;
    const after = cursor === null ? undefined : cursors.get(cursor);
    if (cursor !== null && !after) return route.fulfill({status: 400, json: {error: 'Invalid cursor'}});
    if (stub.failFirst && !cursor) return route.fulfill({status: 503, json: {error: 'storage unavailable'}});
    if (cursor && stub.failNextOlderRead) { stub.failNextOlderRead = false; return route.fulfill({status: 503, json: {error: 'storage unavailable'}}); }
    // A deleted boundary row no longer appears in the results, but its issued key still locates the next page.
    const available = ROWS.filter(row => !stub.removed.has(row.id) && (!after || compareKeys(row, after) > 0));
    const entries = available.slice(0, PAGE_SIZE), more = available.length > PAGE_SIZE;
    const headers: Record<string, string> = {'X-SC-Catch-Log-Has-More': String(more)};
    if (more) {
      const last = entries[PAGE_SIZE - 1]!;
      const next = TOKEN(last.id);
      cursors.set(next, last);
      headers['X-SC-Catch-Log-Next-Cursor'] = next;
    }
    return route.fulfill({json: {entries}, headers});
  });
  await page.route(url => url.pathname.startsWith('/api/catch-log/'), async (route: Route) => {
    if (route.request().method() !== 'DELETE') return route.fulfill({status: 405, headers: {Allow: 'DELETE'}});
    const id = decodeURIComponent(new URL(route.request().url()).pathname.slice('/api/catch-log/'.length));
    stub.deletes.push(id);
    if (stub.failDelete) return route.fulfill({status: 404, json: {error: 'Not found'}});
    stub.removed.add(id);
    return route.fulfill({json: {deleted: true}});
  });
  return stub;
}

async function stubNewEntry(page: Page) {
  await page.route(url => url.pathname === '/api/catch-log', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    return route.fulfill({status: 201, json: {id: 'new-1'}});
  });
}

async function openAccount(page: Page, v2: {open(name: 'app', params?: Record<string, string>): Promise<void>}) {
  await v2.open('app', AREA);
  await page.evaluate(() => { location.hash = 'account'; });
  const card = page.locator('.account-card');
  await expect(card).toContainText('Signed in as Skipper');
  return card;
}

test('a full final page offers no older entries', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  for (const row of ROWS.slice(PAGE_SIZE)) stub.removed.add(row.id);
  const card = await openAccount(page, v2);
  await expect(card.locator('#log-list li')).toHaveCount(PAGE_SIZE);
  await expect(card.locator('#log-older')).toBeHidden();
  expect(stub.reads).toEqual([null]);
  expect(pageErrors).toEqual([]);
});

test('older_entries_append_by_keyboard_after_deleting_the_cursor_row', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  const card = await openAccount(page, v2);
  const items = card.locator('#log-list li'), older = card.locator('#log-older');
  await expect(older).toHaveText('Show older entries');
  await expect(items).toHaveCount(200);
  await expect(older).toBeVisible();

  // Non-DELETE item requests must not silently remove an as-yet-unloaded survivor from the fixture.
  const statuses = await page.evaluate(async () => {
    const url = '/api/catch-log/e201';
    return [(await fetch(url)).status, (await fetch(url, {method: 'PATCH'})).status];
  });
  expect([...stub.removed], 'non-DELETE requests do not remove any rows').toEqual([]);
  expect(statuses).toEqual([405, 405]);

  // Delete the row that issued the cursor, before loading older entries. A filtered offset skips its tied successor e200.
  const boundary = items.filter({has: page.locator('[data-remove-log="e199"]')});
  await boundary.getByRole('button', {name: 'Remove'}).click();
  await expect(boundary).toHaveCount(0);
  await expect(items).toHaveCount(199);
  expect(stub.deletes).toEqual(['e199']);
  expect(stub.reads).toEqual([null]);

  await older.focus();
  // While a page is loading the button says so, a second press does not ask again, and keyboard focus stays on it.
  let release: () => void = () => {};
  stub.gate = new Promise<void>(resolve => { release = resolve; });
  await page.keyboard.press('Enter');
  await expect(older).toHaveText('Loading older entries…');
  await expect(older).toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('Enter');
  await expect(older).toBeFocused();
  release(); stub.gate = undefined;
  await expect(items).toHaveCount(399);
  await expect(older).toHaveText('Show older entries');
  await page.keyboard.press('Enter');
  await expect.poll(() => items.locator('[data-remove-log]').evaluateAll(buttons => buttons.map(b => b.getAttribute('data-remove-log'))),
    {message: 'every surviving ID appears exactly once, in order'}).toEqual(ROWS.filter(row => row.id !== 'e199').map(row => row.id));
  await expect(older).toBeHidden();
  expect(stub.reads, 'the first page, then each cursor once').toEqual([null, TOKEN('e199'), TOKEN('e399')]);
  await expect(items.first()).toContainText('Species 0');
  await expect(items.last()).toContainText('Species 449');
  await expect(items.last()).toContainText('<b>oldest</b>');   // escaped text, not markup

  // The oldest row is removed like any other: only it goes, older pages stay shown, and the list is not read again.
  await items.last().getByRole('button', {name: 'Remove'}).click();
  await expect(items).toHaveCount(448);
  expect(stub.deletes).toEqual(['e199', 'e449']);
  expect(stub.reads, 'a removal does not reset to page one').toHaveLength(3);
  await expect(card.locator('#log-list')).not.toContainText('Species 449');

  // The cursor is a position kept in the page only: never in the address, storage or any shown text.
  expect(page.url()).not.toContain('CURSORTOKEN');
  const kept = await page.evaluate(() => JSON.stringify([{...localStorage}, {...sessionStorage}]));
  expect(kept).not.toContain('CURSORTOKEN');
  await expect(card).not.toContainText('CURSORTOKEN');
  expect(pageErrors).toEqual([]);
});

test('failed_older_read_keeps_rows_and_retries_the_same_cursor_and_failed_remove_keeps_the_row', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  stub.failNextOlderRead = true;
  const card = await openAccount(page, v2);
  const items = card.locator('#log-list li'), older = card.getByRole('button', {name: 'Show older entries'});
  await expect(items).toHaveCount(200);

  await older.click();
  await expect(card.locator('#log-status')).toHaveText('Could not load older entries. Try again.');
  await expect(items).toHaveCount(200);
  await expect(older).toBeVisible();
  await expect(older).toBeEnabled();
  await older.click();
  await expect(items).toHaveCount(400);
  await expect(card.locator('#log-status')).toHaveText('');
  expect(stub.reads, 'the retry asks for the same cursor').toEqual([null, TOKEN('e199'), TOKEN('e199')]);

  stub.failDelete = true;
  await items.nth(250).getByRole('button', {name: 'Remove'}).click();
  await expect(card.locator('#account-status')).toHaveText('Not found.');
  expect(stub.deletes).toEqual(['e250']);
  await expect(items).toHaveCount(400);
  await expect(items.filter({hasText: 'Species 250'})).toHaveCount(1);
  expect(pageErrors).toEqual([]);
});

test('first_read_failure_offers_try_again_and_a_new_entry_starts_again_at_page_one', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  stub.failFirst = true;
  const card = await openAccount(page, v2);
  await expect(card.locator('#log-status')).toHaveText('Could not load your catch log. Try again.');
  await expect(card.getByRole('button', {name: 'Show older entries'})).toBeHidden();
  stub.failFirst = false;
  await card.getByRole('button', {name: 'Try again'}).click();
  await expect(card.locator('#log-list li')).toHaveCount(200);
  await expect(card.getByRole('button', {name: 'Try again'})).toBeHidden();
  await card.getByRole('button', {name: 'Show older entries'}).click();
  await expect(card.locator('#log-list li')).toHaveCount(400);

  // Saving an entry reads page one again (a new entry may sort anywhere by its date); the older pages are not kept.
  await stubNewEntry(page);
  await card.getByLabel('What happened').selectOption('blank');
  await card.getByRole('button', {name: 'Save to my log'}).click();
  await expect(card.locator('#account-status')).toHaveText('Saved to your log.');
  await expect(card.locator('#log-list li')).toHaveCount(200);
  await expect(card.getByRole('button', {name: 'Show older entries'})).toBeVisible();
  expect(stub.reads).toEqual([null, null, TOKEN('e199'), null]);
  expect(pageErrors).toEqual([]);
});

test('a_pending_older_read_cannot_change_a_newer_list_or_a_closed_sheet', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  await stubNewEntry(page);
  const card = await openAccount(page, v2);
  const items = card.locator('#log-list li'), older = card.locator('#log-older');
  await expect(items).toHaveCount(200);
  let release: () => void = () => {};
  stub.gate = new Promise<void>(resolve => { release = resolve; });
  await older.click();
  await expect(older).toHaveText('Loading older entries…');
  // A saved entry starts the list again at page one; the older page that was still loading is then dropped.
  await card.getByRole('button', {name: 'Save to my log'}).click();
  await expect(card.locator('#account-status')).toHaveText('Saved to your log.');
  release(); stub.gate = undefined;
  await expect(items).toHaveCount(200);
  await expect(older).toHaveText('Show older entries');
  await page.waitForTimeout(300);
  await expect(items).toHaveCount(200);

  // Closing the sheet while a page is loading leaves nothing behind and raises no error.
  stub.gate = new Promise<void>(resolve => { release = resolve; });
  await older.click();
  await page.keyboard.press('Escape');
  await expect(page.locator('.account-card')).toHaveCount(0);
  release(); stub.gate = undefined;
  await page.waitForTimeout(300);
  await page.evaluate(() => { location.hash = 'account'; });
  const again = page.locator('.account-card');
  await expect(again).toContainText('Signed in as Skipper');
  await expect(again.locator('#log-list li')).toHaveCount(200);
  expect(pageErrors).toEqual([]);
});
