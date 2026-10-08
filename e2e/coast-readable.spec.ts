// FE-86: the readable and information pages (/report, /methodology, /about;
// server/coast-pages.ts) in the v2 visual system. They load web/tokens.css and
// the self-hosted fonts, link to the sources page (open-questions Q16; the
// canonical /sources, #475), and axe finds
// nothing serious (colour contrast included). /report runs with an empty
// region, the explicit-gap page, so the local Worker fetches no upstream report.
import {readFileSync, readdirSync} from 'node:fs';
import {join} from 'node:path';
import {test, expect, checkA11y} from './fixtures.ts';

for (const [name, path] of [['methodology', '/methodology'], ['about', '/about'], ['report-gap', '/report?region=']] as const) {
  test(`the ${name} page uses the v2 tokens and fonts and passes axe`, async ({page, pageErrors}, info) => {
    expect((await page.goto(path))?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.getByRole('navigation', {name: 'Public information'}).getByRole('link', {name: 'How it’s built'})).toHaveAttribute('href', '/sources');
    const look = await page.evaluate(async () => {
      await document.fonts.ready;
      const root = getComputedStyle(document.documentElement), body = getComputedStyle(document.body);
      return {bg: root.getPropertyValue('--bg').trim(), body: body.backgroundColor, color: body.color, font: body.fontFamily, sans: document.fonts.check('15px "DM Sans"')};
    });
    expect(look.bg).toBe('#07131d');
    expect(look.body).toBe('rgb(7, 19, 29)');
    expect(look.color).toBe('rgb(230, 239, 244)');
    expect(look.font).toMatch(/^"DM Sans"/);
    expect(look.sans).toBe(true);
    if (name === 'report-gap') {
      await expect(page.locator('.gap').first()).toBeVisible();
      expect(await page.locator('.gap').first().evaluate(node => getComputedStyle(node).backgroundColor)).toBe('rgb(18, 37, 53)');
    }
    await checkA11y(page, `coast-readable-${name}`, info.project.name);
    expect((await page.request.get('/sources')).status(), 'the sources link resolves').toBe(200);
    expect(pageErrors).toEqual([]);
  });
}

// The populated report needs the upstream source report, which the local Worker
// would fetch from the network. Instead the page is rendered here by the same
// server/coast-pages.ts code from a synthetic report into the built shell, with
// the Worker's headers (CSP included), and answered for one navigation.
test('the populated report (forecast, nearshore, buoys, sources) passes axe with the v2 tokens', async ({page, pageErrors}, info) => {
  const dir = join(import.meta.dirname, '..', 'dist', 'client');
  const shell = readdirSync(dir).find(file => /^coast-readable\.[0-9a-f]{10}\.html$/.test(file));
  expect(shell, 'run pnpm build first').toBeTruthy();
  const g = globalThis as Record<string, unknown>;
  g.REGIONS ??= {}; g.DEPLOYMENT ??= {allowed_origins: ['https://skippercast.com']};
  const {serveCoastPage} = await import('../server/coast-pages.ts');
  const regions = Object.fromEntries(['morro-bay', 'cambria-san-simeon'].map(id => [id, JSON.parse(readFileSync(join(import.meta.dirname, '..', 'regions', id, 'region.json'), 'utf8'))]));
  const now = new Date('2026-10-07T12:00:00Z'), at = now.toISOString();
  const report = {schemaVersion: 1, countyId: 'slo', generatedAt: '2026-10-07T11:50:00Z',
    forecasts: [{id: 'central', sourceId: 'nws', hours: [{at, windKnots: 8, gustKnots: 12, waveFt: 3, wavePeriodS: 12}]}],
    observations: [{stationId: '46028', observedAt: '2026-10-07T10:30:00Z', waterTempF: 56, waveFt: 4, wavePeriodS: 10, url: 'https://www.ndbc.noaa.gov/'}],
    sources: [{id: 'nws', label: 'NWS forecast', kind: 'forecast', outcome: 'ok', issuedAt: '2026-10-07T10:00:00Z', fetchedAt: '2026-10-07T11:50:00Z', url: 'https://www.weather.gov/'}],
    tides: [], tideEvents: [], alerts: [], catches: [],
    nearshore: [{areaId: 'central', name: 'Synthetic nearshore site', availability: 'available', freshness: 'current', issuedAt: '2026-10-07T10:00:00Z', fetchedAt: '2026-10-07T11:50:00Z', validThrough: '2026-10-07T15:00:00Z', temporalResolutionMinutes: 180, hours: [{at, waveFt: 2, periodS: 11}]}]};
  await page.route('**/report?fixture=populated', async route => {
    const rendered = await serveCoastPage(new Request('https://skippercast.com/report'), {template: readFileSync(join(dir, shell!), 'utf8'), regions, now,
      fetcher: async () => new Response(JSON.stringify(report), {headers: {'Content-Type': 'application/json'}})});
    await route.fulfill({status: rendered.status, headers: Object.fromEntries(rendered.headers), body: await rendered.text()});
  });
  expect((await page.goto('/report?fixture=populated'))?.status()).toBe(200);
  await expect(page.getByText('8 / 12 kt')).toBeVisible();
  await expect(page.locator('article').first()).toBeVisible();
  const look = await page.evaluate(async () => {
    await document.fonts.ready;
    const css = (selector: string) => getComputedStyle(document.querySelector(selector)!);
    return {article: css('article').backgroundColor, scope: css('.scope').backgroundColor, dd: css('dd').fontFamily, mono: document.fonts.check('13px "JetBrains Mono"')};
  });
  expect(look.article).toBe('rgb(14, 29, 43)');
  expect(look.scope).toBe('rgb(18, 37, 53)');
  expect(look.dd).toMatch(/^"JetBrains Mono"/);
  expect(look.mono).toBe(true);
  await checkA11y(page, 'coast-readable-report', info.project.name);
  expect(pageErrors).toEqual([]);
});
