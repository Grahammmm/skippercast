// Spot sheet answer → badge → why (P4-04): the confidence badges open their
// one-line "why" by tap, click and keyboard and close by tap, a tap elsewhere
// and Escape (which must not close the sheet); the limitations that used to
// sit above the spot's name are inside the badges; the sheet shows at most
// 60 words above the fold; axe is clean with a why open.
import {test, expect, openMap, checkA11y} from './fixtures.ts';
import type {Page} from '@playwright/test';

/** Words of visible text in the spot sheet that start above the bottom of the viewport. */
async function wordsAboveFold(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const sheet = document.getElementById('spot-dialog')!;
    const limit = Math.min(innerHeight, sheet.getBoundingClientRect().bottom);
    const words: string[] = [];
    const walker = document.createTreeWalker(sheet, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.parentElement?.checkVisibility()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const rect = range.getBoundingClientRect();
      if (rect.height === 0 || rect.top >= limit) continue;
      words.push(...(node.textContent || '').split(/\s+/).filter(word => /[\p{L}\p{N}]/u.test(word)));
    }
    return words;
  });
}

const ORDER = ['Depth', 'Terrain', 'Fish'];
/** One of the spot sheet's badges (depth, terrain, fish, in that order). */
function badgeFor(page: Page, label: string) {
  return page.locator('#spot-confidence .confidence-badge').nth(ORDER.indexOf(label));
}

/** Open the spot sheet for the first single-target marker and wait for its seabed view. */
async function openSpot(page: Page, path: string): Promise<void> {
  await openMap(page, path);
  await page.locator('#map .leaflet-marker-icon[title*="grade"]').first().click();
  await expect(page.locator('#spot-dialog')).toBeVisible();
  const buttons = page.locator('#spot-confidence .confidence-badge-button');
  await expect(buttons).toHaveCount(3);
  for (const [i, label] of ORDER.entries()) await expect(buttons.nth(i)).toContainText(label);
  await expect(page.locator('#detail .bottom-view')).not.toContainText('Loading survey');
}

test('the spot sheet leads with the answer and keeps limitations in the badges', async ({page, pageErrors}, info) => {
  await openSpot(page, '/?region=morro-bay#map');
  const words = await wordsAboveFold(page);
  console.log(`[${info.project.name}] spot sheet above the fold: ${words.length} words`);
  expect(words.length).toBeLessThanOrEqual(60);

  // Name first, then the answer line, then the badges.
  const order = await page.evaluate(() => ['.detail-top h2', '.spot-answer', '#spot-confidence']
    .map(s => document.querySelector(`#detail ${s}`)!.getBoundingClientRect().top));
  expect(order).toEqual([...order].sort((a, b) => a - b));

  // The research-only paragraph is in the depth badge's why, not above the name.
  await expect(page.locator('#detail > .evidence-note')).toHaveCount(0);
  const depth = badgeFor(page, 'Depth');
  await expect(depth.locator('button')).toContainText('Estimated');
  await expect(depth.locator('.confidence-why')).toBeHidden();
  await expect(depth.locator('.confidence-why')).toContainText('Research-only location.');
  await expect(depth.locator('.confidence-why')).toContainText('The displayed depths are not chart depths');
  // Research-only targets never read as verified; fish presence is never better than unknown.
  await expect(page.locator('#spot-confidence')).not.toContainText('Verified');
  await expect(badgeFor(page, 'Fish').locator('button')).toContainText('Unknown');
  await expect(page.locator('#spot-confidence [title]')).toHaveCount(0);
  await expect(page.locator('#spot-confidence .freshness-pill')).toHaveText(/^Buoy (\d+ min ago|stale \d+ (min|h|d)|unavailable|update unavailable|check source time)$/);
  expect(pageErrors).toEqual([]);
});

test('a confidence badge opens and closes by tap or click', async ({page, pageErrors}, info) => {
  await openSpot(page, '/?region=morro-bay#map');
  const badge = badgeFor(page, 'Terrain');
  const button = badge.locator('button');
  const why = badge.locator('.confidence-why');
  const press = () => info.project.name === 'phone' ? button.tap() : button.click();
  await expect(button).toHaveAttribute('aria-expanded', 'false');
  await press();
  await expect(button).toHaveAttribute('aria-expanded', 'true');
  await expect(why).toBeVisible();
  await expect(why).toContainText('Terrain interpretation confidence:');
  await checkA11y(page, 'spot-badge-open', info.project.name);
  await press();
  await expect(why).toBeHidden();
  // A tap elsewhere in the sheet closes it too.
  await press();
  await expect(why).toBeVisible();
  const heading = page.locator('#detail .detail-top h2');
  if (info.project.name === 'phone') await heading.tap(); else await heading.click();
  await expect(why).toBeHidden();
  await expect(page.locator('#spot-dialog')).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test('a confidence badge opens by keyboard and Escape closes only the why', async ({page, pageErrors}) => {
  await openSpot(page, '/?region=morro-bay#map');
  const badge = badgeFor(page, 'Fish');
  const button = badge.locator('button');
  const why = badge.locator('.confidence-why');
  await button.focus();
  await page.keyboard.press('Enter');
  await expect(why).toBeVisible();
  await expect(why).toContainText('Fish presence is unverified');
  await expect(why.locator('a[href="#charter-evidence"]')).toHaveText('See the AIS research coverage.');
  await page.keyboard.press('Escape');
  await expect(why).toBeHidden();
  await expect(button).toBeFocused();
  await expect(page.locator('#spot-dialog')).toBeVisible();
  await page.keyboard.press('Space');
  await expect(why).toBeVisible();
  await page.keyboard.press('Space');
  await expect(why).toBeHidden();
  // With no why open, Escape closes the sheet as before.
  await page.keyboard.press('Escape');
  await expect(page.locator('#spot-dialog')).toBeHidden();
  expect(pageErrors).toEqual([]);
});

test('a depth-qualified survey target shows verified depth, and the rest stay unverified', async ({page, pageErrors}) => {
  await openSpot(page, '/?region=southern-california&target=reef&view=34.01483,-119.44687,14#map');
  const depth = badgeFor(page, 'Depth');
  await expect(depth.locator('button')).toContainText('Verified');
  await depth.locator('button').click();
  await expect(depth.locator('.confidence-why')).toContainText('Chart-datum depth screen');
  await expect(badgeFor(page, 'Terrain').locator('button')).toContainText('Estimated');
  await expect(badgeFor(page, 'Fish').locator('button')).toContainText('Unknown');
  expect(pageErrors).toEqual([]);
});
