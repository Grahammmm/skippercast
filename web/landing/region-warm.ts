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
  // RF0835-2: a valid chart_files list (written by the build) drops startup copies the region lacks; fail open otherwise.
  const files = (info as {chart_files?: unknown} | null)?.chart_files;
  const known = Array.isArray(files) && files.every(f => typeof f === 'string') ? files as string[] : null;
  const list = [`${base}/region.json`, `${base}/atlas-marks.json`, `${base}/search-plan-index.json`,
    ...['shoreline-overview.geojson', 'poster.svg'].filter(f => !known || known.includes(f)).map(f => `${base}/${f}`)];
  const mpa = (info as {assets?: {protected_areas?: unknown} | null} | null)?.assets?.protected_areas;
  if (typeof mpa === 'string' && ASSET.test(mpa)) list.push(mpa, `${base}/coverage.json`);
  list.push(`/api/forecast?region=${encodeURIComponent(region)}`);
  return list;
}

/** A deadline includes headers AND body; abort-ignoring adapters cannot hold the caller. */
export function startupDeadline<T>(work: (signal: AbortSignal) => Promise<T>, timeoutMs: number, parent?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  const abort = () => controller.abort(parent?.reason ?? Error('Startup deadline'));
  const failed = new Promise<never>((_resolve, reject) => {
    controller.signal.addEventListener('abort', () => reject(controller.signal.reason), {once: true});
  });
  timer = setTimeout(abort, timeoutMs);
  parent?.addEventListener('abort', abort, {once: true});
  if (parent?.aborted) abort();
  const task = Promise.resolve().then(() => { controller.signal.throwIfAborted(); return work(controller.signal); });
  return Promise.race([task, failed]).finally(() => {
    clearTimeout(timer); parent?.removeEventListener('abort', abort);
  });
}

/** Shared W10A contract. Cache hits retain sourceAt; only the caller's clock advances. */
export function sourceFreshness(sourceAt: unknown, maxAgeMs: number, now: () => number = Date.now):
  {state: 'current' | 'stale' | 'unknown'; ageMs: number | null} {
  const age = now() - (typeof sourceAt === 'string' ? Date.parse(sourceAt) : NaN);
  if (!Number.isFinite(age) || age < -300_000) return {state: 'unknown', ageMs: null};
  return {state: age < maxAgeMs ? 'current' : 'stale', ageMs: Math.max(0, age)};
}

/** No waiting queue: join an admitted key or refuse immediately. An adapter that
 * ignores abort retains its slot until it settles; deadlines cannot create unlimited hidden work. */
export function startupAdmission<T>(limit: number, timeoutMs: number) {
  const pending = new Map<string, Promise<T>>();
  return {read(key: string, work: (signal: AbortSignal) => Promise<T>): Promise<T> {
    const shared = pending.get(key); if (shared) return shared;
    if (pending.size >= limit) return Promise.reject(Error('Startup saturated'));
    const result = startupDeadline(async signal => {
      try { return await work(signal); }
      finally { pending.delete(key); }
    }, timeoutMs);
    pending.set(key, result);
    return result;
  }};
}

async function warmBody(response: Response, signal: AbortSignal, parse = false): Promise<unknown> {
  // Small request fixtures may implement the Response methods without a stream.
  if (!response.body) return parse ? response.json() : response.blob();
  const reader = response.body.getReader(), chunks: Uint8Array[] = [];
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener('abort', cancel, {once: true});
  let size = 0;
  try {
    signal.throwIfAborted();
    for (;;) {
      const {done, value} = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      size += value.byteLength;
      if (size > (parse ? 512 * 1024 : 16 * 1024 * 1024)) throw Error('Warmup byte limit');
      if (parse) chunks.push(value);
    }
    if (!parse) return null;
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch (error) { cancel(); throw error; }
  finally { signal.removeEventListener('abort', cancel); reader.releaseLock(); }
}

export type WarmResult = {state: Exclude<WarmState, 'loading'>; paths: string[]};
export type StartupOptions = {timeoutMs?: number; signal?: AbortSignal};

/** W10B's region-switch boundary: stale completions never publish, even A→B→A. */
export function createRegionWarmup(fetchFn: typeof fetch = (...a) => fetch(...a), nav: unknown = (globalThis as {navigator?: unknown}).navigator) {
  let current: AbortController | undefined;
  const cancel = () => { current?.abort(); current = undefined; };
  return {cancel, async select(region: string, page: string, publish: (result: WarmResult) => void, timeoutMs = 8000) {
    cancel();
    const selection = new AbortController(); current = selection;
    const result = await warmRegion(region, page, fetchFn, nav, {signal: selection.signal, timeoutMs});
    if (current === selection && !selection.signal.aborted) publish(result);
    return result;
  }};
}

/** Fetch only the chosen region; the whole warmup (including bodies) has one deadline. */
export async function warmRegion(region: string, page: string, fetchFn: typeof fetch = (...a) => fetch(...a), nav: unknown = (globalThis as {navigator?: unknown}).navigator,
  options: StartupOptions = {}): Promise<WarmResult> {
  if (saveData(nav)) return {state: 'skipped', paths: []};
  try {
    return await startupDeadline(async signal => {
      const low = {priority: 'low', signal} as RequestInit;
      const first = `regions/${encodeURIComponent(region)}/region.json`;
      const response = await fetchFn(new URL(first, page).href, low);
      if (signal.aborted || !response.ok) {
        void response.body?.cancel().catch(() => {});
        signal.throwIfAborted(); return {state: 'failed', paths: [first]};
      }
      const paths = regionWarmList(region, await warmBody(response, signal, true));
      const rest = paths.filter(p => p !== first);
      const results = await Promise.all(rest.map(async p => {
        try {
          const r = await fetchFn(new URL(p, page).href, low);
          if (signal.aborted) { void r.body?.cancel().catch(() => {}); signal.throwIfAborted(); }
          await warmBody(r, signal); return r.ok;
        } catch { return false; }
      }));
      // Missing optional startup copies do not decide readiness.
      const required = rest.map((p, i) => ({p, ok: results[i]})).filter(e => !/\/(?:shoreline-overview\.geojson|poster\.svg)$/.test(e.p));
      return {state: required.every(e => e.ok) ? 'ready' : 'failed', paths};
    }, options.timeoutMs ?? 8000, options.signal);
  } catch { return {state: 'failed', paths: []}; }
}
