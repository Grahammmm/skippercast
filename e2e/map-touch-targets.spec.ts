// SC1922-03 (UX audit S4-26 remainder, S5-REVIEW E36): the small buttons the audit measured on the map reach the app's
// touch size. Cancel waypoint (inside the placing note), Retry region details (Location: the desktop masthead and the
// phone top card) and every Conditions model-family option measure at least the computed --touch-min high in both
// configured projects, keep their words and actions, and an explicit axe target-size scan (WCAG 2.2 AA, which the
// shared checkA11y tag list omits) finds nothing in the armed placing, failed-region and Conditions states.
import AxeBuilder from '@axe-core/playwright';
import type {Page} from '@playwright/test';
import {expect, test} from './fixtures.ts';

const AREA = {region: 'morro-bay', presentation: 'chart'};
const HOUR = 3600;
const WORDS = {
  en: {cancel: 'Cancel waypoint', retry: 'Retry region details', plan: 'Trip plan and GPX'},
  es: {cancel: 'Cancelar punto de ruta', retry: 'Reintentar detalles de la región', plan: 'Plan de viaje y GPX'},
} as const;
type Lang = keyof typeof WORDS;

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
  await page.route('**/api/forecast?*', route => route.fulfill({json: forecast()}));
  await page.route('**/api/coast/report', route => route.fulfill({status: 503, json: {error: 'Offline UI test'}}));
});

/** A synthetic Morro Bay /api/forecast answer (values invented), as e2e/v2-conditions.spec.ts builds it. */
function forecast() {
  const t0 = Math.floor(Date.now() / 1000 / HOUR) * HOUR;
  const time = Array.from({length: 8 * 24}, (_, i) => t0 + i * HOUR);
  const series = (values: Record<string, [number, string]>) => ({
    utc_offset_seconds: 0,
    hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))},
  });
  const points = [['north', 35.45, -121.02], ['central', 35.36, -120.94], ['offshore-1-0', 35.3, -121.25]];
  const meta = {last_run_initialisation_time: t0 - 6 * HOUR, data_end_time: time.at(-1)};
  const model = (values: Record<string, [number, string]>) => ({meta, data: points.map(() => series(values))});
  const wind = {wind_speed_10m: [8, 'kn'], wind_gusts_10m: [12, 'kn'], temperature_2m: [61, '°F'], cloud_cover: [40, '%']} as Record<string, [number, string]>;
  const wave = {wave_height: [4.2, 'ft'], wave_period: [11, 's']} as Record<string, [number, string]>;
  return {region_id: 'morro-bay', retrieved: Date.now() - 20 * 60_000, requested_points: points,
    models: {gfs_global: model(wind), ncep_gfswave016: model(wave), ecmwf_ifs025: model(wind), ecmwf_wam: model(wave)}};
}

/** The computed --touch-min in CSS px, once the app's stylesheets (document and shadow roots) have loaded. */
async function touchMin(page: Page): Promise<number> {
  await page.waitForFunction(() => [...document.querySelectorAll('link[rel=stylesheet]')].every(l => (l as HTMLLinkElement).sheet));
  const min = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--touch-min')));
  expect(min, 'the app defines --touch-min').toBeGreaterThan(0);
  return min;
}

/** Heights of every match, after the boxes stop moving (a sheet or note placed by a transform has settled). */
async function heights(page: Page, selector: string): Promise<number[]> {
  const read = () => page.locator(selector).evaluateAll(els => els.map(e => { const r = e.getBoundingClientRect(); return [r.top, r.height] as const; }));
  let last = JSON.stringify(await read());
  await expect.poll(async () => { const now = JSON.stringify(await read()); const same = now === last; last = now; return same; }, {message: `${selector} has settled`}).toBe(true);
  return (JSON.parse(last) as number[][]).map(([, h]) => h!);
}

/** The explicit WCAG 2.2 target-size scan: no exclusions, no other rule, no filtering. */
async function targetSize(page: Page): Promise<void> {
  const results = await new AxeBuilder({page}).withRules(['target-size']).analyze();
  expect(results.violations.map(v => ({id: v.id, nodes: v.nodes.map(n => n.target.join(' '))})), 'axe target-size').toEqual([]);
}

async function fullSheet(page: Page, isMobile: boolean) {
  if (!isMobile) return;
  await page.locator('.ui-sheet-handle').focus();
  await page.keyboard.press('End');
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'full');
}

/** Arm waypoint placing from the trip planner, as a visitor does (e2e/v2-trip.spec.ts). */
async function armPlacing(page: Page, isMobile: boolean, lang: Lang) {
  await fullSheet(page, isMobile);
  const trigger = page.locator('.app-account-trigger');
  await trigger.scrollIntoViewIfNeeded();
  await trigger.click();
  await page.locator('.app-account-panel').getByRole('button', {name: new RegExp(`^${WORDS[lang].plan}`)}).click();
  await expect(page.getByRole('dialog', {name: WORDS[lang].plan})).toBeVisible();
  await page.locator('#waypoint-place').click();
  await expect(page.getByRole('dialog', {name: WORDS[lang].plan})).toBeHidden();
}

for (const lang of ['en', 'es'] as const) {
  test(`placing_touch_cancel_${lang}: Cancel waypoint is touch size, scans clean, and cancels without placing`, async ({page, pageErrors, v2, isMobile}) => {
    void pageErrors;
    const writes: string[] = [];
    // The anonymous /api/telemetry beacon is not a save; it fires on its own timing (v2-trip and v2-private-map-log leave it out too).
    page.on('request', r => { if (r.method() !== 'GET' && r.method() !== 'HEAD' && new URL(r.url()).pathname !== '/api/telemetry') writes.push(new URL(r.url()).pathname); });
    await v2.open('app', {...AREA, lang});
    await armPlacing(page, isMobile, lang);
    const cancel = page.getByRole('button', {name: WORDS[lang].cancel});
    await expect(cancel).toBeVisible();
    await expect(cancel.locator('xpath=ancestor::p[@role="status"]'), 'still inside the placing note').toBeVisible();
    const min = await touchMin(page);
    expect(await heights(page, `button:has-text("${WORDS[lang].cancel}")`)).toEqual([expect.any(Number)]);
    for (const h of await heights(page, `.app-stage-note button`)) expect(h).toBeGreaterThanOrEqual(min);
    await targetSize(page);
    const before = page.url();
    if (lang === 'en') await cancel.click(); else { await cancel.focus(); await expect(cancel).toBeFocused(); await page.keyboard.press('Enter'); }
    await expect(cancel, 'Cancel clears the placing note').toHaveCount(0);
    await expect(page.getByRole('dialog', {name: WORDS[lang].plan}), 'no waypoint form or navigation').toBeHidden();
    expect(page.url()).toBe(before);
    expect(writes, 'no save or other write').toEqual([]);
  });
}

test('placing_touch_cancel_narrow: at 320 px the wrapped note keeps Cancel whole and touch size', async ({page, pageErrors, v2, isMobile}) => {
  void pageErrors;
  test.skip(!isMobile, 'the narrow phone case runs in the phone project');
  await page.setViewportSize({width: 320, height: 640});
  await v2.open('app', AREA);
  await armPlacing(page, true, 'en');
  const cancel = page.getByRole('button', {name: WORDS.en.cancel});
  await expect(cancel).toBeVisible();
  const min = await touchMin(page);
  for (const h of await heights(page, `.app-stage-note button`)) expect(h).toBeGreaterThanOrEqual(min);
  const [note, button] = await Promise.all([cancel.locator('xpath=ancestor::p[@role="status"]').boundingBox(), cancel.boundingBox()]);
  expect(button!.x).toBeGreaterThanOrEqual(note!.x - 0.5);
  expect(button!.x + button!.width).toBeLessThanOrEqual(note!.x + note!.width + 0.5);
  expect(button!.y + button!.height).toBeLessThanOrEqual(note!.y + note!.height + 0.5);
});

for (const lang of ['en', 'es'] as const) {
  test(`region_error_touch_retry_${lang}: Retry region details is touch size, scans clean, and recovers on the same request`, async ({page, pageErrors, v2}) => {
    void pageErrors;
    let failing = true, asked = 0;
    await page.route('**/regions/morro-bay/region.json', route => {
      asked++;
      return failing ? route.fulfill({status: 503, json: {error: 'Synthetic region failure'}}) : route.continue();
    });
    await v2.open('app', {...AREA, lang});
    const retry = page.getByRole('button', {name: WORDS[lang].retry});
    await expect(retry, 'exactly one visible Retry: the masthead on a laptop, the top card on a phone').toHaveCount(1);
    await expect(retry).toBeVisible();
    await expect(retry.locator('xpath=ancestor::span[@role="status"]'), 'inside the location status').toBeVisible();
    const min = await touchMin(page);
    expect(await heights(page, `[role="status"] button:has-text("${WORDS[lang].retry}")`)).toHaveLength(1);
    for (const h of await heights(page, `[role="status"] button:has-text("${WORDS[lang].retry}")`)) expect(h).toBeGreaterThanOrEqual(min);
    await targetSize(page);
    // A retry while the region still fails: the request is made again, the error and its control stay.
    const before = asked;
    await retry.focus();
    await expect(retry).toBeFocused();
    await page.keyboard.press('Enter');
    await expect.poll(() => asked).toBeGreaterThan(before);
    await expect(retry).toBeVisible();
    // Once the region answers, the same control recovers the location and goes away.
    failing = false;
    await retry.click();
    await expect(retry).toHaveCount(0);
    await expect(page.locator('.app-location').first()).toContainText('Morro Bay');
  });
}

test('region_nonerror_has_no_retry: a missing region shows Choose a port and no Retry', async ({page, pageErrors, v2}) => {
  void pageErrors;
  await v2.open('app', {region: 'no-such-region', presentation: 'chart'});
  await expect(page.getByRole('link', {name: 'Choose a port'}).first()).toBeVisible();
  await expect(page.getByRole('button', {name: WORDS.en.retry})).toHaveCount(0);
});

for (const lang of ['en', 'es'] as const) {
  test(`conditions_each_option_touch_and_select_${lang}: every model-family option is touch size, selectable and inside the header`, async ({page, pageErrors, v2, isMobile}) => {
    void pageErrors;
    const sizes = isMobile ? [{width: 390, height: 844}, {width: 320, height: 640}] : [{width: 1280, height: 800}];
    for (const size of sizes) {
      await page.setViewportSize(size);
      await v2.open('app', {region: 'morro-bay', view: 'conditions', lang});
      await fullSheet(page, isMobile);
      const group = page.locator('.app-conditions-head > .ui-segmented');
      await expect(group).toBeVisible();
      const options = group.locator('button');
      const count = await options.count();
      expect(count, 'the model-family options render').toBeGreaterThan(1);
      const min = await touchMin(page);
      for (const h of await heights(page, '.app-conditions-head > .ui-segmented button')) expect(h).toBeGreaterThanOrEqual(min);
      const head = (await page.locator('.app-conditions-head').boundingBox())!, box = (await group.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(head.x - 0.5);
      expect(box.x + box.width, 'the group stays inside the header').toBeLessThanOrEqual(head.x + head.width + 0.5);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), 'no page-level sideways scroll').toBe(true);
      for (let i = 0; i < count; i++) {
        await options.nth(i).scrollIntoViewIfNeeded();
        await options.nth(i).click();
        await expect(options.nth(i)).toHaveAttribute('aria-pressed', 'true');
        await expect(group.locator('button[aria-pressed="true"]')).toHaveCount(1);
      }
      await targetSize(page);
    }
  });
}
