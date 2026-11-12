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
async function stubDailyFeed(v2: V2) {
  const now = Date.now(), iso = (offsetMs: number) => new Date(now + offsetMs).toISOString(), checked = iso(-10 * 60_000);
  await v2.feed('**/feeds/data/regions/morro-bay/latest.json', {
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
  });
}

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
      // The shared fixtures (e2e/fixtures.ts) answer these on purpose to keep the run offline.
      if (url.pathname === '/api/forecast' || (url.pathname === '/api/daily' && url.searchParams.get('part') === 'brief') || url.pathname.startsWith('/feeds/')) return;
      bad.push(`${req.method()} ${url.pathname}${url.search} ${res.status()}`);
    });
    await v2.open('app', SHELL);
    // The page never goes network-idle (imagery and polling), so wait for the brief's answer, then a fixed quiet spell.
    await expect(page.locator('.app-forecast-failed').first()).toBeVisible();
    await page.waitForTimeout(4_000);
    const m = await page.evaluate(() => { const w = window as unknown as {__csp: string[]; __cls: number; __long: number}; return {csp: w.__csp, cls: w.__cls, long: w.__long}; });
    console.log(`[net-faults] CLS ${m.cls.toFixed(4)}, long tasks total ${Math.round(m.long)} ms (recorded, no threshold)`);
    // The visible map share (map area not under the sheet or brief) is recorded, not asserted: the landscape layout waits for the map decision.
    const share = await page.evaluate(() => {
      const vw = innerWidth, vh = innerHeight, area = (r: DOMRect) => Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
      const map = document.querySelector('.app-chart'), cover = document.querySelector('.ui-sheet, .app-brief');
      return map ? Math.max(0, area(map.getBoundingClientRect()) - (cover ? area(cover.getBoundingClientRect()) : 0)) / (vw * vh) : -1;
    });
    console.log(`[net-faults] ${test.info().project.name} ${page.viewportSize()!.width}x${page.viewportSize()!.height}: visible map share ${(share * 100).toFixed(1)}% (recorded, not asserted)`);
    expect(m.csp, 'securitypolicyviolation events').toEqual([]);
    expect(bad, 'same-origin responses >= 400').toEqual([]);
    expect(pageErrors).toEqual([]);
  });
});
