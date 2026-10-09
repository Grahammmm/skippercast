// Protected areas on the Chart (FE-19, docs/plans/front-end/design.md § 9):
// the region's CDFW ds582 boundary snapshot (and, where the region names
// them, NOAA's groundfish exclusion areas) as a faint `--mpa-fill` with a
// dashed `--mpa-line`, names from `?view=` zoom 11, always on, no rail entry.
//
// The data is the one dist/protected-areas.js draws for v1: region.json
// `assets.protected_areas` and `assets.closures`, checked by the same rule as
// its `validMPAs` (a complete FeatureCollection of named polygons with at
// least `mpa.minimum_features` areas; tests/test_mpa_layer.mjs pins the
// parity). That module is not imported: it reads v1's active region at load
// and brings v1's region graph with it. The snapshot is also checked against
// the region it is drawn for (its query envelope must cover `mpa.bounds`),
// and the region's coverage review (coverage.json, need `protected-areas`)
// decides whether the drawing can be called complete. Anything short of that
// says so in the legend, because a missing outline must never read as "no
// protected area here".
//
// Erasable syntax only: tests/test_mpa_layer.mjs imports this file by type stripping.
import {signal} from '@preact/signals';
import type {ChartMark} from './coastline.ts';
import {ZOOM_OFFSET} from './engine.ts';
import {MPA_SOURCE, layerEntry} from './layers.ts';
import type {Palette} from './palette.ts';
import {LABEL_FONT} from './style.ts';

export const MPA_FILL = 'mpa-fill';
export const MPA_LINE = 'mpa-line';
export const MPA_LABEL = 'mpa-label';
/** Names show from this `?view=` zoom (§ 9), as the ENC base counts zoom. */
export const MPA_LABEL_MIN_ZOOM = 11;
/** The ds582 feature service v1 queries (dist/protected-areas.js `MPA_SERVICE`). */
export const MPA_SERVICE = 'https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query';
/** Official pages for the rules; the map never states them. */
export const CDFW_MPA_PAGE = 'https://wildlife.ca.gov/Conservation/Marine/MPAs';
export const NOAA_GEA_PAGE = 'https://www.fisheries.noaa.gov/west-coast/sustainable-fisheries/west-coast-groundfish-closed-areas';
export const DS582_METADATA = 'https://filelib.wildlife.ca.gov/public/BDB/GIS/BIOS/metadata/DS0582.html';
export const CC_BY_4 = 'https://creativecommons.org/licenses/by/4.0/';
const GEA_BASIS = 'NOAA Southern California groundfish exclusion areas, coordinates as published; the federal regulations control.';

/** Designations as ds582 (and NOAA's closures file) code them. */
export const DESIGNATIONS: Readonly<Record<string, string>> = {
  SMR: 'State Marine Reserve', SMCA: 'State Marine Conservation Area', 'SMCA (No-Take)': 'State Marine Conservation Area (no-take)',
  SMRMA: 'State Marine Recreational Management Area', SMP: 'State Marine Park', FMR: 'Federal Marine Reserve',
  FMCA: 'Federal Marine Conservation Area', 'Special Closure': 'Special Closure', GEA: 'Groundfish Exclusion Area (federal)',
};

/** complete: the reviewed snapshot covers the region; partial: drawn, review not finished; incomplete: the drawing has a known gap. */
export type MpaStatus = 'idle' | 'loading' | 'complete' | 'partial' | 'incomplete' | 'unavailable';
export interface MpaState {
  readonly status: MpaStatus;
  /** The legend's line: the check date, or what is missing. Empty while idle or loading. */
  readonly note: string;
  /** Why, for the basis popover: the region review's own reason or the gap found; empty when complete. */
  readonly detail: string;
  /** The snapshot's check date (YYYY-MM-DD), when known. */
  readonly checked: string | null;
  readonly count: number;
}
const state = (status: MpaStatus, note = '', detail = '', checked: string | null = null, count = 0): MpaState =>
  Object.freeze({status, note, detail, checked, count});
export const IDLE: MpaState = state('idle');
export const LOADING: MpaState = state('loading', 'Loading boundaries.');
/** The drawn snapshot's state, for the legend and the chart host's `data-mpa`. */
export const mpaState = signal<MpaState>(IDLE);

const MAYBE = 'an area without an outline may still be protected.';
export const NOTES = {
  partial: `Boundary review for this region is partial; ${MAYBE}`,
  incomplete: `The boundary snapshot is incomplete for this region; ${MAYBE}`,
  unavailable: `Boundaries did not load, so none are drawn; ${MAYBE}`,
} as const;

type Json = Record<string, unknown>;
type Collection = {type: 'FeatureCollection'; features: Json[]};
export interface RegionMpaConfig {readonly mpa?: {readonly bounds?: readonly number[]; readonly minimum_features?: number}; readonly assets?: Readonly<Record<string, unknown>>}
export interface MpaInput {region: string; config: RegionMpaConfig; snapshot: unknown; coverage?: unknown; closures?: unknown}
export interface MpaResult {readonly state: MpaState; readonly data: Collection}

const EMPTY = (): Collection => ({type: 'FeatureCollection', features: []});
const obj = (v: unknown): Json | null => v && typeof v === 'object' && !Array.isArray(v) ? v as Json : null;
const text = (v: unknown): string => typeof v === 'string' ? v.trim() : '';
const polygon = (f: Json): boolean => ['Polygon', 'MultiPolygon'].includes(text(obj(f.geometry)?.type));
const day = (v: unknown): string | null => /^\d{4}-\d{2}-\d{2}T/.test(text(v)) ? text(v).slice(0, 10) : null;
const features = (v: unknown): Json[] => { const list = obj(v)?.features; return Array.isArray(list) ? list.map(obj).filter((f): f is Json => !!f) : []; };

/** v1's `validMPAs` shape rule, without the count: a whole FeatureCollection of named polygons. */
export function validSnapshot(data: unknown): boolean {
  const d = obj(data), list = d?.features;
  return d?.type === 'FeatureCollection' && !d.exceededTransferLimit && Array.isArray(list) && list.length > 0 &&
    list.every(f => typeof obj(obj(f)?.properties)?.NAME === 'string' && polygon(obj(f) ?? {}));
}

/** The [west, south, east, north] a snapshot was queried for, read from its ds582 `source_url`; null for any other source. */
export function snapshotEnvelope(sourceURL: unknown): number[] | null {
  try {
    const url = new URL(text(sourceURL));
    if (`${url.origin}${url.pathname}` !== MPA_SERVICE) return null;
    const box = (url.searchParams.get('geometry') ?? '').split(',').map(Number);
    return box.length === 4 && box.every(Number.isFinite) ? box : null;
  } catch { return null; }
}

/** True when the envelope contains the region's `mpa.bounds`. */
export const covers = (envelope: readonly number[], bounds: readonly number[]): boolean => {
  const [w = NaN, s = NaN, e = NaN, n = NaN] = bounds, eps = 1e-9;
  return envelope.length === 4 && [w, s, e, n].every(Number.isFinite) &&
    envelope[0]! <= w + eps && envelope[1]! <= s + eps && envelope[2]! >= e - eps && envelope[3]! >= n - eps;
};

/** The region's own review of its boundary data (coverage.json need `protected-areas`). */
function review(coverage: unknown, region: string): {status: string; reason: string} {
  const c = obj(coverage);
  const need = c?.region_id === region && Array.isArray(c.needs) ? c.needs.map(obj).find(n => n?.id === 'protected-areas') : null;
  return need ? {status: text(need.status), reason: text(need.reason)} : {status: '', reason: 'This region\'s boundary review did not load.'};
}

const drawn = (list: Json[], source: 'cdfw' | 'noaa', checked: string | null): Json[] => list.map(f => {
  const p = obj(f.properties) ?? {};
  return {type: 'Feature', geometry: f.geometry, properties: {NAME: text(p.NAME), FULLNAME: text(p.FULLNAME), Type: text(p.Type), CCR: text(p.CCR), source, checked: checked ?? ''}};
});

/**
 * What can be drawn for `region` and how much it can be trusted to be whole. Pure: the loader
 * passes the fetched files (closures `undefined` when the region names none, null when they failed).
 */
export function assessMpas({region, config, snapshot, coverage, closures}: MpaInput): MpaResult {
  if (!validSnapshot(snapshot)) return {state: state('unavailable', NOTES.unavailable, 'The boundary snapshot failed its completeness check.'), data: EMPTY()};
  const snap = obj(snapshot)!, list = features(snap), checked = day(snap.checked_at);
  const bounds = config.mpa?.bounds ?? [], minimum = Math.max(1, Number(config.mpa?.minimum_features) || 1);
  const envelope = snapshotEnvelope(snap.source_url);
  const gaps: string[] = [];
  if (list.length < minimum) gaps.push(`The snapshot holds ${list.length} areas; this region's check expects at least ${minimum}.`);
  if (snap.region_id !== undefined && snap.region_id !== region) gaps.push('The snapshot was taken for another region.');
  if (!envelope || !covers(envelope, bounds)) gaps.push('The snapshot\'s query area does not cover this whole region.');
  const out = drawn(list, 'cdfw', checked);
  if (closures !== undefined) {
    const c = obj(closures), extra = features(c);
    if (c?.type === 'FeatureCollection' && c.region_id === region && extra.length && extra.every(polygon)) out.push(...drawn(extra, 'noaa', day(c.checked_at)));
    else gaps.push('The federal groundfish closures named for this region did not load.');
  }
  const data: Collection = {type: 'FeatureCollection', features: out};
  if (gaps.length) return {state: state('incomplete', NOTES.incomplete, gaps.join(' '), checked, out.length), data};
  const {status, reason} = review(coverage, region);
  if (status === 'ready') return {state: state('complete', checked ? `CDFW ds582 snapshot checked ${checked}.` : 'CDFW ds582 snapshot.', '', checked, out.length), data};
  return {state: state('partial', NOTES.partial, `Region review: ${reason}`, checked, out.length), data};
}

/** A region asset path (relative to the site root) that may be fetched: `data/…` or `regions/<id>/…` GeoJSON. */
const ASSET = /^(?:data|regions\/[a-z0-9-]{1,80})\/[A-Za-z0-9._-]{1,120}\.geojson$/;
async function json(fetchFn: typeof fetch, url: string): Promise<unknown> {
  const response = await fetchFn(url, {signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

/** Fetch and assess the region's boundary files; never throws (a failure is the `unavailable` state). */
export async function loadMpas(region: string, fetchFn: typeof fetch, page: string): Promise<MpaResult> {
  const at = (path: string): string => new URL(path, page).href;
  const failed = (detail: string): MpaResult => ({state: state('unavailable', NOTES.unavailable, detail), data: EMPTY()});
  const base = `regions/${encodeURIComponent(region)}/`;
  let config: RegionMpaConfig;
  try { config = (obj(await json(fetchFn, at(`${base}region.json`))) ?? {}) as RegionMpaConfig; } catch { return failed('The region package did not load.'); }
  const asset = text(config.assets?.protected_areas), closuresAsset = text(config.assets?.closures);
  if (!ASSET.test(asset)) return failed('This region names no boundary snapshot.');
  const [snapshot, coverage, closures] = await Promise.all([
    json(fetchFn, at(asset)).catch(() => null),
    json(fetchFn, at(`${base}coverage.json`)).catch(() => null),
    closuresAsset ? (ASSET.test(closuresAsset) ? json(fetchFn, at(closuresAsset)).catch(() => null) : Promise.resolve(null)) : Promise.resolve(undefined),
  ]);
  if (snapshot === null) return failed('The boundary snapshot did not load.');
  return assessMpas({region, config, snapshot, coverage, closures});
}

export interface MpaLayer {id: string; type: 'fill' | 'line' | 'symbol'; source: string; minzoom?: number; layout: Record<string, unknown>; paint: Record<string, unknown>}

/** The GeoJSON source the Chart adds; the loader fills it (Engine.setData) once the region's files are checked. */
export const mpaSource = () => ({type: 'geojson' as const, data: EMPTY(), attribution: layerEntry('mpas').attribution});

/**
 * Fill, dashed outline and names, in that order. Colours are the `--mpa-*` roles; the fill's
 * opacity is the `--mpa-fill-opacity` token, carried as its CSS text and converted by MapLibre.
 */
export function mpaLayers(p: Palette): MpaLayer[] {
  return [
    {id: MPA_FILL, type: 'fill', source: MPA_SOURCE, layout: {}, paint: {'fill-color': p.mpaFill, 'fill-opacity': ['to-number', p.mpaFillOpacity]}},
    {id: MPA_LINE, type: 'line', source: MPA_SOURCE, layout: {'line-join': 'round'},
      paint: {'line-color': p.mpaLine, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 1, 14, 1.8], 'line-dasharray': [3, 2]}},
    {id: MPA_LABEL, type: 'symbol', source: MPA_SOURCE, minzoom: MPA_LABEL_MIN_ZOOM - ZOOM_OFFSET,
      layout: {'text-field': ['get', 'NAME'], 'text-font': [LABEL_FONT], 'text-size': ['interpolate', ['linear'], ['zoom'], 10, 11, 14, 13], 'text-max-width': 8},
      paint: {'text-color': p.mpaLine, 'text-halo-color': p.bg, 'text-halo-width': 1.2}},
  ];
}

/** The citation as ds582 gives it; never a reading of what the rules allow. */
function citation(type: string, ccr: string): string {
  if (/^Section\s/.test(ccr)) return `CCR Title 14, ${ccr}`;
  if (type === 'GEA' && ccr) return ccr;
  return type === 'FMR' || type === 'FMCA' ? 'Federal waters; ds582 lists no state section.' : 'ds582 lists no regulation section.';
}

/** The mark card for a clicked protected area: its name, designation and citation, the source and check date, and the official rules page. */
export function mpaMark(properties: Record<string, unknown> | null | undefined): ChartMark | null {
  const p = properties ?? {};
  const short = text(p.NAME), name = text(p.FULLNAME) || short;
  if (!name) return null;
  const type = text(p.Type), federal = p.source === 'noaa', checked = text(p.checked);
  return {
    id: `mpa:${short || name}`,
    name,
    kind: DESIGNATIONS[type] ?? (type ? `Designation ${type}` : 'Designation not stated'),
    reading: citation(type, text(p.CCR)),
    source: `${federal ? 'NOAA Fisheries' : 'CDFW ds582'} · ${checked ? `checked ${checked}` : 'check date not stated'}`,
    basis: federal ? GEA_BASIS : layerEntry('mpas').basis,
    regulations: federal ? {href: NOAA_GEA_PAGE, label: 'NOAA groundfish closed areas'} : {href: CDFW_MPA_PAGE, label: 'CDFW marine protected areas'},
  };
}
