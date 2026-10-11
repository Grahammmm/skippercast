// FE-32 (docs/plans/front-end/dev-plan.md, design § 10): the Conditions view
// draws packages/coast chart() through CoastMarkup from the regional forecast.
// The forecast feed is synthetic (values invented, /api/forecast shape) with
// clocks relative to now, and leaves two wind hours out.
// 1. A 2 h hole produces two path segments (also tests/test_conditions_rows.mjs).
// 3. Dragging the chart's cursor moves the store's hour, which the map reads.
// 4. At 390 px the chart scrolls sideways.
// (2, the seven-day horizon against a shorter coast report, is unit-tested.)
import {test, expect} from './fixtures.ts';

const HOUR = 3600;

/** A synthetic Morro Bay /api/forecast answer: hourly series from the current hour for eight days at three points. */
function forecast() {
  const t0 = Math.floor(Date.now() / 1000 / HOUR) * HOUR;
  const time = Array.from({length: 8 * 24}, (_, i) => t0 + i * HOUR);
  const series = (values: Record<string, [number, string]>, hole: number[] = []) => ({
    utc_offset_seconds: 0,
    hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map((_, i) => k === 'wind_speed_10m' && hole.includes(i) ? null : v)]))},
  });
  const points = [['north', 35.45, -121.02], ['central', 35.36, -120.94], ['offshore-1-0', 35.3, -121.25]];
  const meta = {last_run_initialisation_time: t0 - 6 * HOUR, data_end_time: time.at(-1)};
  const model = (values: Record<string, [number, string]>) => ({meta, data: points.map(() => series(values, [10, 11]))});
  const wind = {wind_speed_10m: [8, 'kn'], wind_gusts_10m: [12, 'kn'], temperature_2m: [61, '°F'], cloud_cover: [40, '%']} as Record<string, [number, string]>;
  const wave = {wave_height: [4.2, 'ft'], wave_period: [11, 's']} as Record<string, [number, string]>;
  return {region_id: 'morro-bay', retrieved: Date.now() - 20 * 60_000, requested_points: points,
    models: {gfs_global: model(wind), ncep_gfswave016: model(wave), ecmwf_ifs025: model(wind), ecmwf_wam: model(wave)}};
}

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/api/forecast?*', route => route.fulfill({json: forecast()}));
});

test('acceptance 1, 3 and 4: the chart breaks at the hole, its cursor moves the hour, and it scrolls sideways at 390 px', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', {region: 'morro-bay', view: 'conditions'});
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  const view = page.locator('section.app-conditions');
  await expect(view.getByRole('heading', {name: 'Conditions'})).toBeVisible();
  const chart = view.locator('svg.series-chart');
  await expect(chart).toHaveAttribute('aria-label', /Wind in kt, Gusts in kt, Offshore seas in ft, Air in °F, Cloud in %/);
  await expect(view.locator('.app-conditions-now')).toContainText('8 kt');
  await expect(view.locator('.app-conditions-clocks')).toContainText('NOAA GFS run');
  await expect(view.locator('.app-conditions-caption')).toContainText('local coast report is unavailable here');

  // 1. The wind path (the first row) has two segments.
  const wind = await chart.locator('path').first().getAttribute('d');
  expect((wind?.match(/M/g) ?? []).length).toBe(2);

  // 4. At the phone width the chart region is wider than its box and scrolls.
  const region = view.locator('.app-conditions-chart');
  if (isMobile) {
    const widths = await region.evaluate(el => ({scroll: el.scrollWidth, client: el.clientWidth}));
    expect(widths.scroll).toBeGreaterThan(widths.client);
    await region.evaluate(el => { el.scrollLeft = 200; });
    expect(await region.evaluate(el => el.scrollLeft)).toBeGreaterThan(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await region.evaluate(el => { el.scrollLeft = 0; });
  }

  // 3. A drag on the chart writes ?hour= (the store's hour, which the map stage and the dock read).
  expect(new URL(page.url()).searchParams.get('hour')).toBeNull();
  const box = (await chart.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.3);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.3, {steps: 4});
  await page.mouse.up();
  await expect.poll(() => new URL(page.url()).searchParams.get('hour')).toMatch(/^\d{4}-\d\d-\d\dT\d\d:00Z$/);
  const hour = new URL(page.url()).searchParams.get('hour')!;
  // The drag ended about half way across seven days: some 3 days ahead, never the current hour.
  const ahead = (Date.parse(hour.replace('Z', ':00Z')) - Date.now()) / 3_600_000;
  expect(ahead).toBeGreaterThan(48);
  expect(ahead).toBeLessThan(120);
  await expect(chart.locator('line[stroke-dasharray]')).toHaveCount(1);

  await v2.a11y(isMobile ? 'v2-conditions-sheet' : 'v2-conditions');
  expect(pageErrors).toEqual([]);
});
