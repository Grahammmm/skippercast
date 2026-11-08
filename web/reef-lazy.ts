// SC-PERF-LAZY-1 (PERF-BASELINE-1 B1, P6, P7): the reef export (habitat-export.geojson.gz, ~15 MB, ~11 s of screening work) is
// not fetched with the first page. It starts only after the map has first painted (or failed to start), and never silently on
// Save-Data or a slow link: there the brief offers "Load fishing spots (about N MB) on Wi-Fi" and waits for a tap.
// The brief and the map work without it (web/ranking.ts falls back to the atlas list), and say so plainly (WhereToLook).
// Planner: web/planner.ts loads its own copy when the user opens a plan, so that path is already on demand.
import {mapFirstIdle, markMapIdle} from './map-ready.ts';
import {loadManifest} from '../dist/seafloor-data.js';
import {loadReefPublication, reefPublication, reloadReefPublication} from './ranking.ts';

export {mapFirstIdle, markMapIdle};

/** The parts of `navigator.connection` read here (Network Information API; absent in Safari and Firefox). */
export interface LinkInfo {readonly saveData?: boolean; readonly effectiveType?: string}
/** One finished download: its wire bytes and when it started and ended (ms, same clock). */
export interface Timing {readonly bytes: number; readonly start: number; readonly end: number}
export type SlowWhy = 'save-data' | 'slow-type' | 'slow-measured';
export type LinkVerdict = {readonly slow: false} | {readonly slow: true; readonly why: SlowWhy};

const SLOW_TYPES = new Set(['slow-2g', '2g', '3g']);
/** Below this the link is slow: 150 KB/s, about 1.2 Mbit/s (Lighthouse's slow 4G, 1.6 Mbit/s, measures ~100 KB/s with shared requests). */
export const SLOW_BYTES_PER_S = 150_000;
/** Only downloads this big say anything about the link, and at least this much in all. */
const MIN_ENTRY_BYTES = 20_000, MIN_TOTAL_BYTES = 100_000;

/** Throughput of the page's own first downloads: bytes over the wall-clock span they covered; null when there is too little to judge. */
export function measuredBytesPerSecond(timings: readonly Timing[]): number | null {
  const t = timings.filter(x => x.bytes >= MIN_ENTRY_BYTES && x.end > x.start);
  const total = t.reduce((n, x) => n + x.bytes, 0);
  if (t.length < 2 || total < MIN_TOTAL_BYTES) return null;
  const span = Math.max(...t.map(x => x.end)) - Math.min(...t.map(x => x.start));
  return span > 0 ? total / (span / 1000) : null;
}

/** Fast, or slow and why: Save-Data first, then a 2g/3g effective type, then the measured throughput of the page's own first downloads. */
export function linkVerdict(connection: LinkInfo | undefined, timings: readonly Timing[]): LinkVerdict {
  if (connection?.saveData === true) return {slow: true, why: 'save-data'};
  if (connection?.effectiveType !== undefined && SLOW_TYPES.has(connection.effectiveType)) return {slow: true, why: 'slow-type'};
  const rate = measuredBytesPerSecond(timings);
  return rate !== null && rate < SLOW_BYTES_PER_S ? {slow: true, why: 'slow-measured'} : {slow: false};
}

/** The page's finished same-origin downloads from the Resource Timing buffer (cache hits have no transfer and are left out). */
export function pageTimings(perf: Pick<Performance, 'getEntriesByType'> | undefined = globalThis.performance, origin = globalThis.location?.origin): Timing[] {
  try {
    return (perf?.getEntriesByType('resource') as PerformanceResourceTiming[] | undefined ?? [])
      .filter(e => e.transferSize > 0 && e.responseEnd > e.startTime && (!origin || e.name.startsWith(origin)))
      .map(e => ({bytes: e.transferSize, start: e.startTime, end: e.responseEnd}));
  } catch { return []; }
}

export interface LazyDeps {
  /** Resolves when the map has first painted (or failed). */
  readonly mapIdle: () => Promise<void>;
  /** Resolves when the browser is idle. */
  readonly idle: () => Promise<void>;
  readonly link: () => LinkVerdict;
  /** The published export's size in bytes (the manifest's `export_bytes`), or null when it cannot be read. */
  readonly size: (region: string) => Promise<number | null>;
  readonly load: (region: string) => Promise<void>;
}

const whenMapIdle = (): Promise<void> => new Promise(resolve => {
  let stop: (() => void) | undefined, done = false;
  stop = mapFirstIdle.subscribe(v => { if (v && !done) { done = true; queueMicrotask(() => stop?.()); resolve(); } });
});
const whenIdle = (): Promise<void> => new Promise(resolve => {
  const ric = (globalThis as {requestIdleCallback?: (cb: () => void, o?: {timeout: number}) => number}).requestIdleCallback;
  if (typeof ric === 'function') ric(() => resolve(), {timeout: 2000}); else setTimeout(resolve, 0);
});
const manifestSize = async (region: string): Promise<number | null> => {
  try {
    const g = await loadManifest(region) as {state?: string; manifest?: {export_bytes?: unknown} | null};
    const n = g.manifest?.export_bytes;
    return typeof n === 'number' && Number.isInteger(n) && n > 0 ? n : null;
  } catch { return null; }
};
const DEFAULTS: LazyDeps = {
  mapIdle: whenMapIdle, idle: whenIdle, size: manifestSize, load: r => loadReefPublication(r),
  link: () => linkVerdict((globalThis.navigator as {connection?: LinkInfo} | undefined)?.connection, pageTimings()),
};

/**
 * Ask for the region's reef publication the lazy way: wait for the map's first paint and an idle moment, then fetch it on a fast
 * link, or offer it (state 'offer') on Save-Data or a slow one. Safe to call again: a region already waiting, offered, loading or
 * answered is left alone. The newest region wins if the address changes while waiting.
 */
export async function requestReefPublication(region: string, given: Partial<LazyDeps> = {}): Promise<void> {
  const deps: LazyDeps = {...DEFAULTS, ...given};
  const was = reefPublication.peek();
  if (was.region === region && was.state !== 'idle') return;
  reefPublication.value = {state: 'deferred', region};
  const mine = reefPublication.peek();
  await deps.mapIdle();
  await deps.idle();
  if (reefPublication.peek() !== mine) return; // another region, or the user's own tap, took over
  const verdict = deps.link();
  if (!verdict.slow) { await deps.load(region); return; }
  const bytes = await deps.size(region);
  if (reefPublication.peek() !== mine) return;
  reefPublication.value = {state: 'offer', region, bytes, why: verdict.why};
}

/** The angler tapped "Load fishing spots … on Wi-Fi" (or "Try again"): fetch now, whatever the link. */
export async function acceptReefLoad(region: string, loader?: Parameters<typeof reloadReefPublication>[1]): Promise<void> {
  await reloadReefPublication(region, loader);
}

/** "Load fishing spots (about 15 MB) on Wi-Fi": the size rounded to whole MB (1 MB = 1,000,000 bytes, as download sizes are quoted), at least 1. */
export const offerMegabytes = (bytes: number | null | undefined): number | null =>
  typeof bytes === 'number' && bytes > 0 ? Math.max(1, Math.round(bytes / 1e6)) : null;
