// FE-35 (docs/plans/front-end/dev-plan.md, design § 10): the History view
// mounts packages/coast historyView through CoastMarkup from the coast
// bridge's history snapshot. The bundle is synthetic (two invented stations,
// values invented, clocks relative to now) in the /api/coast/history shape.
// 1. A region without a history binding shows the unavailable state.
// 2. The copy says "recorded history".
// 3. Station, measurement and range choices survive Back and Forward.
import {test, expect} from './fixtures.ts';

const HOUR = 3_600_000;
const METRICS = ['waterTempF', 'airTempF', 'windKnots', 'gustKnots', 'waveFt', 'periodS'] as const;

/** A synthetic history bundle: 48 recent hourly means at two stations and one October monthly band. */
function history() {
  const now = Date.now(), last = Math.floor(now / HOUR) * HOUR - HOUR;
  const hours = Array.from({length: 48}, (_, i) => {
    const values = {waterTempF: 57 + i / 48, airTempF: 60, windKnots: 8, gustKnots: 11, waveFt: 4, periodS: 12};
    return {at: new Date(last - (47 - i) * HOUR).toISOString(), ...values, sampleCount: 6, counts: Object.fromEntries(METRICS.map(m => [m, 6]))};
  });
  const station = (stationId: string, name: string) => ({
    stationId, name, lat: 35.3, lon: -121,
    recent: {from: new Date(now - 45 * 24 * HOUR).toISOString(), through: new Date(last).toISOString(), firstObservedAt: hours[0]!.at, lastObservedAt: hours.at(-1)!.at,
      stale: false, expectedHours: 48, observedHours: 48, hourCoverageFraction: 1, maxGapHours: 0, hours,
      qc: {inputRows: 288, acceptedRows: 288, rejectedRows: 0, duplicateRows: 0, conflictingValues: 0, maskedValues: 0, trailingMissingRows: 0}},
    baseline: {kind: 'multi-year-reference', label: 'Synthetic', years: [2023, 2024, 2025], periodStart: '2023-01-01', periodEnd: '2025-12-31', aggregation: 'UTC-hour means, weighted equally',
      months: METRICS.map(metric => ({month: new Date(last).getUTCMonth() + 1, metric, unit: '', count: 2000, rawSampleCount: 12000, expectedHours: 2232, coverageFraction: 0.9, yearsWithData: [2023, 2024, 2025], p10: 3, median: 5, p90: 8, min: 1, max: 12, mean: 5}))},
    archive: {indexUrl: 'https://example.invalid/history', availableYears: [2023, 2024, 2025], discoveredAt: new Date(now - HOUR).toISOString(), outcome: 'ok'},
    sources: [{url: 'https://example.invalid/history/2025', role: 'annual', year: 2025, outcome: 'ok', fetchedAt: new Date(now - HOUR).toISOString()}],
    limitations: ['Synthetic e2e bundle.'],
  });
  return {schemaVersion: 1, countyId: 'slo', generatedAt: new Date(now - 20 * 60_000).toISOString(), recentWindowDays: 45,
    stations: [station('synthetic-one', 'First synthetic buoy'), station('synthetic-two', 'Second synthetic buoy')]};
}

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/api/coast/history*', route => route.fulfill({json: history()}));
});

const params = (url: string) => {
  const p = new URL(url).searchParams;
  return [p.get('station'), p.get('metric'), p.get('range')];
};

test('acceptance 2 and 3: the recorded history pickers write the address and survive Back and Forward', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', {region: 'morro-bay', view: 'history'});
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  const view = page.locator('section.app-history');
  await expect(view.getByRole('heading', {name: 'Recorded history'})).toBeVisible();
  const station = view.locator('#history-station'), metric = view.locator('#history-metric');
  await expect(station).toHaveValue('synthetic-one');
  await expect(view.locator('.view-heading')).toContainText('RECORDED OCEAN HISTORY');

  await station.selectOption('synthetic-two');
  await expect.poll(() => params(page.url())).toEqual(['synthetic-two', null, null]);
  await metric.selectOption('waveFt');
  await expect.poll(() => params(page.url())).toEqual(['synthetic-two', 'waveFt', null]);
  await view.locator('[data-history-days="14"]').click();
  await expect.poll(() => params(page.url())).toEqual(['synthetic-two', 'waveFt', '14']);
  await expect(view.locator('[data-history-days="14"]')).toHaveAttribute('aria-pressed', 'true');

  await page.goBack();
  await expect.poll(() => params(page.url())).toEqual(['synthetic-two', 'waveFt', null]);
  await expect(view.locator('[data-history-days="45"]')).toHaveAttribute('aria-pressed', 'true');
  await page.goBack();
  await expect(metric).toHaveValue('waterTempF');
  await expect(station).toHaveValue('synthetic-two');
  await page.goForward();
  await page.goForward();
  await expect(metric).toHaveValue('waveFt');
  await expect(view.locator('[data-history-days="14"]')).toHaveAttribute('aria-pressed', 'true');

  await v2.a11y(isMobile ? 'v2-history-sheet' : 'v2-history');
  expect(pageErrors).toEqual([]);
});

test('acceptance 1: a region without a history binding shows the unavailable state', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', {region: 'monterey-point-sur', view: 'history'});
  if (isMobile) { await page.locator('.ui-sheet-handle').press('End'); await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full'); }
  const view = page.locator('section.app-history');
  await expect(view.getByRole('status')).toHaveText(/Recorded history is unavailable for this region\./);
  await expect(view.locator('.app-coast-markup')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});
