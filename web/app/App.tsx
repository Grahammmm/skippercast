// The v2 app shell (FE-05, design § 6, concept A · Bridge): masthead, command
// bar and the desktop layout, or under 1,024 px the mobile layout (FE-06),
// all bound to web/state.ts so that every control writes the URL. The map is
// a placeholder stage until FE-11 brings MapLibre; the brief shows its empty
// state until FE-30 brings the readings. FirstRun (FE-08) asks for the
// profile once, over the map, never blocking it.
import {batch, effect, signal} from '@preact/signals';
import type {ReportLocalArea} from '../../packages/coast/src/state/report-binding.ts';
import {aerialBase, type AerialBase} from '../map/aerial.ts';
import {CommandBar} from './CommandBar.tsx';
import {Desktop} from './Desktop.tsx';
import {FirstRun} from './FirstRun.tsx';
import {Masthead} from './Masthead.tsx';
import {Mobile} from './Mobile.tsx';
import {Trip} from './Trip.tsx';
import {sharedFetch} from '../shared-fetch.ts';
import {loadPlans, regionUnavailable, unavailableTargets} from '../species.ts';
import {region, setRegionDefaultBase} from '../state.ts';

/** The mobile layout's media query (§ 6: under 1,024 px); main.tsx keeps `narrow` in step with it. */
export const NARROW_QUERY = '(max-width: 1023px)';
export const narrow = signal(false);

/** What the masthead knows about the region: name, centre and zone from regions/<id>/region.json. */
export interface RegionInfo {
  readonly id: string; readonly name: string; readonly center: readonly [number, number]; readonly timezone: string;
  /** The reviewed local areas a coast report binds to (packages/coast resolveReportBinding). */
  readonly localAreas?: readonly ReportLocalArea[];
  /** The aerial base the region's package offers (region.json `basemap.aerial`, FE-23); absent where none is. */
  readonly aerial?: AerialBase;
  /** The region's published charter grounds (region.json `assets.charters`), read by the Reports view; absent where none are published. */
  readonly charters?: string;
  /** The targets the region names as outside its researched list (region.json `map.unavailable_targets`, CI6-02): id → reason. */
  readonly unavailableTargets?: Readonly<Record<string, string>>;
}
export const regionInfo = signal<RegionInfo | null>(null);
/** The zone the dock and the command bar format times in (every active region is Pacific until the region loads). */
export const DEFAULT_ZONE = 'America/Los_Angeles';
export const currentRegionInfo = (): RegionInfo | null => {
  const info = regionInfo.value;
  return info?.id === region.value ? info : null;
};
export const zone = (): string => currentRegionInfo()?.timezone ?? DEFAULT_ZONE;

/** One deadline covers headers and body; shared static reads remain cacheable. */
export const REGION_READ_TIMEOUT_MS = 10_000;
export const regionLoad = signal<{id: string; state: 'loading' | 'ready' | 'error'} | null>(null);
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
    if (regionInfo.peek()?.id !== id) regionInfo.value = null;
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

/** Only the current region and latest request may publish; failure withdraws its metadata. */
/** `fetchFn` defaults to the shared static read, so the masthead and the Chart ask for region.json once. */
export async function loadRegion(id: string, fetchFn: typeof fetch = sharedFetch, retry = false): Promise<RegionInfo | null> {
  if (id !== region.peek()) return null;
  const generation = ++regionGeneration;
  regionRequest?.abort();
  const controller = regionRequest = new AbortController();
  const current = (): boolean => generation === regionGeneration && id === region.peek();
  batch(() => { regionInfo.value = null; regionLoad.value = {id, state: 'loading'}; });
  let rejectAborted: (() => void) | undefined;
  const aborted = new Promise<never>((_resolve, reject) => {
    rejectAborted = () => reject(new Error('Region read cancelled or timed out'));
    controller.signal.addEventListener('abort', rejectAborted, {once: true});
  });
  const timer = setTimeout(() => controller.abort(), REGION_READ_TIMEOUT_MS);
  try {
    const read = async (): Promise<RegionInfo | null> => {
      if (!retry && fetchFn === sharedFetch && recoveredRegionInfo.has(id)) return recoveredRegionInfo.get(id)!;
      const response = await fetchFn(`regions/${encodeURIComponent(id)}/region.json`, {signal: controller.signal, ...(retry ? {cache: 'reload' as const} : {})});
      if (!response.ok) return null;
      const json = await response.json() as {name?: string; map?: {center?: [number, number]; local_areas?: unknown}; timezone?: string; assets?: {charters?: unknown}};
      const center = json.map?.center;
      if (typeof json.name !== 'string' || !center || center.length !== 2 || !center.every(Number.isFinite)) return null;
      const areas = Array.isArray(json.map?.local_areas) ? json.map.local_areas as ReportLocalArea[] : [];
      const aerial = aerialBase(json);
      const unavailable = unavailableTargets(json);
      const info: RegionInfo = {id, name: json.name, center: [center[0], center[1]], timezone: json.timezone ?? DEFAULT_ZONE,
        localAreas: areas.filter(a => typeof a?.id === 'string' && Array.isArray(a.bounds)), ...aerial ? {aerial} : {}, ...typeof json.assets?.charters === 'string' ? {charters: json.assets.charters} : {},
        ...Object.keys(unavailable).length ? {unavailableTargets: unavailable} : {}};
      return info;
    };
    const info = await Promise.race([read(), aborted]);
    if (!current()) return null;
    if (!info) { regionLoad.value = {id, state: 'error'}; return null; }
    if (retry && fetchFn === sharedFetch) recoveredRegionInfo.set(id, info);
    batch(() => {
      regionInfo.value = info;
      regionLoad.value = {id, state: 'ready'};
      regionUnavailable.value = {region: id, targets: info.unavailableTargets ?? {}};
      setRegionDefaultBase(info.aerial?.byDefault ? 'aerial' : 'night');
    });
    return info;
  } catch {
    if (current()) regionLoad.value = {id, state: 'error'};
    return null;
  } finally {
    clearTimeout(timer);
    if (rejectAborted) controller.signal.removeEventListener('abort', rejectAborted);
    if (regionRequest === controller) regionRequest = null;
  }
}

/** The shell; `now` fixes the clock the dock, the window and the day chips read (tests pass a date). The trip dialogs keep their place across layouts. */
export function App({now = new Date()}: {now?: Date} = {}) {
  return (
    <>
      {narrow.value ? <Mobile now={now} firstRun={<FirstRun />} /> : (
        <div class="app">
          <Masthead />
          <CommandBar now={now} />
          <Desktop now={now} />
          <FirstRun />
        </div>
      )}
      <Trip />
    </>
  );
}
