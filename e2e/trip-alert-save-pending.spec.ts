// SCP3-11: Save in the trip-alerts dialog (web/app/TripAlerts.tsx) sends one POST while the first is unresolved, so a
// double tap cannot create two pending alerts. The API is stubbed and the first POST is held: no account, no real alert.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const SAVE = 'Save this fishing window';

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
});

/** Signed in, trips stubbed: each POST waits for `replies` to hand it a status (or 0 to answer at once with 201). */
async function stubTrips(page: Page) {
  const posts: unknown[] = [], waiting: ((status: number) => void)[] = [];
  await page.route('**/api/session', route => route.fulfill({json: {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null}}));
  await page.route('**/api/trips', async route => {
    if (route.request().method() !== 'POST') return route.fulfill({json: {trips: [], events: []}});
    posts.push(route.request().postDataJSON());
    const status = await new Promise<number>(resolve => { waiting.push(resolve); });
    return route.fulfill(status === 201 ? {status, json: {id: 't' + posts.length}} : {status, json: {error: 'Too many active alerts.'}});
  });
  return {posts, answer: async (status: number) => { await expect.poll(() => waiting.length).toBeGreaterThan(0); waiting.shift()!(status); }};
}

async function openAlerts(page: Page, v2: {open: (...a: any[]) => Promise<unknown>}, isMobile: boolean) {
  await v2.open('app', {region: 'morro-bay'});
  if (isMobile) {
    await page.locator('.ui-sheet-handle').focus();
    await page.keyboard.press('End');
    await page.locator('.app-account-trigger').scrollIntoViewIfNeeded();
  }
  await page.locator('.app-account-trigger').click();
  await page.getByRole('button', {name: 'Saved-trip alerts'}).click();
  const dialog = page.getByRole('dialog', {name: 'Trip alerts'});
  await expect(dialog.getByRole('button', {name: SAVE})).toBeEnabled();
  return dialog;
}
const doubleSubmit = (page: Page) => page.evaluate(() => { const f = document.querySelector<HTMLFormElement>('#save-alert')!; f.requestSubmit(); f.requestSubmit(); });

test('a double submit while the first save is waiting sends one POST, disables Save, and a later save sends a new one', async ({page, pageErrors, v2, isMobile}) => {
  const api = await stubTrips(page);
  const dialog = await openAlerts(page, v2, isMobile);
  await doubleSubmit(page);
  await expect(dialog.getByRole('button', {name: SAVE})).toBeDisabled();
  await expect.poll(() => api.posts.length).toBe(1);
  await page.waitForTimeout(300);
  expect(api.posts).toHaveLength(1);
  await api.answer(201);
  await expect(dialog.locator('#alert-status')).toContainText('Trip saved.');
  await expect(dialog.getByRole('button', {name: SAVE})).toBeEnabled();
  await dialog.getByRole('button', {name: SAVE}).click();
  await expect.poll(() => api.posts.length).toBe(2);
  await api.answer(201);
  await expect(dialog.getByRole('button', {name: SAVE})).toBeEnabled();
  expect(pageErrors).toEqual([]);
});

test('a rejected save shows the server error, clears pending and a retry sends again', async ({page, pageErrors, v2, isMobile}) => {
  const api = await stubTrips(page);
  const dialog = await openAlerts(page, v2, isMobile);
  await doubleSubmit(page);
  await expect.poll(() => api.posts.length).toBe(1);
  await api.answer(400);
  await expect(dialog.locator('#alert-status')).toHaveText('Too many active alerts.');
  await expect(dialog.getByRole('button', {name: SAVE})).toBeEnabled();
  await dialog.getByRole('button', {name: SAVE}).click();
  await expect.poll(() => api.posts.length).toBe(2);
  await api.answer(201);
  await expect(dialog.locator('#alert-status')).toContainText('Trip saved.');
  expect(pageErrors).toEqual([]);
});

test('an invalid form sends no POST and Save does not stay pending', async ({page, pageErrors, v2, isMobile}) => {
  const api = await stubTrips(page);
  const dialog = await openAlerts(page, v2, isMobile);
  await dialog.getByLabel('From', {exact: false}).first().fill('12');
  await dialog.getByLabel('Until', {exact: false}).first().fill('8');
  await dialog.getByRole('button', {name: SAVE}).click();
  await expect(dialog.locator('#alert-status')).not.toBeEmpty();
  await expect(dialog.getByRole('button', {name: SAVE})).toBeEnabled();
  expect(api.posts).toHaveLength(0);
  await dialog.getByLabel('Until', {exact: false}).first().fill('14');
  await dialog.getByRole('button', {name: SAVE}).click();
  await expect.poll(() => api.posts.length).toBe(1);
  await api.answer(201);
  expect(pageErrors).toEqual([]);
});
