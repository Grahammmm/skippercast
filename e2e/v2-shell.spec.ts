// The v2 app shell behind ?ui=v2 (FE-05, docs/plans/front-end/dev-plan.md):
// at laptop width the brief column is 332 px beside a map stage that fills
// the rest; view links, the profile switch, the rail and the dock write the
// address without a reload; every control is reachable by keyboard; no
// horizontal page scroll at any viewport preset; axe is clean; the page
// paints within the LCP budget on the throttled mobile profile (FE-09,
// design § 13). FE-06 adds the sheet and tab layout for the phone project.
import {test, expect, VIEWPORTS, LCP_BUDGET_MS} from './fixtures.ts';

const AREA = {region: 'morro-bay'};

test('the shell lays out the brief beside the map at every viewport preset and axe is clean', async ({page, pageErrors, v2}) => {
  await v2.open('app', AREA);
  await expect(page.locator('header.app-masthead .app-location')).toContainText('Morro Bay');
  await expect(page.locator('.ui-tile .ui-reading')).toHaveText(['—', '—', '—', '—']);
  await v2.a11y('v2-shell');
  for (const [name, viewport] of Object.entries(VIEWPORTS)) {
    await v2.open('app', AREA, name as keyof typeof VIEWPORTS);
    const brief = page.locator('aside.app-brief'), stage = page.locator('section.app-stage');
    await expect(brief).toBeVisible();
    await expect(stage).toBeVisible();
    const [b, s] = [await brief.boundingBox(), await stage.boundingBox()];
    if (viewport.width >= 1024) {
      expect(Math.round(b!.width), name).toBe(332);
      expect(Math.round(s!.x), name).toBe(Math.round(b!.x + b!.width));
      expect(Math.round(s!.x + s!.width), name).toBe(viewport.width);
    } else {
      expect(Math.round(b!.width), name).toBe(viewport.width);
    }
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth, `${name}: no horizontal page scroll`).toBeLessThanOrEqual(viewport.width);
  }
  expect(pageErrors).toEqual([]);
});

test('view links, the profile switch, the rail and the dock update the address without a reload', async ({page, pageErrors, v2}) => {
  await v2.open('app', AREA);
  await page.evaluate(() => { (window as unknown as {__v2: number}).__v2 = 1; });
  const stillLoaded = () => page.evaluate(() => (window as unknown as {__v2?: number}).__v2 === 1);
  await page.locator('nav[aria-label="Views"] a[data-view="conditions"]').click();
  await expect(page).toHaveURL(/[?&]view=conditions/);
  await expect(page.locator('a[data-view="conditions"]')).toHaveAttribute('aria-current', 'page');
  await page.locator('[aria-label="Profile"] button', {hasText: 'Spear'}).click();
  await expect(page).toHaveURL(/[?&]profile=spear/);
  await expect(page.locator('.app-caveat')).toContainText('In-water visibility is unverified');
  await page.locator('.ui-rail-toggle', {hasText: 'Clouds'}).click();
  await expect(page).toHaveURL(/[?&]layers=[^&]*clouds/);
  await expect(page.locator('.app-legend')).toContainText(/Clouds|No layers/);
  const slider = page.locator('input[aria-label="Hour"]');
  await slider.focus();
  await page.keyboard.press('End');
  await expect(page).toHaveURL(/[?&]hour=\d{4}-\d{2}-\d{2}T\d{2}%3A00Z/);
  await expect(page.locator('.ui-dock-readout')).toHaveText('11 pm');
  expect(await stillLoaded(), 'no reload').toBe(true);
  // A shared link restores the same choices.
  const shared = page.url();
  await page.goto('about:blank');
  await page.goto(shared);
  await expect(page.locator('[aria-label="Profile"] button[aria-pressed="true"]')).toHaveText('Spear');
  await expect(page.locator('.ui-dock-readout')).toHaveText('11 pm');
  expect(pageErrors).toEqual([]);
});

test('keyboard reaches every control', async ({page, pageErrors, v2}) => {
  await v2.open('app', AREA);
  const wanted = ['nav[aria-label="Views"] a[data-view="fleet"]', '[aria-label="Profile"] button:last-child', 'label:has-text("Target") select', 'label:has-text("Area") select',
    '.ui-rail-item:last-child .ui-rail-toggle', 'input[aria-label="Hour"]', 'button[aria-label="Play"]'];
  const reached = new Set<string>();
  for (let i = 0; i < 60 && reached.size < wanted.length; i++) {
    await page.keyboard.press('Tab');
    for (const selector of wanted) if (!reached.has(selector) && await page.locator(selector).evaluate(el => el === document.activeElement)) reached.add(selector);
  }
  expect([...reached].sort()).toEqual([...wanted].sort());
  expect(pageErrors).toEqual([]);
});

test('the shell paints within the LCP budget on the throttled mobile profile', async ({pageErrors, v2}, info) => {
  test.skip(info.project.name !== 'phone', 'measured once, at phone size');
  const lcp = await v2.lcp('app', AREA);
  console.log(`v2 app shell LCP ${Math.round(lcp)} ms (budget ${LCP_BUDGET_MS}, design § 13)`);
  expect(lcp, 'Largest Contentful Paint recorded').toBeGreaterThan(0);
  expect(lcp).toBeLessThanOrEqual(LCP_BUDGET_MS);
  expect(pageErrors).toEqual([]);
});
