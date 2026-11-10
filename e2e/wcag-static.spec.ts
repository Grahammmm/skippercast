// SC1722-17: the sources, coverage, status and licences pages on phones and desktops: no serious or critical
// axe finding (target-size and nested-interactive run explicitly), list links at the app's touch height, a
// decorative coverage drawing with the region list as its only navigation, and tables that scroll inside their
// own wrapper so the page never scrolls sideways. The pages read only the local Worker's static files; the
// status feeds answer 404 (e2e/fixtures.ts) unless a test stubs the region list.
import AxeBuilder from '@axe-core/playwright';
import {test, expect, checkA11y} from './fixtures.ts';
import type {Page} from '@playwright/test';

const PAGES = [['sources', '/sources'], ['coverage', '/coverage'], ['status', '/status'], ['licenses', '/licenses.html']] as const;
const BLOCKING = new Set(['serious', 'critical']);

/** Open a page and wait until its own content (not a loading line) is on screen. */
async function open(page: Page, name: string, path: string): Promise<void> {
  expect((await page.goto(path))?.status()).toBe(200);
  await expect(page.locator('h1')).toBeVisible();
  if (name === 'coverage') {
    await expect(page.locator('#coverage-map svg')).toBeVisible();
    await expect(page.locator('#coverage-list li a').first()).toBeVisible();
  }
  if (name === 'status') await expect(page.locator('#status-rows table').first()).toBeVisible();
  if (name === 'sources') await expect(page.locator('#sources-content li > a').first()).toBeVisible();
  if (name === 'licenses') await expect(page.locator('table').first()).toBeAttached();
  await page.evaluate(() => document.fonts.ready);
}

/** Axe with the WCAG 2.2 AA tag, so target-size is in the run; both rules must have been evaluated. */
async function checkTargets(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'])
    .options({rules: {'target-size': {enabled: true}, 'nested-interactive': {enabled: true}}}).analyze();
  const ran = new Set([...results.passes, ...results.violations, ...results.incomplete, ...results.inapplicable].map(r => r.id));
  expect(ran.has('target-size') && ran.has('nested-interactive'), `target-size and nested-interactive ran on ${label}`).toBe(true);
  const blocking = results.violations.filter(v => BLOCKING.has(String(v.impact))).map(v => ({id: v.id, nodes: v.nodes.map(n => n.target.join(' ')).slice(0, 5)}));
  expect(blocking, `serious or critical axe violations on ${label}`).toEqual([]);
}

const touchMin = (page: Page) => page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--touch-min')));
const overflow = (page: Page) => page.evaluate(() => ({inner: innerWidth, doc: document.documentElement.scrollWidth, body: document.body.scrollWidth, x: scrollX}));

for (const width of [390, 1440]) {
  test.describe(`at ${width} px`, () => {
    test.use({viewport: {width, height: 900}, isMobile: false, hasTouch: false});

    for (const [name, path] of PAGES) {
      test(`${name} has a description and no serious or critical axe finding`, async ({page, pageErrors}) => {
        await open(page, name, path);
        const description = await page.locator('meta[name="description"]').evaluateAll(tags => tags.map(tag => tag.getAttribute('content')));
        expect(description.length, 'exactly one description').toBe(1);
        expect(description[0]!.trim().length).toBeGreaterThan(20);
        await checkA11y(page, `static-${name}-${width}`, test.info().project.name);
        await checkTargets(page, `${name} at ${width}`);
        expect(pageErrors).toEqual([]);
      });
    }

    test('every source link and region link is at least the touch height', async ({page}) => {
      await open(page, 'sources', '/sources');
      const min = await touchMin(page);
      expect(min).toBeGreaterThanOrEqual(44);
      const sources = await page.locator('#sources-content li > a').evaluateAll(links => links.map(link => link.getBoundingClientRect().height));
      expect(sources.length).toBeGreaterThanOrEqual(8);
      for (const height of sources) expect(height).toBeGreaterThanOrEqual(min - 0.5);
      await open(page, 'coverage', '/coverage');
      const regions = await page.locator('#coverage-list li > a').evaluateAll(links => links.map(link => link.getBoundingClientRect().height));
      expect(regions.length).toBe(await page.locator('#coverage-map rect.cov-active, #coverage-map rect.cov-preview').count());
      for (const height of regions) expect(height).toBeGreaterThanOrEqual(min - 0.5);
    });
  });
}

test.describe('a region with a long name, an empty list and an unreadable list', () => {
  test.use({viewport: {width: 390, height: 900}, isMobile: false, hasTouch: false});

  test('a long wrapped region name keeps its link at least the touch height and inside the page', async ({page}) => {
    const index = await (await page.request.get('/regions/index.json')).json();
    for (const region of index.regions) region.name = `Synthetic region with a very long name that must wrap onto several lines ${'Extraordinarily'.repeat(6)}`;
    await page.route('**/regions/index.json', route => route.fulfill({json: index}));
    await open(page, 'coverage', '/coverage');
    const link = page.locator('#coverage-list li > a').first();
    const [box, min] = [(await link.boundingBox())!, await touchMin(page)];
    expect(box.height).toBeGreaterThan(min * 2);
    const widths = await overflow(page);
    expect(widths.doc).toBeLessThanOrEqual(widths.inner);
    await checkTargets(page, 'coverage with a long region name');
  });

  for (const [label, respond] of [
    ['an empty index', (route: import('@playwright/test').Route) => route.fulfill({json: {regions: []}})],
    ['an unreadable index', (route: import('@playwright/test').Route) => route.fulfill({status: 500, json: {error: 'x'}})],
  ] as const) {
    test(`coverage with ${label} passes axe and shows no drawing`, async ({page}) => {
      await page.route('**/regions/index.json', respond);
      expect((await page.goto('/coverage'))?.status()).toBe(200);
      await expect(page.locator('#coverage-list p')).toBeVisible();
      await expect(page.locator('#coverage-map svg')).toHaveCount(0);
      await checkA11y(page, `static-coverage-${label.replace(/\W+/g, '-')}`, test.info().project.name);
      await checkTargets(page, `coverage with ${label}`);
    });
  }
});

test.describe('the coverage drawing', () => {
  test.use({viewport: {width: 390, height: 900}, isMobile: false, hasTouch: false});

  test('is decorative, holds no controls, and the region list is the only way to a region', async ({page}) => {
    await open(page, 'coverage', '/coverage');
    const svg = page.locator('#coverage-map svg');
    await expect(svg).toHaveAttribute('aria-hidden', 'true');
    await expect(svg).toHaveAttribute('focusable', 'false');
    expect(await svg.locator('a, button, input, select, textarea, [tabindex], [role="link"], [role="button"]').count()).toBe(0);
    const rects = await svg.locator('rect.cov-active, rect.cov-preview').count();
    const hrefs = await page.locator('#coverage-list li > a').evaluateAll(links => links.map(link => link.getAttribute('href')));
    expect(hrefs.length).toBe(rects);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    for (const href of hrefs) expect(href).toMatch(/^\/map\?region=[a-z0-9-]+$/);
    // Keyboard: Tab from the first region link lands on the second region link, never on a drawn box.
    await page.locator('#coverage-list li > a').first().focus();
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => document.activeElement?.closest('#coverage-list li > a') !== null && !document.activeElement?.closest('svg'))).toBe(true);
    expect(await page.evaluate(() => document.activeElement?.getAttribute('href'))).toBe(hrefs[1]);
  });
});

test.describe('at 360 px', () => {
  test.use({viewport: {width: 360, height: 740}, isMobile: false, hasTouch: false});

  for (const [name, path] of PAGES) {
    test(`${name} does not scroll sideways`, async ({page}) => {
      await open(page, name, path);
      const widths = await overflow(page);
      expect(widths.inner, 'the layout viewport is 360 px').toBe(360);
      expect(widths.doc, 'document scrollWidth').toBeLessThanOrEqual(widths.inner);
      expect(widths.body, 'body scrollWidth').toBeLessThanOrEqual(widths.inner);
      if (name === 'coverage') {
        const [svg, column] = await page.evaluate(() => [document.querySelector('#coverage-map svg')!.getBoundingClientRect().right, document.querySelector('main')!.getBoundingClientRect().right]);
        expect(svg!).toBeLessThanOrEqual(column! + 0.5);
      }
    });
  }

  test('every status group scrolls inside its own wrapper, by keyboard, without moving the page', async ({page}) => {
    const index = await (await page.request.get('/regions/index.json')).json();
    for (const region of index.regions) region.name = 'W'.repeat(90);   // an unbreakable name wider than the phone
    await page.route('**/regions/index.json', route => route.fulfill({json: index}));
    await open(page, 'status', '/status');
    const wraps = page.locator('#status-rows .forecast-table-wrap');
    expect(await wraps.count()).toBeGreaterThanOrEqual(3);
    for (const info of await wraps.evaluateAll(nodes => nodes.map(node => ({
      overflowX: getComputedStyle(node).overflowX, role: node.getAttribute('role'), tabindex: node.getAttribute('tabindex'),
      name: node.getAttribute('aria-label'), tables: node.querySelectorAll(':scope > table').length, width: node.getBoundingClientRect().width,
    })))) {
      expect(info).toMatchObject({overflowX: 'auto', role: 'region', tabindex: '0', tables: 1});
      expect(info.name).toMatch(/ data table$/);
      expect(info.width).toBeLessThanOrEqual(360);
    }
    const wide = wraps.first();
    expect(await wide.evaluate(node => node.scrollWidth > node.clientWidth)).toBe(true);
    await wide.focus();
    for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight');
    await expect.poll(() => wide.evaluate(node => node.scrollLeft)).toBeGreaterThan(0);
    const widths = await overflow(page);
    expect(widths.doc).toBeLessThanOrEqual(widths.inner);
    expect(widths.x).toBe(0);
    await expect(wide.locator('table thead th[scope="col"]')).toHaveCount(4);
    await expect(wide.locator('tbody th[scope="row"]', {hasText: 'Buoys: WWWW'})).toHaveCount(index.regions.length);
  });

  test('the licences and sources tables are in their own named scrollers', async ({page}) => {
    await open(page, 'licenses', '/licenses.html');
    const licence = page.locator('.forecast-table-wrap');
    await expect(licence).toHaveCount(1);
    await expect(licence).toHaveAttribute('aria-labelledby', 'data');
    await expect(licence.locator('table')).toHaveCount(1);
    expect(await licence.evaluate(node => getComputedStyle(node).overflowX)).toBe('auto');
    expect(await licence.evaluate(node => node.getBoundingClientRect().width)).toBeLessThanOrEqual(360);
    await open(page, 'sources', '/sources');
    const wraps = page.locator('.forecast-table-wrap');
    await expect(wraps).toHaveCount(2);
    for (const wrap of await wraps.all()) {
      await expect(wrap).toHaveAttribute('tabindex', '0');
      await expect(wrap).toHaveAttribute('role', 'region');
      await expect(wrap.locator('table')).toHaveCount(1);
      expect(await wrap.evaluate(node => getComputedStyle(node).overflowX)).toBe('auto');
    }
  });
});
