// The region the app has read (regions/<id>/region.json): its reader and the regionInfo signal, apart
// from the app shell (BF-landing-live). App.tsx re-exports them and keeps the loading lifecycle
// (loadRegion, retryRegion); the brief and the landing's live verdict (web/landing/live-verdict.ts)
// import them from here, so the landing does not reach the app's views and their funnel events
// (tests/test_v2_telemetry.mjs).
import {signal} from '@preact/signals';
import type {ReportLocalArea} from '../../packages/coast/src/state/report-binding.ts';
import {aerialBase, type AerialBase} from '../map/aerial.ts';
import {chartFilesOf} from '../chart-files.ts';
import {startupAdmission} from '../landing/region-warm.ts';
import {tideRegion, type TideRegion} from '../tide-stations.ts';
import {unavailableTargets} from '../species.ts';
import {region} from '../state.ts';
import {DEFAULT_ZONE, validZone} from '../zone.ts';
import type {RulesRegion} from '../regs.ts';

/** What the masthead knows about the region: name, centre and zone from regions/<id>/region.json. */
export interface RegionInfo {
  readonly id: string; readonly name: string; readonly center: readonly [number, number]; readonly timezone: string;
  /** The reviewed local areas a coast report binds to (packages/coast resolveReportBinding). */
  readonly localAreas?: readonly ReportLocalArea[];
  /** The aerial base the region's package offers (region.json `basemap.aerial`, FE-23); absent where none is. */
  readonly aerial?: AerialBase;
  /** The region's published charter grounds (region.json `assets.charters`), read by the Reports view; absent where none are published. */
  readonly charters?: string;
  readonly tide?: TideRegion;
  /** The targets the region names as outside its researched list (region.json `map.unavailable_targets`, CI6-02): id → reason. */
  readonly unavailableTargets?: Readonly<Record<string, string>>;
  /** The Chart side files the region publishes (region.json `chart_files`, RF0835-2); absent where it names none. */
  readonly chartFiles?: readonly string[];
  /** The region.json fields web/regs.ts reads (SC-LAUNCH-3: the brief's lead states the target's legality). */
  readonly rules?: RulesRegion;
}
export const regionInfo = signal<RegionInfo | null>(null);
export {DEFAULT_ZONE};
export const currentRegionInfo = (): RegionInfo | null => {
  const info = regionInfo.value;
  return info?.id === region.value ? info : null;
};
export const zone = (): string => currentRegionInfo()?.timezone ?? DEFAULT_ZONE;

/** One deadline covers headers and body; shared static reads remain cacheable. */
export const REGION_READ_TIMEOUT_MS = 10_000;
/** SCJ-7: the reader's answer when regions/<id>/region.json is a 404, so the region does not exist (not a failed read). */
export const REGION_MISSING = 'missing' as const;

/** Share parsed cold reads, not just headers: each admitted slot includes JSON consumption.
 * Caller cancellation withdraws publication without freeing an abort-ignoring task's slot. */
export function createRegionReader(fetchFn: typeof fetch, {limit = 4, timeoutMs = REGION_READ_TIMEOUT_MS} = {}) {
  const admission = startupAdmission<RegionInfo | typeof REGION_MISSING | null>(limit, timeoutMs);
  return (id: string, retry = false): Promise<RegionInfo | typeof REGION_MISSING | null> => admission.read(`${retry ? 'retry' : 'cached'}:${id}`, async signal => {
    const response = await fetchFn(`regions/${encodeURIComponent(id)}/region.json`, {signal, ...(retry ? {cache: 'reload' as const} : {})});
    if (!response.ok) { void response.body?.cancel().catch(() => {}); return response.status === 404 ? REGION_MISSING : null; }
    const json = await response.json() as {name?: string; map?: {center?: [number, number]; local_areas?: unknown}; timezone?: string; assets?: {charters?: unknown}; chart_files?: unknown}
      & Omit<RulesRegion, 'id' | 'assets'>;
    if (!json || typeof json !== 'object' || Array.isArray(json)) return null;
    const center = json.map?.center;
    if (typeof json.name !== 'string' || !center || center.length !== 2 || !center.every(Number.isFinite)) return null;
    const timezone = json.timezone === undefined ? DEFAULT_ZONE : validZone(json.timezone) ? json.timezone : null;
    if (!timezone) return null;
    const areas = Array.isArray(json.map?.local_areas) ? json.map.local_areas as ReportLocalArea[] : [];
    const aerial = aerialBase(json), tide = tideRegion(id, json), unavailable = unavailableTargets(json), chartFiles = chartFilesOf(json.chart_files);
    return {id, name: json.name, center: [center[0], center[1]], timezone,
      ...tide ? {tide} : {}, ...chartFiles ? {chartFiles} : {},
      localAreas: areas.filter(a => typeof a?.id === 'string' && Array.isArray(a.bounds)), ...aerial ? {aerial} : {},
      ...typeof json.assets?.charters === 'string' ? {charters: json.assets.charters} : {},
      ...Object.keys(unavailable).length ? {unavailableTargets: unavailable} : {},
      ...typeof json.jurisdiction_id === 'string' ? {rules: {id, timezone: json.timezone, species: json.species, jurisdiction_id: json.jurisdiction_id,
        regulatory_authority_hosts: json.regulatory_authority_hosts, assets: json.assets as RulesRegion['assets']}} : {}};
  });
}
