// SC0922-03: the account sheet's catch log reaches every stored entry. The route sends 200 rows a page and says in two response
// headers whether older rows exist; the sheet offers "Show older entries", appends the next page, and removes any entry singly.
// Drives the real account dialog (dist/account.js) in the app. Fully stubbed with synthetic rows: the session, passkeys, trips,
// spots and catch log are answered here, non-local traffic is aborted by the shared fixtures, nothing authenticates.
import type {Page, Route} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const TOKEN = (n: number) => `CURSORTOKEN${n}`;
const rowFor = (i: number) => ({id: `e${String(i).padStart(3, '0')}`, started_at: new Date(Date.UTC(2026, 5, 1) - i * 3600_000).toISOString(), outcome: 'blank', count: 0, trip_id: null, species: `Species ${i}`, note: i === 449 ? '<b>oldest</b>' : null});
const ROWS = Array.from({length: 450}, (_, i) => rowFor(i));

interface Stub {reads: (string | null)[]; deletes: string[]; failPage?: number; failDelete?: boolean; failFirst?: boolean; gate?: Promise<void>; removed: Set<string>}

/** Session, passkeys, spots and trips, plus a paged catch log: page n (0-based) holds ROWS[200n..200n+200), cursor token for page n+1 is TOKEN(200 * (n+1)). */
async function stubAccount(page: Page): Promise<Stub> {
  const stub: Stub = {reads: [], deletes: [], removed: new Set()};
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null}}));
  await page.route('**/api/auth/passkeys', route => route.fulfill({json: {passkeys: [{id: 'p1', created_at: '2026-10-01T00:00:00Z', last_used_at: null}]}}));
  await page.route('**/api/spots', route => route.fulfill({json: {spots: []}}));
  await page.route('**/api/trips', route => route.fulfill({json: {trips: [], events: []}}));
  await page.route(url => url.pathname === '/api/catch-log', async (route: Route) => {
    const cursor = new URL(route.request().url()).searchParams.get('cursor');
    stub.reads.push(cursor);
    if (cursor && stub.gate) await stub.gate;
    const start = cursor ? Number(cursor.replace('CURSORTOKEN', '')) : 0, page_ = start / 200;
    if (stub.failFirst && !cursor) return route.fulfill({status: 503, json: {error: 'storage unavailable'}});
    if (cursor && stub.failPage === page_) { stub.failPage = undefined; return route.fulfill({status: 503, json: {error: 'storage unavailable'}}); }
    const rows = ROWS.filter(r => !stub.removed.has(r.id)).slice(start, start + 200);
    const more = start + 200 < ROWS.length;
    return route.fulfill({json: {entries: rows}, headers: more ? {'X-SC-Catch-Log-Has-More': 'true', 'X-SC-Catch-Log-Next-Cursor': TOKEN(start + 200)} : {'X-SC-Catch-Log-Has-More': 'false'}});
  });
  await page.route(url => url.pathname.startsWith('/api/catch-log/'), async (route: Route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.slice('/api/catch-log/'.length));
    stub.deletes.push(id);
    if (stub.failDelete) return route.fulfill({status: 404, json: {error: 'Not found'}});
    stub.removed.add(id);
    return route.fulfill({json: {deleted: true}});
  });
  return stub;
}

async function openAccount(page: Page, v2: {open(name: 'app', params?: Record<string, string>): Promise<void>}) {
  await v2.open('app', AREA);
  await page.evaluate(() => { location.hash = 'account'; });
  const card = page.locator('.account-card');
  await expect(card).toContainText('Signed in as Skipper');
  return card;
}

test('older_entries_append_by_keyboard_and_any_row_is_removed', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  const card = await openAccount(page, v2);
  const items = card.locator('#log-list li'), older = card.locator('#log-older');
  await expect(older).toHaveText('Show older entries');
  await expect(items).toHaveCount(200);
  await expect(older).toBeVisible();

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
  await expect(items).toHaveCount(400);
  await expect(older).toHaveText('Show older entries');
  await page.keyboard.press('Enter');
  await expect(items).toHaveCount(450);
  await expect(older).toBeHidden();
  expect(stub.reads, 'the first page, then each cursor once').toEqual([null, TOKEN(200), TOKEN(400)]);
  await expect(items.first()).toContainText('Species 0');
  await expect(items.last()).toContainText('Species 449');
  await expect(items.last()).toContainText('<b>oldest</b>');   // escaped text, not markup

  // The oldest row is removed like any other: only it goes, older pages stay shown, and the list is not read again.
  await items.last().getByRole('button', {name: 'Remove'}).click();
  await expect(items).toHaveCount(449);
  expect(stub.deletes).toEqual(['e449']);
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
  stub.failPage = 1;
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
  expect(stub.reads, 'the retry asks for the same cursor').toEqual([null, TOKEN(200), TOKEN(200)]);

  stub.failDelete = true;
  await items.nth(250).getByRole('button', {name: 'Remove'}).click();
  await expect(card.locator('#account-status')).toHaveText('Not found.');
  await expect(items).toHaveCount(400);
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
  await page.route(url => url.pathname === '/api/catch-log', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    return route.fulfill({status: 201, json: {id: 'new-1'}});
  });
  await card.getByLabel('What happened').selectOption('blank');
  await card.getByRole('button', {name: 'Save to my log'}).click();
  await expect(card.locator('#account-status')).toHaveText('Saved to your log.');
  await expect(card.locator('#log-list li')).toHaveCount(200);
  await expect(card.getByRole('button', {name: 'Show older entries'})).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test('a_pending_older_read_cannot_change_a_newer_list_or_a_closed_sheet', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page);
  await page.route(url => url.pathname === '/api/catch-log', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    return route.fulfill({status: 201, json: {id: 'new-1'}});
  });
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
