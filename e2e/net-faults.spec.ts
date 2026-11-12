// UXFIX-12 @nightly: network faults and a clean console, on fixtures. Runs only when E2E_WIDE=1 (the nightly e2e step in ci.yml);
// a pull-request run lists these cases and skips every one. Nothing here reaches a live host: fixtures.ts aborts every other origin,
// and every case takes the `v2` fixture, which answers the local Worker's /feeds/ proxy offline (404 unless stubbed).
import type {Page, Route} from '@playwright/test';
import {test, expect, type V2} from './fixtures.ts';

const WIDE = process.env.E2E_WIDE === '1';
const SHELL = {region: 'morro-bay'};
const HOUR = 3_600_000;
const FORECAST = '**/api/forecast?*';
/** The day verdict's words (web/brief/verdict.ts VERDICT_WORD): none may show before the final answer (SC1722-02). */
const VERDICT = /^(Comfortable|Marginal|Rough|Unknown)$/;

/**
 * A synthetic Morro Bay daily feed (values invented, clocks relative to now: a fresh buoy reading, tide events, a quiet advisory check).
 * The brief only reaches its forecast-failed state once the feeds can answer, and the offline v2 fixture answers /feeds/ with 404 unless a
 * case stubs it, so every case here stubs this one instead of letting the local Worker's /feeds/ proxy fetch upstream.
 */
function dailyFeed() {
  const now = Date.now(), iso = (offsetMs: number) => new Date(now + offsetMs).toISOString(), checked = iso(-10 * 60_000);
  return {
    schema_version: 1, generated_at: checked, region_id: 'morro-bay',
    sources: {
      'buoy-46011': {id: 'buoy-46011', name: 'NOAA NDBC 46011 observations', kind: 'observation', url: 'https://www.ndbc.noaa.gov/station_page.php?station=46011',
        checked_at: checked, max_age_hours: 6, status: 'ok',
        data: {station: '46011', observations: [{time: iso(-HOUR), WSPD: 4, GST: 6, WVHT: 1.2, DPD: 11, MWD: 295, WTMP: 14.5}]}},
      tides: {id: 'tides', name: 'NOAA CO-OPS 9412110 predictions', kind: 'prediction', url: 'https://tidesandcurrents.noaa.gov/stationhome.html?id=9412110',
        checked_at: checked, max_age_hours: 36, status: 'ok',
        data: {station: '9412110', datum: 'MLLW', predictions: [{time: iso(2 * HOUR), height_ft: 4.1, type: 'H'}, {time: iso(8 * HOUR), height_ft: 0.6, type: 'L'}]}},
      'nws-alerts': {id: 'nws-alerts', name: 'NWS marine alerts', kind: 'advisory', url: 'https://api.weather.gov/alerts/active?zone=PZZ670', checked_at: checked, status: 'ok', data: {alerts: []}},
    },
    landing_names: ['Morro Bay', 'Avila'], reports: [],
  };
}

async function stubDailyFeed(v2: V2) { await v2.feed('**/feeds/data/regions/morro-bay/latest.json', dailyFeed()); }

/** A calm synthetic Morro Bay /api/forecast answer (values invented, as e2e/v2-brief.spec.ts builds it): eight days from two hours ago, three points. */
function calmForecast() {
  const now = Date.now(), t0 = Math.floor((now - 2 * HOUR) / 1000 / 3600) * 3600;
  const time = Array.from({length: 8 * 24}, (_, i) => t0 + i * 3600);
  const series = (values: Record<string, [number, string]>) => ({utc_offset_seconds: 0,
    hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
  const points = [['north', 35.45, -121.02], ['central', 35.36, -120.94], ['offshore-1-0', 35.3, -121.25]];
  const meta = {last_run_initialisation_time: Math.floor((now - 3 * HOUR) / 1000), data_end_time: time.at(-1)};
  const model = (values: Record<string, [number, string]>) => ({meta, data: points.map(() => series(values))});
  const wind = {wind_speed_10m: [6, 'kn'], wind_gusts_10m: [9, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [20, '%']} as Record<string, [number, string]>;
  const wave = {wave_height: [2.5, 'ft'], wave_period: [11, 's']} as Record<string, [number, string]>;
  return {region_id: 'morro-bay', retrieved: now - 20 * 60_000, requested_points: points,
    models: {gfs_global: model(wind), ncep_gfswave016: model(wave), ecmwf_ifs025: model(wind), ecmwf_wam: model(wave)}};
}

/**
 * Successful offline answers for everything a baseline /map load asks the local Worker for, so the clean-console budget counts any
 * other >= 400 as a finding instead of exempting an endpoint. fixtures.ts answers /api/forecast and the brief part with 503 and /feeds/
 * with 404 to stay offline; this case replaces each with a 200 (page routes win over the fixture's context routes).
 */
async function stubBaselineAnswers(page: Page, v2: V2) {
  const feed = dailyFeed();
  await page.route('**/api/forecast?*', route => route.fulfill({json: calmForecast()}));
  await page.route('**/api/daily?*', route => new URL(route.request().url()).searchParams.get('part') === 'brief'
    ? route.fulfill({json: {...feed, part: 'brief', catch_probability: null, bite_score: null}}) : route.fallback());
  await v2.feed('**/feeds/conditions/regions/morro-bay/latest.json', feed);   // the conditions feed, read beside the daily one
  await v2.feed('**/feeds/tiles/basemap/manifest.json', {});   // no archive key: the Aerial base draws, no archive is fetched
  await v2.feed('**/feeds/tiles/seafloor/manifest-morro-bay.json', {status: 'held', region: 'morro-bay'});   // layer hidden, nothing to fetch
}

/**
 * The share of the viewport that shows map: the map's area inside the viewport, less the part of it under the cover (sheet or brief).
 * Only the map/cover intersection (both clipped to the viewport) is subtracted. Self-contained: page.evaluate serialises it into the page.
 */
type Box = {left: number; right: number; top: number; bottom: number};
function visibleMapShare(vw: number, vh: number, map: Box | null, cover: Box | null): number {
  if (!map) return -1;
  const clip = (r: Box): Box => ({left: Math.max(r.left, 0), right: Math.min(r.right, vw), top: Math.max(r.top, 0), bottom: Math.min(r.bottom, vh)});
  const area = (r: Box) => Math.max(0, r.right - r.left) * Math.max(0, r.bottom - r.top);
  const m = clip(map), c = cover ? clip(cover) : null;
  const overlap = c ? area({left: Math.max(m.left, c.left), right: Math.min(m.right, c.right), top: Math.max(m.top, c.top), bottom: Math.min(m.bottom, c.bottom)}) : 0;
  return Math.max(0, area(m) - overlap) / (vw * vh);
}

test.describe('visible map share geometry', () => {
  const box = (left: number, top: number, right: number, bottom: number): Box => ({left, top, right, bottom});
  test('adjacent rectangles: the cover does not hide any map', () => {
    expect(visibleMapShare(1024, 768, box(300, 0, 1024, 768), box(0, 0, 300, 768))).toBeCloseTo(724 / 1024, 6);
  });
  test('overlapping rectangles: only the overlap is subtracted', () => {
    expect(visibleMapShare(1024, 768, box(0, 0, 1024, 768), box(0, 0, 300, 768))).toBeCloseTo(724 / 1024, 6);
  });
  test('partially offscreen, disjoint rectangles: offscreen parts count for nothing', () => {
    expect(visibleMapShare(1024, 768, box(300, 0, 1024, 768), box(-500, 0, 300, 768))).toBeCloseTo(724 / 1024, 6);
    expect(visibleMapShare(1024, 768, box(300, 0, 1324, 768), box(0, 0, 300, 768))).toBeCloseTo(724 / 1024, 6);
  });
  test('no map is -1; no cover leaves the whole map', () => {
    expect(visibleMapShare(1024, 768, null, null)).toBe(-1);
    expect(visibleMapShare(1024, 768, box(0, 0, 512, 768), null)).toBeCloseTo(0.5, 6);
  });
});

test.describe('@nightly net-faults', () => {
  test.beforeEach(async ({v2}) => { test.skip(!WIDE, 'nightly only: set E2E_WIDE=1'); await stubDailyFeed(v2); });

  /** Records every verdict word the page ever renders, from before the first script runs. */
  async function watchVerdict(page: Page) {
    await page.addInitScript(() => {
      const seen: string[] = [];
      (window as unknown as {__verdictSeen: string[]}).__verdictSeen = seen;
      const look = () => { for (const el of document.querySelectorAll('.app-verdict-word, [data-verdict]')) seen.push((el.textContent ?? '').trim() || String(el.getAttribute('data-verdict'))); };
      new MutationObserver(look).observe(document, {subtree: true, childList: true, characterData: true, attributes: true});
    });
  }
  const verdictSeen = (page: Page) => page.evaluate(() => (window as unknown as {__verdictSeen: string[]}).__verdictSeen);

  const faults: Array<[string, (route: Route) => Promise<void>]> = [
    ['aborted', route => route.abort('failed')],
    ['500', route => route.fulfill({status: 500, json: {error: 'fixture fault'}})],
    ['empty object {}', route => route.fulfill({json: {}})],
    ['8 s delay then 503', async route => { await new Promise(r => setTimeout(r, 8_000)); await route.fulfill({status: 503, json: {error: 'fixture fault'}}).catch(() => undefined); }],
  ];
  for (const [name, answer] of faults) {
    test(`forecast ${name}: no verdict word before the final one, and a failed state with Try again by 20 s`, async ({page, v2, pageErrors}) => {
      await watchVerdict(page);
      await page.route(FORECAST, answer);
      await v2.open('app', SHELL);
      const failed = page.locator('.app-forecast-failed').first();
      await expect(failed).toBeVisible({timeout: 20_000});
      await expect(failed.locator('.app-forecast-retry')).toBeEnabled({timeout: 20_000});
      const seen = await verdictSeen(page);
      expect(seen.filter(w => VERDICT.test(w)), 'verdict words rendered under this fault').toEqual([]);
      expect(pageErrors).toEqual([]);
    });
  }

  test('aerial imagery host aborted: after the first failures, at most 2 further requests to it in the next 30 s (RF1935-3)', async ({page, v2, pageErrors}) => {
    test.setTimeout(90_000);
    const times: number[] = [];
    await page.route('https://imagery.nationalmap.gov/**', route => { times.push(Date.now()); return route.abort('failed'); });
    await v2.open('app', SHELL);
    await expect.poll(() => times.length, {message: 'the Aerial base asks for imagery', timeout: 20_000}).toBeGreaterThan(0);
    await page.waitForTimeout(5_000);
    const after = Date.now(), already = times.length;
    await page.waitForTimeout(30_000);
    const further = times.filter(t => t > after).length;
    console.log(`[net-faults] aerial requests before the window: ${already}, further in 30 s: ${further}`);
    expect(further, 'requests to the failed host in the 30 s after the first failures settled').toBeLessThanOrEqual(2);
    expect(pageErrors).toEqual([]);
  });

  test('console budget on a baseline /map load: no CSP violation, no same-origin response >= 400 except the Fleet HEAD probe; CLS and long tasks recorded', async ({page, v2, pageErrors}) => {
    await page.addInitScript(() => {
      const w = window as unknown as {__csp: string[]; __cls: number; __long: number};
      w.__csp = []; w.__cls = 0; w.__long = 0;
      document.addEventListener('securitypolicyviolation', e => w.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
      new PerformanceObserver(list => { for (const e of list.getEntries() as Array<PerformanceEntry & {hadRecentInput?: boolean; value?: number}>) if (!e.hadRecentInput) w.__cls += e.value ?? 0; }).observe({type: 'layout-shift', buffered: true});
      new PerformanceObserver(list => { for (const e of list.getEntries()) w.__long += e.duration; }).observe({type: 'longtask', buffered: true});
    });
    const bad: string[] = [];
    const origin = new URL(test.info().project.use.baseURL ?? `http://localhost:${process.env.E2E_PORT || '8787'}`).origin;
    page.on('response', res => {
      const req = res.request(), url = new URL(res.url());
      if (url.origin !== origin || res.status() < 400) return;
      // The Fleet view's HEAD probe of /ports/<id> answers 404 by design while the public boat list is off (web/fleet.ts).
      if (req.method() === 'HEAD' && /^\/ports\/[^/]+$/.test(url.pathname)) return;
      bad.push(`${req.method()} ${url.pathname}${url.search} ${res.status()}`);
    });
    await stubBaselineAnswers(page, v2);
    await v2.open('app', SHELL);
    // The page never goes network-idle (imagery and polling), so wait for the brief's answer (a verdict word, the forecast being served), then a fixed quiet spell.
    await expect(page.locator('.app-verdict-word').first()).toHaveText(VERDICT);
    await page.waitForTimeout(4_000);
    const m = await page.evaluate(() => { const w = window as unknown as {__csp: string[]; __cls: number; __long: number}; return {csp: w.__csp, cls: w.__cls, long: w.__long}; });
    console.log(`[net-faults] CLS ${m.cls.toFixed(4)}, long tasks total ${Math.round(m.long)} ms (recorded, no threshold)`);
    // The visible map share (map area not under the sheet or brief) is recorded, not asserted: the landscape layout waits for the map decision.
    const share = await page.evaluate(([src, vw, vh]) => {
      const visibleMapShare = new Function(`return ${src}`)() as (w: number, h: number, m: Box | null, c: Box | null) => number;
      const rect = (el: Element | null) => el ? el.getBoundingClientRect() : null;
      return visibleMapShare(vw as number, vh as number, rect(document.querySelector('.app-chart')), rect(document.querySelector('.ui-sheet, .app-brief')));
    }, [visibleMapShare.toString(), page.viewportSize()!.width, page.viewportSize()!.height] as const);
    console.log(`[net-faults] ${test.info().project.name} ${page.viewportSize()!.width}x${page.viewportSize()!.height}: visible map share ${(share * 100).toFixed(1)}% (recorded, not asserted)`);
    expect(m.csp, 'securitypolicyviolation events').toEqual([]);
    expect(bad, 'same-origin responses >= 400').toEqual([]);
    expect(pageErrors).toEqual([]);
  });
});
