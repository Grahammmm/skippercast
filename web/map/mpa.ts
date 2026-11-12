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
// protected area here". Each result also carries the files under v1's own
// rules (`screen`) for the reef marks' run-time screen (web/map/habitat.ts, #489).
//
// Erasable syntax only: tests/test_mpa_layer.mjs imports this file by type stripping.
import {signal} from '@preact/signals';
import type {StringId} from '../i18n.ts';
import {cp, type MarkCopyPart} from '../mark-copy.ts';
import type {ChartMark} from './coastline.ts';
import {ZOOM_OFFSET} from './engine.ts';
import {MPA_SOURCE, layerEntry} from './layers.ts';
import type {Palette} from './palette.ts';
import {sp, type StatusCopy, type StatusPart, type StatusVar} from './status-copy.ts';
import {LABEL_FONT} from './style.ts';

export const MPA_FILL = 'mpa-fill';
export const MPA_LINE = 'mpa-line';
export const MPA_LABEL = 'mpa-label';
/** Names show from this `?view=` zoom (§ 9), as the ENC base counts zoom. */
export const MPA_LABEL_MIN_ZOOM = 11;
/** The ds582 feature service v1 queries (dist/protected-areas.js `MPA_SERVICE`). */
export const MPA_SERVICE = 'https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query';
/** v1's live boundary query for a region's `mpa.bounds` (dist/protected-areas.js `MPA_QUERY`); the reef marks' screen asks it (#489). */
export const mpaQuery = (bounds: readonly number[]): string => `${MPA_SERVICE}?${new URLSearchParams({where: '1=1', geometry: bounds.join(','),
  geometryType: 'esriGeometryEnvelope', inSR: '4326', spatialRel: 'esriSpatialRelIntersects', outFields: 'NAME,FULLNAME,Type,CCR', returnGeometry: 'true', outSR: '4326', f: 'geojson'})}`;
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
  /** Why, for the basis popover: what the drawn data covers, or the gap found; empty when complete. */
  readonly detail: string;
  /** The snapshot's check date (YYYY-MM-DD), when known. */
  readonly checked: string | null;
  readonly count: number;
  /** SC1352-04: catalogue parts for `note` and `detail` (as `note` and `reason`); display only. The strings above stay English and are what status and Retry compare. */
  readonly copy?: StatusCopy;
}
const state = (status: MpaStatus, note = '', detail = '', checked: string | null = null, count = 0, copy?: StatusCopy): MpaState =>
  Object.freeze(copy ? {status, note, detail, checked, count, copy} : {status, note, detail, checked, count});
/** A catalogue part for `map.mpa.<key>`. */
const P = (key: string, vars?: Readonly<Record<string, StatusVar>>): StatusPart => sp(`map.mpa.${key}` as StringId, vars);
/** A civil check date (YYYY-MM-DD) as a date the language formats. */
const civil = (date: string): StatusVar => ({day: date, tz: 'UTC'});
const spaced = (parts: readonly StatusPart[]): StatusPart[] => parts.flatMap((p, i) => i ? [' ', p] : [p]);
export const IDLE: MpaState = state('idle');
export const LOADING: MpaState = state('loading', 'Loading boundaries.', '', null, 0, {note: [P('loading')]});
/** The drawn snapshot's state, for the legend and the chart host's `data-mpa`. */
export const mpaState = signal<MpaState>(IDLE);

const MAYBE = 'an area without an outline may still be protected.';
export const NOTES = {
  partial: `Boundary review for this region is partial; ${MAYBE}`,
  incomplete: `The boundary snapshot is incomplete for this region; ${MAYBE}`,
  unavailable: `Boundaries did not load, so none are drawn; ${MAYBE}`,
} as const;
const NOTE_PARTS: Readonly<Record<keyof typeof NOTES, StatusPart[]>> = {partial: [P('partial'), P('maybe')], incomplete: [P('incomplete'), P('maybe')], unavailable: [P('unavailable'), P('maybe')]};
/** The Chart itself could not start (no WebGL): nothing is drawn at all. */
export const MAP_UNAVAILABLE: MpaState = state('unavailable', 'Map unavailable.', `The map could not start, so no boundaries are drawn; ${MAYBE}`, null, 0,
  {note: [P('mapUnavailable')], reason: [P('mapStart'), P('maybe')]});

/**
 * What the legend shows: "Loading boundaries." until the Chart has loaded them, "Map unavailable."
 * when the Chart cannot start, and unavailable when MapLibre reported an error on the boundary
 * source after the loader checked it, so a drawing that failed never shows the check's date.
 */
export function shownMpaState(s: MpaState, {sourceFailed = false, mapFailed = false}: {sourceFailed?: boolean; mapFailed?: boolean} = {}): MpaState {
  if (mapFailed) return MAP_UNAVAILABLE;
  if (s.status === 'idle') return LOADING;
  if (sourceFailed && s.status !== 'unavailable') return state('unavailable', NOTES.unavailable, 'The map could not draw the boundary data.', s.checked, 0, {note: NOTE_PARTS.unavailable, reason: [P('drawFail')]});
  return s;
}

type Json = Record<string, unknown>;
type Collection = {type: 'FeatureCollection'; features: Json[]};
export interface RegionMpaConfig {readonly mpa?: {readonly bounds?: readonly number[]; readonly minimum_features?: number}; readonly assets?: Readonly<Record<string, unknown>>}
export interface MpaInput {region: string; config: RegionMpaConfig; snapshot: unknown; coverage?: unknown; closures?: unknown}
/**
 * What the reef marks' run-time screen reads (web/map/habitat.ts, #489): the files under v1's own
 * rules (dist/protected-areas.js), with each check's full time and the closures file's hash.
 */
export interface ScreenSource {
  /** The snapshot's areas when it passes v1's `validMPAs`; null otherwise. */
  readonly areas: readonly Json[] | null;
  readonly checkedAt: string | null;
  /** The region's closures: undefined where it names none, null when they failed v1's check. */
  readonly closures?: {readonly areas: readonly Json[]; readonly checkedAt: string | null; readonly sha256: string | null} | null;
}
export interface MpaResult {readonly state: MpaState; readonly data: Collection; readonly screen: ScreenSource}

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
/** v1's whole `validMPAs`: the snapshot rule and the region's `mpa.minimum_features` (a region without one passes nothing). */
export const validMpas = (data: unknown, minimum: unknown): boolean => validSnapshot(data) && features(data).length >= Number(minimum);
/** v1's closures rule: a non-empty FeatureCollection of polygons for this region. */
const validClosures = (c: Json | null, region: string): boolean => {
  const list = features(c);
  return c?.type === 'FeatureCollection' && c.region_id === region && list.length > 0 && list.every(polygon);
};
const closuresSource = (closures: unknown, region: string): ScreenSource['closures'] => {
  if (closures === undefined) return undefined;
  const c = obj(closures);
  return c && validClosures(c, region) ? {areas: features(c), checkedAt: text(c.checked_at) || null, sha256: text(c.source_sha256) || null} : null;
};

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

/** The status of the region's own review of its boundary data (coverage.json need `protected-areas`); '' when it did not load. */
function review(coverage: unknown, region: string): string {
  const c = obj(coverage);
  const need = c?.region_id === region && Array.isArray(c.needs) ? c.needs.map(obj).find(n => n?.id === 'protected-areas') : null;
  return need ? text(need.status) : '';
}

/** What a partial drawing holds, in the data's own terms (the review's reasons describe v1's screening, which this drawing does not do). */
function partialDetail(count: number, checked: string | null, reviewed: boolean): {text: string; parts: StatusPart[]} {
  const drawnLine = `Drawn: ${count} areas from the CDFW ds582 snapshot${checked ? ` checked ${checked}` : ''}.`;
  return {text: `${drawnLine} ${reviewed ? 'The region\'s review has not confirmed that this is every protected area here.' : 'This region\'s boundary review did not load, so the drawing is unconfirmed.'}`,
    parts: spaced([checked ? P('drawn', {n: count, date: civil(checked)}) : P('drawnUndated', {n: count}), P(reviewed ? 'reviewOpen' : 'reviewMissing')])};
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
  // v1 reads the closures only after the snapshot passes, so a failed snapshot fails them too.
  if (!validSnapshot(snapshot)) return {state: state('unavailable', NOTES.unavailable, 'The boundary snapshot failed its completeness check.', null, 0, {note: NOTE_PARTS.unavailable, reason: [P('completeness')]}), data: EMPTY(),
    screen: {areas: null, checkedAt: null, closures: closures === undefined ? undefined : null}};
  const snap = obj(snapshot)!, list = features(snap), checked = day(snap.checked_at);
  const valid = validMpas(snap, config.mpa?.minimum_features);
  const screen: ScreenSource = {areas: valid ? list : null, checkedAt: valid ? text(snap.checked_at) || null : null, closures: valid ? closuresSource(closures, region) : closures === undefined ? undefined : null};
  const bounds = config.mpa?.bounds ?? [], minimum = Math.max(1, Number(config.mpa?.minimum_features) || 1);
  const envelope = snapshotEnvelope(snap.source_url);
  const gaps: string[] = [], gapParts: StatusPart[] = [];
  const gap = (text: string, part: StatusPart): void => { gaps.push(text); gapParts.push(part); };
  if (list.length < minimum) gap(`The snapshot holds ${list.length} areas; this region's check expects at least ${minimum}.`, P('fewAreas', {n: list.length, minimum}));
  if (snap.region_id !== undefined && snap.region_id !== region) gap('The snapshot was taken for another region.', P('otherRegion'));
  if (!envelope || !covers(envelope, bounds)) gap('The snapshot\'s query area does not cover this whole region.', P('envelope'));
  const out = drawn(list, 'cdfw', checked);
  if (closures !== undefined) {
    const c = obj(closures);
    if (validClosures(c, region)) out.push(...drawn(features(c), 'noaa', day(c!.checked_at)));
    else gap('The federal groundfish closures named for this region did not load.', P('closures'));
  }
  const data: Collection = {type: 'FeatureCollection', features: out};
  if (gaps.length) return {state: state('incomplete', NOTES.incomplete, gaps.join(' '), checked, out.length, {note: NOTE_PARTS.incomplete, reason: spaced(gapParts)}), data, screen};
  const status = review(coverage, region);
  if (status === 'ready') return {state: state('complete', checked ? `CDFW ds582 snapshot for this region, checked ${checked}.` : 'CDFW ds582 snapshot for this region.', '', checked, out.length,
    {note: [checked ? P('complete', {date: civil(checked)}) : P('completeUndated')]}), data, screen};
  const detail = partialDetail(out.length, checked, status !== '');
  return {state: state('partial', NOTES.partial, detail.text, checked, out.length, {note: NOTE_PARTS.partial, reason: detail.parts}), data, screen};
}

/** The read failures a retry can clear (SC2007-02); a region that names no snapshot is a package fact, not one of them. */
export const TRANSIENT_DETAILS = {region: 'The region package did not load.', snapshot: 'The boundary snapshot did not load.'} as const;
const NO_SNAPSHOT = 'This region names no boundary snapshot.';
const DETAIL_PARTS: Readonly<Record<string, StatusPart>> = {[TRANSIENT_DETAILS.region]: P('regionLoad'), [TRANSIENT_DETAILS.snapshot]: P('snapshotLoad'), [NO_SNAPSHOT]: P('noSnapshot')};
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
  // Closures the region names fail with its snapshot (null); unknown before region.json loads (the screen reads the region's own copy).
  const failed = (detail: string, closures?: null): MpaResult => ({state: state('unavailable', NOTES.unavailable, detail, null, 0, {note: NOTE_PARTS.unavailable, reason: [DETAIL_PARTS[detail]!]}), data: EMPTY(), screen: {areas: null, checkedAt: null, closures}});
  const base = `regions/${encodeURIComponent(region)}/`;
  let config: RegionMpaConfig;
  try { config = (obj(await json(fetchFn, at(`${base}region.json`))) ?? {}) as RegionMpaConfig; } catch { return failed(TRANSIENT_DETAILS.region); }
  const asset = text(config.assets?.protected_areas), closuresAsset = text(config.assets?.closures), named = closuresAsset ? null : undefined;
  if (!ASSET.test(asset)) return failed(NO_SNAPSHOT, named);
  const [snapshot, coverage, closures] = await Promise.all([
    json(fetchFn, at(asset)).catch(() => null),
    json(fetchFn, at(`${base}coverage.json`)).catch(() => null),
    closuresAsset ? (ASSET.test(closuresAsset) ? json(fetchFn, at(closuresAsset)).catch(() => null) : Promise.resolve(null)) : Promise.resolve(undefined),
  ]);
  if (snapshot === null) return failed(TRANSIENT_DETAILS.snapshot, named);
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
      paint: {'text-color': p.mpaLine, 'text-halo-color': p.mapInkHalo, 'text-halo-width': 1.2}},
  ];
}

/** The citation as ds582 gives it; never a reading of what the rules allow. */
function citation(type: string, ccr: string): {text: string; copy?: MarkCopyPart[]} {
  if (/^Section\s/.test(ccr)) return {text: `CCR Title 14, ${ccr}`};
  if (type === 'GEA' && ccr) return {text: ccr};
  return type === 'FMR' || type === 'FMCA' ? {text: 'Federal waters; ds582 lists no state section.', copy: [cp('map.mpa.cite.federal')]}
    : {text: 'ds582 lists no regulation section.', copy: [cp('map.mpa.cite.none')]};
}

/** The mark card for a clicked protected area: its name, designation and citation, the source and check date, and the official rules page. */
export function mpaMark(properties: Record<string, unknown> | null | undefined): ChartMark | null {
  const p = properties ?? {};
  const short = text(p.NAME), name = text(p.FULLNAME) || short;
  if (!name) return null;
  const type = text(p.Type), federal = p.source === 'noaa', checked = text(p.checked), cite = citation(type, text(p.CCR)), official = Object.hasOwn(DESIGNATIONS, type) ? DESIGNATIONS[type]! : null;
  const origin = federal ? 'NOAA Fisheries' : 'CDFW ds582';
  // SC1352-04: display wording only. A Spanish card gives a readable label with the official designation beside it (never in place of it); area names, citations and links stay as published.
  const kind = official ? [cp(`map.mpa.kind.${type}` as StringId, {official})] : [type ? cp('map.mpa.kind.unknown', {type}) : cp('map.mpa.kind.none')];
  return {
    id: `mpa:${short || name}`,
    name,
    kind: official ?? (type ? `Designation ${type}` : 'Designation not stated'),
    reading: cite.text,
    source: `${origin} · ${checked ? `checked ${checked}` : 'check date not stated'}`,
    basis: federal ? GEA_BASIS : layerEntry('mpas').basis,
    regulations: federal ? {href: NOAA_GEA_PAGE, label: 'NOAA groundfish closed areas'} : {href: CDFW_MPA_PAGE, label: 'CDFW marine protected areas'},
    copy: {
      kind, ...(cite.copy ? {reading: cite.copy} : {}), source: [checked ? cp('map.mpa.source.checked', {source: origin, date: checked}) : cp('map.mpa.source.undated', {source: origin})],
      basis: [federal ? cp('map.mpa.geaBasis') : cp('layer.mpas.basis')],
      regulationsLabel: [cp(federal ? 'mark.layer.habitat.regs.noaa' : 'mark.layer.habitat.regs.mpa')],
    },
  };
}
