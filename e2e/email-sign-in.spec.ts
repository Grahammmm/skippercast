// Email sign-in in a real browser against the built Worker: ask for a link in the
// account sheet, open it, land signed in with the token gone from the address
// bar, and see the address on the account. `wrangler dev` runs with
// MAIL_TRANSPORT=log (e2e/serve.mjs), so the link is read from the Worker log.
import {readFile} from 'node:fs/promises';
import {test, expect, openMap, checkA11y} from './fixtures.ts';

const LOG = new URL('../test-results/worker.log', import.meta.url);
async function linkFor(email: string): Promise<string> {
  let link = '';
  await expect.poll(async () => {
    const log = await readFile(LOG, 'utf8').catch(() => '');
    const at = log.lastIndexOf(`to ${email}:`);
    link = at < 0 ? '' : (log.slice(at).match(/http:\/\/localhost:\d+\/#email-sign-in=[\w-]{43}/)?.[0] ?? '');
    return link;
  }, {timeout: 15_000}).not.toBe('');
  return link;
}

test('an emailed link signs in, once, and the address shows on the account', async ({page, pageErrors}, info) => {
  const email = `e2e-${info.project.name}-${Date.now()}@example.com`;
  await openMap(page, '/?region=morro-bay#guide');
  await page.locator('#account-entry').click();
  const input = page.locator('#account-email');
  await expect(input).toBeVisible();
  await checkA11y(page, 'account-email', info.project.name);
  await input.fill(email);
  await page.locator('#account-email-send').click();
  await expect(page.locator('#account-status')).toHaveText(`Check ${email} for a sign-in link. It works once, for 15 minutes.`);

  const link = await linkFor(email);
  await page.goto(link);
  // The page posts the token, reloads signed in and returns to the guide.
  await expect.poll(async () => (await (await page.request.get('/api/session')).json()).signedIn, {timeout: 30_000}).toBe(true);
  await expect(page).toHaveURL(/#guide$/);
  await expect(page.locator('#account-entry span')).toHaveText('Signed in');
  await page.locator('#account-entry').click();
  await expect(page.locator('.account-card')).toContainText(email);
  await expect(page.locator('#account-email-remove')).toBeVisible();
  await checkA11y(page, 'account-signed-in-email', info.project.name);

  // The same link again is refused, without a token left in the address.
  await page.locator('#account-signout').click();
  await expect.poll(async () => (await (await page.request.get('/api/session')).json()).signedIn).toBe(false);
  await page.goto(link);
  await expect(page.locator('#account-status')).toHaveText('This link has expired or was already used; ask for a new one.');
  expect(page.url()).not.toContain('email-sign-in');
  expect(pageErrors).toEqual([]);
});
