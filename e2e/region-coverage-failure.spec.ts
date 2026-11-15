import {test, expect} from './fixtures.ts';

// The normal picker flow lives in region-coverage.spec.ts; this is the failed cold-load path.
test('coverage code loads only on request and a failed cold load leaves the port chooser usable', async ({page, v2}) => {
  let reads = 0;
  await page.route('**/assets/RegionPicker.*.js', route => { reads++; return route.abort('failed'); });
  await v2.open('landing');
  expect(reads).toBe(0);
  await page.getByText('Browse California regions and coverage', {exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Coverage could not load.'})).toBeVisible();
  // With lazy CSS, Vite preloads the module before importing it; an aborted
  // preload can be followed by the import request. Neither is a UI retry loop.
  expect(reads).toBeGreaterThan(0);
  expect(reads).toBeLessThanOrEqual(2);
  await expect(page.getByRole('searchbox', {name: 'Where are you launching?'})).toBeEnabled();
  await expect(page.getByRole('button', {name: 'Explore the coast', exact: true})).toBeEnabled();
  await page.getByText('Browse California regions and coverage', {exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Coverage could not load.'})).toHaveCount(0);
});
