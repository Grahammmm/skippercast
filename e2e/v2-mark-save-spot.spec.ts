// SC0022-05: "Save this spot" on the map mark card, in a real browser, offline. The session, the protected-area
// answer and /api/spots are stubs; the mark is the committed atlas mark SC26-001 opened from ?spot=. Checks the
// actual card: shown to a signed-in person only, keyboard activation, a live status, the refusal in words with no
// write, the cap message and a deliberate retry, and that nothing about the spot reaches the address, a link,
// storage or any other request (the private sentinels below appear only in the one authorized POST answer).
import {readFile} from 'node:fs/promises';
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';
import {stubLiveFeeds} from '../scripts/measure_startup.mjs';

const MARK = {id: 'SC26-001', name: 'Southern rocky rise', latitude: 35.164314, longitude: -120.843179};
const AREA = {region: 'morro-bay', presentation: 'chart', profile: 'boat', target: 'lingcod', spot: MARK.id, view: '35.164314,-120.843179,14'};
const OWNER = 'OWNER-SENTINEL-7f3a', ROW_ID = 'ROW-SENTINEL-91c2', RAW = 'RAW-SERVER-TEXT-55d0';
const SIGNED_IN = {signIn: '/#account', signedIn: true, user: {display_name: 'Skipper'}, publicKey: null};
const SIGNED_OUT = {signIn: '/#account', signedIn: false};

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
});

/** Stubs the session and the spots route; returns what the page sent. `answers` are used in order, the last one repeating. */
async function stubAccount(page: Page, session: unknown, answers: Array<{status: number; body: unknown}> = []) {
  const spots: Array<{method: string; body: Record<string, unknown>}> = [], others: Array<{url: string; body: string}> = [];
  await page.route('**/api/session', route => route.fulfill({json: session}));
  await page.route('**/api/spots', async route => {
    const request = route.request(), body = request.postDataJSON() as Record<string, unknown>;
    spots.push({method: request.method(), body});
    const answer = answers[Math.min(spots.length - 1, answers.length - 1)] ?? {status: 201, body: {id: ROW_ID, owner: OWNER, ...body, created_at: '2026-11-04T00:00:00Z'}};
    await route.fulfill({status: answer.status, json: typeof answer.body === 'function' ? (answer.body as (b: unknown) => unknown)(body) : answer.body});
  });
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path !== '/api/spots' && request.method() !== 'GET') others.push({url: request.url(), body: request.postData() ?? ''});
  });
  return {spots, others};
}

async function openCard(page: Page, v2: {open: (name: 'app', params?: Record<string, string>) => Promise<void>}) {
  await v2.open('app', AREA);
  const card = page.getByRole('region', {name: 'Selected mark'});
  await expect(card.getByRole('heading')).toHaveText(MARK.name);
  return card;
}

/** Nothing the spot's save wrote or linked: the address, links, storage, other writes. */
async function expectNoTrace(page: Page, before: {url: string; storage: string; history: number}, others: Array<{url: string; body: string}>) {
  // The map may still settle its own camera (?view=) after the card opened; every other part of the address is untouched, and no history entry was added.
  const address = (href: string) => { const u = new URL(href); u.searchParams.delete('view'); return u.href; };
  expect(address(page.url()), 'the address is unchanged').toBe(address(before.url));
  expect(await page.evaluate(() => history.length), 'no history entry').toBe(before.history);
  const after = await page.evaluate(() => ({links: [...document.querySelectorAll('a')].map(a => a.getAttribute('href') ?? ''), storage: JSON.stringify([{...localStorage}, {...sessionStorage}])}));
  expect(after.storage, 'no storage write').toBe(before.storage);
  for (const secret of [OWNER, ROW_ID, RAW]) {
    expect(after.links.some(href => href.includes(secret)), `no link carries ${secret}`).toBe(false);
    expect(page.url()).not.toContain(secret);
    expect(JSON.stringify(others).includes(secret), `no other request carries ${secret}`).toBe(false);
    expect(after.storage.includes(secret)).toBe(false);
  }
  for (const request of others) expect(`${request.url} ${request.body}`).not.toMatch(/Southern rocky rise|35\.1643|120\.8431/);
}

test('signed out: the mark card offers no way to save a spot', async ({page, pageErrors, v2}) => {
  await stubLiveFeeds(page);
  const account = await stubAccount(page, SIGNED_OUT);
  const card = await openCard(page, v2);
  await expect(card.getByRole('button', {name: 'GPX', exact: true})).toBeVisible();
  await expect(card.getByRole('button', {name: 'Save this spot'})).toHaveCount(0);
  await expect(card).not.toContainText('Private to your account');
  expect(account.spots).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('save_spot_preserves_address_and_privacy: a keyboard save posts the mark once, says so, and leaves no trace', async ({page, pageErrors, v2}) => {
  await stubLiveFeeds(page);
  const account = await stubAccount(page, SIGNED_IN);
  const card = await openCard(page, v2);
  const save = card.getByRole('button', {name: 'Save this spot'});
  await expect(save).toBeEnabled();
  await expect(card).toContainText('Private to your account. You can keep up to 100 saved spots.');
  const before = {url: page.url(), storage: await page.evaluate(() => JSON.stringify([{...localStorage}, {...sessionStorage}])), history: await page.evaluate(() => history.length)};
  await save.focus();
  await page.keyboard.press('Enter');
  await expect(card.getByRole('button', {name: 'Saved to your spots'})).toBeDisabled();
  expect(account.spots).toHaveLength(1);
  expect(account.spots[0]!.method).toBe('POST');
  expect(Object.keys(account.spots[0]!.body).sort()).toEqual(['lat', 'lon', 'name', 'note']);
  expect(account.spots[0]!.body.name).toBe(MARK.name);
  expect(account.spots[0]!.body.note).toBeNull();
  expect(Math.abs(Number(account.spots[0]!.body.lat) - MARK.latitude)).toBeLessThan(1e-4);
  expect(Math.abs(Number(account.spots[0]!.body.lon) - MARK.longitude)).toBeLessThan(1e-4);
  // A second press on the confirmed card writes nothing more.
  // The click is dispatched on the button itself: at phone peek the card's button rests under the tab bar, where a coordinate click (even forced)
  // lands on the History tab and pushes a history entry that this test is not about.
  await card.getByRole('button', {name: 'Saved to your spots'}).dispatchEvent('click').catch(() => undefined);
  await page.waitForTimeout(300);
  expect(account.spots).toHaveLength(1);
  await expectNoTrace(page, before, account.others);
  expect(pageErrors).toEqual([]);
});

test('the cap and a failed save are said in words, nothing raw shows, and a retry is the person\'s own tap', async ({page, pageErrors, v2}) => {
  await stubLiveFeeds(page);
  const account = await stubAccount(page, SIGNED_IN, [
    {status: 400, body: {error: 'you can keep at most 100 saved spots; remove one first'}},
    {status: 500, body: {error: RAW}},
    {status: 201, body: (b: unknown) => ({id: ROW_ID, owner: OWNER, ...(b as object), created_at: '2026-11-04T00:00:00Z'})},
  ]);
  const card = await openCard(page, v2);
  const before = {url: page.url(), storage: await page.evaluate(() => JSON.stringify([{...localStorage}, {...sessionStorage}])), history: await page.evaluate(() => history.length)};
  const save = card.getByRole('button', {name: 'Save this spot'}), status = card.locator('.app-mark-why').getByRole('status');
  await save.click();
  await expect(status).toHaveText('You can keep up to 100 saved spots. Remove one in Account before saving another.');
  await expect(save).toBeEnabled();
  expect(account.spots).toHaveLength(1);
  await save.click();
  await expect(status).toHaveText('Could not confirm this spot was saved. Check Saved spots in Account before trying again.');
  await expect(card).not.toContainText(RAW);
  expect(account.spots).toHaveLength(2);
  await page.waitForTimeout(400);
  expect(account.spots, 'a failure is never retried by itself').toHaveLength(2);
  await save.click();
  await expect(card.getByRole('button', {name: 'Saved to your spots'})).toBeDisabled();
  expect(account.spots).toHaveLength(3);
  await expectNoTrace(page, before, account.others);
  expect(pageErrors).toEqual([]);
});

test('a place the shared screen refuses is not saved and the card says why', async ({page, pageErrors, v2}) => {
  await stubLiveFeeds(page);
  // The live protected-area answer now holds a synthetic area around the mark: the card's own screen withholds it, so it cannot be saved.
  const committed = JSON.parse(await readFile('dist/data/protected-areas.geojson', 'utf8')), d = 0.01;
  const x = MARK.longitude, y = MARK.latitude;
  committed.features.push({type: 'Feature', properties: {NAME: 'Synthetic Test SMR', FULLNAME: 'Synthetic Test State Marine Reserve', Type: 'SMR', CCR: 'Section 632(b)'},
    geometry: {type: 'Polygon', coordinates: [[[x - d, y - d], [x + d, y - d], [x + d, y + d], [x - d, y + d], [x - d, y - d]]]}});
  await page.route(url => url.hostname === 'services2.arcgis.com', route => route.fulfill({json: committed}));
  const account = await stubAccount(page, SIGNED_IN);
  await v2.open('app', AREA);
  const card = page.getByRole('region', {name: 'Selected mark'});
  await expect(card.getByRole('heading')).toHaveText('Reef mark withheld');
  const save = card.getByRole('button', {name: 'Save this spot'});
  await expect(save).toBeDisabled();
  await expect(card.getByRole('status')).toContainText('Not saved.');
  await expect(card).not.toContainText(String(MARK.latitude));
  await save.click({force: true}).catch(() => undefined);
  await page.waitForTimeout(300);
  expect(account.spots).toEqual([]);
  expect(pageErrors).toEqual([]);
});
