// SC2207-11: the first answer's token styles (web/app/app.css, "SC2207-11: first answer") in a real browser.
// Component evidence: the production FirstAnswerLine (web/app/App.tsx) and the production sheets (tokens, ui, app) are
// bundled by esbuild into a page whose host is exactly 320 px or 1440 px wide, with a fixed clock and synthetic state, so the
// width is the section's available inline-size. That is NOT evidence that the phone shell mounts the section: under
// 1,024 px the app mounts the mobile layout, which has no first-answer section (the third test pins that).
// Every API/feed request is answered by a stub or aborted (e2e/fixtures.ts); nothing here changes copy or verdict logic.
import {build} from 'esbuild';
import type {Page} from '@playwright/test';
import {test, expect} from './fixtures.ts';
import {contrast} from '../scripts/check_contrast.mjs';
import {rendererPlugins} from '../tests/helpers/esbuild-url.mjs';

const AREA = {region: 'morro-bay'};
const NOW = '2026-09-30T16:00:00Z';   // 9 am PDT; tomorrow is 1 October
const FISHABLE_ROLE = {yes: 'mint', marginal: 'amber', no: 'coral', unknown: 'muted'} as const;
type Fishable = keyof typeof FISHABLE_ROLE;

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => { try { localStorage.setItem('skippercast-profile-v1', 'boat'); } catch { /* storage blocked */ } });
});

/** The production component and sheets in one page; its synthetic state is the one tests/test_first_answer.mjs drives. */
async function bundleHost() {
  return build({stdin: {resolveDir: process.cwd(), loader: 'ts', contents: `
    import {render, h} from 'preact';
    import {FirstAnswerLine, regionInfo} from './web/app/App.tsx';
    import {dailyFeed, regionalForecast} from './web/brief/Brief.tsx';
    import {parseConditionsForecast} from './web/conditions.ts';
    import {regsData} from './web/regs.ts';
    import {species, profile, hour, day} from './web/state.ts';
    import {region} from './tests/fixtures/regulations/fe61-v1.json';
    import daily from './tests/fixtures/brief/monterey-daily.json';
    import './web/tokens.css'; import './web/ui/ui.css'; import './web/app/app.css';
    const NOW = new Date(${JSON.stringify(NOW)});
    function forecastFeed(id, wind) {
      const start = Date.parse('2026-09-29T07:00:00Z') / 1000, time = Array.from({length: 16 * 24}, (_, i) => start + i * 3600);
      const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
        hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
      const meta = {last_run_initialisation_time: NOW.getTime() / 1000 - 6 * 3600, data_end_time: time.at(-1)};
      return {region_id: id, retrieved: NOW.getTime() - 20 * 60_000, requested_points: [['monterey-bay', 36.7, -121.95], ['offshore-0-0', 36.5, -122.25]],
        models: {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [wind, 'kn'], wind_gusts_10m: [wind + 4, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
          ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [wind > 20 ? 14 : 2, 'ft'], wave_period: [12, 's']}))}}};
    }
    // No rules on the region: the card then reads "Rules unavailable" and never fetches regulations. The fixture pipeline holds a clear day at
    // Marginal (tests/test_first_answer.mjs says so), so the Yes state is the Marginal render with the attribute the CSS keys on set to yes.
    window.__fa = {
      show(state) {
        const live = state === 'yes' ? 'marginal' : state;
        regionInfo.value = {id: region.id, name: region.name, center: region.map.center, timezone: region.timezone};
        dailyFeed.value = live === 'unknown' ? null : {...daily, region_id: region.id};
        regionalForecast.value = live === 'unknown' ? null : parseConditionsForecast(forecastFeed(region.id, live === 'no' ? 30 : 5), region.id, region.map.center);
        regsData.value = null; species.value = 'salmon'; profile.value = 'boat'; hour.value = null; day.value = null;
        render(null, document.getElementById('host'));
        render(h(FirstAnswerLine, {now: NOW}), document.getElementById('host'));
        if (state === 'yes') document.querySelector('#host .app-first-answer').setAttribute('data-fishable', 'yes');
      },
    };`}, bundle: true, format: 'iife', outfile: 'fa-host.js', write: false, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  plugins: rendererPlugins, loader: {'.woff2': 'dataurl'}});
}

async function openHost(page: Page, bundle: Awaited<ReturnType<typeof bundleHost>>, width: number, theme: 'dark' | 'light') {
  await page.route('**/first-answer-host', route => route.fulfill({contentType: 'text/html',
    body: `<!doctype html><html lang="en"${theme === 'light' ? ' data-theme="light"' : ''}><title>First answer host</title><body><div id="host"></div></body></html>`}));
  await page.setViewportSize({width, height: 800});
  await page.goto('/first-answer-host');
  await page.addStyleTag({content: bundle.outputFiles.find(f => f.path.endsWith('.css'))!.text});
  await page.addScriptTag({content: bundle.outputFiles.find(f => f.path.endsWith('.js'))!.text});
  await page.evaluate(w => { document.body.style.margin = '0'; document.getElementById('host')!.style.width = `${w}px`; }, width);
}

const hex = (rgb: string): string => {
  const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/.exec(rgb);
  if (!m) throw Error(`not an opaque rgb colour: ${rgb}`);
  if (m[4] !== undefined && Number(m[4]) !== 1) throw Error(`translucent colour: ${rgb}`);
  return `#${[m[1], m[2], m[3]].map(v => Number(v).toString(16).padStart(2, '0')).join('')}`;
};

test('first_answer_wraps_at_320_and_desktop: the production component fits its host in every state and theme (component-width evidence, not mobile mounting evidence)', async ({page, pageErrors}) => {
  const bundle = await bundleHost();
  for (const theme of ['dark', 'light'] as const) {
    for (const width of [320, 1440]) {
      await page.unroute('**/first-answer-host');
      await openHost(page, bundle, width, theme);
      for (const state of Object.keys(FISHABLE_ROLE) as Fishable[]) {
        const label = `${theme} ${width}px ${state}`;
        await page.evaluate(s => (window as unknown as {__fa: {show(s: string): void}}).__fa.show(s), state);
        const section = page.locator('#host .app-first-answer');
        await expect(section, label).toHaveAttribute('data-fishable', state);
        const words = await section.evaluate(el => el.textContent);
        // A long unbroken reason and a long link text: the section must wrap them, not widen or clip.
        const stress = await page.evaluate(() => {
          const s = document.querySelector('#host .app-first-answer')!;
          s.querySelector('.app-first-answer-reason')!.textContent += ' ' + 'wind-and-seas-'.repeat(24);
          s.querySelector('.app-first-answer-rules a')!.textContent = 'https://example.invalid/' + 'official-rules-'.repeat(12);
          return true;
        });
        expect(stress).toBe(true);
        const m = await page.evaluate(() => {
          const host = document.getElementById('host')!, sec = host.querySelector<HTMLElement>('.app-first-answer')!;
          const root = getComputedStyle(document.documentElement), token = (n: string) => root.getPropertyValue(`--${n}`).trim();
          const box = (el: Element) => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, r: r.right, b: r.bottom, w: r.width, h: r.height}; };
          const parts = ['.app-first-answer-line', '.app-first-answer-reason', '.app-first-answer-rules', '.app-first-answer-more'].map(sel => {
            const el = sec.querySelector<HTMLElement>(sel)!, cs = getComputedStyle(el);
            return {sel, ...box(el), color: cs.color, bg: cs.backgroundColor, sw: el.scrollWidth, cw: el.clientWidth, sh: el.scrollHeight, ch: el.clientHeight,
              overflow: cs.overflow, clamp: cs.webkitLineClamp, textOverflow: cs.textOverflow, margin: cs.marginTop + '/' + cs.marginBottom};
          });
          const a = sec.querySelector<HTMLElement>('.app-first-answer-rules a')!, acs = getComputedStyle(a);
          const scs = getComputedStyle(sec);
          return {host: box(host), sec: box(sec), parts, anchor: {...box(a), color: acs.color, deco: acs.textDecorationLine},
            section: {color: scs.color, bg: scs.backgroundColor, minWidth: scs.minWidth, gridCols: scs.gridTemplateColumns, height: scs.height},
            doc: document.documentElement.scrollWidth, view: window.innerWidth,
            tokens: Object.fromEntries(['mint', 'amber', 'coral', 'muted', 'text', 'blue', 'panel', 'panel-2'].map(n => [n, token(n)]))};
        });
        // Inside the host, no horizontal overflow, nothing clipped, nothing overlapping.
        expect(Math.round(m.sec.w), label).toBe(width);
        expect(m.sec.x, label).toBeGreaterThanOrEqual(m.host.x - 0.5);
        expect(m.sec.r, label).toBeLessThanOrEqual(m.host.r + 0.5);
        expect(m.doc, `${label}: no horizontal page scroll`).toBeLessThanOrEqual(m.view);
        let previous = m.sec.y;
        for (const p of m.parts) {
          expect(p.x, `${label} ${p.sel} left`).toBeGreaterThanOrEqual(m.sec.x - 0.5);
          expect(p.r, `${label} ${p.sel} right`).toBeLessThanOrEqual(m.sec.r + 0.5);
          expect(p.y, `${label} ${p.sel} does not overlap the one above`).toBeGreaterThanOrEqual(previous - 0.5);
          expect(p.sw, `${label} ${p.sel} content is not wider than its box`).toBeLessThanOrEqual(p.cw + 1);
          expect(p.sh, `${label} ${p.sel} content is not taller than its box`).toBeLessThanOrEqual(p.ch + 1);
          expect(p.clamp === 'none' || p.clamp === undefined, `${label} ${p.sel} no line clamp`).toBe(true);
          expect(p.textOverflow, `${label} ${p.sel} no ellipsis`).toBe('clip');
          previous = p.b;
        }
        expect(m.anchor.r, `${label} link right`).toBeLessThanOrEqual(m.sec.r + 0.5);
        expect(m.anchor.deco, `${label}: the link is underlined`).toBe('underline');
        expect(m.sec.b, label).toBeGreaterThanOrEqual(previous - 0.5);
        expect(await section.evaluate(el => el.textContent!.length), `${label}: the words stay`).toBeGreaterThan((words ?? '').length);
        // Computed colours are the declared roles, and the existing contrast function holds each pair at 4.5:1.
        const tok = m.tokens;
        const heading = m.parts[0]!, reason = m.parts[1]!, rules = m.parts[2]!, more = m.parts[3]!;
        expect(hex(heading.color), `${label} heading`).toBe(tok[FISHABLE_ROLE[state]]);
        expect(hex(reason.color), label).toBe(tok.text);
        expect(hex(rules.color), label).toBe(tok.muted);
        expect(hex(m.anchor.color), label).toBe(tok.blue);
        expect(hex(m.section.bg), `${label}: opaque --panel backing`).toBe(tok.panel);
        expect(hex(more.bg), `${label}: the shared ghost Button backing`).toBe(tok['panel-2']);
        expect(hex(more.color), label).toBe(tok.text);
        for (const [what, fg, bg] of [['heading', heading.color, m.section.bg], ['reason', reason.color, m.section.bg], ['rules', rules.color, m.section.bg],
          ['link', m.anchor.color, m.section.bg], ['action', more.color, more.bg]] as const)
          expect(contrast(hex(fg), hex(bg)), `${label} ${what} contrast`).toBeGreaterThanOrEqual(4.5);
        // Colour is never the only cue: unknown is muted (not mint) and each state's own words are on the page.
        if (state === 'unknown') expect(hex(heading.color)).not.toBe(tok.mint);
      }
    }
  }
  expect(pageErrors).toEqual([]);
});

test('first_answer_links_and_map_action_keep_keyboard_behavior: the desktop app keeps order, link attributes, visible focus and the map action', async ({page, pageErrors, v2}) => {
  await page.addInitScript(() => {
    (window as unknown as {__scrolled: string[]}).__scrolled = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element, ...args: unknown[]) {
      (window as unknown as {__scrolled: string[]}).__scrolled.push(String(this.className));
      return (original as (...a: unknown[]) => void).apply(this, args);
    };
  });
  await v2.open('app', AREA, 'desktop');
  const section = page.locator('section.app-first-answer');
  await expect(section).toBeVisible();
  const heading = section.locator('h2.app-first-answer-line'), reason = section.locator('p.app-first-answer-reason'), rules = section.locator('p.app-first-answer-rules');
  const more = section.locator('button.app-first-answer-more'), link = rules.locator('a');
  await expect(heading).toBeVisible(); await expect(reason).toBeVisible(); await expect(rules).toBeVisible();
  const ys = [heading, reason, rules, more].map(async l => (await l.boundingBox())!.y);
  const [h, r, p, b] = await Promise.all(ys);
  expect(h! < r! && r! < p! && p! < b!, 'heading, reason, rules, action in order').toBe(true);
  // Answer before map: the section sits above the stage, and the 300 px brief column is unchanged.
  const stage = (await page.locator('section.app-stage').boundingBox())!, secBox = (await section.boundingBox())!;
  expect(secBox.y + secBox.height).toBeLessThanOrEqual(stage.y + 0.5);
  expect(Math.round((await page.locator('aside.app-brief').boundingBox())!.width)).toBe(300);
  await expect(link).toHaveText('Official rules');
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(link).toHaveAttribute('rel', 'noopener');
  expect(await link.getAttribute('href')).toMatch(/^https:\/\//);
  // Keyboard: Tab reaches the link, which shows the token focus ring.
  await page.locator('body').focus();
  let reached = false;
  for (let i = 0; i < 40 && !reached; i++) {
    await page.keyboard.press('Tab');
    reached = await link.evaluate(el => el === document.activeElement);
  }
  expect(reached, 'Tab reaches the Official rules link').toBe(true);
  const ring = await link.evaluate(el => { const cs = getComputedStyle(el), root = getComputedStyle(document.documentElement);
    return {width: cs.outlineWidth, style: cs.outlineStyle, colour: cs.outlineColor, offset: cs.outlineOffset, focus: root.getPropertyValue('--focus').trim(), mint: root.getPropertyValue('--mint').trim()}; });
  expect(ring.style).toBe('solid'); expect(ring.width).toBe('2px'); expect(ring.offset).toBe('2px');
  expect(hex(ring.colour)).toBe(ring.focus || ring.mint);
  // The action is the shared 44 px ghost Button, reachable by Tab, and Enter scrolls the existing map/detail into view.
  expect((await more.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await expect(more).toHaveClass(/ui-button--ghost/);
  await more.focus();
  await expect(more).toBeFocused();
  await page.keyboard.press('Enter');
  expect(await page.evaluate(() => (window as unknown as {__scrolled: string[]}).__scrolled)).toContain('app-main');
  expect(pageErrors).toEqual([]);
});

test('mobile_shell_stays_map_first_without_duplicate_answer: the 320 px app keeps its sheet verdict and map and mounts no first-answer section', async ({page, pageErrors, v2}) => {
  await v2.open('app', AREA, 'narrow');
  await expect(page.locator('section.app-stage')).toBeVisible();
  await expect(page.locator('.ui-sheet')).toHaveAttribute('data-detent', 'peek');
  await expect(page.locator('.ui-sheet h1')).toBeInViewport();
  await expect(page.locator('.app-tabs a')).toHaveCount(4);
  // Absence is the mobile shell's own behaviour (BF-one-answer mounts the section on desktop only); the component-width test above
  // is the proof that the section is readable at 320 px.
  await expect(page.locator('.app-first-answer')).toHaveCount(0);
  await expect(page.locator('aside.app-brief')).toHaveCount(0);
  const stage = (await page.locator('section.app-stage').boundingBox())!;
  expect([Math.round(stage.x), Math.round(stage.y), Math.round(stage.width), Math.round(stage.height)]).toEqual([0, 0, 320, 568]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  expect(pageErrors).toEqual([]);
});
