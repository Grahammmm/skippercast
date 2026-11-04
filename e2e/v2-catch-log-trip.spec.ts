// SC0022-06: the account sheet's catch-log form offers the signed-in person's own saved trips as an
// optional "Trip" choice (saved date and area), sends the chosen id as trip_id, and the list shows the
// associated trip's date. Drives the real account dialog (dist/account.js) in the app. Fully stubbed:
// the session, passkeys, trips, catch log and spots are answered here, non-local traffic is aborted by
// the shared fixtures, nothing authenticates and no account is written.
import type {Page, Route} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const trip = (id: string, date: string, point = 'north') => ({id, region: 'morro-bay', point, date, species: 'reef'});
const TRIPS = [trip('trip-late', '2026-11-20'), trip('trip-a', '2026-11-05'), trip('trip-b', '2026-11-05', 'south')];

interface Stub {posts: Record<string, unknown>[]; entries: Record<string, unknown>[]}

/** Session, passkeys and spots, plus a catch log that stores what is posted. `tripsRoute` answers GET /api/trips. */
async function stubAccount(page: Page, tripsRoute: (route: Route, call: number) => Promise<void>, options: {refuse?: boolean} = {}): Promise<Stub> {
  const stub: Stub = {posts: [], entries: [{id: 'old-1', started_at: '2026-10-30T15:00:00.000Z', outcome: 'blank', count: 0, trip_id: 'trip-a', note: null}]};
  let calls = 0;
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null}}));
  await page.route('**/api/auth/passkeys', route => route.fulfill({json: {passkeys: [{id: 'p1', created_at: '2026-10-01T00:00:00Z', last_used_at: null}]}}));
  await page.route('**/api/spots', route => route.fulfill({json: {spots: []}}));
  await page.route('**/api/trips', route => tripsRoute(route, ++calls));
  await page.route('**/api/catch-log', async route => {
    if (route.request().method() === 'GET') return route.fulfill({json: {entries: stub.entries}});
    const body = route.request().postDataJSON() as Record<string, unknown>;
    stub.posts.push(body);
    if (options.refuse && body.trip_id) return route.fulfill({status: 404, json: {error: 'Not found'}});   // the route's own answer for a deleted trip
    stub.entries.unshift({id: `new-${stub.posts.length}`, started_at: body.started_at, outcome: body.outcome, count: body.count ?? 0, trip_id: body.trip_id ?? null, note: body.note});
    return route.fulfill({status: 201, json: {id: `new-${stub.posts.length}`}});
  });
  return stub;
}

const answer = (trips: unknown[]) => async (route: Route) => { await route.fulfill({json: {trips, events: []}}); };

async function openAccount(page: Page, v2: {open(name: 'app', params?: Record<string, string>): Promise<void>}) {
  await v2.open('app', AREA);
  await page.evaluate(() => { location.hash = 'account'; });
  const card = page.locator('.account-card');
  await expect(card).toContainText('Signed in as Skipper');
  return card;
}

test('optional_trip_selection_posts_and_resets', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page, answer(TRIPS));
  const card = await openAccount(page, v2);
  const select = card.getByLabel('Trip');
  await expect(select.locator('option')).toHaveText(['No trip', '2026-11-20 · Point Estero', '2026-11-05 · Point Estero', '2026-11-05 · Point Buchon']);
  await expect(select).toHaveValue('');
  await expect(card.getByText('Trip: 2026-11-05')).toHaveCount(1);   // the earlier entry names trip-a
  await expect(card.locator('#log-list li').first()).toContainText('Trip: 2026-11-05');

  // No trip chosen behaves as before: the body has no trip_id.
  await card.getByLabel('What happened').selectOption('blank');
  await card.getByRole('button', {name: 'Save to my log'}).click();
  await expect(card.locator('#account-status')).toHaveText('Saved to your log.');
  expect(stub.posts).toHaveLength(1);
  expect('trip_id' in stub.posts[0]!, 'unassociated logging sends no trip_id').toBe(false);
  await expect(card.locator('#log-list li').first()).not.toContainText('Trip:');

  // A chosen trip is sent exactly, shown on the list, and the choice resets afterwards.
  await select.selectOption({label: '2026-11-20 · Point Estero'});
  await card.getByRole('button', {name: 'Save to my log'}).click();
  await expect(card.locator('#log-list li').first()).toContainText('Trip: 2026-11-20');
  expect(stub.posts[1]!.trip_id).toBe('trip-late');
  await expect(select).toHaveValue('');
  expect(pageErrors).toEqual([]);
});

test('stale_trip_and_failed_trip_read_keep_logging_honest', async ({page, pageErrors, v2}) => {
  // Metadata that arrives after the entries still dates them; a trip deleted since it was read is refused and nothing is retried without it.
  let release: () => void = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  const stub = await stubAccount(page, async route => { await gate; await route.fulfill({json: {trips: TRIPS, events: []}}); }, {refuse: true});
  const card = await openAccount(page, v2);
  await expect(card.locator('#log-list li')).toHaveCount(1);
  await expect(card.locator('#log-list li').first()).not.toContainText('Trip:');
  await expect(card.getByLabel('Trip').locator('option')).toHaveText(['No trip']);
  release();
  await expect(card.locator('#log-list li').first()).toContainText('Trip: 2026-11-05');

  await card.getByLabel('Trip').selectOption('trip-b');
  await card.getByLabel('Note', {exact: true}).fill('kept for correction');
  await card.getByLabel('What happened').selectOption('unknown');
  await card.getByRole('button', {name: 'Save to my log'}).click();
  await expect(card.locator('#account-status')).toHaveText('Not found.');
  expect(stub.posts, 'one refused POST and no fallback without the trip').toHaveLength(1);
  expect(stub.posts[0]!.trip_id).toBe('trip-b');
  await expect(card.getByLabel('Trip')).toHaveValue('trip-b');
  await expect(card.getByLabel('Note', {exact: true})).toHaveValue('kept for correction');
  await expect(card.getByLabel('What happened')).toHaveValue('unknown');
  await expect(card.locator('#log-list li')).toHaveCount(1);
  expect(pageErrors).toEqual([]);
});

test('failed trip read leaves logging without a trip usable', async ({page, pageErrors, v2}) => {
  const stub = await stubAccount(page, async route => { await route.fulfill({status: 500, json: {error: 'down'}}); });
  const card = await openAccount(page, v2);
  await expect(card.locator('#account-status')).toHaveText('Saved trips could not be loaded. You can still save without a trip.');
  await expect(card.getByLabel('Trip').locator('option')).toHaveText(['No trip']);
  await card.getByRole('button', {name: 'Save to my log'}).click();
  await expect(card.locator('#account-status')).toHaveText('Saved to your log.');
  expect(stub.posts).toHaveLength(1);
  expect('trip_id' in stub.posts[0]!).toBe(false);
  expect(pageErrors).toEqual([]);
});

test('closing and reopening is not updated by an older dialog\'s late trips answer', async ({page, pageErrors, v2}) => {
  let releaseFirst: () => void = () => {};
  const gate = new Promise<void>(resolve => { releaseFirst = resolve; });
  await stubAccount(page, async (route, call) => {
    if (call === 1) { await gate; return route.fulfill({json: {trips: [trip('old-dialog', '2020-01-01')], events: []}}); }
    return route.fulfill({json: {trips: [trip('new-dialog', '2026-12-01', 'south')], events: []}});
  });
  const card = await openAccount(page, v2);
  await card.getByRole('button', {name: 'Close account'}).click();
  await expect(page.locator('.account-card')).toHaveCount(0);
  await page.evaluate(() => { location.hash = 'account'; });
  const again = page.locator('.account-card');
  await expect(again.getByLabel('Trip').locator('option')).toHaveText(['No trip', '2026-12-01 · Point Buchon']);
  releaseFirst();
  await page.waitForTimeout(300);
  await expect(again.getByLabel('Trip').locator('option')).toHaveText(['No trip', '2026-12-01 · Point Buchon']);
  await expect(again.locator('#account-status')).toHaveText('');
  expect(pageErrors).toEqual([]);
});
