// The v2 app shell (FE-05, design § 6, concept A · Bridge): masthead, command
// bar and the desktop layout, or under 1,024 px the mobile layout (FE-06),
// all bound to web/state.ts so that every control writes the URL. The map is
// a placeholder stage until FE-11 brings MapLibre; the brief shows its empty
// state until FE-30 brings the readings. FirstRun (FE-08) asks for the
// profile once, over the map, never blocking it.
import {batch, effect, signal} from '@preact/signals';
import {CommandBar} from './CommandBar.tsx';
import {Desktop} from './Desktop.tsx';
import {FirstRun} from './FirstRun.tsx';
import {Masthead} from './Masthead.tsx';
import {Mobile} from './Mobile.tsx';
import {Trip} from './Trip.tsx';
import {sharedFetch} from '../shared-fetch.ts';
import {publishedChartFiles} from '../chart-files.ts';
import {sourceFreshness, startupDeadline} from '../landing/region-warm.ts';
import type {BriefTile} from '../brief/types.ts';
import {tideSelection} from '../tide-selection.ts';
import {loadPlans, regionUnavailable} from '../species.ts';
import {region, setRegionDefaultBase} from '../state.ts';
import {FirstAnswerLine} from './FirstAnswerLine.tsx';
import {DEFAULT_ZONE} from '../zone.ts';
import {regionLoad} from '../ranking.ts';
import {createRegionReader, currentRegionInfo, REGION_MISSING, REGION_READ_TIMEOUT_MS, regionInfo, zone, type RegionInfo} from './region-info.ts';
export {createRegionReader, REGION_MISSING, REGION_READ_TIMEOUT_MS, type RegionInfo};

/** The mobile layout's media query (§ 6: under 1,024 px); main.tsx keeps `narrow` in step with it. */
export const NARROW_QUERY = '(max-width: 1023px)';
export const narrow = signal(false);

export {regionInfo, DEFAULT_ZONE, currentRegionInfo, zone};

export {regionLoad, FirstAnswerLine};
let regionGeneration = 0;
let regionRequest: AbortController | null = null;
// A successful retry supersedes a shared static response whose headers/body may still be stalled.
const recoveredRegionInfo = new Map<string, RegionInfo>();
// Invalidate even when a caller has not started the next read yet (including Back/Forward).
effect(() => {
  const id = region.value;
  regionGeneration++;
  regionRequest?.abort();
  regionRequest = null;
  batch(() => {
    // RF0850-2: pending until loadRegion publishes the list (or fails open), so the Chart waits instead of guessing.
    if (regionInfo.peek()?.id !== id) { regionInfo.value = null; publishedChartFiles.value = id ? {region: id, files: null, pending: true} : null; }
    tideSelection.configure(null);
    regionLoad.value = null;
  });
});

/** Retry bypasses a shared read that may still be stalled, and refreshes the target plans too. */
export function retryRegion(): void {
  const id = region.peek();
  if (!id) return;
  void loadRegion(id, sharedFetch, true);
  void loadPlans(id);
}

/** The freshness dot (§ 6): ok when every tile's source is within its limit, stale when any is past it, offline, or unknown before any reading. */
export type Freshness = {state: 'ok' | 'stale' | 'offline' | 'unknown'; /** The oldest age, as shown ("4 min"); null before any reading. */ age: string | null};
export const freshness = signal<Freshness>({state: 'unknown', age: null});

const regionReaders = new WeakMap<typeof fetch, ReturnType<typeof createRegionReader>>();
function regionReader(fetchFn: typeof fetch): ReturnType<typeof createRegionReader> {
  let reader = regionReaders.get(fetchFn);
  if (!reader) { reader = createRegionReader(fetchFn); regionReaders.set(fetchFn, reader); }
  return reader;
}

type StartupReading = Pick<BriefTile, 'at' | 'limitMs' | 'value' | 'state' | 'lastGood'>;
/** Source age, never arrival/cache age. Missing tiles cannot produce an all-fresh claim. */
export function startupFreshness(readings: readonly StartupReading[], now: () => number = Date.now, online = true): Freshness {
  if (!online) return {state: 'offline', age: null};
  const clocks = readings.map(tile => ({tile, clock: sourceFreshness(tile.at, tile.limitMs, now)}));
  const known = clocks.filter(({tile, clock}) => tile.value !== null && tile.state !== 'unavailable' && clock.ageMs !== null);
  const oldest = known.length ? Math.max(...known.map(({clock}) => clock.ageMs!)) : null;
  const age = oldest === null ? null : oldest < 3_600_000 ? `${Math.floor(oldest / 60_000)} min` : `${Math.floor(oldest / 3_600_000)} h`;
  const stale = known.some(({tile, clock}) => tile.lastGood || tile.state === 'stale' || clock.state === 'stale');
  return {state: stale ? 'stale' : !known.length || known.length !== readings.length ? 'unknown' : 'ok', age};
}

/** Re-evaluate existing sources, not the network, on minute ticks and connectivity changes.
 * The reactive effect also withdraws age immediately when the current region's brief disappears. */
export function bindStartupFreshness(read: () => readonly StartupReading[],
  {now = Date.now, online = () => navigator.onLine, target = window}: {now?: () => number; online?: () => boolean; target?: EventTarget} = {}): () => void {
  const refresh = () => { freshness.value = startupFreshness(read(), now, online()); };
  const stop = effect(refresh);
  const timer = setInterval(refresh, 60_000);
  for (const event of ['online', 'offline', 'pageshow']) target.addEventListener(event, refresh);
  return () => {
    stop(); clearInterval(timer);
    for (const event of ['online', 'offline', 'pageshow']) target.removeEventListener(event, refresh);
  };
}

/** Only the current region and latest request may publish; failure withdraws its metadata. */
/** `fetchFn` defaults to the shared static read, so the masthead and the Chart ask for region.json once. */
export async function loadRegion(id: string, fetchFn: typeof fetch = sharedFetch, retry = false): Promise<RegionInfo | null> {
  if (id !== region.peek()) return null;
  const generation = ++regionGeneration;
  regionRequest?.abort();
  const controller = regionRequest = new AbortController();
  const current = (): boolean => generation === regionGeneration && id === region.peek();
  batch(() => { regionInfo.value = null; regionLoad.value = {id, state: 'loading'}; });
  // RF0850-2: a failed read ends the wait with no list, so every chart file fails open as before.
  const failed = (state: 'error' | 'missing' = 'error'): void => batch(() => {
    regionLoad.value = {id, state};
    if (publishedChartFiles.peek()?.region === id && publishedChartFiles.peek()?.pending) publishedChartFiles.value = {region: id, files: null};
  });
  try {
    const info = await startupDeadline(() =>
      !retry && fetchFn === sharedFetch && recoveredRegionInfo.has(id)
        ? Promise.resolve(recoveredRegionInfo.get(id)!) : regionReader(fetchFn)(id, retry),
    REGION_READ_TIMEOUT_MS, controller.signal);
    if (!current()) return null;
    if (info === REGION_MISSING) { failed(REGION_MISSING); return null; }
    if (!info) { failed(); return null; }
    if (retry && fetchFn === sharedFetch) recoveredRegionInfo.set(id, info);
    batch(() => {
      regionInfo.value = info;
      publishedChartFiles.value = {region: id, files: info.chartFiles ?? null};
      tideSelection.configure(info.tide ?? null);
      regionLoad.value = {id, state: 'ready'};
      regionUnavailable.value = {region: id, targets: info.unavailableTargets ?? {}};
      setRegionDefaultBase(info.aerial?.byDefault ? 'aerial' : 'night');
    });
    return info;
  } catch {
    if (current()) failed();
    return null;
  } finally {
    if (regionRequest === controller) regionRequest = null;
  }
}

/** The shell; `now` fixes the clock the dock, the window and the day chips read (tests pass a date). The trip dialogs keep their place across layouts. */
export function App({now = new Date()}: {now?: Date} = {}) {
  return (
    <>
      {narrow.value ? <Mobile now={now} firstRun={<FirstRun />} /> : (
        <div class="app" style={{gridTemplateRows: 'auto auto auto 1fr'}}>
          <Masthead />
          <CommandBar now={now} />
          <FirstAnswerLine now={now} />
          <Desktop now={now} />
          <FirstRun />
        </div>
      )}
      <Trip />
    </>
  );
}
