// Offline boundary checks for browser tests. Use the committed regional
// polygons; only the simulated check time is current. No production gate,
// geometry or timeout changes, and per-test routes can override these responses.
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import type {BrowserContext} from '@playwright/test';

const root = resolve(import.meta.dirname, '..');
const read = (path: string) => JSON.parse(readFileSync(resolve(root, path), 'utf8'));
const directory = read('dist/regions/index.json');
const service = 'https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query';

function packet(id: string) {
  const entry = directory.regions.find((row: {id: string}) => row.id === id);
  if (!entry) return null;
  const region = read(`dist/${entry.config}`);
  return {region, mpas: read(`dist/${region.assets.protected_areas}`),
    closures: region.assets.closures ? read(`dist/${region.assets.closures}`) : null};
}

export async function stubBoundaryChecks(context: BrowserContext) {
  await context.route(url => url.origin + url.pathname === service, async route => {
    const url = new URL(route.request().url());
    const id = new URL(route.request().frame().url()).searchParams.get('region') || directory.default_region;
    const data = packet(id);
    // Never answer a different geographic query with this region's polygons.
    if (!data || url.searchParams.get('geometry') !== data.region.mpa.bounds.join(',')) {
      await route.abort('blockedbyclient');
      return;
    }
    await route.fulfill({json: data.mpas});
  });
  await context.route('**/api/daily?*', async route => {
    const url = new URL(route.request().url());
    const part = url.searchParams.get('part');
    if (part !== 'mpa-boundaries' && part !== 'additional-closures') {
      await route.fallback();
      return;
    }
    const data = packet(url.searchParams.get('region') || directory.default_region);
    if (!data) {
      await route.fulfill({status: 503, json: {error: 'No regional boundary fixture'}});
      return;
    }
    const stamp = new Date().toISOString();
    const source = part === 'mpa-boundaries' ? {geojson: data.mpas}
      : data.closures ? {sha256: data.closures.source_sha256} : null;
    await route.fulfill({json: {schema_version: 1, region_id: data.region.id, part,
      generated_at: stamp, catch_probability: null, bite_score: null,
      sources: source ? {[part]: {status: 'ok', data_retrieved_at: stamp, data: source}} : {}}});
  });
}
