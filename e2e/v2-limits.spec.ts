// Your limits (#542): the trigger beside the profile switch (an icon button in
// the phone's top bar) opens a modal dialog with the active profile's limits,
// keyboard reachable and axe clean; Save keeps them on the device under
// skippercast-limits-v1 and the trigger says they are set; Reset to defaults
// clears them; Escape closes the dialog.
import type {Page} from '@playwright/test';
import {test, expect, checkA11y} from './fixtures.ts';

const SHELL = '/map?region=morro-bay&ui=v2&profile=shore';
const PROFILE_KEY = 'skippercast-profile-v1';
const LIMITS_KEY = 'skippercast-limits-v1';
const withProfile = (page: Page) => page.addInitScript(key => { try { localStorage.setItem(key, 'shore'); } catch { /* storage blocked */ } }, PROFILE_KEY);
const stored = (page: Page) => page.evaluate(key => localStorage.getItem(key), LIMITS_KEY);

test('the limits dialog saves to the device, resets, and is accessible', async ({page, pageErrors}, info) => {
  await withProfile(page);
  await page.goto(SHELL);
  const trigger = page.locator('button.app-limits-trigger');
  await expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
  await trigger.click();
  const dialog = page.locator('dialog.app-limits-dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', {name: 'Your limits · Shore'})).toBeVisible();
  await expect(dialog.getByText('Shore uses the default limits.')).toBeVisible();
  await checkA11y(page, 'v2-limits', info.project.name);
  const wind = dialog.getByLabel(/Highest sustained wind/);
  await wind.fill('6');
  await dialog.getByRole('button', {name: 'Save'}).click();
  await expect(dialog).toBeHidden();
  expect(JSON.parse(await stored(page) ?? '{}')).toEqual({shore: {wind: 6, gust: 12, seas: 3}});
  await expect(trigger).toHaveAttribute('data-own', 'true');
  await trigger.click();
  await expect(dialog.getByText('Shore uses your limits.')).toBeVisible();
  await expect(dialog.getByLabel(/Highest sustained wind/)).toHaveValue('6');
  await dialog.getByRole('button', {name: 'Reset to defaults'}).click();
  await expect(dialog.getByLabel(/Highest sustained wind/)).toHaveValue('8');
  expect(JSON.parse(await stored(page) ?? '{}')).toEqual({});
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  expect(pageErrors).toEqual([]);
});
