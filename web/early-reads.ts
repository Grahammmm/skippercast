// SCB-11: the first verdict's reads start with the page, not after the app's code has loaded.
//
// On a slow phone the app's code takes seconds to arrive, and the brief only asks for the files its weather
// answer waits on (web/brief/verdict-load.ts) once that code has run. The page's early script (web/app/early.ts,
// linked async ahead of the app) calls startEarlyReads as soon as it arrives: for a link that names a region it asks at once for the region's
// metadata, the daily feed's brief part, the conditions feed, the forecast and, where the region binds one, the
// coast report. The same call wraps the page's fetch so the app's own first read of each of those URLs (a plain
// GET with the same credentials and no headers, body or cache mode) takes the answer already on its way instead
// of asking again. Each answer is handed over once, and only within EARLY_READ_TTL_MS of its start; every other
// read (a refresh, a retry, another region, a different request) goes to the network exactly as before. A
// caller's own signal still ends its wait, as it would end its own request.
//
// Erasable syntax only: the node tests import it by type stripping.

/** How long a started read waits for the app to take it; after this the app's read goes to the network. */
export const EARLY_READ_TTL_MS = 30_000;

/** Region ids as the site publishes them (regions/<id>/): lowercase words joined by single hyphens. */
const REGION_ID = /^[a-z0-9]+(?:-[a-z0-9]+){0,15}$/;

/**
 * The regions whose brief binds the coast report (packages/coast/src/state/report-binding.ts `bindings`); the report is
 * read early only for these, so no other region's first visit pays for it. A test keeps the two lists equal.
 */
export const REPORT_REGIONS: readonly string[] = Object.freeze(['morro-bay', 'cambria-san-simeon']);

export interface EarlyRead {path: string; init: RequestInit}

/**
 * The reads the verdict of region `id` waits on, exactly as the app asks for them (same path, same credentials):
 * web/app/region-info.ts (region.json), web/brief/Brief.tsx readDaily and readFeed (the daily brief part and the
 * conditions feed), web/conditions.ts loadConditionsForecast, and packages/coast's coastFetch for the report.
 */
export function earlyReads(id: string): EarlyRead[] {
  const r = encodeURIComponent(id);
  const reads: EarlyRead[] = [
    {path: `/regions/${r}/region.json`, init: {}},
    {path: `/api/daily?region=${r}&part=brief`, init: {}},
    {path: `/feeds/conditions/regions/${id}/latest.json`, init: {}},
    {path: `/api/forecast?region=${r}`, init: {}},
  ];
  if (REPORT_REGIONS.includes(id)) reads.push({path: '/api/coast/report', init: {credentials: 'omit', redirect: 'error'}});
  return reads;
}

/** The region a page address names for the early reads, or null (no region, or not a well-formed id). */
export function earlyRegion(href: string): string | null {
  let id: string | null;
  try { id = new URL(href).searchParams.get('region'); } catch { return null; }
  return id && id.length <= 64 && REGION_ID.test(id) ? id : null;
}

interface Started {credentials: RequestCredentials; redirect: RequestRedirect; at: number; response: Promise<Response>}
interface Scope {fetch?: typeof fetch; location?: {href: string}}

/** True when `init` holds anything that could change the request: a method other than GET, a body, headers, a cache mode or integrity. */
function plain(init: RequestInit): boolean {
  if ((init.method ?? 'GET').toUpperCase() !== 'GET' || init.body != null || init.cache !== undefined || init.integrity !== undefined) return false;
  if (init.headers == null) return true;
  try {
    for (const _entry of new Headers(init.headers)) return false;
    return true;
  } catch { return false; }
}

/** Reject when `signal` aborts first, as the caller's own request would; the started read itself carries no caller's signal. */
function untilAborted(promise: Promise<Response>, signal: AbortSignal | null | undefined): Promise<Response> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise<Response>((resolve, reject) => {
    const abort = (): void => reject(signal.reason);
    signal.addEventListener('abort', abort, {once: true});
    promise.then(value => { signal.removeEventListener('abort', abort); resolve(value); },
      error => { signal.removeEventListener('abort', abort); reject(error); });
  });
}

/**
 * Start region `id`'s verdict reads now (the region the page address names by default) and wrap `scope.fetch` so the first
 * matching read takes each answer. Does nothing without a region, a fetch or a page address. Returns the started paths.
 */
export function startEarlyReads(scope: Scope = globalThis, id: string | null = scope.location ? earlyRegion(scope.location.href) : null,
  now: () => number = Date.now): string[] {
  const page = scope.location?.href, original = scope.fetch;
  if (!id || !page || typeof original !== 'function') return [];
  const started = new Map<string, Started>();
  for (const {path, init} of earlyReads(id)) {
    const url = new URL(path, page).href;
    const response = original.call(scope, url, init);
    response.catch(() => {}); // a failed early read is the app's read failing: it is reported where the app takes it, never here
    started.set(url, {credentials: init.credentials ?? 'same-origin', redirect: init.redirect ?? 'follow', at: now(), response});
  }
  scope.fetch = ((input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    if (started.size && (typeof input === 'string' || input instanceof URL) && plain(init)) {
      let url: string | null;
      try { url = new URL(input, scope.location?.href ?? page).href; } catch { url = null; }
      const read = url === null ? undefined : started.get(url);
      if (read && url !== null) {
        started.delete(url);
        if (read.credentials === (init.credentials ?? 'same-origin') && read.redirect === (init.redirect ?? 'follow') && now() - read.at <= EARLY_READ_TTL_MS) return untilAborted(read.response, init.signal);
      }
    }
    return original.call(scope, input, init);
  }) as typeof fetch;
  return [...started.keys()];
}
