// S4-46 (RF1925-6): every rendered app view has exactly one top-level main, also after Chart/2D/3D changes and across the
// 1,024 px breakpoint, and the phone Conditions view exposes one Conditions region. The four axe landmark rules are best
// practices that the WCAG tag set in e2e/wcag-views.spec.ts does not include, so they are switched on explicitly here.
// The terrain is the synthetic fixture (e2e/terrain-keyboard-fixture.ts), never live data.
import AxeBuilder from '@axe-core/playwright';
import type {Page} from '@playwright/test';
import {syntheticTerrain} from './terrain-keyboard-fixture.ts';
import {expect, test} from './fixtures.ts';

const RULES = ['landmark-one-main', 'landmark-main-is-top-level', 'landmark-no-duplicate-main', 'landmark-unique'];
const PLACE = {region: 'morro-bay', profile: 'spear', target: 'rockfish', hour: '2030-01-02T03:00Z'};
const VIEWS = ['coast', 'conditions', 'history', 'fleet', 'reports', 'plan'];
const holdCoastData = (page: Page) => page.route(/\/(?:api\/coast|coast-data)\//, () => { /* never answered */ });
const failCoastData = (page: Page) => page.route(/\/(?:api\/coast|coast-data)\//, route => route.fulfill({status: 503, json: {error: 'Offline map test'}}));
const toggle = (page: Page, name: string) => page.getByRole('group', {name: 'Map presentation'}).getByRole('button', {name, exact: true});

/** Main landmarks across the document and every open shadow root: <main> and [role=main], however deep. */
const mains = (page: Page) => page.evaluate(() => {
  const found: string[] = [];
  const walk = (root: Document | ShadowRoot) => {
    for (const el of root.querySelectorAll('main, [role="main"]')) found.push(`${el.tagName.toLowerCase()}.${el.className}`);
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) walk(el.shadowRoot);
  };
  walk(document);
  return found;
});

/** One main in the composed tree, and none of the four landmark rules broken. */
async function expectOneMain(page: Page, label: string) {
  const found = await mains(page);
  expect(found, `${label}: exactly one main in the composed tree`).toHaveLength(1);
  const results = await new AxeBuilder({page}).withRules(RULES).analyze();
  expect(results.violations.map(v => ({id: v.id, nodes: v.nodes.map(n => n.target.join(' '))})), `${label}: axe landmark rules`).toEqual([]);
}
/** The mounted terrain scene: visible in the host's shadow root, so a failed terrain cannot pass as a presentation change. */
async function expectScene(page: Page, perspective: '2d' | '3d') {
  const host = page.locator('.app-terrain');
  await expect(host).toBeVisible();
  await expect.poll(() => host.evaluate(el => el.shadowRoot?.getElementById('scene')?.dataset.perspective ?? null)).toBe(perspective);
  await expect(host.locator('#scene')).toBeVisible();
}
const noOverflow = async (page: Page) => expect(await page.evaluate(() => document.documentElement.scrollWidth), 'no horizontal page scroll').toBeLessThanOrEqual(page.viewportSize()!.width);

test.beforeEach(async ({page, v2: _v2}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
});

test('composed_tree_presentations: Chart, 2D, 3D and Chart again keep one main and break no landmark rule', async ({page, pageErrors, v2}) => {
  await holdCoastData(page);
  (await syntheticTerrain(page)).release();
  await v2.open('app', {...PLACE, presentation: 'chart'});
  await expect(page.locator('.app-map')).toBeVisible();
  await expectOneMain(page, 'chart');
  await toggle(page, '2D').click();
  await expectScene(page, '2d');
  await expectOneMain(page, '2d');
  await toggle(page, '3D').click();
  await expectScene(page, '3d');
  // The renderer's own scene root is a group, never a second page landmark.
  expect(await page.locator('.app-terrain').evaluate(el => el.shadowRoot?.getElementById('scene')?.getAttribute('role'))).toBe('group');
  await expectOneMain(page, '3d');
  await toggle(page, 'Chart').click();
  await expect(page.locator('.app-terrain')).toBeHidden();
  await expectOneMain(page, 'chart again');
  expect(pageErrors).toEqual([]);
});

test('composed_tree_fallback: a failed terrain still leaves the shell with its one main', async ({page, v2}) => {
  await failCoastData(page);
  await v2.open('app', {...PLACE, presentation: '3d'});
  await expect(page.locator('.app-map')).toBeVisible();
  await expect(toggle(page, 'Chart')).toHaveAttribute('aria-pressed', 'true');
  await expectOneMain(page, 'terrain unavailable');
});

for (const view of VIEWS) {
  test(`one_main_${view}: the view has one top-level main and one region per name`, async ({page, v2}) => {
    await holdCoastData(page);
    await v2.open('app', {...PLACE, presentation: 'chart', ...(view === 'coast' ? {} : {view})});
    await expect(page.locator('h1, h2').first()).toBeVisible();
    await expectOneMain(page, view);
    const phone = page.viewportSize()!.width < 1024;
    if (phone && (view === 'reports' || view === 'plan')) await expect(page.locator('.app-mobile-page')).toHaveCount(1);
    if (phone && view === 'conditions') {
      await expect(page.getByRole('region', {name: 'Conditions', exact: true})).toHaveCount(1);
      await expect(page.getByRole('group', {name: 'Conditions', exact: true})).toHaveCount(1);
    }
  });
}

test('responsive_landmark_handoff: crossing the breakpoint leaves one main and one Conditions region, and the sheet still works', async ({page, v2}) => {
  await holdCoastData(page);
  await v2.open('app', {...PLACE, view: 'conditions', presentation: 'chart'}, 'phone');
  await expect(page.locator('.app-mobile')).toBeVisible();
  await expectOneMain(page, 'phone conditions');
  await expect(page.getByRole('region', {name: 'Conditions', exact: true})).toHaveCount(1);
  await noOverflow(page);

  await page.setViewportSize({width: 1280, height: 800});
  await expect(page.locator('.app-main')).toBeVisible();
  await expect(page.locator('.app-mobile')).toHaveCount(0);
  await expectOneMain(page, 'laptop conditions');
  await expect(page.getByRole('region', {name: 'Conditions', exact: true})).toHaveCount(1);
  await noOverflow(page);

  await page.setViewportSize({width: 390, height: 844});
  await expect(page.locator('.app-mobile')).toBeVisible();
  await expect(page.locator('.app-main')).toHaveCount(0);
  await expectOneMain(page, 'phone again');
  await expect(page.getByRole('region', {name: 'Conditions', exact: true})).toHaveCount(1);

  // Keyboard: the handle still steps the detent, and the tabs still change the view.
  const sheet = page.locator('.ui-sheet');
  const before = await sheet.getAttribute('data-detent');
  await page.locator('.ui-sheet-handle').focus();
  await page.keyboard.press(before === 'full' ? 'Home' : 'End');
  await expect(sheet).not.toHaveAttribute('data-detent', before!);
  await page.locator('.app-tabs [data-view="reports"]').click();
  await expect(page.locator('.app-mobile-page')).toBeVisible();
  await expectOneMain(page, 'phone reports');
  await page.locator('.app-tabs [data-view="conditions"]').click();
  await expect(page.getByRole('region', {name: 'Conditions', exact: true})).toHaveCount(1);
  await expectOneMain(page, 'phone conditions again');
  await noOverflow(page);
});
