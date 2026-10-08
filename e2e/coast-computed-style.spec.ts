// FE-76 (docs/plans/front-end/design.md § 3A.4 item 5): the token bridge for
// packages/coast leaves v1 unchanged. Computed colours and fonts of fixed
// elements on /coast and in the v1 terrain presentation (the Leaflet page's
// shadow-root workspace) must equal the values recorded from main before the
// literals became var(--coast-…, literal) fallbacks. With the opt-in
// (data-coast-theme="tokens") the same chrome reads web/tokens.css.
//
// The expected values live in e2e/coast-computed-style.json, one block per
// Playwright project. A deliberate coast.css change re-records them:
//   COAST_STYLE_RECORD=1 pnpm exec playwright test e2e/coast-computed-style.spec.ts --workers=1
import {existsSync, readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import type {Page} from '@playwright/test';
import {expect, test} from './fixtures.ts';

const ROOT = join(import.meta.dirname, '..');
const EXPECTED = join(import.meta.dirname, 'coast-computed-style.json');
const RECORD = !!process.env.COAST_STYLE_RECORD;
const PROPS = ['color', 'background-color', 'background-image', 'border-top-color', 'border-right-color', 'border-bottom-color',
  'border-left-color', 'outline-color', 'box-shadow', 'text-shadow', 'accent-color', 'font-family'];
// Elements of dist/coast.html's static template, so the list never depends on loaded data.
const CHROME = ['#scene', '#loading', '.layers', '.layers .select-label', '#layers-toggle', '.layer-row', '.layer-row > span',
  '.layer-controls > .note', '.layer-controls > input[type=range]', '#water', '.relief', '.relief span', '#habitat-status', '#next-reef', '.rankings',
  '.rankings summary', '.gold-dot', '#target-detail', '#target-detail .eyebrow', '#target-close', '#reading', '#reading span', '.view-controls button',
  'footer', '.legend > span', '.depth-ramp', '.ticks', '.map-note', '.gesture', '#sources', '#sources h2', '#sources p', '#sources-close'];
const PAGE = ['body', 'header', 'header .brand', 'header .brand span', 'header .brand small', '#daily-report-open', '#full-report-link',
  '.perspectives', '#perspective-2d', '#perspective-3d', '#home-settings', '#sources-open', '#report-bar', '.intro', '.intro .eyebrow',
  '#place-title', '.intro p', '#location', '.layers > .eyebrow', '.layers h2', '#species', '#home-setup', '.home-art', '.home-contours',
  '.home-art strong', '.home-content > p', '.home-methods label', '.home-methods small', '.home-methods input', '#home-county',
  '.home-submit', '.home-storage', '#report-dialog', '#report-close', '#loading .loader', ...CHROME];

type Styles = Record<string, Record<string, string>>;

/** Computed PROPS of the first match of each selector, in the document or in the workspace's shadow root. */
async function read(page: Page, selectors: string[], shadowHost?: string): Promise<Styles> {
  return page.evaluate(({selectors, props, shadowHost}) => {
    const root: ParentNode = shadowHost ? document.querySelector(shadowHost)!.shadowRoot! : document;
    const out: Record<string, Record<string, string>> = {};
    const pick = (el: Element) => { const s = getComputedStyle(el); return Object.fromEntries(props.map(p => [p, s.getPropertyValue(p)])); };
    if (shadowHost) out[':host'] = pick(document.querySelector(shadowHost)!);
    for (const sel of selectors) { const el = root.querySelector(sel); out[sel] = el ? pick(el) : {missing: 'true'}; }
    return out;
  }, {selectors, props: PROPS, shadowHost});
}

/** One line per element, so a re-recording diffs by element. */
const format = (all: Record<string, Record<string, Styles>>) => {
  const block = (entries: [string, unknown][], indent: string, inner: (value: any) => string) =>
    `{\n${entries.map(([k, v]) => `${indent}${JSON.stringify(k)}: ${inner(v)}`).join(',\n')}\n${indent.slice(1)}}`;
  return block(Object.entries(all), ' ', pages => block(Object.entries(pages), '  ',
    styles => block(Object.entries(styles), '   ', JSON.stringify))) + '\n';
};

function check(project: string, page: string, actual: Styles) {
  const all = existsSync(EXPECTED) ? JSON.parse(readFileSync(EXPECTED, 'utf8')) : {};
  if (RECORD) {
    all[project] = {...all[project], [page]: actual};
    writeFileSync(EXPECTED, format(all));
    return;
  }
  const expected: Styles = all[project]?.[page];
  expect(expected, `no recorded values for ${project} ${page}`).toBeTruthy();
  for (const sel of Object.keys(expected)) expect(actual[sel], `${page} ${sel}`).toEqual(expected[sel]);
}

// The coast bridge and Fish Worker data never decide a style result.
test.beforeEach(async ({context}) => {
  await context.route(/\/(?:api\/coast|coast-data)\//, route => route.fulfill({status: 503, json: {error: 'Offline style test'}}));
});

const openCoast = async (page: Page) => {
  await page.goto('/coast');
  await expect(page.locator('#scene')).toBeAttached();
  await page.waitForLoadState('networkidle');
};
const openWorkspace = async (page: Page) => {
  await page.goto('/?region=morro-bay&presentation=3d');
  // The Leaflet page never goes network-idle; wait for the shadow root's stylesheet instead.
  await expect.poll(() => page.evaluate(() => {
    const root = document.getElementById('coast-workspace')?.shadowRoot;
    return !!root?.getElementById('scene') && [...root.querySelectorAll('link')].every(link => !!link.sheet);
  })).toBe(true);
};

test('/coast computes the same colours and fonts as before the token bridge', async ({page}, info) => {
  await openCoast(page);
  check(info.project.name, '/coast', await read(page, PAGE));
});

test('the v1 terrain presentation computes the same colours and fonts as before the token bridge', async ({page}, info) => {
  await openWorkspace(page);
  check(info.project.name, 'workspace', await read(page, CHROME, '#coast-workspace'));
});

test.describe('with data-coast-theme="tokens"', () => {
  test.skip(RECORD, 'the opt-in has nothing to record');
  // The site's CSP (style-src-elem 'self') rightly refuses injected <style>; only these probes bypass it.
  test.use({bypassCSP: true});
  const css = (file: string) => readFileSync(join(ROOT, file), 'utf8').replace(/@font-face\s*\{[^}]*\}/g, '');
  /** Each bridged pair: the chrome property must equal the web/tokens.css variable computed in the same tree. */
  const PAIRS: [string, string, string][] = [['body', 'background-color', '--bg'], ['body', 'color', '--text'], ['body', 'font-family', '--font-sans'],
    ['header', 'background-color', '--panel'], ['header', 'border-bottom-color', '--line'], ['.view-controls button', 'background-color', '--panel'],
    ['.eyebrow', 'color', '--muted'], ['#perspective-3d', 'background-color', '--mint'], ['#next-reef', 'background-color', '--mint'],
    ['.layer-row', 'border-bottom-color', '--line'], ['.gold-dot', 'background-color', '--amber']];
  // The workspace has no page header, and its perspective buttons are hidden stand-ins.
  const SHADOW_PAIRS = PAIRS.filter(([sel]) => !['body', 'header', '#perspective-3d'].includes(sel));
  const compare = (page: Page, pairs: [string, string, string][], shadowHost?: string) => page.evaluate(({pairs, shadowHost}) => {
    const root: ParentNode = shadowHost ? document.querySelector(shadowHost)!.shadowRoot! : document;
    return pairs.filter(([sel]) => root.querySelector(sel)).map(([sel, prop, token]) => {
      const el = root.querySelector(sel)!, probe = document.createElement('i');
      const property = prop.startsWith('font') ? 'font-family' : 'color';
      probe.style.setProperty(property, `var(${token})`);
      el.parentElement!.append(probe);
      const want = getComputedStyle(probe).getPropertyValue(property);
      probe.remove();
      return [sel, prop, getComputedStyle(el).getPropertyValue(prop), want];
    });
  }, {pairs, shadowHost});

  test('/coast chrome reads web/tokens.css', async ({page}) => {
    await openCoast(page);
    await page.addStyleTag({content: css('web/tokens.css') + css('packages/coast/tokens-bridge.css')});
    await page.evaluate(() => { document.documentElement.dataset.coastTheme = 'tokens'; });
    const rows = await compare(page, PAIRS);
    expect(rows.length).toBe(PAIRS.length);
    for (const [sel, prop, got, want] of rows) expect(got, `${sel} ${prop}`).toBe(want);
  });

  test('the terrain presentation reads web/tokens.css through :host', async ({page}) => {
    await openWorkspace(page);
    await page.addStyleTag({content: css('web/tokens.css')});
    await page.evaluate(bridge => {
      const host = document.getElementById('coast-workspace')!, style = document.createElement('style');
      style.textContent = bridge;
      host.shadowRoot!.append(style);
      host.dataset.coastTheme = 'tokens';
    }, css('packages/coast/tokens-bridge.css'));
    const rows = await compare(page, SHADOW_PAIRS, '#coast-workspace');
    expect(rows.length).toBe(SHADOW_PAIRS.length);
    for (const [sel, prop, got, want] of rows) expect(got, `${sel} ${prop}`).toBe(want);
  });
});
