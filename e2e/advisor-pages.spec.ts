// The Text Advisor's public pages (TA-W1, docs/plans/text-advisor/08-website.md
// § Public pages): the port, species and boat pages render from D1 in the real
// Worker, the chat island mounts closed on them, and axe finds nothing serious.
// D1 holds e2e/seed/advisor-pages.sql, which e2e/serve.mjs loads before the
// Worker starts (TEXT_ADVISOR_ENABLED=true for these runs only).
import {test, expect, checkA11y} from './fixtures.ts';

test('the port page shows the reports, the boats and the seasons, with the chat closed', async ({page, pageErrors}, info) => {
  expect((await page.goto('/ports/morro-bay'))?.status()).toBe(200);
  await expect(page.locator('h1')).toHaveText('Morro Bay fishing report');
  const reports = page.getByRole('region', {name: 'Skipper reports, last 14 days'});
  await expect(reports.getByRole('link', {name: 'Rita G'})).toHaveAttribute('href', '/boats/e2e-rita-g');
  await expect(reports).toContainText('45 vermilion, 12 lingcod (2 released)');
  await expect(reports).toContainText('Another boat');
  await expect(reports).not.toContainText('Sea Wolf');
  const seasons = page.getByRole('region', {name: 'Species and seasons'});
  await expect(seasons.getByRole('listitem').filter({hasText: 'Lingcod'})).toContainText('Open today');
  await expect(seasons.getByRole('listitem').filter({hasText: 'Rockfish'})).toContainText('Under review');
  await expect(page.getByRole('contentinfo')).toContainText('Planning aid · not a navigation chart.');
  await expect(page.getByRole('button', {name: 'Text SkipperCast'})).toBeVisible();   // the chat island, closed
  await checkA11y(page, 'advisor-port', info.project.name);
  expect(pageErrors).toEqual([]);
});

test('the species page shows the cues, the rules card and recent catches', async ({page, pageErrors}, info) => {
  expect((await page.goto('/species/lingcod'))?.status()).toBe(200);
  await expect(page.locator('h1')).toHaveText('Lingcod');
  await expect(page.getByRole('region', {name: 'How to tell it apart'})).toContainText('huge head and mouth');
  const rules = page.locator('#rules');
  await expect(rules).toContainText('Minimum size');
  await expect(rules.getByRole('link', {name: 'CDFW Ocean Sport Fishing Regulations'})).toHaveAttribute('href', 'https://wildlife.ca.gov/Fishing/Ocean/Regulations');
  await expect(page.getByRole('region', {name: 'Recent catches, last 14 days'})).toContainText('Morro Bay');
  await checkA11y(page, 'advisor-species', info.project.name);

  await page.goto('/species/rockfish?lang=es');
  await expect(page.locator('html')).toHaveAttribute('lang', 'es');
  await expect(page.locator('#rules')).toContainText('En revisión');
  await checkA11y(page, 'advisor-species-es', info.project.name);
  expect(pageErrors).toEqual([]);
});

test('the boat page shows the verified badge, the reports and the booking link; a pending boat says so', async ({page, pageErrors}, info) => {
  expect((await page.goto('/boats/e2e-rita-g'))?.status()).toBe(200);
  await expect(page.locator('h1')).toHaveText('Rita G');
  await expect(page.getByText('Verified boat')).toBeVisible();
  await expect(page.getByRole('region', {name: 'Reports, last 30 days'})).toContainText('edited');
  await expect(page.getByRole('link', {name: 'Booking page'})).toHaveAttribute('href', 'https://example.com/book');
  await checkA11y(page, 'advisor-boat', info.project.name);

  await page.goto('/boats/e2e-sea-wolf');
  await expect(page.getByText('Not verified yet')).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex');
  const missing = await page.goto('/boats/no-such-boat');
  expect(missing?.status()).toBe(404);
  expect(pageErrors).toEqual([]);
});
