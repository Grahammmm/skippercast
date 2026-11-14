import {test, expect} from './fixtures.ts';
import {snapshot} from '../web/region-coverage.ts';

const browse = 'Browse California regions and coverage';

test('California picker: all regions, honest gaps, drafts stay closed and preview navigation clears old port', async ({page, v2}) => {
  const styles: string[] = [];
  page.on('request', request => { if (/\/assets\/region-picker\.[^/]+\.css$/.test(new URL(request.url()).pathname)) styles.push(request.url()); });
  await v2.open('landing');
  expect(styles, 'picker CSS stays off the cold landing path').toEqual([]);
  await page.getByText(browse, {exact: true}).click();
  const picker = page.getByRole('region', {name: 'California region'});
  await expect.poll(() => styles.length, {message: 'opening the picker loads its stylesheet'}).toBe(1);
  const select = picker.getByLabel('California region', {exact: true});
  await expect(select.locator('option')).toHaveCount(snapshot.regions.length);
  for (const row of snapshot.regions) {
    await select.selectOption(row.id);
    await expect(picker.locator('[data-coverage-region]')).toHaveAttribute('data-coverage-region', row.id);
    await expect(picker.locator('[data-coverage-layer]')).toHaveCount(6);
    await expect(picker.getByRole('button', {name: /Open .*map/})).toBeEnabled({enabled: row.lifecycle !== 'draft'});
  }
  await select.selectOption('santa-cruz-monterey-bay');
  await expect(picker.locator('[data-coverage-layer=habitat]')).toContainText('Held for review');
  await select.selectOption('trinidad-klamath');
  await expect(picker.locator('[data-coverage-layer=basemap]')).toContainText('Overview only');
  await expect(picker.locator('[data-coverage-layer=rules]')).toContainText('Review needed');
  await expect(picker).toContainText('dated snapshot, not live feed health');
  await expect(picker.getByRole('button', {name: 'Open preview map'})).toBeVisible();
  await expect.poll(() => picker.evaluate(el => getComputedStyle(el).display), {message: 'picker stylesheet is applied before measuring layout'}).toBe('grid');
  expect(await picker.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await v2.a11y('scb16-picker');
  if (test.info().project.name === 'phone') {
    await picker.scrollIntoViewIfNeeded();
    await page.screenshot({path: 'test-results/scb16-phone.png', fullPage: true});
  }
  await picker.getByRole('button', {name: 'Open preview map'}).click();
  await expect(page).toHaveURL(/region=trinidad-klamath/);
  expect(new URL(page.url()).searchParams.has('port')).toBe(false);
});

test('map port dialog shares the picker; selection is local until Open and Escape restores focus', async ({page, v2}) => {
  await v2.open('app', {region: 'morro-bay', port: 'morro-bay'});
  if (test.info().project.name === 'phone') await page.locator('.ui-sheet-handle').press('End');
  const trigger = page.getByRole('button', {name: /^(Choose port|Change port \()/}).filter({visible: true});
  await trigger.click();
  const dialog = page.getByRole('dialog', {name: 'Change port'});
  await dialog.getByText(browse, {exact: true}).click();
  await dialog.getByRole('combobox', {name: 'California region', exact: true}).selectOption('san-diego');
  await expect(dialog.getByRole('button', {name: 'Open region map'})).toBeDisabled();
  await expect(page).toHaveURL(/region=morro-bay/);
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test('Spanish picker labels, gaps and draft action are translated', async ({page, v2}) => {
  await v2.open('landing', {lang: 'es'});
  await page.getByText('Ver regiones de California y su cobertura', {exact: true}).click();
  const picker = page.getByRole('region', {name: 'Región de California'});
  await picker.getByLabel('Región de California', {exact: true}).selectOption('santa-cruz-monterey-bay');
  await expect(picker.locator('[data-coverage-layer=habitat]')).toContainText('Retenido para revisión');
  await picker.getByLabel('Región de California', {exact: true}).selectOption('san-diego');
  await expect(picker).toContainText('Borrador · aún no disponible');
  await expect(picker.getByRole('button', {name: 'Abrir mapa regional'})).toBeDisabled();
});
