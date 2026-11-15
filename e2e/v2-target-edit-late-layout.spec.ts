// E2E-TARGET-EDIT-1: the sheet can keep growing after the last viewport, focus or scroll event
// (late page data on a slow phone). The edited field must be revealed again, not left under the clip edge.
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';

const AREA = {region: 'morro-bay', profile: 'boat', target: 'lingcod'};
test.beforeEach(async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('skippercast-profile-v1', 'boat'));
});

const inside = (page: Page) => page.locator('.app-sheet .app-target-search').evaluate(el => {
  const r = el.getBoundingClientRect(), body = el.closest('.ui-sheet-body')!, b = body.getBoundingClientRect();
  return r.height > 0 && r.top >= Math.max(0, b.top + body.clientTop)
    && r.bottom <= Math.min(innerHeight, b.top + body.clientTop + body.clientHeight);
});

test('late growth of the sheet header and content re-reveals the edited field', async ({page, v2, isMobile}) => {
  test.skip(!isMobile, 'phone visual viewport');
  await page.setViewportSize({width: 390, height: 844});
  await v2.open('app', AREA);
  const sheet = page.locator('.app-sheet'), search = sheet.locator('.app-target-search');
  await page.locator('.ui-sheet-handle').press('End');
  await search.focus();
  // Synthetic visual-only keyboard shrink, as in v2-target-edit-layout.spec.ts.
  await page.evaluate(() => {
    const viewport = window.visualViewport!;
    Object.defineProperty(viewport, 'height', {configurable: true, value: 220});
    Object.defineProperty(viewport, 'offsetTop', {configurable: true, value: 40});
    viewport.dispatchEvent(new Event('resize'));
  });
  await expect.poll(() => inside(page)).toBe(true);
  // Grow the header a little (the app's own late header growth still has to fit) and the content above
  // the field a lot, with no viewport, focus or scroll event. The growth pushes the field out of the clip box.
  const pushedOut = await search.evaluate(el => {
    const grow = (parent: Element, before: Node | null, height: number) => {
      const block = document.createElement('div');
      block.style.cssText = `height:${height}px;flex:none`;
      parent.insertBefore(block, before);
    };
    const body = el.closest('.ui-sheet-body')!, content = [...body.children].find(c => c.contains(el))!;
    grow(el.closest('.ui-sheet')!.querySelector('.ui-sheet-edge')!, null, 8);
    grow(content, content.firstChild, 300);
    const r = el.getBoundingClientRect(), b = body.getBoundingClientRect();
    return r.bottom > b.top + body.clientTop + body.clientHeight || r.top < b.top + body.clientTop;
  });
  expect(pushedOut).toBe(true);
  await expect.poll(() => inside(page)).toBe(true);
  await expect(search).toBeFocused();
});
