// SC-LAUNCH-4: a hard daily ceiling on the metered work anonymous traffic can
// cause, which degrades instead of billing (docs/operations/cost-ceiling.md).
//
// What is counted: R2 Class B operations (get and head on the FEEDS bucket),
// the one meter an anonymous visitor drives that bills past its free
// allowance (R2 has a payment method on file; Workers and D1 on the Free plan
// stop rather than bill). Every request's bucket is wrapped by meter(), so no
// route can read R2 without being counted.
//
// Where the count lives: one D1 row per UTC day in request_limits (pruned by
// the existing cron), written in batches: each isolate adds its pending reads
// every FLUSH_READS reads or FLUSH_MS, and learns the global total from the
// same statement. Without D1 (tests, a bare dev runtime) the count stays in
// the isolate. A failed write keeps the reads pending; it never blocks a
// request.
//
// Past the ceiling the Worker is "degraded" until the UTC day ends:
//   - no request reads R2 (the bucket is withheld, so every route takes the
//     path it takes with no bucket bound: GitHub branches for feeds, shipped
//     assets for tiles, the Fish bridge for coast data);
//   - public reads are answered first from their last-known copy, kept in the
//     edge cache for LAST_KNOWN_SECONDS from the last time they were served
//     normally;
//   - every response says so: X-SC-Degraded: cost-ceiling, and
//     X-SC-Last-Known-At on a last-known copy;
//   - a public read with neither a copy nor a free fallback answers 503 with
//     {degraded: true} and Retry-After, never an R2 read.
import type {MiddlewareHandler} from 'hono';
import type {WaitUntil} from './edge-cache.ts';
import {useBucket} from './feeds.ts';
import type {AppEnv, Env} from './env.ts';

/** R2's free Class B allowance (10 million a month) over a 31-day month, rounded down. */
export const DEFAULT_R2_READS_PER_DAY = 300_000;
export const FLUSH_READS = 50;
export const FLUSH_MS = 30_000;
export const LAST_KNOWN_SECONDS = 7 * 24 * 3600;
export const LAST_KNOWN_MAX_BYTES = 32 * 1024 * 1024;
export const DEGRADED_RETRY_SECONDS = 600;
export const DEGRADED_HEADER = 'X-SC-Degraded';

/** The day's ceiling: COST_CEILING_R2_READS_PER_DAY when a positive integer, else the default. "off" disables it. */
export function ceilingOf(env: Pick<Env, 'COST_CEILING_R2_READS_PER_DAY'> | undefined): number {
  const raw = String(env?.COST_CEILING_R2_READS_PER_DAY ?? '').trim();
  if (raw === 'off') return Infinity;
  return /^[1-9]\d{0,11}$/.test(raw) ? Number(raw) : DEFAULT_R2_READS_PER_DAY;
}

const utcDay = (ms: number): string => new Date(ms).toISOString().slice(0, 10);

/** The isolate's view of today's count: `known` from the last D1 write, plus reads not yet written. */
const state = {day: '', known: 0, pending: 0, lastFlush: 0, flushing: null as Promise<void> | null};

function roll(now: number): void {
  const day = utcDay(now);
  if (day !== state.day) { state.day = day; state.known = 0; state.pending = 0; state.lastFlush = now; }
}

/** Count `n` R2 Class B reads now. */
export function recordReads(n = 1, now = Date.now()): void { roll(now); state.pending += n; }

/** Today's reads as this isolate knows them. */
export function readsToday(now = Date.now()): number { roll(now); return state.known + state.pending; }

export function overCeiling(env: Env | undefined, now = Date.now()): boolean { return readsToday(now) >= ceilingOf(env); }

/** Tests only: forget the isolate's count. */
export function resetMeter(): void { state.day = ''; state.known = 0; state.pending = 0; state.lastFlush = 0; state.flushing = null; }

const rowId = (day: string): string => 'cost-ceiling:r2-reads:' + day;

/** Add the pending reads to today's D1 row and learn the global total; local only without D1. */
export function flush(env: Env | undefined, now = Date.now()): Promise<void> {
  roll(now);
  if (state.flushing || state.pending === 0) return state.flushing ?? Promise.resolve();
  const n = state.pending, day = state.day;
  state.pending = 0; state.lastFlush = now;
  if (!env?.DB) { state.known += n; return Promise.resolve(); }
  const expires = Math.floor(Date.parse(day + 'T00:00:00Z') / 1000) + 3 * 86400;
  state.flushing = env.DB.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET count=count+excluded.count RETURNING count')
    .bind(rowId(day), n, expires).first<{count: number}>()
    .then(row => { if (state.day !== day) return; state.known = Math.max(state.known + n, Number(row?.count) || 0); })
    .catch(() => { if (state.day === day) state.pending += n; console.warn('Cost meter write unavailable'); })
    .finally(() => { state.flushing = null; });
  return state.flushing;
}

const shouldFlush = (now: number): boolean => state.pending >= FLUSH_READS || (state.pending > 0 && now - state.lastFlush >= FLUSH_MS);

/** The bucket with get and head counted; every other method passes through unchanged. */
export function meter(bucket: R2Bucket): R2Bucket {
  return new Proxy(bucket, {get(target, name) {
    const value = Reflect.get(target, name, target);
    if (typeof value !== 'function') return value;
    if (name === 'get' || name === 'head') return (...args: unknown[]) => { recordReads(1); return (value as (...a: unknown[]) => unknown).apply(target, args); };
    return value.bind(target);
  }});
}

// ---- last-known copies -----------------------------------------------------

const API_READS = new Set(['/api/daily', '/api/forecast', '/api/intelligence', '/api/habitat']);

/** Public reads that keep a last-known copy: published feeds (seafloor archives excepted: they need a live receipt) and the cached feed APIs. */
export function lastKnownEligible(request: Request, path: string): boolean {
  if (request.method !== 'GET') return false;
  if (path.startsWith('/feeds/')) return !path.startsWith('/feeds/tiles/seafloor/');
  return API_READS.has(path) || path.startsWith('/api/om/');
}

/** Edge-cache key of the last-known copy: path, sorted query and the exact byte range asked for. */
export function lastKnownKey(request: Request): Request {
  const source = new URL(request.url), key = new URL(source.origin + '/__sc-last-known' + source.pathname);
  for (const [name, value] of [...source.searchParams].sort(([a, x], [b, y]) => a < b ? -1 : a > b ? 1 : x < y ? -1 : x > y ? 1 : 0)) key.searchParams.append(name, value);
  const range = request.headers.get('Range');
  if (range) key.searchParams.set('sc-range', range);
  return new Request(key.href);
}

const INTERNAL = ['X-SC-LK-Status', 'X-SC-Last-Known-At'];

/**
 * Last-known copies live in their own named cache, never caches.default: the
 * feed edge cache keeps its own rules (no objects over EDGE_CACHE_MAX_BYTES,
 * no 404s, no seafloor archives) and its entries are never displaced by
 * copies that exist only for degraded mode. A copy may be a single byte range
 * of an object too large for the feed cache, which is how the basemap PMTiles
 * stays usable when degraded. Unavailable (tests, bare dev) means no copies.
 */
export const LAST_KNOWN_CACHE = 'skippercast-last-known-v1';
async function lastKnownCache(): Promise<Cache | null> {
  try { return (await (globalThis as {caches?: CacheStorage}).caches?.open(LAST_KNOWN_CACHE)) ?? null; } catch { return null; }
}

/** Keep `response` (a 200 or 206 served normally) as the last-known copy of `request`. */
export async function keepLastKnown(request: Request, response: Response, ctx: WaitUntil, now = Date.now()): Promise<void> {
  if ((response.status !== 200 && response.status !== 206) || !response.body) return;
  if (/no-store|private/.test(response.headers.get('Cache-Control') || '') || response.headers.has('Set-Cookie')) return;
  const length = Number(response.headers.get('Content-Length'));
  if (!(length > 0) || length > LAST_KNOWN_MAX_BYTES) return;
  const headers = new Headers(response.headers);
  headers.set('X-SC-LK-Status', String(response.status));
  headers.set('X-SC-Last-Known-At', new Date(now).toISOString());
  headers.set('Cache-Control', `public, max-age=${LAST_KNOWN_SECONDS}`);
  headers.delete('X-SC-Cache');
  // Opened before cloning, so an unavailable cache never leaves a teed body unread.
  const cache = await lastKnownCache();
  if (!cache) return;
  const write = cache.put(lastKnownKey(request), new Response(response.clone().body, {status: 200, headers})).catch(() => console.warn('Last-known copy write unavailable'));
  if (ctx?.waitUntil) ctx.waitUntil(write); else await write;
}

/** The last-known copy of `request` as it was served, marked degraded, or null. */
export async function lastKnown(request: Request): Promise<Response | null> {
  const cache = await lastKnownCache();
  if (!cache) return null;
  let hit: Response | undefined;
  try { hit = await cache.match(lastKnownKey(request)); } catch { return null; }
  if (!hit) return null;
  const headers = new Headers(hit.headers), status = Number(headers.get('X-SC-LK-Status')) === 206 ? 206 : 200;
  const at = headers.get('X-SC-Last-Known-At');
  for (const name of INTERNAL) headers.delete(name);
  headers.set('Cache-Control', 'no-store');
  headers.set(DEGRADED_HEADER, 'cost-ceiling');
  if (at) headers.set('X-SC-Last-Known-At', at);
  headers.set('Access-Control-Expose-Headers', [headers.get('Access-Control-Expose-Headers'), DEGRADED_HEADER, 'X-SC-Last-Known-At'].filter(Boolean).join(', '));
  return new Response(hit.body, {status, headers});
}

export function degradedUnavailable(): Response {
  return new Response(JSON.stringify({error: 'Live data is paused for today to stay inside SkipperCast\'s free running budget, and no saved copy of this is held yet.', degraded: true}),
    {status: 503, headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Retry-After': String(DEGRADED_RETRY_SECONDS), [DEGRADED_HEADER]: 'cost-ceiling',
      'Access-Control-Expose-Headers': DEGRADED_HEADER}});
}

function marked(response: Response): Response {
  const out = new Response(response.body, response);
  out.headers.set(DEGRADED_HEADER, 'cost-ceiling');
  out.headers.set('Access-Control-Expose-Headers', [out.headers.get('Access-Control-Expose-Headers'), DEGRADED_HEADER].filter(Boolean).join(', '));
  return out;
}

/**
 * Per request, after `context`: decide degraded or not, hand the routes a
 * metered bucket (or none), keep last-known copies of normal public reads and
 * write the count in batches.
 */
export const costCeiling: MiddlewareHandler<AppEnv> = async (c, next) => {
  const env = c.env ?? {}, now = Date.now(), ctx = (() => { try { return c.executionCtx as WaitUntil; } catch { return undefined; } })();
  const degraded = !!env.FEEDS && overCeiling(env, now);
  const feeds = env.FEEDS && !degraded ? meter(env.FEEDS) : null;
  c.set('feeds', feeds);
  c.set('degraded', degraded);
  useBucket({FEEDS: feeds ?? undefined});
  const request = c.req.raw, eligible = lastKnownEligible(request, c.var.path);
  if (degraded && eligible) {
    const copy = await lastKnown(request);
    if (copy) return copy;
  }
  await next();
  if (degraded) {
    c.res = eligible && c.res.status >= 400 ? degradedUnavailable() : marked(c.res);
  } else if (eligible && c.res.headers.get('X-SC-Cache') !== 'hit') {
    await keepLastKnown(request, c.res, ctx, now);
  }
  if (shouldFlush(Date.now())) {
    const write = flush(env);
    if (ctx?.waitUntil) ctx.waitUntil(write); else await write;
  }
};
