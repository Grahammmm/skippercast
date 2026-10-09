// The v2 app shell (FE-05, design § 6, concept A · Bridge): masthead, command
// bar and the desktop layout, or under 1,024 px the mobile layout (FE-06),
// all bound to web/state.ts so that every control writes the URL. The map is
// a placeholder stage until FE-11 brings MapLibre; the brief shows its empty
// state until FE-30 brings the readings. FirstRun (FE-08) asks for the
// profile once, over the map, never blocking it.
import {signal} from '@preact/signals';
import type {ReportLocalArea} from '../../packages/coast/src/state/report-binding.ts';
import {aerialBase, type AerialBase} from '../map/aerial.ts';
import {CommandBar} from './CommandBar.tsx';
import {Desktop} from './Desktop.tsx';
import {FirstRun} from './FirstRun.tsx';
import {Masthead} from './Masthead.tsx';
import {Mobile} from './Mobile.tsx';

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
}
export const regionInfo = signal<RegionInfo | null>(null);
/** The zone the dock and the command bar format times in (every active region is Pacific until the region loads). */
export const DEFAULT_ZONE = 'America/Los_Angeles';
export const zone = (): string => regionInfo.value?.timezone ?? DEFAULT_ZONE;

/** The freshness dot (§ 6): ok when every tile's source is within its limit, stale when any is past it, offline, or unknown before any reading. */
export type Freshness = {state: 'ok' | 'stale' | 'offline' | 'unknown'; /** The oldest age, as shown ("4 min"); null before any reading. */ age: string | null};
export const freshness = signal<Freshness>({state: 'unknown', age: null});

/** Load the region's name, centre and zone for `id`; a failed fetch leaves the masthead's placeholders. */
export async function loadRegion(id: string, fetchFn: typeof fetch = fetch): Promise<RegionInfo | null> {
  try {
    const response = await fetchFn(`regions/${encodeURIComponent(id)}/region.json`);
    if (!response.ok) return null;
    const json = await response.json() as {name?: string; map?: {center?: [number, number]; local_areas?: unknown}; timezone?: string};
    const center = json.map?.center;
    if (typeof json.name !== 'string' || !center || center.length !== 2) return null;
    const areas = Array.isArray(json.map?.local_areas) ? json.map.local_areas as ReportLocalArea[] : [];
    const aerial = aerialBase(json);
    const info: RegionInfo = {id, name: json.name, center: [center[0], center[1]], timezone: json.timezone ?? DEFAULT_ZONE,
      localAreas: areas.filter(a => typeof a?.id === 'string' && Array.isArray(a.bounds)), ...aerial ? {aerial} : {}};
    regionInfo.value = info;
    return info;
  } catch { return null; }
}

/** The shell; `now` fixes the clock the dock, the window and the day chips read (tests pass a date). */
export function App({now = new Date()}: {now?: Date} = {}) {
  if (narrow.value) return <><Mobile now={now} /><FirstRun /></>;
  return (
    <div class="app">
      <Masthead />
      <CommandBar now={now} />
      <Desktop now={now} />
      <FirstRun />
    </div>
  );
}
