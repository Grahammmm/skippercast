// One network request per committed static file (the v2 startup budget,
// scripts/startup-budget.json): the masthead, the Chart's reef marks and its
// protected-area screen each read regions/<id>/region.json, and the marks'
// run-time screen and the Chart both load the region's protected areas and
// coverage review. shareStatic wraps a fetch so concurrent and later reads of
// the same committed JSON (`regions/…` or `data/…`, GET, default caching)
// share one request; each caller gets its own clone of the response. Live
// feeds (/api/, /feeds/), other origins and reads asking for a fresh copy
// (`cache: 'no-store' | 'no-cache' | 'reload'`) pass straight through. A
// failed or non-OK read is forgotten, so the next caller asks again. An OK
// body is read whole before the share is kept: a body that breaks mid-transfer
// fails that read like a transport failure and is forgotten too.
//
// Erasable syntax only: the node tests import it by type stripping.

const STATIC = /^\/(?:regions|data)\/[^?#]+\.(?:geo)?json$/;
const FRESH = new Set(['no-store', 'no-cache', 'reload']);
const wrapped = new WeakMap<typeof fetch, typeof fetch>();

const pageBase = (): string => (globalThis as {location?: {href?: string}}).location?.href ?? 'http://localhost/';

/** The cache key for a shareable read of `input`, or null when the read must go to the network itself. */
export function sharedKey(input: RequestInfo | URL, init: RequestInit = {}, base: string = pageBase()): string | null {
  if (typeof input !== 'string' && !(input instanceof URL)) return null;
  if ((init.method ?? 'GET').toUpperCase() !== 'GET' || (init.cache && FRESH.has(init.cache)) || init.body != null) return null;
  let url: URL, page: URL;
  try { url = new URL(input, base); page = new URL(base); } catch { return null; }
  return url.origin === page.origin && STATIC.test(url.pathname) && !url.search ? url.href : null;
}

/** Reject when `signal` aborts first; the shared request itself carries no caller's signal. */
function untilAborted<T>(promise: Promise<T>, signal: AbortSignal | null | undefined): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise<T>((resolve, reject) => {
    const abort = (): void => reject(signal.reason);
    signal.addEventListener('abort', abort, {once: true});
    promise.then(value => { signal.removeEventListener('abort', abort); resolve(value); },
      error => { signal.removeEventListener('abort', abort); reject(error); });
  });
}

/** `fetchFn`, sharing one request per committed static JSON file; the same wrapper for the same `fetchFn`. */
export function shareStatic(fetchFn: typeof fetch): typeof fetch {
  const existing = wrapped.get(fetchFn);
  if (existing) return existing;
  const reads = new Map<string, Promise<Response>>();
  const shared = ((input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const key = sharedKey(input, init);
    if (!key) return fetchFn(input, init);
    let read = reads.get(key);
    if (!read) {
      const {signal: _signal, ...rest} = init;
      read = fetchFn(input, rest).then(async response => {
        // Read an OK body whole (from a clone) before sharing; a double with no body or clone is shared as is.
        if (response.ok && response.body != null && typeof response.clone === 'function') await response.clone().arrayBuffer();
        return response;
      });
      reads.set(key, read);
      read.then(response => { if (!response.ok) reads.delete(key); }, () => reads.delete(key));
    }
    // A real Response is cloned for every caller (the stored one is never read); a test double without clone is shared as is.
    return untilAborted(read, init.signal).then(response => typeof response.clone === 'function' ? response.clone() : response);
  }) as typeof fetch;
  wrapped.set(fetchFn, shared);
  wrapped.set(shared, shared);
  return shared;
}

/** The page's fetch with committed static JSON shared: the default for the app's region and Chart reads. */
export const sharedFetch: typeof fetch = shareStatic((...args: Parameters<typeof fetch>) => fetch(...args));
