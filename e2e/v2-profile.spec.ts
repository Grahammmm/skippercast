// Profiles applied across the app (FE-30, docs/plans/front-end/dev-plan.md; design § 8): the
// Boat / Shore / Spear switch changes the Chart's reef marks, the target menu (shared by the
// Chart and the terrain) and the terrain's species and depth limit; the link's ?profile= and
// Fish's ?mode= win over the stored profile. The coast data bridge is held open, so the terrain
// mounts and waits; marks come from the committed Morro Bay atlas.
import {readFileSync} from 'node:fs';
import type {Page} from '@playwright/test';
import {expect, test} from './fixtures.ts';

const TINY = readFileSync(new URL('../tests/fixtures/basemap/tiny.pmtiles', import.meta.url));
const ARCHIVE = 'tiles/basemap/ca-coast-fixture.pmtiles';
const VIEW = '35.164314,-120.843179,12';

test.beforeEach(async ({page, v2: _v2}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/feeds/tiles/basemap/manifest.json', route => route.fulfill({json: {schema_version: 1, key: ARCHIVE}}));
  await page.route(`**/feeds/${ARCHIVE}`, route => {
    const range = /bytes=(\d+)-(\d+)/.exec(route.request().headers().range ?? '');
    if (!range) return route.fulfill({body: TINY, headers: {'Accept-Ranges': 'bytes'}});
    const start = Number(range[1]), end = Math.min(Number(range[2]), TINY.length - 1);
    return route.fulfill({status: 206, body: TINY.subarray(start, end + 1),
      headers: {'Content-Range': `bytes ${start}-${end}/${TINY.length}`, 'Accept-Ranges': 'bytes', 'Content-Type': 'application/octet-stream'}});
  });
  await page.route(/\/(?:api\/coast|coast-data)\//, () => { /* never answered */ });
});

const profileChip = (page: Page, name: string) => page.locator('[aria-label="Profile"] button', {hasText: name});
const params = (page: Page) => Object.fromEntries(new URL(page.url()).searchParams);
/** The target menu's values in order; on a phone it sits at the end of the brief sheet. */
async function targets(page: Page): Promise<string[]> {
  const select = page.locator('label:has-text("Target") select');
  return select.locator('option').evaluateAll(options => options.map(o => (o as HTMLOptionElement).value));
}
const marks = async (page: Page) => Number(await page.locator('.app-chart').getAttribute('data-marks'));

test('Shore hides reef marks and lists surfperch first on the Chart and in the terrain; Spear keeps marks within 60 ft', async ({page, pageErrors, v2}) => {
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', target: 'lingcod', view: VIEW});
  const chart = page.locator('.app-chart');
  await expect(chart).toHaveAttribute('data-marks', /^[1-9]\d*$/);
  const boat = await marks(page);

  await profileChip(page, 'Shore').click();
  await expect.poll(() => params(page).profile).toBe('shore');
  expect(params(page).target, 'the switch drops the boat target').toBeUndefined();
  await expect(chart).toHaveAttribute('data-marks', '0');
  await expect.poll(() => targets(page)).toEqual(expect.arrayContaining(['surfperch']));
  expect((await targets(page))[0]).toBe('surfperch');

  await page.getByRole('group', {name: 'Map presentation'}).getByRole('button', {name: '3D', exact: true}).click();
  await expect(page.locator('.app-terrain')).toBeVisible();
  expect((await targets(page))[0], 'the one menu serves the terrain too').toBe('surfperch');
  await page.getByRole('group', {name: 'Map presentation'}).getByRole('button', {name: 'Chart', exact: true}).click();

  // Spear with the same reef target: only marks whose nearby depths stay within 60 ft.
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', profile: 'spear', target: 'lingcod', view: VIEW});
  await expect(chart).toHaveAttribute('data-marks', /^\d+$/);
  await expect.poll(() => marks(page)).toBeLessThan(boat);
  await expect(page.locator('label:has-text("Target") select'), 'the link\'s target stays chosen').toHaveValue('lingcod');
  expect(pageErrors).toEqual([]);
});

test('?profile= and Fish ?mode= win over the stored profile; an unsupported target stays explicit', async ({page, pageErrors, v2}) => {
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', mode: 'shore'});
  await expect(profileChip(page, 'Shore')).toHaveAttribute('aria-pressed', 'true');
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', profile: 'spear', mode: 'shore'});
  await expect(profileChip(page, 'Spear')).toHaveAttribute('aria-pressed', 'true');
  await v2.open('app', {region: 'morro-bay', presentation: 'chart', profile: 'shore', target: 'yellowtail'});
  await expect.poll(() => targets(page)).toEqual(['yellowtail', 'surfperch', 'halibut']);
  await expect(page.locator('label:has-text("Target") select')).toHaveValue('yellowtail');
  expect(params(page).target).toBe('yellowtail');
  expect(pageErrors).toEqual([]);
});
