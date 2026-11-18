// Synthetic NOAA responses: exercise the actual picker, persistence and port action.
import {test, expect} from './fixtures.ts';

const NOW = '2026-10-08T19:00:00Z';
// Same interval and time for every station, a different height for each, so only the requested station's response can pass.
const heights: Record<string, string> = {'9000001': '1.7', '9000002': '2.9', '9000004': '3.4', '9000005': '4.6'};
const stations = [
  {id: '9000001', name: 'Fixture North', lat: 35.7, lng: -121.1, type: 'S'},
  {id: '9000002', name: 'Fixture Port', lat: 35.36, lng: -120.85, type: 'S'},
  {id: '9000003', name: 'Fixture Outside', lat: 40, lng: -121, type: 'S'},
  {id: '9000004', name: 'Fixture South', lat: 35.2, lng: -121, type: 'S'},
  {id: '9000005', name: 'Fixture Bay', lat: 35.3, lng: -121, type: 'S'},
];

test('tide chooser saves three, switches, removes and restores; active only at 390 px', async ({page, v2, isMobile, pageErrors}) => {
  await page.clock.setFixedTime(new Date(NOW));
  await page.addInitScript(() => { localStorage.setItem('skippercast-profile-v1', 'boat'); localStorage.setItem('skippercast-home-port-v1', 'morro-bay'); });
  await v2.feed('**/feeds/data/regions/morro-bay/latest.json', {schema_version: 1, region_id: 'morro-bay', sources: {
    tides: {id: 'tides', name: 'Configured station', kind: 'prediction', url: 'https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9412110', checked_at: NOW, status: 'ok',
      data: {station: '9412110', predictions: [{time: '2026-10-08T21:00:00Z', height_ft: 4.1, type: 'H'}]}}
  }});
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Fixture unavailable'}}));
  await page.route('**/mdapi/prod/webapi/stations.json?*', route => route.fulfill({json: {stations}}));
  let failPredictions = false;
  const requested: string[] = [];
  await page.route('**/api/prod/datagetter?*', route => {
    const station = new URL(route.request().url()).searchParams.get('station') ?? '';
    requested.push(station);
    return route.fulfill(failPredictions || !heights[station]
      ? {status: 500, json: {error: 'Fixture unavailable'}}
      : {json: {predictions: [{t: '2026-10-08 21:00', v: heights[station], type: 'H'}]}});
  });
  await v2.open('app', {region: 'morro-bay'});
  const root = page.locator(isMobile ? '.app-sheet-brief' : 'aside.app-brief');
  const open = async () => {
    if (isMobile) await page.locator('.ui-sheet-handle').press('End');
    await root.getByRole('button', {name: /^Tide station:/}).click();
  };
  await open();
  const picker = root.getByLabel('Prediction station');
  await expect(picker).toHaveValue('');
  await expect(picker.locator('option')).toHaveCount(5);
  const add = root.getByRole('button', {name: 'Add current station'});
  await picker.selectOption('9000001');
  await add.click();
  const tide = root.locator('.ui-tile', {hasText: 'Tide'});
  await expect(tide.locator('.ui-tile-source')).toContainText('9000001 Fixture North');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000001']);
  expect(requested).toContain('9000001');
  await page.reload();
  await open();
  await expect(picker).toHaveValue('9000001');
  await root.getByRole('button', {name: 'Use nearest to port'}).click();
  await expect(picker).toHaveValue('9000002');
  await expect(tide.locator('.ui-tile-source')).toContainText('9000002 Fixture Port');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000002']);
  const saved = root.getByRole('group', {name: 'Saved tide stations'});
  await picker.selectOption('9000004'); await add.click();
  await expect(saved.getByRole('button', {name: /^Use /})).toHaveCount(3);
  await picker.selectOption('9000005'); await add.click();
  await expect(root.getByRole('status').filter({hasText: /Up to three/})).toBeVisible();
  await expect(root.getByRole('button', {name: 'Retry tide station'})).toHaveCount(0);
  await expect(saved.getByRole('button', {name: /^Use /})).toHaveCount(3);
  await expect(tide.locator('.ui-tile-source')).toContainText('9000004 Fixture South');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000004']);
  await saved.getByRole('button', {name: 'Use Fixture North', exact: true}).click();
  await expect(tide.locator('.ui-tile-source')).toContainText('9000001 Fixture North');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000001']);
  await expect(saved.getByRole('button', {name: 'Use Fixture North', exact: true})).toHaveAttribute('aria-pressed', 'true');
  if (isMobile) expect(page.viewportSize()!.width).toBe(390);
  for (const button of await saved.getByRole('button').all()) {
    await expect(button).toBeVisible();
    const box = (await button.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  }
  await page.reload(); await open();
  await expect(saved.getByRole('button', {name: /^Use /})).toHaveCount(3);
  await expect(picker).toHaveValue('9000001');
  // A saved-list edit or cap refusal must never conceal an active source failure.
  failPredictions = true;
  await saved.getByRole('button', {name: 'Use Fixture North', exact: true}).click();
  const failure = root.getByRole('status').filter({hasText: /Some chosen-station predictions are unavailable/});
  const retry = root.getByRole('button', {name: 'Retry tide station'});
  await expect(failure).toBeVisible(); await expect(retry).toBeVisible();
  await picker.selectOption('9000005'); await add.click();
  const cap = root.getByRole('status').filter({hasText: /Up to three/});
  await expect(cap).toBeVisible(); await expect(failure).toBeVisible();
  await expect(cap.getByRole('button')).toHaveCount(0);
  await saved.getByRole('button', {name: 'Remove Fixture Port', exact: true}).click();
  await expect(cap).toHaveCount(0); await expect(failure).toBeVisible(); await expect(retry).toBeVisible();
  await expect(saved.getByRole('button', {name: 'Use Fixture North', exact: true})).toHaveAttribute('aria-pressed', 'true');
  failPredictions = false;
  await retry.click();
  await expect(failure).toHaveCount(0); await expect(retry).toHaveCount(0);
  await expect(tide.locator('.ui-tile-source')).toContainText('9000001 Fixture North');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000001']);
  await saved.getByRole('button', {name: 'Remove Fixture North', exact: true}).click();
  await expect(picker).toHaveValue('');
  await expect(tide.locator('.ui-tile-source')).toContainText('Configured station');
  await picker.selectOption('9000005'); await add.click();
  await expect(tide.locator('.ui-tile-source')).toContainText('9000005 Fixture Bay');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000005']);
  await picker.selectOption('');
  await expect(tide.locator('.ui-tile-source')).toContainText('Configured station');
  expect(pageErrors).toEqual([]);
});


// An old station's response that finishes last must not replace the requested station's height or attribution.
test('tide height follows the requested station when an earlier response finishes last', async ({page, v2, isMobile, pageErrors}) => {
  await page.clock.setFixedTime(new Date(NOW));
  await page.addInitScript(() => { localStorage.setItem('skippercast-profile-v1', 'boat'); localStorage.setItem('skippercast-home-port-v1', 'morro-bay'); });
  await v2.feed('**/feeds/data/regions/morro-bay/latest.json', {schema_version: 1, region_id: 'morro-bay', sources: {
    tides: {id: 'tides', name: 'Configured station', kind: 'prediction', url: 'https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9412110', checked_at: NOW, status: 'ok',
      data: {station: '9412110', predictions: [{time: '2026-10-08T21:00:00Z', height_ft: 4.1, type: 'H'}]}}
  }});
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Fixture unavailable'}}));
  await page.route('**/mdapi/prod/webapi/stations.json?*', route => route.fulfill({json: {stations}}));
  // Requests for held stations wait here; each is answered only when the test releases it, after every later request has finished.
  const held = new Map<string, Promise<void>>();
  const hold = (station: string) => {
    let release!: () => void;
    held.set(station, new Promise<void>(resolve => { release = resolve; }));
    return {release};
  };
  const arrivals: string[] = [];
  await page.route('**/api/prod/datagetter?*', async route => {
    const station = new URL(route.request().url()).searchParams.get('station') ?? '';
    arrivals.push(station);
    const gate = held.get(station);
    if (gate) { held.delete(station); await gate; }
    await route.fulfill({json: {predictions: [{t: '2026-10-08 21:00', v: heights[station] ?? '0.0', type: 'H'}]}});
  });
  await v2.open('app', {region: 'morro-bay'});
  const root = page.locator(isMobile ? '.app-sheet-brief' : 'aside.app-brief');
  if (isMobile) await page.locator('.ui-sheet-handle').press('End');
  await root.getByRole('button', {name: /^Tide station:/}).click();
  const picker = root.getByLabel('Prediction station');
  const add = root.getByRole('button', {name: 'Add current station'});
  const tide = root.locator('.ui-tile', {hasText: 'Tide'});
  const settle = () => page.evaluate(() => new Promise<void>(resolve => setTimeout(resolve, 250)));

  // Choose North (response held), then Port (answered at once); North answers last.
  const north = hold('9000001');
  await picker.selectOption('9000001'); await add.click();
  await expect.poll(() => arrivals).toContain('9000001');
  await picker.selectOption('9000002'); await add.click();
  await expect(tide.locator('.ui-tile-source')).toContainText('9000002 Fixture Port');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000002']);
  north.release(); await settle();
  await expect(tide.locator('.ui-tile-source')).toContainText('9000002 Fixture Port');
  await expect(tide.locator('.ui-tile-source')).not.toContainText('Fixture North');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000002']);

  // Switching back refetches or reuses North's own value, never Port's.
  const saved = root.getByRole('group', {name: 'Saved tide stations'});
  await saved.getByRole('button', {name: 'Use Fixture North', exact: true}).click();
  await expect(tide.locator('.ui-tile-source')).toContainText('9000001 Fixture North');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000001']);

  // Same race on a switch between saved stations: Port held, North chosen afterwards.
  const port = hold('9000002');
  await saved.getByRole('button', {name: 'Use Fixture Port', exact: true}).click();
  await saved.getByRole('button', {name: 'Use Fixture North', exact: true}).click();
  await expect(tide.locator('.ui-tile-source')).toContainText('9000001 Fixture North');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000001']);
  port.release(); await settle();
  await expect(tide.locator('.ui-tile-source')).toContainText('9000001 Fixture North');
  await expect(tide.locator('.ui-reading')).toHaveText(heights['9000001']);
  expect(pageErrors).toEqual([]);
});
