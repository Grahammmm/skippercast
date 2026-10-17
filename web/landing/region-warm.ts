// Warm the chosen region from the landing (#622, guided first run): once a
// port is chosen, and while the visitor picks how they fish, fetch the files
// the map reads first for that region into the browser cache at low priority,
// so /map opens on revalidated copies instead of full downloads. The list is
// the map's own startup reads (e2e/startup.spec.ts), built from the region's
// regions/<id>/region.json, so any region works: the region file, the startup
// copies the platform build writes beside it (src/skippercast/platform/
// startup_forms.py; a region without a shoreline has no overview or poster,
// and the map asks for them anyway), the protected areas its `assets` name
// with the coverage review the protected-area screen reads beside them,
// and the regional forecast (edge-cached for five minutes, so the map's read
// is answered from the cache). Only the chosen region is fetched, nothing
// under Save-Data, and a failure is quiet: the map loads as it would have.
// Erasable syntax only: tests/test_landing.mjs imports this file by type stripping.
import {saveData} from './save-data.ts';

export type WarmState = 'loading' | 'ready' | 'failed' | 'skipped';

/** The protected-area paths the map's screen accepts (web/map/mpa.ts ASSET, equal by test), so nothing is warmed that the map would refuse. */
export const ASSET = /^(?:data|regions\/[a-z0-9-]{1,80})\/[A-Za-z0-9._-]{1,120}\.geojson$/;

/**
 * What the map reads first for `region`, given its parsed region.json: the
 * region file itself (read again by the map, so it is warmed too), its startup
 * copies, its protected areas and coverage review, and its forecast. Unknown or unsafe asset paths
 * are left out.
 */
export function regionWarmList(region: string, info: unknown): string[] {
  const base = `regions/${encodeURIComponent(region)}`;
  const list = [`${base}/region.json`, `${base}/atlas-marks.json`, `${base}/search-plan-index.json`, `${base}/shoreline-overview.geojson`, `${base}/poster.svg`];
  const mpa = (info as {assets?: {protected_areas?: unknown} | null} | null)?.assets?.protected_areas;
  if (typeof mpa === 'string' && ASSET.test(mpa)) list.push(mpa, `${base}/coverage.json`);
  list.push(`/api/forecast?region=${encodeURIComponent(region)}`);
  return list;
}

/** A deadline covers headers and body consumption; optional files get their own budget. */
export const WARM_TIMEOUT_MS = 10_000;
export type WarmOptions = {signal?: AbortSignal; timeoutMs?: number};

async function readWarm<T>(url: string, fetchFn: typeof fetch, read: (response: Response) => Promise<T>, {signal, timeoutMs = WARM_TIMEOUT_MS}: WarmOptions): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, {once: true});
  let rejectAbort: () => void = () => {};
  const aborted = new Promise<never>((_, reject) => {
    rejectAbort = () => reject(new Error('Warm-up cancelled or timed out'));
    controller.signal.addEventListener('abort', rejectAbort, {once: true});
  });
  const timer = setTimeout(abort, timeoutMs);
  try {
    if (signal?.aborted) controller.abort();
    if (controller.signal.aborted) return await aborted;
    // Race body consumption too: a stalled body (or a non-cooperative fetch)
    // cannot leave the caller loading after the deadline or cancellation.
    return await Promise.race([
      fetchFn(url, {priority: 'low', signal: controller.signal} as RequestInit).then(response => {
        if (controller.signal.aborted) throw new Error('Warm-up cancelled');
        return read(response);
      }),
      aborted,
    ]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
    controller.signal.removeEventListener('abort', rejectAbort);
  }
}

/**
 * Fetch `region`'s startup files once (resolved against `page`); resolves
 * with what happened and the paths asked for. Never rejects. The manifest
 * and each subsequent body have a bounded deadline; cancellation stops all.
 */
export async function warmRegion(region: string, page: string, fetchFn: typeof fetch = (...a) => fetch(...a), nav: unknown = globalThis.navigator, options: WarmOptions = {}): Promise<{state: Exclude<WarmState, 'loading'>; paths: string[]}> {
  if (saveData(nav)) return {state: 'skipped', paths: []};
  try {
    const first = `regions/${encodeURIComponent(region)}/region.json`;
    const info = await readWarm(new URL(first, page).href, fetchFn, async response => {
      if (!response.ok) throw new Error('Region unavailable');
      return response.json();
    }, options);
    const paths = regionWarmList(region, info);
    const rest = paths.filter(p => p !== first);
    const results = await Promise.all(rest.map(p => readWarm(new URL(p, page).href, fetchFn, async response => {
      await response.blob();
      return response.ok;
    }, options).catch(() => false)));
    // The startup copies are optional per region, including failed body reads.
    const required = rest.map((p, i) => ({p, ok: results[i]})).filter(e => !/\/(?:shoreline-overview\.geojson|poster\.svg)$/.test(e.p));
    return {state: options.signal?.aborted ? 'failed' : required.every(e => e.ok) ? 'ready' : 'failed', paths};
  } catch { return {state: 'failed', paths: []}; }
}
