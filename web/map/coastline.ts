// The coastline glow (FE-11, design § 9): the region's NOAA CUSP shoreline
// (dist/regions/<id>/shoreline.geojson, built by FE-10) drawn as a blurred line
// under a crisp one, as fish's map drew it, with colours from the palette. A
// click on the line selects that segment: the mark card shows its source date
// and stated accuracy, because every feature keeps them. In the published form
// (schema_version 2, src/skippercast/platform/shoreline.py) a feature is one
// MultiLineString per distinct set of source properties, so each line still
// reads its own fields from the feature it belongs to.
//
// Erasable syntax only: tests/test_map_layers.mjs imports this file by type stripping.
import type {Palette} from './palette.ts';
import {COASTLINE_SOURCE, layerEntry} from './layers.ts';
import {ZOOM_OFFSET} from './engine.ts';

export const COASTLINE_GLOW = 'coastline-glow';
export const COASTLINE_LINE = 'coastline';
/** The layer a click selects on (the glow is wider, so it is the easier target). */
export const COASTLINE_PICK = COASTLINE_GLOW;

/** The published shoreline for `region`, relative to the app page. */
export const shorelineURL = (region: string): string => `regions/${encodeURIComponent(region)}/shoreline.geojson`;
/**
 * #617: its overview form (src/skippercast/platform/shoreline.py `overview_shoreline`: simplified to
 * 10 m, single rocks under 20 m left out; same features and properties), about a fifth of the bytes.
 */
export const shorelineOverviewURL = (region: string): string => `regions/${encodeURIComponent(region)}/shoreline-overview.geojson`;
/** The MapLibre zoom the full shoreline loads from (shoreline.py OVERVIEW_MAX_ZOOM); `?view=` zooms are ZOOM_OFFSET more. */
export const SHORELINE_DETAIL_ZOOM = 12;
/** The shoreline file the Chart draws at a `?view=` zoom: the overview below the detail zoom, unless the full one already loaded. */
export const shorelineFor = (region: string, viewZoom: number, detail = false): string =>
  detail || viewZoom - ZOOM_OFFSET >= SHORELINE_DETAIL_ZOOM ? shorelineURL(region) : shorelineOverviewURL(region);

export interface LineLayer {
  id: string; type: 'line'; source: string;
  layout: Record<string, unknown>; paint: Record<string, unknown>;
}

/** The GeoJSON source the Chart adds for the coastline. */
export const coastlineSource = (region: string, base: string, path: string = shorelineURL(region)) =>
  ({type: 'geojson' as const, data: new URL(path, base).href, attribution: layerEntry('coastline').attribution});

/** Glow under line, both drawn last (§ 9: the coastline glow is the top of the draw order). */
export function coastlineLayers(p: Palette): LineLayer[] {
  const layout = {'line-cap': 'round', 'line-join': 'round'};
  return [
    {id: COASTLINE_GLOW, type: 'line', source: COASTLINE_SOURCE, layout,
      paint: {'line-color': p.blue, 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 3, 14, 7], 'line-blur': 4, 'line-opacity': 0.28}},
    {id: COASTLINE_LINE, type: 'line', source: COASTLINE_SOURCE, layout,
      paint: {'line-color': p.muted, 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 0.8, 14, 1.4], 'line-opacity': 0.85}},
  ];
}

/** What the mark card shows for any Chart selection (web/app/MarkCard.tsx renders it). */
export interface ChartMark {
  /** Position supplied by the source; omitted for withheld marks and area-only cards. */
  readonly position?: {latitude: number; longitude: number};
  readonly id: string; readonly name: string; readonly kind: string; readonly reading: string; readonly source: string; readonly basis: string;
  /** The official page with the rules that apply there (FE-19's protected areas); the card's Regulations action opens it. */
  readonly regulations?: {readonly href: string; readonly label: string};
  /** The regulations line (FE-18): what the feature's own build screened, and the rules check. */
  readonly rules?: string;
  /** An atlas mark the run-time screen withholds (#489): the card offers no trip actions. */
  readonly withheld?: boolean;
  /** The trip plan's spot this card reviews in the planner (a ranked trip spot, #495). */
  readonly trip?: string;
  /** The source publishers' own terms pages (https only), linked beside the basis as v1's "Publisher terms" was. */
  readonly terms?: readonly {readonly href: string; readonly label: string}[];
}

const text = (value: unknown): string => typeof value === 'string' ? value.trim() : typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * The mark for a clicked shoreline feature, from its own properties: CUSP's
 * ATTRIBUTE ("Natural.Mean High Water") and DATA_SOURC, the source date FE-10
 * kept per feature and the stated horizontal accuracy in metres. A feature
 * without a valid source date is not selectable (FE-10 drops undated features).
 */
export function coastlineMark(properties: Record<string, unknown> | null | undefined): ChartMark | null {
  const p = properties ?? {};
  const date = text(p.source_date);
  if (!DATE.test(date)) return null;
  const [kind, line] = text(p.ATTRIBUTE).split('.', 2).map(s => s.trim());
  const method = text(p.DATA_SOURC), accuracy = Number(text(p.HOR_ACC));
  return {
    id: `coastline:${text(p.SOURCE_ID) || text(p.source_tile) || date}`,
    name: 'Shoreline',
    kind: [line || kind, line ? kind : ''].filter(Boolean).join(' · ') || 'Shoreline segment',
    reading: [method, Number.isFinite(accuracy) && accuracy > 0 ? `±${accuracy} m stated` : ''].filter(Boolean).join(' · ') || 'Accuracy not stated',
    source: `NOAA NGS CUSP · source date ${date}`,
    basis: layerEntry('coastline').basis,
  };
}
