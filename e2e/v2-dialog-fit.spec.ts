import type {Locator, Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';
import {stubLiveFeeds} from '../scripts/measure_startup.mjs';

const sizes = [{width: 360, height: 640}, {width: 390, height: 844}, {width: 844, height: 390}];

// DOM rectangles never scroll a target into view (unlike click/fill/focus).
async function fits(dialog: Locator, actions?: Locator) {
  const geometry = await dialog.evaluate(el => {
    const r = el.getBoundingClientRect();
    return {left: r.left, top: r.top, right: r.right, bottom: r.bottom,
      width: innerWidth, height: innerHeight, horizontal: el.scrollWidth - el.clientWidth};
  });
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.top).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(geometry.width);
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.height);
  expect(geometry.horizontal).toBeLessThanOrEqual(1);
  for (const action of await actions?.all() ?? []) {
    await expect(action).toBeEnabled();
    expect(await action.evaluate(el => {
      const r = el.getBoundingClientRect(), d = el.closest('dialog')!, b = d.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.left >= Math.max(0, b.left + d.clientLeft) &&
        r.right <= Math.min(innerWidth, b.left + d.clientLeft + d.clientWidth) &&
        r.top >= Math.max(0, b.top + d.clientTop) && r.bottom <= Math.min(innerHeight, b.top + d.clientTop + d.clientHeight);
    }), 'full enabled action rectangle inside viewport and dialog scrollport').toBe(true);
  }
}

async function account(page: Page, name: RegExp | string) {
  await page.locator('.ui-sheet-handle').focus();
  await page.keyboard.press('End');
  await page.locator('.app-account-trigger').click();
  await page.locator('.app-account-panel').getByRole('button', {name}).click();
}

async function scrollChecks(dialog: Locator, actions: Locator, last: Locator) {
  for (const fraction of [0, 0.5, 1]) {
    await dialog.evaluate((el, f) => { el.scrollTop = f * (el.scrollHeight - el.clientHeight); }, fraction);
    await fits(dialog, actions);
  }
  await last.scrollIntoViewIfNeeded();
  await fits(dialog, last);
  expect(await actions.first().evaluate(el => getComputedStyle(el.parentElement!).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)');
}

for (const size of sizes) {
  test(`dialogs_fit_phone_and_landscape_without_action_autoscroll ${size.width}x${size.height}`, async ({page, v2, pageErrors}) => {
    await page.setViewportSize(size);
    await page.addInitScript(() => localStorage.setItem('skippercast-profile-v1', 'boat'));
    await stubLiveFeeds(page);
    await v2.open('app', {region: 'morro-bay', profile: 'boat'});
    await page.locator('.app-limits-trigger').click();
    const limits = page.locator('dialog.app-limits-dialog').first();
    await expect(limits).toBeVisible();
    const buttons = limits.locator('.app-limits-actions button');
    await fits(limits, buttons);
    await scrollChecks(limits, buttons, limits.locator('input').last());
    await page.keyboard.press('Escape');
    await expect(limits).toBeHidden();
    await expect(page.locator('.app-limits-trigger')).toBeFocused();
    await page.locator('.app-limits-trigger').click();
    await fits(limits, buttons);
    await limits.getByRole('button', {name: 'Reset to defaults'}).click();
    await limits.getByRole('button', {name: 'Save', exact: true}).click();
    await expect(limits).toBeHidden();

    await v2.open('app', {region: 'morro-bay', profile: 'boat'});
    // Trigger positioning is outside this dialog-only regression; dispatch does not scroll the dialog.
    await page.locator('button.app-port').dispatchEvent('click');
    const port = page.locator('dialog.port-dialog');
    await expect(port).toBeVisible();
    await fits(port, port.locator('.port-input-option').first());
    await page.keyboard.press('Escape');
    await expect(port).toBeHidden();

    await account(page, /^Trip plan and GPX/);
    const trip = page.locator('dialog.app-trip');
    await expect(trip).toBeVisible();
    await fits(trip);
    await page.keyboard.press('Escape');
    await expect(trip).toBeHidden();

    await account(page, 'Save for offline');
    const offline = page.getByRole('dialog', {name: 'Save for offline'});
    await expect(offline).toBeVisible();
    const save = offline.locator('.app-offline-actions .ui-button--primary');
    await expect(save).toHaveCount(1);
    await fits(offline, save);
    await page.keyboard.press('Escape');
    await expect(offline).toBeHidden();
    expect(pageErrors).toEqual([]);
  });
}

for (const profile of ['boat', 'spear']) {
  test(`dialog_scroll_keeps_actions_and_content_reachable ${profile} light`, async ({page, v2}) => {
    await page.setViewportSize({width: 844, height: 390});
    await page.addInitScript(p => {
      localStorage.setItem('skippercast-profile-v1', p);
      localStorage.setItem('skippercast-limits-v1', JSON.stringify({spear: {from: 'shore'}}));
    }, profile);
    await stubLiveFeeds(page);
    await v2.open('app', {region: 'morro-bay', profile});
    await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });
    await page.locator('.app-limits-trigger').click();
    const limits = page.locator('dialog.app-limits-dialog').first();
    await expect(limits).toBeVisible();
    await fits(limits, limits.locator('.app-limits-actions button'));
    await scrollChecks(limits, limits.locator('.app-limits-actions button'), limits.locator('input').last());
    await page.keyboard.press('Escape');
    await page.evaluate(async () => {
      for (let i = 0; i < 12; i++) {
        const cache = await caches.open(`sc-pack-fixture-${i}`);
        await cache.put('/__skippercast-pack.json', new Response(JSON.stringify({schema_version: 1,
          region_name: `Synthetic saved region ${i}`, region_id: 'morro-bay', saved_at: '2026-01-01T00:00:00Z',
          bytes: 100, missing: [], tiles: {saved: 0, planned: 0, max_zoom: null}})));
      }
    });
    await account(page, 'Save for offline');
    const offline = page.getByRole('dialog', {name: 'Save for offline'});
    const save = offline.getByRole('button', {name: /^Save Morro Bay/});
    await expect(offline.locator('.app-offline-list > li')).toHaveCount(12);
    await fits(offline, save);
    await offline.evaluate(el => { el.scrollTop = (el.scrollHeight - el.clientHeight) / 2; });
    await fits(offline, save);
    await offline.locator('.app-offline-list > li').last().getByRole('button').scrollIntoViewIfNeeded();
    await fits(offline, offline.locator('.app-offline-list > li').last().getByRole('button'));
    await expect(save).toBeEnabled();
    await save.scrollIntoViewIfNeeded();
    await fits(offline, save);
    await page.keyboard.press('Escape');
    await account(page, 'Save for offline');
    await fits(offline, save);
  });
}
