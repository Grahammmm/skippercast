import {test, expect, openMap} from './fixtures.ts';
import {readFileSync} from 'node:fs';
import {boundaryEnvelopeMatches, stubBoundaryChecks} from './boundary-fixture.ts';

test('boundary envelopes compare numerically and reject a different saved region or service', () => {
  const saved = JSON.parse(readFileSync('dist/data/protected-areas.geojson', 'utf8'));
  const bounds = [-121.9, 34.95, -120.55, 35.85];
  expect(boundaryEnvelopeMatches(saved.source_url, bounds)).toBe(true);
  const equivalent = new URL(saved.source_url);
  equivalent.searchParams.set('geometry', '-121.900,34.950,-120.550,35.850');
  expect(boundaryEnvelopeMatches(equivalent.href, bounds)).toBe(true);
  equivalent.searchParams.set('geometry', '-124.2,38.4,-122.85,39.0');
  expect(boundaryEnvelopeMatches(equivalent.href, [-124.2, 38.4, -122.85, 39])).toBe(true);
  expect(boundaryEnvelopeMatches(saved.source_url, [-123.7, 37.95, -122.7, 38.5])).toBe(false);
  equivalent.hostname = 'example.test';
  expect(boundaryEnvelopeMatches(equivalent.href, [-124.2, 38.4, -122.85, 39])).toBe(false);
  expect(boundaryEnvelopeMatches(undefined, bounds)).toBe(false);
  expect(boundaryEnvelopeMatches('not a URL', bounds)).toBe(false);
});

test('both fixture routes reject a wrong saved region and a mismatched request envelope', async () => {
  const handlers: Array<{match: unknown; handle: (route: any) => Promise<void>}> = [];
  await stubBoundaryChecks({route: async (match: unknown, handle: (route: any) => Promise<void>) => {
    handlers.push({match, handle});
  }} as any);
  const saved = JSON.parse(readFileSync('dist/data/protected-areas.geojson', 'utf8'));
  async function response(index: number, url: string, region: string) {
    let result = '';
    await handlers[index].handle({request: () => ({url: () => url,
      frame: () => ({url: () => `http://localhost/?region=${region}#map`})}),
      abort: async () => { result = 'aborted'; },
      fulfill: async (value: {status?: number}) => { result = String(value.status || 200); },
      fallback: async () => { result = 'fallback'; }});
    return result;
  }
  for (const region of ['morro-bay', 'cambria-san-simeon']) {
    expect(await response(0, saved.source_url, region)).toBe('200');
    expect(await response(1, `http://localhost/api/daily?region=${region}&part=mpa-boundaries`, region)).toBe('200');
  }
  const wrongQuery = new URL(saved.source_url);
  wrongQuery.searchParams.set('geometry', '-123.7,37.95,-122.7,38.5');
  expect(await response(0, wrongQuery.href, 'morro-bay')).toBe('aborted');
  expect(await response(0, wrongQuery.href, 'bodega-point-reyes')).toBe('aborted');
  for (const part of ['mpa-boundaries', 'additional-closures']) {
    expect(await response(1, `http://localhost/api/daily?region=bodega-point-reyes&part=${part}`, 'bodega-point-reyes')).toBe('503');
  }
});

test('a simulated current boundary check draws the map without the upstream feed', async ({page, pageErrors}) => {
  await page.route('**/feeds/data/**', route => route.fulfill({status: 503, json: {error: 'Offline boundary test'}}));
  await openMap(page);
  await expect(page.locator('#mpa-status')).toContainText('checked now');
  await expect(page.locator('#mpa-status')).not.toHaveClass(/error/);
  expect(pageErrors).toEqual([]);
});

test('unavailable current boundary checks still withhold fishing targets', async ({page, pageErrors}) => {
  const saved = JSON.parse(readFileSync('dist/data/protected-areas.geojson', 'utf8'));
  saved.checked_at = new Date(Date.now() - 72 * 3600_000).toISOString();
  await page.route('**/data/protected-areas.geojson', route => route.fulfill({json: saved}));
  await page.route(url => url.hostname === 'services2.arcgis.com', route => route.abort('blockedbyclient'));
  await page.route('**/api/daily?*', route => route.fulfill({status: 503, json: {error: 'Offline boundary test'}}));
  await page.route('**/feeds/data/**', route => route.fulfill({status: 503, json: {error: 'Offline boundary test'}}));
  await page.goto('/?region=morro-bay#map');
  await expect(page.locator('#mpa-status')).toContainText('live check unavailable');
  await expect(page.locator('#mpa-status')).toHaveClass(/error/);
  await expect(page.locator('#map .target-pin, #map .reef-cluster')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});
