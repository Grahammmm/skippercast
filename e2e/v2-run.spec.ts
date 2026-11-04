// Roadmap P2: the Boat brief's fishing time and return (web/brief/Run.tsx).
// The feeds are synthetic (values invented) with the page's clock pinned at
// 5 am in Morro Bay, so the day's lower-exposure window opens at daylight.
// 1. With no cruise speed on the device the line asks for one, and its button
//    opens the Boat limits form at the cruise speed field (axe clean).
// 2. Saving a speed keeps it on the device and the line shows fishing time,
//    the turn-back time and the run, at both widths.
// 3. Shore has no run line.
import {test, expect, checkA11y} from './fixtures.ts';

const HOUR = 3_600_000;
const CRUISE_KEY = 'skippercast-cruise-v1';

/** 5 am in Morro Bay on the Pacific date of `now`. */
function pacificFive(now: number): number {
  const day = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit'}).format(now);
  const hour = (ms: number) => Number(new Intl.DateTimeFormat('en-US', {timeZone: 'America/Los_Angeles', hour: 'numeric', hourCycle: 'h23'}).format(ms));
  return ['-07:00', '-08:00'].map(offset => Date.parse(`${day}T05:00:00${offset}`)).find(ms => hour(ms) === 5)!;
}
const BASE = pacificFive(Date.now());
const iso = (offsetMs: number) => new Date(BASE + offsetMs).toISOString();

/** A quiet synthetic daily feed: a fresh buoy, tide events and a fresh, empty marine alert check. */
function feed() {
  const checked = iso(-10 * 60_000);
  return {
    schema_version: 1, generated_at: checked, region_id: 'morro-bay', landing_names: ['Morro Bay', 'Avila'], reports: [],
    sources: {
      'buoy-46011': {id: 'buoy-46011', name: 'NOAA NDBC 46011 observations', kind: 'observation', url: 'https://www.ndbc.noaa.gov/station_page.php?station=46011',
        checked_at: checked, max_age_hours: 6, status: 'ok', data: {station: '46011', observations: [{time: iso(-HOUR), WSPD: 3, GST: 5, WVHT: 0.8, DPD: 11, MWD: 295, WTMP: 14.5}]}},
      tides: {id: 'tides', name: 'NOAA CO-OPS 9412110 predictions', kind: 'prediction', url: 'https://tidesandcurrents.noaa.gov/stationhome.html?id=9412110',
        checked_at: checked, max_age_hours: 36, status: 'ok', data: {station: '9412110', datum: 'MLLW', predictions: [{time: iso(2 * HOUR), height_ft: 4.1, type: 'H'}, {time: iso(8 * HOUR), height_ft: 0.6, type: 'L'}]}},
      'nws-alerts': {id: 'nws-alerts', name: 'NWS marine alerts', kind: 'advisory', url: 'https://api.weather.gov/alerts/active?zone=PZZ670', checked_at: checked, status: 'ok', data: {alerts: []}},
    },
  };
}

/** A calm synthetic /api/forecast answer from two hours before the clock, eight days long, issued three hours before it. */
function forecast() {
  const t0 = (BASE - 2 * HOUR) / 1000;
  const time = Array.from({length: 8 * 24}, (_, i) => t0 + i * 3600);
  const series = (values: Record<string, [number, string]>) => ({utc_offset_seconds: 0,
    hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
  const points = [['north', 35.45, -121.02], ['central', 35.36, -120.94], ['offshore-1-0', 35.3, -121.25]];
  const meta = {last_run_initialisation_time: (BASE - 3 * HOUR) / 1000, data_end_time: time.at(-1)};
  const model = (values: Record<string, [number, string]>) => ({meta, data: points.map(() => series(values))});
  const wind = {wind_speed_10m: [6, 'kn'], wind_gusts_10m: [9, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [20, '%']} as Record<string, [number, string]>;
  const wave = {wave_height: [2.5, 'ft'], wave_period: [11, 's']} as Record<string, [number, string]>;
  return {region_id: 'morro-bay', retrieved: BASE - 20 * 60_000, requested_points: points,
    models: {gfs_global: model(wind), ncep_gfswave016: model(wave), ecmwf_ifs025: model(wind), ecmwf_wam: model(wave)}};
}

test.beforeEach(async ({page, v2}) => {
  await page.clock.setFixedTime(BASE);
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/api/forecast?*', route => route.fulfill({json: forecast()}));
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
  await v2.feed('**/feeds/data/regions/morro-bay/latest.json', feed());
});

test('acceptance 1 and 2: the line asks for a cruise speed, saves it on the device, then shows fishing time and the return', async ({page, pageErrors, v2, isMobile}, info) => {
  await v2.open('app', {region: 'morro-bay'});
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  const root = page.locator(isMobile ? '.app-sheet-brief' : 'aside.app-brief');
  const run = root.locator('.app-run');
  await expect(run).toHaveAttribute('data-state', 'no-speed');
  await expect(run).toContainText('Set your cruise speed to see run time and when to turn back.');
  await run.getByRole('button', {name: 'Set cruise speed'}).click();
  const dialog = page.locator('dialog.app-limits-dialog[open]');
  await expect(dialog.getByRole('heading', {name: 'Your limits · Boat'})).toBeVisible();
  const speed = dialog.getByLabel(/Cruise speed/);
  await expect(speed).toBeFocused();
  await expect(speed).toHaveValue('');
  await checkA11y(page, 'v2-run', info.project.name);
  await speed.fill('20');
  await dialog.getByRole('button', {name: 'Save'}).click();
  await expect(page.locator('dialog.app-limits-dialog[open]')).toHaveCount(0);
  expect(JSON.parse(await page.evaluate(key => localStorage.getItem(key), CRUISE_KEY) ?? '{}')).toEqual({knots: 20});
  await expect(run).toHaveAttribute('data-state', 'ok');
  await expect(run.locator('.app-run-lead')).toContainText(/Up to \d+ h( \d+ min)? fishing at /);
  await expect(run.locator('.app-run-times')).toContainText(/Leave \d+(:\d\d)? am · there \d+(:\d\d)? am · turn back \d+(:\d\d)? (am|pm) · in by \d+(:\d\d)? (am|pm)/);
  // FSC-05: Morro Bay's land/water product routes the top pick over water, so the run reads "by water", not the straight-line fallback.
  await expect(run.locator('.app-run-detail')).toContainText(/\d+\.\d nm by water · at least \d+ min each way at 20 kt/);
  await expect(run.locator('.app-run-detail')).not.toContainText('nm straight line');
  await run.scrollIntoViewIfNeeded();
  await info.attach(`run-${info.project.name}`, {body: await page.screenshot(), contentType: 'image/png'});
  expect(pageErrors).toEqual([]);
});

test('acceptance 3: Shore has no run line', async ({page, pageErrors, v2}) => {
  await v2.open('app', {region: 'morro-bay', profile: 'shore'});
  await expect(page.locator('h1').first()).not.toHaveText('Waiting for readings.');
  await expect(page.locator('.app-run')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});


test('wanted hours focus, shortfall, cross-tab reload and selected-target closure', async ({page, v2, isMobile}, info) => {
  const {readFileSync} = await import('node:fs');
  const fixture = JSON.parse(readFileSync('tests/fixtures/regulations/fe61-v1.json', 'utf8'));
  const d = fixture.regulations;
  d.reviewed_at = new Date(BASE).toISOString(); d.rules_review_status = 'reviewed';
  d.valid_from = '2026-01-01'; d.valid_through = '2030-12-31';
  for (const [id, source] of Object.entries(d.sources) as [string, any][]) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: source.approved_content_sha256, data_retrieved_at: d.reviewed_at};
  }
  for (const id of ['lingcod', 'rockfish']) d.species[id].windows = [{start: '2026-01-01', end: '2030-12-31'}];
  d.species.rockfish.windows = [];
  await page.route('**/regulations.json', route => route.fulfill({json: d}));
  await page.addInitScript(() => localStorage.setItem('skippercast-cruise-v1', '{"knots":20}'));
  await v2.open('app', {region: 'morro-bay', target: 'lingcod'});
  if (isMobile) await page.locator('.ui-sheet-handle').press('End');
  const run = page.locator(isMobile ? '.app-sheet-brief .app-run' : 'aside.app-brief .app-run');
  await run.getByRole('button', {name: 'Set hours I want'}).click();
  const dialog = page.locator('dialog.app-limits-dialog[open]'), wanted = dialog.getByLabel('Hours I want to fish');
  await expect(wanted).toBeFocused(); await expect(wanted).toHaveValue('');
  await wanted.fill('4'); await dialog.getByRole('button', {name: 'Save'}).click();
  await expect(run.locator('.app-run-hours')).toContainText('4 h wanted');
  await page.evaluate(() => { localStorage.setItem('skippercast-fishhours-v1', '{"hours":10}'); window.dispatchEvent(new StorageEvent('storage', {key: 'skippercast-fishhours-v1'})); });
  await expect(run.locator('.app-run-hours')).toContainText(/short/);
  await checkA11y(page, 'v2-fishing-hours', info.project.name);
  await v2.open('app', {region: 'morro-bay', target: 'rockfish'});
  if (isMobile) await page.locator('.ui-sheet-handle').press('End');
  await expect(run.locator('.app-run-hours')).toContainText('is closed that day');
  await expect(run.locator('.app-run-hours')).not.toContainText('available');
});
