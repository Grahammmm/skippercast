// The Text Advisor web chat (TA-C3, docs/plans/text-advisor/08-website.md § Web chat)
// on dist/chat.html: open the panel, send a message, see the reply
// the engine gives without ANTHROPIC_API_KEY (the warm-up text, TA-E1), and run axe on the open panel.
// e2e/serve.mjs sets TEXT_ADVISOR_ENABLED=true for these runs only.
import {test, expect, checkA11y} from './fixtures.ts';

const WARM_UP = 'SkipperCast is warming up. Check back soon.';   // server/advisor/consumer.ts WARM_UP_TEXT

test('the web chat opens, sends a message and shows the reply', async ({page, context, pageErrors}, info) => {
  await page.goto('/chat.html');
  await expect(page.locator('h1')).toHaveText('Text SkipperCast');
  const panel = page.getByRole('region', {name: 'Chat with SkipperCast'});
  await expect(panel).toBeVisible();

  // Collapse and reopen: the state is the only thing kept in localStorage.
  await panel.getByRole('button', {name: 'Close chat'}).click();
  const launcher = page.getByRole('button', {name: 'Text SkipperCast'});
  await expect(launcher).toBeVisible();
  await expect(launcher).toBeFocused();
  expect(await page.evaluate(() => localStorage.getItem('skippercast-chat-open'))).toBe('0');
  await launcher.click();
  await expect(panel).toBeVisible();

  const input = panel.getByRole('textbox', {name: 'Message'});
  await input.fill('Where are the rockfish biting?');
  const answered = page.waitForResponse(r => r.url().endsWith('/api/advisor/web/message') && r.request().method() === 'POST');
  await panel.getByRole('button', {name: 'Send'}).click();
  const response = await answered;
  expect(response.status()).toBe(200);
  await expect(panel.locator('.chat-line.is-you').last()).toContainText('Where are the rockfish biting?');
  await expect(panel.locator('.chat-line.is-skippercast').last()).toContainText(WARM_UP);
  await expect(input).toHaveValue('');

  // Identity is the HttpOnly cookie, not storage.
  const cookie = (await context.cookies()).find(c => c.name === 'sc_adv');
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe('Lax');
  const stored = await page.evaluate(() => Object.keys(localStorage));
  expect(stored.filter(k => !['skippercast-first-run-v1', 'skippercast-chat-open'].includes(k))).toEqual([]);

  // Enter sends too, and the same cookie is reused.
  await input.fill('And lingcod?');
  await input.press('Enter');
  await expect(panel.locator('.chat-line.is-skippercast')).toHaveCount(3);
  expect((await context.cookies()).filter(c => c.name === 'sc_adv').map(c => c.value)).toEqual([cookie!.value]);

  await expect(panel.getByRole('link', {name: 'Save the number'})).toHaveAttribute('href', '/contact.vcf');
  await expect(panel.getByRole('link', {name: 'Text us'})).toHaveAttribute('href', '/text?s=web');
  await checkA11y(page, 'advisor-chat', info.project.name);
  expect(pageErrors).toEqual([]);
});
