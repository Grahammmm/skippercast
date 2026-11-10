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

test('caption_live_switch_and_visibility: real pickers and en–es–en keep chart caption in the top gutter', async ({page, pageErrors, v2, isMobile}) => {
  await v2.open('app', {region: 'morro-bay', view: 'history'});
  if (isMobile) await page.locator('.ui-sheet-handle').press('End');
  const view = page.locator('section.app-history');
  const svg = view.locator('svg.history-chart');
  const caption = svg.locator('text.history-measurement-caption');
  await view.locator('#history-station').selectOption('synthetic-two');
  await view.locator('[data-history-days="14"]').click();
  await expect(caption).toHaveText('Sea temperature, °F');
  await view.locator('#history-metric').selectOption('periodS');
  await expect(caption).toHaveText('Dominant wave period, sec');
  const keys = params(page.url());
  for (const lang of ['es', 'en']) {
    // On phones the account menu belongs to the Brief footer, not the History sheet.
    if (isMobile) await page.locator('.app-tabs [data-view="coast"]').click();
    const trigger = page.locator('.app-account-trigger');
    await trigger.scrollIntoViewIfNeeded();
    await trigger.click();
    await page.locator('.app-account-panel').getByRole('button', {name: lang === 'es' ? 'Español' : 'English', exact: true}).click();
    await expect(page.locator('html')).toHaveAttribute('lang', lang);
    await trigger.click();
    if (isMobile) await page.goBack();
    await expect(caption).toHaveText(lang === 'es' ? 'Período dominante de ola, sec' : 'Dominant wave period, sec');
    await expect(svg).toHaveAttribute('aria-label', lang === 'es' ? 'Período dominante de ola, últimos 14 días, sec. Las observaciones faltantes quedan como huecos.' : 'Dominant wave period, previous 14 days, sec. Missing observations remain gaps.');
    expect(params(page.url())).toEqual(keys);
    await caption.scrollIntoViewIfNeeded();
    await expect(caption).toBeInViewport();
    const placement = await caption.evaluate(el => {
      const text = el as SVGTextElement, box = text.getBBox(), svg = text.ownerSVGElement!;
      const ticks = [...svg.querySelectorAll('text.axis:not(.history-measurement-caption)')].map(t => (t as SVGTextElement).getBBox());
      const style = getComputedStyle(text);
      return {bounds: {x: box.x, y: box.y, width: box.width, height: box.height}, fontSize: style.fontSize, x: text.getAttribute('x'), y: text.getAttribute('y'), inside: box.x >= 0 && box.y >= 0 && box.x + box.width <= 1000 && box.y + box.height <= 20,
        clear: ticks.every(t => box.x + box.width <= t.x || t.x + t.width <= box.x || box.y + box.height <= t.y || t.y + t.height <= box.y), visible: style.display !== 'none' && style.visibility === 'visible' && style.fill !== 'none'};
    });
    expect(placement, JSON.stringify(placement)).toMatchObject({x: '47', y: '12', inside: true, clear: true, visible: true});
    const overflow = svg.locator('..');
    await overflow.evaluate(el => { el.scrollLeft = el.scrollWidth; });
    expect(await overflow.evaluate(el => el.scrollWidth > el.clientWidth ? el.scrollLeft > 0 : el.scrollLeft === 0)).toBe(true);
    await overflow.evaluate(el => { el.scrollLeft = 0; });
    await expect(caption).toBeInViewport();
  }
  expect(pageErrors).toEqual([]);
});
