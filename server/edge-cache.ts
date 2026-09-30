// Edge caching and per-IP rate limits for the anonymous read endpoints
// (/api/om, /api/forecast, /api/intelligence, /api/habitat and R2 /feeds/).
//
// Both are optional: without the shared default cache or a Rate Limiting
// binding (local tests, a bare wrangler dev) each quietly does nothing. A cache or
// limiter failure must never take a public feed down: lookups, writes and
// limit checks fail open.

/** The Workers shared cache, or null where it is unavailable. */
export function edgeCache(): Cache | null {
  try { return (globalThis as {caches?: CacheStorage}).caches?.default ?? null; } catch { return null; }
}

/**
 * Cache key for a public GET: same origin and path, only the named query
 * parameters (all of them when `params` is omitted), sorted, plus the build id
 * so a deploy never serves output computed by older code.
 */
export interface CacheKeyOptions {params?: string[]; build?: string; headers?: Headers}
export function cacheKey(url: URL | string, {params, build = 'dev', headers}: CacheKeyOptions = {}): Request {
  const source = new URL(url), key = new URL(source.origin + source.pathname);
  const entries = [...source.searchParams].filter(([name]) => !params || params.includes(name))
    .sort(([a, x], [b, y]) => a < b ? -1 : a > b ? 1 : x < y ? -1 : x > y ? 1 : 0);
  for (const [name, value] of entries) key.searchParams.append(name, value);
  key.searchParams.set('sc-build', build);
  return new Request(key.href, headers ? {headers} : undefined);
}

/** A copy of the response marked X-SC-Cache: hit|miss. */
export function tagged(response: Response, state: 'hit' | 'miss'): Response {
  const out = new Response(response.body, response);
  out.headers.set('X-SC-Cache', state);
  return out;
}

/** Store a 200 response under key, after the reply when ctx.waitUntil exists. */
/** The part of ExecutionContext the Worker uses; absent in direct test calls. */
export type WaitUntil = {waitUntil(promise: Promise<unknown>): void} | undefined;

export async function store(cache: Cache | null, key: Request, response: Response, ctx: WaitUntil): Promise<void> {
  if (!cache || response.status !== 200) return;
  const write = cache.put(key, response).catch(() => console.warn('Edge cache write unavailable'));
  if (ctx?.waitUntil) ctx.waitUntil(write); else await write;
}

/**
 * Serve key from the edge cache, or produce() it and store 200s.
 * `extra` responses produced alongside (same upstream read) are stored too.
 */
export interface Produced {response: Response; extra?: [Request, Response][]}
export async function cached(key: Request, ctx: WaitUntil, produce: () => Promise<Produced>,
  onMiss?: () => Promise<Response | null>): Promise<Response> {
  const cache = edgeCache();
  if (cache) {
    try { const hit = await cache.match(key); if (hit) return tagged(hit, 'hit'); }
    catch { /* fall through to the origin */ }
  }
  // A gate that applies only to work the cache could not answer (a per-IP
  // limit on origin reads, say); a response from it is returned as is.
  const refused = onMiss ? await onMiss() : null;
  if (refused) return refused;
  const {response, extra = []} = await produce();
  if (cache && response.status === 200) {
    await store(cache, key, response.clone(), ctx);
    for (const [otherKey, other] of extra) await store(cache, otherKey, other, ctx);
  }
  return tagged(response, 'miss');
}

// ---- rate limits -------------------------------------------------------------

export const RETRY_AFTER_SECONDS = 60;

/** True when the Rate Limiting binding says this key is over its limit. */
export async function overLimit(limiter: RateLimit | undefined, key: string): Promise<boolean> {
  if (typeof limiter?.limit !== 'function') return false;
  try { return !(await limiter.limit({key})).success; }
  catch { return false; }
}

export function clientIP(request: Request): string {
  return request.headers.get('cf-connecting-ip') || 'unknown';
}

export function tooManyRequests(): Response {
  return new Response(JSON.stringify({error: 'Too many requests; try again in a minute.'}), {status: 429,
    headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Retry-After': String(RETRY_AFTER_SECONDS)}});
}
