// One network request per committed static file (the v2 startup budget,
// scripts/startup-budget.json): the masthead, the Chart's reef marks and its
// protected-area screen each read regions/<id>/region.json, and the marks'
// run-time screen and the Chart both load the region's protected areas and
// coverage review. shareStatic wraps a fetch so concurrent and later reads of
// the same committed JSON (`regions/…` or `data/…`, GET, default caching)
// share one request; each caller gets its own clone of the response. Live
// feeds (/api/, /feeds/), other origins and reads asking for a fresh copy
// (`cache: 'no-store' | 'no-cache' | 'reload'`) pass straight through, as do
// reads carrying any request header (Range, If-None-Match, Authorization…):
// a header can change the representation, so such a read neither seeds nor
// reuses the shared whole-file cache. A
// failed or non-OK read is forgotten, so the next caller asks again. An OK
// body is read whole before the share is kept: a body that breaks mid-transfer
// fails that read like a transport failure and is forgotten too. A shared
// transfer that stalls before or during that read expires independently of
// any caller's signal. Region metadata is capped at 512 KiB and its transfer
// is cancelled when its last waiting reader leaves; other readers can continue.
// A body that
// arrives whole but fails a caller's read (malformed JSON) is forgotten when
// that read rejects, so a retry fetches the file again (SC2007-02).
//
// Erasable syntax only: the node tests import it by type stripping.

const STATIC = /^\/(?:regions|data)\/[^?#]+\.(?:geo)?json$/;
const FRESH = new Set(['no-store', 'no-cache', 'reload']);
const SHARED_TRANSFER_MS = 30_000;
const wrapped = new WeakMap<typeof fetch, typeof fetch>();

const pageBase = (): string => (globalThis as {location?: {href?: string}}).location?.href ?? 'http://localhost/';

/** True when `headers` holds any header entry (any name: it may change the representation) or cannot be inspected; the caller's headers are only read, never changed. */
function hasHeaders(headers: HeadersInit | undefined): boolean {
  if (headers == null) return false;
  try {
    for (const _entry of new Headers(headers)) return true;
    return false;
  } catch { return true; }
}

/** The cache key for a shareable read of `input`, or null when the read must go to the network itself. */
export function sharedKey(input: RequestInfo | URL, init: RequestInit = {}, base: string = pageBase()): string | null {
  if (typeof input !== 'string' && !(input instanceof URL)) return null;
  if ((init.method ?? 'GET').toUpperCase() !== 'GET' || (init.cache && FRESH.has(init.cache)) || init.body != null) return null;
  if (hasHeaders(init.headers)) return null;
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

const BODY_READS = ['json', 'text', 'arrayBuffer', 'blob'] as const;

/** `response` with each body read calling `forget` when it rejects (a malformed body that arrived whole). */
function watchBody(response: Response, forget: () => void): Response {
  for (const name of BODY_READS) {
    const read = response[name] as ((...args: unknown[]) => Promise<unknown>) | undefined;
    if (typeof read !== 'function') continue;
    Object.defineProperty(response, name, {configurable: true, value: (...args: unknown[]) => read.apply(response, args).catch((error: unknown) => { forget(); throw error; })});
  }
  return response;
}

async function readStatic(fetchFn: typeof fetch, input: RequestInfo | URL, init: RequestInit, transfer: AbortController, regionMetadata: boolean): Promise<Response> {
  const {signal} = transfer;
  const timer = setTimeout(() => transfer.abort(new DOMException('Shared static transfer timed out', 'TimeoutError')), SHARED_TRANSFER_MS);
  try {
    const response = fetchFn(input, {...init, signal}).then(async response => {
      if (signal.aborted) { void response.body?.cancel().catch(() => {}); signal.throwIfAborted(); }
      // Region metadata must be bounded before it enters the shared cache.
      if (response.ok && response.body != null && typeof response.clone === 'function') {
        if (!regionMetadata) await response.clone().arrayBuffer();
        else {
          const reader = response.clone().body!.getReader();
          const cancel = () => { void reader.cancel().catch(() => {}); void response.body?.cancel().catch(() => {}); };
          signal.addEventListener('abort', cancel, {once: true});
          let size = 0;
          try {
            signal.throwIfAborted();
            for (;;) {
              const {done, value} = await reader.read();
              signal.throwIfAborted();
              if (done) break;
              size += value.byteLength;
              if (size > 512 * 1024) throw Error('Warmup byte limit');
            }
          } catch (error) { cancel(); transfer.abort(error); throw error; }
          finally { signal.removeEventListener('abort', cancel); reader.releaseLock(); }
        }
      }
      return response;
    });
    // Bound the cache entry even if a fetch implementation does not honor its signal.
    return await untilAborted(response, signal);
  } finally {
    clearTimeout(timer);
  }
}

/** `fetchFn`, sharing one request per committed static JSON file; the same wrapper for the same `fetchFn`. */
export function shareStatic(fetchFn: typeof fetch): typeof fetch {
  const existing = wrapped.get(fetchFn);
  if (existing) return existing;
  const reads = new Map<string, {promise: Promise<Response>; transfer: AbortController; users: number; pending: boolean}>();
  /** Drop `key` if it still holds `read`, so the next caller asks the network again. */
  const forget = (key: string, read: Promise<Response>): void => { if (reads.get(key)?.promise === read) reads.delete(key); };
  const shared = ((input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const key = sharedKey(input, init);
    if (!key) return fetchFn(input, init);
    if (init.signal?.aborted) return Promise.reject(init.signal.reason);
    const regionMetadata = /^\/regions\/[^/]+\/region\.json$/.test(new URL(key).pathname);
    let entry = reads.get(key);
    if (!entry) {
      const transfer = new AbortController();
      const own = readStatic(fetchFn, input, init, transfer, regionMetadata);
      entry = {promise: own, transfer, users: 0, pending: true};
      const created = entry;
      reads.set(key, created);
      own.then(response => { created.pending = false; if (!response.ok) forget(key, own); }, () => { created.pending = false; forget(key, own); });
    }
    const active = entry, kept = entry.promise;
    active.users++;
    // A real Response is cloned for every caller; one aborted caller cannot cancel other readers.
    return untilAborted(kept, init.signal).then(response => typeof response.clone === 'function' ? watchBody(response.clone(), () => forget(key, kept)) : response).finally(() => {
      active.users--;
      if (regionMetadata && active.pending && active.users === 0) {
        forget(key, kept);
        active.transfer.abort(new DOMException('No remaining readers', 'AbortError'));
      }
    });
  }) as typeof fetch;
  wrapped.set(fetchFn, shared);
  wrapped.set(shared, shared);
  return shared;
}

/** The page's fetch with committed static JSON shared: the default for the app's region and Chart reads. */
export const sharedFetch: typeof fetch = shareStatic((...args: Parameters<typeof fetch>) => fetch(...args));
