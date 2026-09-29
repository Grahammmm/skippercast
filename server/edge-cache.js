// Edge caching and per-IP rate limits for the anonymous read endpoints
// (/api/om, /api/forecast, /api/intelligence, /api/habitat and R2 /feeds/).
//
// Both are optional: without the shared default cache or a Rate Limiting
// binding (local tests, a bare wrangler dev) each quietly does nothing. A cache or
// limiter failure must never take a public feed down: lookups, writes and
// limit checks fail open.

/** The Workers shared cache, or null where it is unavailable. */
export function edgeCache() {
  try { return globalThis.caches?.default ?? null; } catch { return null; }
}

/**
 * Cache key for a public GET: same origin and path, only the named query
 * parameters (all of them when `params` is omitted), sorted, plus the build id
 * so a deploy never serves output computed by older code.
 */
export function cacheKey(url, {params, build = 'dev', headers} = {}) {
  const source = new URL(url), key = new URL(source.origin + source.pathname);
  const entries = [...source.searchParams].filter(([name]) => !params || params.includes(name))
    .sort(([a, x], [b, y]) => a < b ? -1 : a > b ? 1 : x < y ? -1 : x > y ? 1 : 0);
  for (const [name, value] of entries) key.searchParams.append(name, value);
  key.searchParams.set('sc-build', build);
  return new Request(key.href, headers ? {headers} : undefined);
}

/** A copy of the response marked X-SC-Cache: hit|miss. */
export function tagged(response, state) {
  const out = new Response(response.body, response);
  out.headers.set('X-SC-Cache', state);
  return out;
}

/** Store a 200 response under key, after the reply when ctx.waitUntil exists. */
export async function store(cache, key, response, ctx) {
  if (!cache || response.status !== 200) return;
  const write = cache.put(key, response).catch(() => console.warn('Edge cache write unavailable'));
  if (ctx?.waitUntil) ctx.waitUntil(write); else await write;
}

/**
 * Serve key from the edge cache, or produce() it and store 200s.
 * `extra` responses produced alongside (same upstream read) are stored too.
 */
export async function cached(key, ctx, produce) {
  const cache = edgeCache();
  if (cache) {
    try { const hit = await cache.match(key); if (hit) return tagged(hit, 'hit'); }
    catch { /* fall through to the origin */ }
  }
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
export async function overLimit(limiter, key) {
  if (typeof limiter?.limit !== 'function') return false;
  try { return !(await limiter.limit({key})).success; }
  catch { return false; }
}

export function clientIP(request) {
  return request.headers.get('cf-connecting-ip') || 'unknown';
}

export function tooManyRequests() {
  return new Response(JSON.stringify({error: 'Too many requests; try again in a minute.'}), {status: 429,
    headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Retry-After': String(RETRY_AFTER_SECONDS)}});
}
