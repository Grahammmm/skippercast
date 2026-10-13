// Warm the chosen region from the landing (#622, guided first run): once a
// port is chosen, and while the visitor picks how they fish, fetch the files
// the map reads first for that region into the browser cache at low priority,
// so /map opens on revalidated copies instead of full downloads. The list is
// the map's own startup reads (e2e/startup.spec.ts), built from the region's
// regions/<id>/region.json, so any region works: the region file, the startup
// copies the platform build writes beside it (src/skippercast/platform/
// startup_forms.py; a region without a shoreline has no overview or poster,
// and the map asks for them anyway), the protected areas its `assets` name,
// and the regional forecast (edge-cached for five minutes, so the map's read
// is answered from the cache). Only the chosen region is fetched, nothing
// under Save-Data, and a failure is quiet: the map loads as it would have.
// Erasable syntax only: tests/test_landing.mjs imports this file by type stripping.
import {saveData} from './save-data.ts';

export type WarmState = 'loading' | 'ready' | 'failed' | 'skipped';

/** A same-origin data path a region file may name: no scheme, no parent step, JSON or GeoJSON. */
const DATA_PATH = /^(?:data|regions)\/[\w./-]+\.(?:geo)?json$/;

/**
 * What the map reads first for `region`, given its parsed region.json: the
 * region file itself (read again by the map, so it is warmed too), its startup
 * copies, its protected areas and its forecast. Unknown or unsafe asset paths
 * are left out.
 */
export function regionWarmList(region: string, info: unknown): string[] {
  const base = `regions/${encodeURIComponent(region)}`;
  const list = [`${base}/region.json`, `${base}/atlas-marks.json`, `${base}/search-plan-index.json`, `${base}/shoreline-overview.geojson`, `${base}/poster.svg`];
  const mpa = (info as {assets?: {protected_areas?: unknown} | null} | null)?.assets?.protected_areas;
  if (typeof mpa === 'string' && DATA_PATH.test(mpa) && !mpa.includes('..')) list.push(mpa);
  list.push(`/api/forecast?region=${encodeURIComponent(region)}`);
  return list;
}

/**
 * Fetch `region`'s startup files once (resolved against `page`); resolves
 * with what happened and the paths asked for. Never rejects.
 */
export async function warmRegion(region: string, page: string, fetchFn: typeof fetch = (...a) => fetch(...a), nav: unknown = globalThis.navigator): Promise<{state: Exclude<WarmState, 'loading'>; paths: string[]}> {
  if (saveData(nav)) return {state: 'skipped', paths: []};
  const low = {priority: 'low'} as RequestInit;
  try {
    const first = `regions/${encodeURIComponent(region)}/region.json`;
    const response = await fetchFn(new URL(first, page).href, low);
    if (!response.ok) return {state: 'failed', paths: [first]};
    const paths = regionWarmList(region, await response.json());
    const rest = paths.filter(p => p !== first);
    const results = await Promise.all(rest.map(p => fetchFn(new URL(p, page).href, low).then(r => r.blob().then(() => r.ok), () => false)));
    // The startup copies are optional per region (see above), so only the files every region has decide "ready".
    const required = rest.map((p, i) => ({p, ok: results[i]})).filter(e => !/\/(?:shoreline-overview\.geojson|poster\.svg)$/.test(e.p));
    return {state: required.every(e => e.ok) ? 'ready' : 'failed', paths};
  } catch { return {state: 'failed', paths: []}; }
}
