// BF-tile-cost: classifies what a page requested and sums what it cost. Pure
// (no DOM, no Playwright): e2e/tile-cost.spec.ts feeds it performance
// entries and requestfailed events; tests/test_tile_cost_classify.mjs unit
// checks it. Honesty rule: the audit never lets a remote origin load (see
// the spec), so a remote request is counted, never sized (bytes stay null).
export type Kind = 'script' | 'style' | 'font' | 'image' | 'tile' | 'feed' | 'api' | 'other';
export const KINDS = ['script', 'style', 'font', 'image', 'tile', 'feed', 'api', 'other'] as const;
export interface Classified {kind: Kind; remote: boolean}
/** What the page reported about one resource (or one failed request). */
export interface ResourceEntry {url: string; transfer_bytes: number | null; body_bytes: number | null}
export interface Row {
  view: string;
  project: string;
  pass: 'cold' | 'warm';
  requests: number;
  transfer_bytes: number | null;
  body_bytes: number | null;
  by_kind: Record<string, {requests: number; transfer_bytes: number | null}>;
  remote: Record<string, number>;
  /** Same-origin entries whose body came from a cache (HTTP cache hit, 304, or a preload/duplicate reused within the load). */
  cache_reused: number;
  /** Warm rows: distinct URLs fetched over the network in the cold pass and reused from cache here. Cold rows: null. */
  reused_from_cold: number | null;
  settled: boolean;
}
/** The kind of a URL and whether it leaves the origin; null for data:/blob: (never network) and unparseable URLs. */
export function classify(url: string, origin: string): Classified | null {
  let u: URL;
  try { u = new URL(url); } catch { return null; }
  if (u.protocol === 'data:' || u.protocol === 'blob:') return null;
  const remote = u.origin !== origin;
  const path = u.pathname;
  if (/\bGetMap\b/i.test(u.search)) return {kind: 'tile', remote};    // WMS raster (the ENC chart)
  if (path.startsWith('/tiles/')) return {kind: 'tile', remote};      // the site's own tile feeds
  if (path.startsWith('/feeds/tiles/')) return {kind: 'tile', remote};// basemap and seafloor pmtiles
  if (/\.(pbf|mvt)$/i.test(path)) return {kind: 'tile', remote};      // vector tiles
  if (/\.(png|webp|jpe?g)$/i.test(path) && (path.startsWith('/feeds/') || path.startsWith('/tiles/'))) return {kind: 'tile', remote};
  if (path.endsWith('.js')) return {kind: 'script', remote};
  if (path.endsWith('.css')) return {kind: 'style', remote};
  if (/\.(woff2?|ttf|otf|eot)$/i.test(path)) return {kind: 'font', remote};
  if (/\.(svg|gif|avif|ico|png|webp|jpe?g)$/i.test(path)) return {kind: 'image', remote};
  if (path.startsWith('/feeds/')) return {kind: 'feed', remote};
  if (path.startsWith('/api/')) return {kind: 'api', remote};
  return {kind: 'other', remote};
}
/** Host key for the report's remote column: host:port. */
export function hostOf(url: string): string {
  try { return new URL(url).host; } catch { return url; }
}
/** Sum transfer/body bytes over a list; null bytes never count as 0. */
export function sumBytes(rows: Array<{transfer_bytes: number | null; body_bytes: number | null}>): {transfer_bytes: number | null; body_bytes: number | null} {
  let transfer: number | null = 0, body = 0, saw = false;
  for (const r of rows) {
    if (r.transfer_bytes !== null) { transfer! += r.transfer_bytes; saw = true; }
    if (r.body_bytes !== null) body += r.body_bytes;
  }
  return {transfer_bytes: saw ? transfer! : null, body_bytes: body};
}
/**
 * A same-origin entry whose body was reused from a cache: it has a body, and
 * less than that body crossed the network (0 for a cache hit, headers only
 * for a 304). A network fetch transfers headers plus the body, so never less.
 */
export function cacheReused(e: ResourceEntry, c: Classified): boolean {
  return !c.remote && e.body_bytes !== null && e.body_bytes > 0 && (e.transfer_bytes === null || e.transfer_bytes < e.body_bytes);
}
/** A same-origin entry that crossed the network in full (headers plus body). */
function fetched(e: ResourceEntry, c: Classified): boolean {
  return !c.remote && e.body_bytes !== null && e.body_bytes > 0 && e.transfer_bytes !== null && e.transfer_bytes >= e.body_bytes;
}
/**
 * Distinct same-origin URLs the cold pass fetched over the network and the warm
 * pass then reused from the HTTP cache. A page can also reuse a preloaded or
 * duplicate request inside one load, so cache_reused alone does not prove a
 * warm pass; this does. Empty when the cache was off (e.g. under routing).
 */
export function reusedAcrossPasses(origin: string, cold: ResourceEntry[], warm: ResourceEntry[]): string[] {
  const network = new Set(cold.filter(e => { const c = classify(e.url, origin); return c !== null && fetched(e, c); }).map(e => e.url));
  return [...new Set(warm.filter(e => { const c = classify(e.url, origin); return c !== null && network.has(e.url) && cacheReused(e, c); }).map(e => e.url))];
}
/**
 * One (view, project, pass) row from raw entries; duplicate URLs count twice.
 * Pass the cold pass's entries with a warm pass to fill reused_from_cold.
 */
export function aggregate(origin: string, view: string, project: string, pass: 'cold' | 'warm', entries: ResourceEntry[], settled: boolean, cold?: ResourceEntry[]): Row {
  const by_kind: Record<string, {requests: number; transfer_bytes: number | null}> = {};
  const remote: Record<string, number> = {};
  let requests = 0, transfer: number | null = 0, body = 0, saw = false, cache_reused = 0;
  for (const e of entries) {
    const c = classify(e.url, origin);
    if (c === null) continue;
    requests += 1;
    const bucket = (by_kind[c.kind] ??= {requests: 0, transfer_bytes: null});
    bucket.requests += 1;
    if (e.transfer_bytes !== null) {
      bucket.transfer_bytes = (bucket.transfer_bytes ?? 0) + e.transfer_bytes;
      transfer! += e.transfer_bytes;
      saw = true;
    }
    if (e.body_bytes !== null) body += e.body_bytes;
    if (c.remote) remote[hostOf(e.url)] = (remote[hostOf(e.url)] ?? 0) + 1;
    if (cacheReused(e, c)) cache_reused += 1;
  }
  const reused_from_cold = cold ? reusedAcrossPasses(origin, cold, entries).length : null;
  return {view, project, pass, requests, transfer_bytes: saw ? transfer! : null, body_bytes: body, by_kind, remote, cache_reused, reused_from_cold, settled};
}
