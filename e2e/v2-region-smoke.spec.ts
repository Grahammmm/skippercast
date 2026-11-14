// R4-SC-11: a phone smoke test for every Stage 1 region (BETA-GATE items 1 and 2 need a per-region check; SC-MOBILE measured only
// Morro Bay). One browser test per region at 390x844 on the phone profile. For each region it opens the map page on the Boat profile
// and checks, with the live feeds answered by the same deterministic stand-ins as the first-run funnel spec (scripts/measure_startup.mjs
// stubLiveFeeds: each region's own committed region.json, rules registry and protected-areas file):
//   1. open     the page loads for this region (title, brief sheet, the region kept in the address);
//   2. verdict  the day verdict (Comfortable, Marginal or Rough) and its limit line show on the first screen;
//   3. rules    the rules card line draws and can be scrolled into view with the sheet at full: status badge, the day's words and the
//               official link. Its season status is NOT judged (the stand-in feed carries no daily source checks, so every region reads
//               "Check rules" here); that is BETA-GATE item 2, owned by the rules probe, not by this layout check;
//   4. map      the Chart's canvas is on screen and reached its first idle frame ("skippercast-chart-idle"), no poster left behind;
//   5. fit      nothing runs off the side of the screen, on the first screen and with the sheet pulled to full: no page-wide sideways
//               scroll, and no visible control, text or sheet part outside the 390 px width (anything clipped inside its own scroller
//               does not count);
//   6. errors   no uncaught page error while it did all that.
// Every region runs every check and records each result; none stops at its first failure.
//
// What fails the run. A region the published index calls `active` (today Morro Bay) must pass all six: a failure fails the test. A
// `preview` region is reported, not failed: that report is the finding (the card says this test "may fail on preview regions"). The
// result is the line "<region> | <check>: PASS|FAIL detail" in the log, the test's annotations and one line per region in the GitHub job summary.
// A listed region missing from the index fails too. A region that SCB-18 promotes to `active` turns strict by itself, because the status is read from dist/regions/index.json at run time.
// E2E_REGION_SMOKE_STRICT=1 makes every listed region strict (use it to see a red run locally).
//
// When it runs. It is a nightly check, not a pull request check: it runs only where E2E_WIDE=1 (the scheduled run in .github/workflows/ci.yml,
// which already sets it) or where E2E_REGION_SMOKE=1 is set by hand, and only in the `phone` project. Locally:
//   pnpm build && E2E_REGION_SMOKE=1 pnpm e2e e2e/v2-region-smoke.spec.ts --project=phone
// E2E_REGION_SMOKE_REGIONS=id,id narrows or widens the list (any id in dist/regions/index.json). Rollback: delete this file.
//
// Limits (say so in any report that quotes it): hermetic. The Worker is the local one, the feeds and forecast are stand-ins, the map's
// base layers are blocked, and software WebGL draws the canvas. It proves the page opens, answers and fits for each region's committed
// package and rules; it does not prove a live feed is fresh or a real phone is fast (SC-MOBILE and the freshness alarm own those).
import {appendFileSync, readFileSync} from 'node:fs';
import type {Page} from '@playwright/test';
import {stubForecast, stubLiveFeeds} from '../scripts/measure_startup.mjs';
import {forecastFixture} from './forecast-fixture.ts';
import {expect, test} from './fixtures.ts';

/** Stage 1 of the beta (BETA-GATE.md): Morro Bay & Avila plus the five Central Coast regions SCB-18 promotes with it. */
const STAGE_1 = ['morro-bay', 'cambria-san-simeon', 'south-big-sur-san-simeon', 'big-sur-coast', 'monterey-point-sur', 'point-arguello-conception'];
const REGIONS = process.env.E2E_REGION_SMOKE_REGIONS ? process.env.E2E_REGION_SMOKE_REGIONS.split(',').map(s => s.trim()).filter(Boolean) : STAGE_1;
const STRICT_ALL = process.env.E2E_REGION_SMOKE_STRICT === '1';
const PHONE = {width: 390, height: 844};
/** The published index at this commit: the region ids and the status each carries (build output of the platform build, never hand-edited). */
const INDEX = JSON.parse(readFileSync(new URL('../dist/regions/index.json', import.meta.url), 'utf8')) as {regions: {id: string; status: string}[]};
const statusOf = (id: string): string => INDEX.regions.find(r => r.id === id)?.status ?? 'missing';

interface Result {check: 'open' | 'verdict' | 'rules' | 'map' | 'fit' | 'errors'; ok: boolean; detail: string}

/** Run one check and record it. A check that throws is a FAIL with the first lines of the error (what was expected, what was seen), never a stop. */
async function record(results: Result[], check: Result['check'], run: () => Promise<string>): Promise<void> {
  try { results.push({check, ok: true, detail: await run()}); }
  catch (error) {
    // eslint-disable-next-line no-control-regex
    const lines = String((error as Error).message ?? error).replace(/\u001b\[[0-9;]*m/g, '').split('\n').map(l => l.trim()).filter(Boolean);
    results.push({check, ok: false, detail: lines.slice(0, 4).join(' / ') || 'failed'});
  }
}

/** Pull the sheet up to its full detent (the handle's End key) and let its slide finish. */
async function openFull(page: Page): Promise<void> {
  const sheet = page.locator('.ui-sheet');
  if ((await sheet.getAttribute('data-detent')) === 'full') return;
  await page.locator('.ui-sheet-handle').press('End');
  await expect(sheet).toHaveAttribute('data-detent', 'full');
  await page.waitForTimeout(600);   // the slide (about 300 ms) has finished
}

/** The funnel spec's stand-ins: this region's committed files for rules and protected areas, and a calm unit-checked forecast at its points. */
async function stubRegion(page: Page, id: string): Promise<void> {
  await stubLiveFeeds(page, {id});
  const definition = JSON.parse(readFileSync(new URL(`../dist/regions/${id}/region.json`, import.meta.url), 'utf8'));
  await page.route('**/api/forecast?*', route => {
    const feed = stubForecast(definition);
    for (const model of Object.values(feed.models) as {data: {latitude: number; longitude: number; hourly: Record<string, unknown>}[]}[]) {
      model.data = model.data.map(point => {
        const url = new URL('https://fixture.invalid/forecast');
        url.search = new URLSearchParams({latitude: String(point.latitude), longitude: String(point.longitude),
          hourly: Object.keys(point.hourly).filter(key => key !== 'time').join(',')}).toString();
        return forecastFixture(url) as never;
      });
    }
    return route.fulfill({json: feed});
  });
}

/** Everything on the page that sticks out of the width, measured as it sits. Parts inside a sideways scroller (their own, or an ancestor's) are fine. */
function overflowProbe(): {page: {scrollWidth: number; clientWidth: number}; out: string[]; clipped: string[]} {
  const vw = document.documentElement.clientWidth;
  const out: string[] = [], clipped: string[] = [];
  const name = (el: Element) => `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''}`;
  const insideScroller = (el: Element): boolean => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const x = getComputedStyle(p).overflowX;
      if (x !== 'visible') { const r = p.getBoundingClientRect(); if (r.left >= -0.5 && r.right <= vw + 0.5) return true; }
    }
    return false;
  };
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('.maplibregl-map, svg, [hidden], [inert], canvas') && !el.closest('.ui-sheet, .app-tabs')) continue;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if ((r.right > vw + 0.5 || r.left < -0.5) && !insideScroller(el)) out.push(`${name(el)} ${Math.round(r.left)}..${Math.round(r.right)}`);
    // Text cut off by its own box: a verdict, rules or brief line whose content is wider than the box that shows it.
    if (el.matches('.app-verdict *, .app-verdict-rules, .app-verdict-rules *, .ui-tile, .ui-tile *, h1, h2') && (el as HTMLElement).scrollWidth > (el as HTMLElement).clientWidth + 1
      && style.overflowX !== 'visible' && style.overflowX !== 'auto' && style.overflowX !== 'scroll') clipped.push(`${name(el)} ${(el as HTMLElement).scrollWidth}>${(el as HTMLElement).clientWidth}`);
  }
  return {page: {scrollWidth: document.documentElement.scrollWidth, clientWidth: vw}, out: [...new Set(out)].slice(0, 12), clipped: [...new Set(clipped)].slice(0, 12)};
}

test.describe('Stage 1 region phone smoke', () => {
  test.beforeEach(({}, info) => {
    test.skip(info.project.name !== 'phone', 'phone project only: this is the 390 px check');
    test.skip(process.env.E2E_WIDE !== '1' && process.env.E2E_REGION_SMOKE !== '1', 'nightly check: runs where E2E_WIDE=1 (scheduled CI) or E2E_REGION_SMOKE=1');
  });
  test.use({viewport: PHONE, hasTouch: true, isMobile: true});

  for (const id of REGIONS) {
    test(`${id}: opens, shows a verdict and the rules card, draws the map, and fits 390 px`, async ({page}, info) => {
      // A region that fails every check waits out each one's timeout (about 15 s each, 30 s for the map); a failing region is a result to report,
      // so the run must not time out first and turn a reported preview into a red run.
      test.setTimeout(180_000);
      const status = statusOf(id), strict = status === 'active' || status === 'missing' || STRICT_ALL;   // a listed region that is not in the index at all is a broken list, never a preview
      const pageErrors: string[] = [];
      page.on('pageerror', error => pageErrors.push(String(error).split('\n')[0]!));
      const results: Result[] = [];

      await record(results, 'open', async () => {
        expect(status, `${id} is in dist/regions/index.json`).not.toBe('missing');
        await stubRegion(page, id);
        await page.goto(`/map?region=${id}&profile=boat`);
        await expect(page).toHaveTitle(/SkipperCast/);
        await expect(page.locator('.app-sheet-brief')).toBeVisible();
        expect(new URL(page.url()).searchParams.get('region'), 'the address keeps the region').toBe(id);
        return `index status ${status}`;
      });

      // Without an open page every later check would only wait out its timeout; say so once instead.
      const opened = results[0]!.ok;
      const later = async (check: Result['check'], run: () => Promise<string>) => opened ? record(results, check, run) : void results.push({check, ok: false, detail: 'not run: the page did not open'});

      await later('verdict', async () => {
        const word = page.locator('.app-verdict .app-verdict-word');
        await expect(word, 'the verdict word is on screen').toBeVisible();
        await expect(word).toHaveText(/^(Comfortable|Marginal|Rough)$/);
        await expect(page.locator('.app-verdict-limit')).toHaveText(/\.$/);
        await expect(word, 'the verdict word is on the first screen, not below the fold').toBeInViewport();
        return `"${await word.innerText()}"`;
      });

      await later('map', async () => {
        const canvas = page.locator('.app-chart canvas.maplibregl-canvas');
        await expect(canvas, 'the map canvas is on screen').toBeVisible();
        const box = (await canvas.boundingBox())!;
        expect(box.width * box.height, 'the canvas has a real size').toBeGreaterThan(50_000);
        await expect.poll(() => page.evaluate(() => performance.getEntriesByName('skippercast-chart-idle').length), {message: 'the Chart reached its first idle frame', timeout: 30_000}).toBeGreaterThan(0);
        await expect(page.locator('.app-poster'), 'the coast poster is gone once the map drew').toHaveCount(0);
        await expect(page.locator('[data-chart-loading-status]'), 'no "loading the chart" notice left').toHaveText('');
        const idle = await page.evaluate(() => Math.round(performance.getEntriesByName('skippercast-chart-idle')[0]!.startTime));
        return `canvas ${Math.round(box.width)}x${Math.round(box.height)}, first idle ${idle} ms`;
      });

      await later('fit', async () => {
        // The first screen (peek), then the sheet pulled to full: the full sheet is where a region's longer wording would run out of its box.
        const seen: string[] = [], problems: string[] = [];
        for (const detent of ['peek', 'full'] as const) {
          if (detent === 'full') await openFull(page);
          const m = await page.evaluate(overflowProbe);
          seen.push(`${detent}: page ${m.page.scrollWidth} wide in ${m.page.clientWidth}`);
          if (m.page.scrollWidth > m.page.clientWidth) problems.push(`${detent}: the page scrolls sideways (${m.page.scrollWidth} > ${m.page.clientWidth})`);
          if (m.out.length) problems.push(`${detent}: outside the screen: ${m.out.join('; ')}`);
          if (m.clipped.length) problems.push(`${detent}: text cut off: ${m.clipped.join('; ')}`);
        }
        if (problems.length) throw new Error(`overflow: ${problems.join(' | ')}`);
        return seen.join(', ');
      });

      await later('rules', async () => {
        // The card DRAWS and can be reached: with the sheet pulled to full, the line, its status badge and the official link are on the
        // screen. Whether it carries a season status is not judged here: the stand-in feed has no daily source checks, so every region reads
        // "Check rules" in this test whatever its signed rules say. The per-region season status is BETA-GATE item 2 (the rules probe,
        // scripts/rules_status_probe.mjs, and its per-region follow-up); the label is reported below only so a reader can see what drew.
        await openFull(page);
        const line = page.locator('.app-verdict-rules');
        await expect(line, 'the rules line is on the page').toBeVisible();
        await line.evaluate(el => el.scrollIntoView({block: 'center'}));
        await expect(line, 'the rules line can be scrolled fully into view').toBeInViewport({ratio: 1});
        const badge = line.locator('.app-mark-regs-badge');
        await expect(badge).toBeVisible();
        const label = (await badge.innerText()).trim(), state = await badge.getAttribute('data-status');
        expect(label, 'the badge says something').not.toBe('');
        await expect(line.locator('a'), 'the official rules link is on screen').toBeVisible();
        await expect(line.locator('a')).toHaveAttribute('href', /^https?:\/\//);
        const words = (await line.innerText()).replace(/\s+/g, ' ').trim();
        return `badge "${label}" (${state}), link ${await line.locator('a').getAttribute('href')}, ${words.length} characters of wording`;
      });

      await record(results, 'errors', async () => {
        expect(pageErrors, 'uncaught page errors').toEqual([]);
        return 'no uncaught page errors';
      });

      const failed = results.filter(r => !r.ok);
      const lines = results.map(r => `${id} | ${r.check}: ${r.ok ? 'PASS' : 'FAIL'} ${r.detail}`);
      const verdict = `${id} (${status}${strict ? ', must pass' : ', reported only'}): ${failed.length ? `${failed.length} of ${results.length} FAILED` : 'all passed'}`;
      console.log([verdict, ...lines.map(l => `  ${l}`)].join('\n'));
      info.annotations.push({type: 'region-smoke', description: verdict}, ...results.map(r => ({type: `${r.check}:${r.ok ? 'PASS' : 'FAIL'}`, description: r.detail})));
      await info.attach(`region-smoke-${id}.json`, {body: JSON.stringify({region: id, status, strict, results}, null, 1), contentType: 'application/json'});
      if (process.env.GITHUB_STEP_SUMMARY) {
        const cell = (check: Result['check']) => results.filter(r => r.check === check).map(r => (r.ok ? 'PASS' : `**FAIL** ${r.detail.replace(/\|/g, '/')}`)).join('; ');
        const row = `- **${id}** (${status}${strict ? ', must pass' : ', reported only'}): open ${cell('open')} · verdict ${cell('verdict')} · rules ${cell('rules').slice(0, 90)} · map ${cell('map')} · fit ${cell('fit')} · errors ${cell('errors')}\n`;
        try { appendFileSync(process.env.GITHUB_STEP_SUMMARY, row); } catch { /* the summary is a courtesy */ }
      }
      if (strict) expect(failed.map(r => `${r.check}: ${r.detail}`), `${id} is ${STRICT_ALL && status !== 'active' ? 'held to the full check by E2E_REGION_SMOKE_STRICT' : 'active'} and must pass every check`).toEqual([]);
    });
  }
});
