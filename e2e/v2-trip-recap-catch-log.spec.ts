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

interface Calls {catchLog: number; trips: number; comfort: number}

/** Session, trips and comfort answered here; `catchLog` answers GET /api/catch-log (the nth call). */
async function stub(page: Page, catchLog: (route: Route, call: number) => Promise<void>, signedIn = true): Promise<Calls> {
  const calls: Calls = {catchLog: 0, trips: 0, comfort: 0};
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
  await page.route('**/api/catch-log', route => catchLog(route, ++calls.catchLog));
  return calls;
}

const answer = (entries: unknown) => async (route: Route) => { await route.fulfill({json: {entries}}); };

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

  // Existing mutations refresh trips and comfort but never the log.
  await dialog.getByRole('button', {name: /^Delete the trip on 2020-03-01 /}).click();
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
  expect(calls).toEqual({catchLog: 0, trips: 0, comfort: 0});
  expect(pageErrors).toEqual([]);
});

test('catch_log_failure_or_delay_does_not_hide_recap', async ({page, pageErrors, v2, isMobile}) => {
  // A pending read leaves the recap usable; the answer then adds the list to the mounted dialog.
  let release: () => void = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  await stub(page, async route => { await gate; await route.fulfill({json: {entries: ENTRIES}}); });
  await v2.open('app', AREA);
  const dialog = await openAlerts(page, isMobile);
  const articles = dialog.locator('#saved-trips article');
  await expect(articles).toHaveCount(3);
  await expect(articles.nth(0)).toContainText('Your comfort reports');
  await expect(articles.nth(0)).not.toContainText('Your catch log');
  release();
  await expect(articles.nth(0).locator('li')).toHaveText(['Fish · 3 fish', 'Blank: no fish']);
  expect(pageErrors).toEqual([]);
});

for (const [name, fulfil] of [
  ['an error status', (route: Route) => route.fulfill({status: 503, json: {error: 'down'}})],
  ['a refused session', (route: Route) => route.fulfill({status: 401, json: {error: 'Sign in'}})],
  ['a body that is not JSON', (route: Route) => route.fulfill({status: 200, contentType: 'text/html', body: '<html>'})],
  ['a network failure', (route: Route) => route.abort('failed')],
  ['entries that are not a list', (route: Route) => route.fulfill({json: {entries: 'nope'}})],
  ['only malformed entries', (route: Route) => route.fulfill({json: {entries: [null, 3, {id: 1}, {id: 'x', trip_id: 'past-a', started_at: 'now', outcome: 'caught', count: 2}]}})],
  ['an empty list', (route: Route) => route.fulfill({json: {entries: []}})],
] as const) {
  test(`catch_log_failure_or_delay_does_not_hide_recap: ${name} leaves the recap as before`, async ({page, pageErrors, v2, isMobile}) => {
    await stub(page, fulfil);
    await v2.open('app', AREA);
    const dialog = await openAlerts(page, isMobile);
    const articles = dialog.locator('#saved-trips article');
    await expect(articles).toHaveCount(3);
    await expect(articles.nth(0)).toContainText('Your comfort reports');
    await expect(articles.nth(0)).toContainText('No day-before assessment was delivered');
    await page.waitForTimeout(300);
    await expect(dialog.locator('#saved-trips')).not.toContainText(/catch log|Fish ·|Blank|Not sure/i);
    await expect(dialog.getByRole('button', {name: /^Delete the trip on 2020-03-02 /})).toHaveCount(2);
    expect(pageErrors).toEqual([]);
  });
}

test('a later dialog does not show an earlier dialog\'s entries, and a late answer after closing changes nothing', async ({page, pageErrors, v2, isMobile}) => {
  let releaseFirst: () => void = () => {};
  const gate = new Promise<void>(resolve => { releaseFirst = resolve; });
  await stub(page, async (route, call) => {
    if (call === 1) { await gate; return route.fulfill({json: {entries: [row('old', 'past-a', 'fish', 9)]}}); }
    return route.fulfill({json: {entries: [row('new', 'past-a', 'unknown')]}});
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
