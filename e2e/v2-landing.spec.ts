// The v2 entry flow behind ?ui=v2 (FE-08, docs/plans/front-end/dev-plan.md):
// /map with no area opens the saved port or the landing; the command bar's
// port chooser matches by name and Enter navigates in place, saving the port
// under the key v1 reads; a refused location leaves a message with the input
// focused; the first-run profile choice shows once and never with ?profile=
// in the address. FE-07 adds the landing's own input to this file.
import {test, expect, checkA11y} from './fixtures.ts';

const SHELL = '/map?region=morro-bay&ui=v2';
const PORT_KEY = 'skippercast-home-port-v1';
const stay = (page: Parameters<typeof checkA11y>[0]) => page.evaluate(() => { (window as unknown as {__v2: number}).__v2 = 1; });
const stayed = (page: Parameters<typeof checkA11y>[0]) => page.evaluate(() => (window as unknown as {__v2?: number}).__v2 === 1);

test('/map with no area opens the landing without a saved port, and the saved port with one', async ({page, context, pageErrors}) => {
  await page.goto('/map?ui=v2');
  await expect(page).toHaveURL(/\/\?ui=v2$/);
  await expect(page.locator('h1')).toContainText('Know the water');
  await context.addInitScript(key => { try { localStorage.setItem(key, 'san-diego'); } catch { /* storage blocked */ } }, PORT_KEY);
  await page.goto('/map?ui=v2');
  await expect(page).toHaveURL(/\/map\?[^#]*region=southern-california/);
  await expect(page).toHaveURL(/[?&]ui=v2/);
  await expect(page.locator('header.app-masthead .app-location')).toContainText(/Southern California/i);
  expect(pageErrors).toEqual([]);
});

test('the port chooser matches by name, Enter navigates in place, and v1 reads the saved port', async ({page, pageErrors}, info) => {
  await page.goto(SHELL);
  await stay(page);
  await page.locator('.app-port').click();
  const dialog = page.locator('dialog.port-dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[data-port]')).toHaveCount(6);   // the featured ports before a query
  await checkA11y(page, 'v2-port-chooser', info.project.name);
  const input = dialog.locator('input[type="search"]');
  await expect(input).toBeFocused();
  await input.fill('san d');
  await expect(dialog.locator('[data-port]')).toHaveText([/San Diego/]);
  await input.press('Enter');
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/[?&]region=southern-california/);
  await expect(page).toHaveURL(/[?&]ui=v2/);
  await expect(page).toHaveURL(/[?&]profile=boat/);   // the choice carries the profile (§ 7)
  expect(await stayed(page), 'no reload').toBe(true);
  expect(await page.evaluate(key => localStorage.getItem(key), PORT_KEY)).toBe('san-diego');
  await expect(page.locator('.app-port')).toContainText('San Diego');
  // v1 (shared key): a bare visit opens the port v2 saved instead of its chooser.
  await page.goto('/?ui=v1');
  await expect(page).toHaveURL(/[?&]region=southern-california/);
  await expect(page.locator('.home-port-card')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('a refused location leaves a message and the input focused; Explore the coast opens the central coast', async ({page, context, pageErrors}) => {
  // The browser refuses: the error callback fires with PERMISSION_DENIED (a pending prompt would hang the test).
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'geolocation', {value: {getCurrentPosition: (_ok: unknown, fail: (e: {code: number; message: string}) => void) => fail({code: 1, message: 'denied'})}});
  });
  await page.goto(SHELL);
  await page.locator('button[aria-label="Use my location"]').click();
  const dialog = page.locator('dialog.port-dialog');
  await expect(dialog.locator('[role="status"]')).toHaveText('Location was unavailable. Search for a port instead.');
  await expect(dialog.locator('input[type="search"]')).toBeFocused();
  await expect(dialog).toContainText('Your choice stays in this browser.');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await page.locator('.app-port').click();
  await dialog.getByRole('button', {name: 'Explore the coast'}).click();
  await expect(page).toHaveURL(/[?&]coast=central/);
  await expect(page).not.toHaveURL(/region=/);
  expect(pageErrors).toEqual([]);
});

test('first run asks for the profile once and never when the address names one', async ({page, pageErrors}) => {
  await page.goto(SHELL);
  const card = page.locator('.app-firstrun');
  await expect(card).toBeVisible();
  await expect(card).not.toHaveAttribute('aria-modal', 'true');
  await expect(page.locator('aside.app-brief')).toBeVisible();   // the map and brief are never blocked
  await card.locator('button[data-profile="shore"]').click();
  await expect(card).toHaveCount(0);
  await expect(page).toHaveURL(/[?&]profile=shore/);
  await expect(page.locator('[aria-label="Profile"] button[aria-pressed="true"]')).toHaveText('Shore');
  await page.goto(SHELL);
  await expect(page.locator('aside.app-brief')).toBeVisible();
  await expect(card).toHaveCount(0);
  await expect(page.locator('[aria-label="Profile"] button[aria-pressed="true"]')).toHaveText('Shore', {timeout: 5_000});
  await page.evaluate(() => localStorage.clear());
  await page.goto(SHELL + '&profile=boat');
  await expect(page.locator('aside.app-brief')).toBeVisible();
  await expect(card).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});
