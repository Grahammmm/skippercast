// FE-37 (docs/plans/front-end/dev-plan.md, design § 10): the brief column
// and the mobile sheet render the FE-31 model from the region's daily feed.
// The feed is synthetic (values invented) with clocks relative to now: the
// buoy reading is five hours old, past the water tile's 3 h limit.
// 1. A stale tile renders the stale state and its age.
// 2. The mobile sheet shows the headline, tiles, top pick and hour slider at
//    the half detent.
// 3. axe is clean at both widths (the phone and laptop projects).
// FE-33: the tide sparkline draws the bound coast report's curve through
// CoastMarkup in token colours; the regional brief (high and low events only)
// says "Tide series unavailable" and still lists the events.
import {test, expect} from './fixtures.ts';

const HOUR = 3_600_000;
const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();

/** A synthetic Morro Bay daily feed (regions/<id>/latest.json shape): a buoy five hours old, tide predictions and a fresh, quiet advisory check. */
function feed() {
  const checked = iso(-10 * 60_000);
  return {
    schema_version: 1, generated_at: checked, region_id: 'morro-bay',
    sources: {
      'buoy-46011': {id: 'buoy-46011', name: 'NOAA NDBC 46011 observations', kind: 'observation', url: 'https://www.ndbc.noaa.gov/station_page.php?station=46011',
        checked_at: checked, max_age_hours: 6, status: 'ok',
        data: {station: '46011', observations: [{time: iso(-5 * HOUR), WSPD: 4, GST: 6, WVHT: 1.2, DPD: 11, MWD: 295, WTMP: 14.5}]}},
      tides: {id: 'tides', name: 'NOAA CO-OPS 9412110 predictions', kind: 'prediction', url: 'https://tidesandcurrents.noaa.gov/stationhome.html?id=9412110',
        checked_at: checked, max_age_hours: 36, status: 'ok',
        data: {station: '9412110', datum: 'MLLW', predictions: [{time: iso(2 * HOUR), height_ft: 4.1, type: 'H'}, {time: iso(8 * HOUR), height_ft: 0.6, type: 'L'}]}},
      'nws-alerts': {id: 'nws-alerts', name: 'NWS marine alerts', kind: 'advisory', url: 'https://api.weather.gov/alerts/active?zone=PZZ670', checked_at: checked, status: 'ok', data: {alerts: []}},
    },
  };
}

test.beforeEach(async ({page, v2}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await v2.feed('**/feeds/conditions/regions/morro-bay/latest.json', feed());
});

test('acceptance 1 and 3: a stale tile shows the stale state and its age; the brief renders the model and axe is clean', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', {region: 'morro-bay'});
  const root = page.locator(isMobile ? '.app-sheet-brief' : 'aside.app-brief');
  await expect(root).toHaveAttribute('data-basis', 'regional');
  // The full sheet shows each tile's detail line and basis (below full the tiles are compact).
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  const water = root.locator('.ui-tile', {hasText: 'Water'});
  await expect(water).toHaveAttribute('data-state', 'stale');
  await expect(water.locator('.ui-tile-stale')).toHaveText('stale');
  await expect(water.locator('.ui-tile-source')).toContainText('5 h old');
  await expect(water.locator('.ui-reading')).toHaveText('58.1');
  // No regional forecast yet (FE-32): wind and swell say unavailable instead of a number.
  await expect(root.locator('.ui-tile', {hasText: 'Wind'}).locator('.ui-reading')).toHaveText('—');
  await expect(root.locator('.ui-tile', {hasText: 'Wind'}).locator('.ui-tile-source')).toContainText('unavailable');
  await expect(root.locator('.ui-tile', {hasText: 'Tide'}).locator('.ui-tile-detail')).toContainText('MLLW');
  await expect(root.locator('h1')).not.toHaveText('Waiting for readings.');
  await expect(root.locator('.app-local')).toContainText('Local coast report unavailable here');
  const spark = root.locator('figure.app-spark');
  await expect(spark.locator('.app-spark-empty')).toHaveText('Tide series unavailable');
  // The day's events only: the low falls on tomorrow late in the day.
  await expect(spark.locator('.app-spark-events li').first()).toHaveText(/^High \d{1,2}:\d\d [ap]m · 4\.1 ft MLLW$/);
  await v2.a11y(isMobile ? 'v2-brief-sheet' : 'v2-brief');
  expect(pageErrors).toEqual([]);
});

test('acceptance 2: at the half detent the sheet shows the headline, tiles, top pick and hour slider', async ({page, pageErrors, v2, isMobile}) => {
  test.skip(!isMobile, 'the sheet is the phone layout');
  await v2.open('app', {region: 'morro-bay'});
  await expect(page.locator('.app-sheet-brief')).toHaveAttribute('data-basis', 'regional');
  await page.locator('.ui-sheet-handle').click();
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'half');
  const sheet = page.locator('.ui-sheet');
  for (const part of [sheet.locator('h1'), sheet.locator('.app-tiles'), sheet.getByRole('heading', {name: 'Where to look'}),
    sheet.locator('.app-pick, .app-empty').first(), sheet.getByRole('slider', {name: 'Hour'})]) await expect(part).toBeInViewport({ratio: 1});
  // Compact tiles keep the stale state and the age.
  const water = sheet.locator('.ui-tile', {hasText: 'Water'});
  await expect(water).toHaveAttribute('data-state', 'stale');
  await expect(water.locator('.ui-tile-source')).toContainText('NDBC 46011 · 5 h');
  expect(pageErrors).toEqual([]);
});

/** A synthetic coast report (values invented) with a six-minute tide curve from three hours ago to nine hours ahead, as the bridge serves it. */
function coastReport() {
  const now = Date.now(), t0 = Math.floor(now / HOUR) * HOUR - 3 * HOUR;
  const tides = Array.from({length: 121}, (_, i) => ({at: new Date(t0 + i * 360_000).toISOString(), heightFt: +(2.5 + 2 * Math.sin(i / 20)).toFixed(3)}));
  const source = {id: 'coops-9412110', label: 'NOAA CO-OPS 9412110 predictions', url: 'https://tidesandcurrents.noaa.gov/stationhome.html?id=9412110', kind: 'prediction', outcome: 'ok', fetchedAt: iso(-HOUR)};
  return {schemaVersion: 1, countyId: 'slo', generatedAt: iso(-600_000), forecasts: [], observations: [], tides,
    tideEvents: [{at: tides[40]!.at, heightFt: 4.4, type: 'H'}], alerts: [], catches: [], catchStatus: '', habitatStatus: '', sources: [source],
    visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}};
}

test('FE-33: where a coast report binds, the sparkline draws its tide curve in token colours under the events', async ({page, pageErrors, v2, isMobile}) => {
  await page.route(/\/(?:api\/coast|coast-data)\//, () => { /* held: only the report answers */ });
  await page.route('**/api/coast/report', route => route.fulfill({json: coastReport()}));
  // The coast report is requested for the place while a layer that reads it (Swell) is on.
  await v2.open('app', {region: 'morro-bay', layers: 'swell'});
  const root = page.locator(isMobile ? '.app-sheet-brief' : 'aside.app-brief');
  await expect(root).toHaveAttribute('data-basis', 'coast-report');
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  const spark = root.locator('figure.app-spark');
  const chart = spark.locator('svg.series-chart');
  await expect(chart).toHaveAttribute('aria-label', /^Tide in ft MLLW\./);
  expect(await chart.locator('path').evaluate(el => getComputedStyle(el).stroke)).toBe(await page.evaluate(() => {
    const probe = Object.assign(document.createElement('i'), {style: 'color: var(--amber)'});
    document.body.append(probe);
    const colour = getComputedStyle(probe).color;
    probe.remove();
    return colour;
  }));
  await expect(spark.locator('.app-spark-events li')).toHaveText([/^High \d{1,2}:\d\d [ap]m · 4\.4 ft MLLW$/]);
  await expect(root.locator('.ui-tile', {hasText: 'Tide'}).locator('.ui-tile-detail')).toHaveText(/^(Rising|Falling|Turning) · .+ · MLLW$/);
  await v2.a11y(isMobile ? 'v2-brief-spark-sheet' : 'v2-brief-spark');
  expect(pageErrors).toEqual([]);
});
