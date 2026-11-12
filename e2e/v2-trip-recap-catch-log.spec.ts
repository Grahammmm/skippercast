// SC1137-12: the recap follows the catch log's cursor pages (X-SC-Catch-Log-Has-More / -Next-Cursor) and reads as complete only when the
// last page was reached; a stopped read keeps what it read and says older entries were not read.
// SC0022-07: each past trip in the signed-in Saved trips recap lists what the person logged for that exact
// trip (fish with count, blank, not sure) beside its comfort reports. Drives the real alerts dialog
// (web/app/TripAlerts.tsx) in the app. Fully stubbed: the session, trips, comfort and catch log are answered
// here, non-local traffic is aborted by the shared fixtures, nothing authenticates and no account is written.
import type {Page, Route} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay'};
const trip = (id: string, date: string) => ({id, region: 'morro-bay', point: 'central', date, species: 'halibut', start_hour: 7, end_hour: 13});
const TRIPS = [trip('past-a', '2020-03-02'), trip('past-b', '2020-03-02'), trip('past-c', '2020-03-01')];
const row = (id: string, trip_id: string | null, outcome: string, count = 0) =>
  ({id, trip_id, started_at: '2020-03-02T20:00:00.000Z', ended_at: null, outcome, count, note: 'LOGNOTE-private', lat: 35.123456, lon: -120.654321, method: 'jig', species: 'lingcod', owner: 'OWNER-private'});
const ENTRIES = [row('e1', 'past-a', 'fish', 3), row('e2', 'past-a', 'blank'), row('e3', 'past-b', 'unknown'), row('e4', null, 'fish', 5), row('e5', 'deleted-trip', 'fish', 7)];

interface Calls {catchLog: number; trips: number; comfort: number; urls: string[]}
const DONE = {'X-SC-Catch-Log-Has-More': 'false'};
const NOT_READ = 'Older catch-log entries were not read. The entries shown may be incomplete.';

/** Session, trips and comfort answered here; `catchLog` answers GET /api/catch-log (the nth call). */
async function stub(page: Page, catchLog: (route: Route, call: number) => Promise<void>, signedIn = true): Promise<Calls> {
  const calls: Calls = {catchLog: 0, trips: 0, comfort: 0, urls: []};
  const trips = [...TRIPS];
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn, user: signedIn ? {display_name: 'Skipper'} : null, publicKey: null}}));
  await page.route('**/api/trips', route => {
    const method = route.request().method();
    if (method === 'DELETE') { const {id} = route.request().postDataJSON() as {id: string}; trips.splice(trips.findIndex(t => t.id === id), 1); return route.fulfill({json: {ok: true}}); }
    calls.trips++;
    return route.fulfill({json: {trips, events: []}});
  });
  await page.route('**/api/comfort', route => {
    if (route.request().method() === 'POST') return route.fulfill({status: 201, json: {ok: true}});
    calls.comfort++;
    return route.fulfill({json: {feedback: [{observed_at: '2020-03-02T20:00:00Z', rating: 8, context: JSON.stringify({phase: 'fishing'})}]}});
  });
  await page.route(/\/api\/catch-log(\?.*)?$/, route => { calls.urls.push(new URL(route.request().url()).search); return catchLog(route, ++calls.catchLog); });
  return calls;
}

/** One last page: the answer's entries and no more pages. */
const answer = (entries: unknown) => async (route: Route) => { await route.fulfill({json: {entries}, headers: DONE}); };

async function openAlerts(page: Page, isMobile: boolean) {
  const trigger = page.locator('.app-account-trigger');
  if (isMobile) {
    await page.locator('.ui-sheet-handle').focus();
    await page.keyboard.press('End');
    await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
    await trigger.scrollIntoViewIfNeeded();
  }
  await trigger.click();
  await page.getByRole('button', {name: 'Saved-trip alerts'}).click();
  return page.getByRole('dialog', {name: 'Trip alerts'});
}


test('catch_log_is_read_once_for_signed_in_recap', async ({page, pageErrors, v2, isMobile}) => {
  const calls = await stub(page, answer(ENTRIES));
  await v2.open('app', AREA);
  const dialog = await openAlerts(page, isMobile);
  const saved = dialog.locator('#saved-trips');
  await expect(saved.locator('article')).toHaveCount(3);
  await expect(saved.locator('li')).toHaveCount(3);
  await expect.poll(() => calls.catchLog).toBe(1);

  // past-a has two entries in the answer's order beside its comfort reports; past-b one; past-c none; the orphan, null and deleted-trip rows nowhere.
  const articles = saved.locator('article');
  await expect(articles.nth(0).locator('li')).toHaveText(['Fish · 3 fish', 'Blank: no fish']);
  await expect(articles.nth(0).locator('h4')).toHaveText(['Your comfort reports', 'Your catch log']);
  await expect(articles.nth(1).locator('li')).toHaveText(['Not sure']);
  await expect(articles.nth(2)).not.toContainText('Your catch log');
  await expect(saved).not.toContainText(/Fish · 5|Fish · 7|LOGNOTE|OWNER|lingcod|35\.12|120\.65/);
  await expect(saved).not.toContainText(NOT_READ);
  await expect(saved).not.toContainText('Reading your catch log');

  // Existing mutations refresh trips and comfort but never the log.
  await dialog.getByRole('button', {name: /^Delete the trip on Sun 1 Mar /}).click();
  await expect(saved.locator('article')).toHaveCount(2);
  await dialog.getByText('How did your boat feel today?').click();
  await dialog.getByRole('button', {name: 'Save private feedback'}).click();
  await expect(dialog.locator('#comfort-status')).not.toHaveText('');
  expect(calls.catchLog, 'one GET per mount, not per trip, rerender, save, delete or comfort refresh').toBe(1);

  // Closing and reopening is a new mount with its own single read.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', {name: 'Trip alerts'})).toHaveCount(0);
  const again = await openAlerts(page, isMobile);
  await expect(again.locator('#saved-trips article')).toHaveCount(2);
  await expect.poll(() => calls.catchLog).toBe(2);
  expect(pageErrors).toEqual([]);
});

test('catch_log_is_not_read_when_signed_out', async ({page, pageErrors, v2, isMobile}) => {
  const calls = await stub(page, answer(ENTRIES), false);
  await v2.open('app', AREA);
  const dialog = await openAlerts(page, isMobile);
  await expect(dialog).toContainText(/sign in/i);
  await page.waitForTimeout(300);
  expect(calls).toEqual({catchLog: 0, trips: 0, comfort: 0, urls: []});
  expect(pageErrors).toEqual([]);
});

test('catch_log_failure_or_delay_does_not_hide_recap', async ({page, pageErrors, v2, isMobile}) => {
  // A pending read leaves the recap usable; the answer then adds the list to the mounted dialog.
  let release: () => void = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  await stub(page, async route => { await gate; await answer(ENTRIES)(route); });
  await v2.open('app', AREA);
  const dialog = await openAlerts(page, isMobile);
  const articles = dialog.locator('#saved-trips article');
  await expect(articles).toHaveCount(3);
  await expect(articles.nth(0)).toContainText('Your comfort reports');
  await expect(articles.nth(0)).not.toContainText('Your catch log');
  await expect(dialog.locator('#saved-trips')).toContainText('Reading your catch log…');
  release();
  await expect(articles.nth(0).locator('li')).toHaveText(['Fish · 3 fish', 'Blank: no fish']);
  await expect(dialog.locator('#saved-trips')).not.toContainText('Reading your catch log');
  expect(pageErrors).toEqual([]);
});

for (const [name, fulfil, incomplete] of [
  ['an error status', (route: Route) => route.fulfill({status: 503, json: {error: 'down'}}), true],
  ['a refused session', (route: Route) => route.fulfill({status: 401, json: {error: 'Sign in'}}), true],
  ['a body that is not JSON', (route: Route) => route.fulfill({status: 200, contentType: 'text/html', body: '<html>'}), true],
  ['a network failure', (route: Route) => route.abort('failed'), true],
  ['entries that are not a list', (route: Route) => route.fulfill({json: {entries: 'nope'}, headers: DONE}), true],
  ['only malformed entries', (route: Route) => route.fulfill({json: {entries: [null, 3, {id: 1}, {id: 'x', trip_id: 'past-a', started_at: 'now', outcome: 'caught', count: 2}]}, headers: DONE}), true],
  ['an answer without the has-more header', (route: Route) => route.fulfill({json: {entries: []}}), true],
  ['an empty last page', (route: Route) => route.fulfill({json: {entries: []}, headers: DONE}), false],
] as const) {
  test(`catch_log_failure_or_delay_does_not_hide_recap: ${name} ${incomplete ? 'says older entries were not read' : 'reads as complete'}`, async ({page, pageErrors, v2, isMobile}) => {
    await stub(page, fulfil);
    await v2.open('app', AREA);
    const dialog = await openAlerts(page, isMobile);
    const articles = dialog.locator('#saved-trips article');
    await expect(articles).toHaveCount(3);
    await expect(articles.nth(0)).toContainText('Your comfort reports');
    await expect(articles.nth(0)).toContainText('No day-before assessment was delivered');
    const saved = dialog.locator('#saved-trips');
    if (incomplete) await expect(saved).toContainText(NOT_READ); else await expect(saved).not.toContainText(NOT_READ);
    await expect(saved).not.toContainText('Reading your catch log');
    expect((await saved.innerText()).split(NOT_READ).length - 1).toBe(incomplete ? 1 : 0);
    // Nothing is claimed about an empty history, and no private field is drawn.
    await expect(saved).not.toContainText(/Your catch log|Fish ·|Blank|Not sure|no catches|nothing logged|LOGNOTE|OWNER|lingcod/i);
    await expect(dialog.getByRole('button', {name: /^Delete the trip on Mon 2 Mar /})).toHaveCount(2);
    expect(pageErrors).toEqual([]);
  });
}

test('catch_log_pages_are_followed_with_the_opaque_cursor_until_the_last_page', async ({page, pageErrors, v2, isMobile}) => {
  const old = {...row('older', 'past-c', 'fish', 4), started_at: '2019-01-01T00:00:00.000Z'};
  const calls = await stub(page, async (route, call) => {
    if (call === 1) return route.fulfill({json: {entries: ENTRIES}, headers: {'X-SC-Catch-Log-Has-More': 'true', 'X-SC-Catch-Log-Next-Cursor': 'tok+/=1'}});
    return route.fulfill({json: {entries: [old]}, headers: DONE});
  });
  await v2.open('app', AREA);
  const dialog = await openAlerts(page, isMobile);
  const articles = dialog.locator('#saved-trips article');
  // past-c's entry started long before its trip and sits past page one: it is shown, and nothing says older entries were not read.
  await expect(articles.nth(2).locator('li')).toHaveText(['Fish · 4 fish']);
  await expect(articles.nth(0).locator('li')).toHaveText(['Fish · 3 fish', 'Blank: no fish']);
  await expect(dialog.locator('#saved-trips')).not.toContainText(NOT_READ);
  expect(calls.urls).toEqual(['', '?cursor=tok%2B%2F%3D1']);
  expect(pageErrors).toEqual([]);
});

test('catch_log_second_page_failure_keeps_page_one_and_says_older_entries_were_not_read', async ({page, pageErrors, v2, isMobile}) => {
  const calls = await stub(page, async (route, call) => {
    if (call === 1) return route.fulfill({json: {entries: ENTRIES}, headers: {'X-SC-Catch-Log-Has-More': 'true', 'X-SC-Catch-Log-Next-Cursor': 'c1'}});
    return route.fulfill({status: 503, json: {error: 'down'}});
  });
  await v2.open('app', AREA);
  const dialog = await openAlerts(page, isMobile);
  const saved = dialog.locator('#saved-trips');
  await expect(saved).toContainText(NOT_READ);
  await expect(saved.locator('article').nth(0).locator('li')).toHaveText(['Fish · 3 fish', 'Blank: no fish']);
  await expect(saved.locator('article').nth(1).locator('li')).toHaveText(['Not sure']);
  expect((await saved.innerText()).split(NOT_READ).length - 1).toBe(1);
  expect(calls.catchLog, 'no third request after the failed page').toBe(2);
  expect(pageErrors).toEqual([]);
});

test('a later dialog does not show an earlier dialog\'s entries, and a late answer after closing changes nothing', async ({page, pageErrors, v2, isMobile}) => {
  let releaseFirst: () => void = () => {};
  const gate = new Promise<void>(resolve => { releaseFirst = resolve; });
  await stub(page, async (route, call) => {
    if (call === 1) { await gate; return route.fulfill({json: {entries: [row('old', 'past-a', 'fish', 9)]}, headers: DONE}); }
    return route.fulfill({json: {entries: [row('new', 'past-a', 'unknown')]}, headers: DONE});
  });
  await v2.open('app', AREA);
  await openAlerts(page, isMobile);
  await expect(page.locator('#saved-trips article')).toHaveCount(3);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', {name: 'Trip alerts'})).toHaveCount(0);
  const again = await openAlerts(page, isMobile);
  await expect(again.locator('#saved-trips article').nth(0).locator('li')).toHaveText(['Not sure']);
  releaseFirst();
  await page.waitForTimeout(300);
  await expect(again.locator('#saved-trips article').nth(0).locator('li')).toHaveText(['Not sure']);
  await expect(again.locator('#saved-trips')).not.toContainText('Fish · 9');
  expect(pageErrors).toEqual([]);
});
