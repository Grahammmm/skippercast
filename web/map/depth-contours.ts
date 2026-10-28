// Shelf depth contours on the Chart (CI6-13, docs/plans/front-end/design.md § 9):
// the region's contours traced from its reviewed survey grids by
// scripts/build_depth_contours.py and published by the platform build
// (src/skippercast/platform/depth_contours.py) as
// dist/regions/<id>/depth-contours.geojson, with an overview form the Chart
// draws below DETAIL_ZOOM, as the coastline does (coastline.ts `shorelineFor`).
// Always on, at every zoom, Chart only. The ENC chart base (zoom ≥ 10) is drawn
// as it was; these lines are a separate overlay above the fields and under the
// protected areas.
//
// Every line carries its survey, survey date and vertical datum; a click opens
// a card with them. The dashed survey edge is where the reviewed grid stops,
// so a missing line past it never reads as flat or shallow water. The file is
// checked before it draws (region, units, interval, sources) and withheld from
// its `review_expires` date (the layer's age limit). A region without a
// published file draws nothing (404).
//
// Erasable syntax only: tests/test_depth_contours.mjs imports this file by type stripping.
import {effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {region} from '../state.ts';
import type {ChartMark} from './coastline.ts';
import {ZOOM_OFFSET, type Engine, type Overlay} from './engine.ts';
import {DEPTH_CONTOURS_SOURCE, layerEntry} from './layers.ts';
import {MPA_FILL} from './mpa.ts';
import {readPalette, type Palette} from './palette.ts';
import {camera} from './stage.ts';
import {LABEL_FONT} from './style.ts';

const REGISTRY_ID = 'depth-contours';
export const DEPTH_EDGE = 'depth-contours-edge';
export const DEPTH_LINE = 'depth-contours-line';
/** A transparent wide line over every contour and edge: the click target. */
export const DEPTH_HIT = 'depth-contours-hit';
/** Labels on the index contours at every zoom, and on the others from DETAIL_ZOOM. */
export const DEPTH_LABEL = 'depth-contours-label';
export const DEPTH_LABEL_MINOR = 'depth-contours-label-minor';
/** The overlay's bottom layer: the fields below it (water temperature, swell) draw under it (§ 9 order). */
export const DEPTH_BOTTOM = DEPTH_EDGE;
/** The MapLibre zoom the full contours load from (depth_contours.py OVERVIEW_MAX_ZOOM); `?view=` zooms are ZOOM_OFFSET more. */
export const DETAIL_ZOOM = 12;
/** depth_contours.py INTERVAL_FT and INDEX_FT. */
export const INTERVAL_FT = 30;
export const INDEX_FT = 150;
const KINDS = ['contour', 'survey-edge'];

export const depthContoursURL = (id: string): string => `regions/${encodeURIComponent(id)}/depth-contours.geojson`;
export const depthContoursOverviewURL = (id: string): string => `regions/${encodeURIComponent(id)}/depth-contours-overview.geojson`;
/** The contour file the Chart draws at a `?view=` zoom: the overview below the detail zoom, unless the full one already loaded. */
export const contoursFor = (id: string, viewZoom: number, detail = false): string =>
  detail || viewZoom - ZOOM_OFFSET >= DETAIL_ZOOM ? depthContoursURL(id) : depthContoursOverviewURL(id);

type Json = Record<string, unknown>;
export interface ContourSource {
  readonly source_id: string; readonly name: string; readonly url: string; readonly attribution: string;
  readonly survey_date: string; readonly vertical_datum: string;
}
export interface ContourCollection {readonly type: 'FeatureCollection'; readonly features: readonly Json[]}
/** drawn: checked and current; none: the region publishes none; withheld: past its age limit; failed: did not load or failed its check. */
export type ContourStatus = 'idle' | 'loading' | 'drawn' | 'none' | 'withheld' | 'failed';
export interface ContourAssessment {
  readonly status: 'drawn' | 'withheld' | 'failed';
  readonly data: ContourCollection | null;
  readonly sources: readonly ContourSource[];
  readonly expires: string | null;
}
export interface ContourState {readonly status: ContourStatus; readonly note: string; readonly sources: readonly ContourSource[]}

export const NOTES = {
  none: '',
  withheld: 'Depth contours withheld: their source review is past its one-year age limit.',
  failed: 'Depth contours did not load, so none are drawn.',
  loading: 'Loading depth contours.',
} as const;
const IDLE: ContourState = Object.freeze({status: 'idle', note: '', sources: []});
/** What the legend shows for the contours. */
export const contourState = signal<ContourState>(IDLE);

const obj = (v: unknown): Json | null => v && typeof v === 'object' && !Array.isArray(v) ? v as Json : null;
const text = (v: unknown): string => typeof v === 'string' ? v.trim() : '';
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const line = (g: Json | null): boolean => {
  const type = text(g?.type), c = g?.coordinates;
  const ok = (l: unknown): boolean => Array.isArray(l) && l.length >= 2 && l.every(p => Array.isArray(p) && p.length >= 2 && p.every(n => Number.isFinite(n)));
  return type === 'LineString' ? ok(c) : type === 'MultiLineString' && Array.isArray(c) && c.length > 0 && c.every(ok);
};

/**
 * Check a published contour file for `id` at `today` (YYYY-MM-DD, UTC): its region, feet, the 30 ft interval, a
 * listed source with survey date and datum on every line, line geometry, and `review_expires`. Past that date
 * the contours are withheld; any other gap fails the whole file (nothing partial draws).
 */
export function assessContours(data: unknown, id: string, today: string): ContourAssessment {
  const failed: ContourAssessment = {status: 'failed', data: null, sources: [], expires: null};
  const d = obj(data), p = obj(d?.provenance), list = d?.features;
  if (d?.type !== 'FeatureCollection' || !p || p.region_id !== id || p.units !== 'ft' || p.interval_ft !== INTERVAL_FT || !Array.isArray(list)) return failed;
  const expires = text(p.review_expires);
  if (!DAY.test(expires)) return failed;
  const sources = (Array.isArray(p.sources) ? p.sources : []).map(obj).filter((s): s is Json => !!s).map(s => ({
    source_id: text(s.source_id), name: text(s.name), url: text(s.url), attribution: text(s.attribution),
    survey_date: text(s.survey_date), vertical_datum: text(s.vertical_datum)}));
  if (!sources.length || sources.some(s => !s.source_id || !s.name || !s.survey_date || !s.vertical_datum)) return failed;
  const byId = new Map(sources.map(s => [s.source_id, s]));
  const valid = list.every(f => {
    const props = obj(obj(f)?.properties), s = byId.get(text(props?.source_id));
    if (!props || !s || !KINDS.includes(text(props.kind)) || props.survey_date !== s.survey_date || props.vertical_datum !== s.vertical_datum) return false;
    const depth = props.depth_ft;
    if (props.kind === 'contour' && !(Number.isInteger(depth) && (depth as number) > 0 && (depth as number) % INTERVAL_FT === 0)) return false;
    return line(obj(obj(f)?.geometry));
  });
  if (!valid) return failed;
  if (today > expires) return {status: 'withheld', data: null, sources, expires};
  return {status: 'drawn', data: {type: 'FeatureCollection', features: list as Json[]}, sources, expires};
}

/** Survey edge (dashed), contours (index heavier), the click target, then the labels in feet. */
export function contoursOverlay(p: Palette, data: ContourCollection): Overlay {
  const contour = ['==', ['get', 'kind'], 'contour'], index = ['==', ['get', 'index'], true];
  const label = {'symbol-placement': 'line', 'text-field': ['concat', ['to-string', ['get', 'depth_ft']], ' ft'], 'text-font': [LABEL_FONT],
    'text-size': ['interpolate', ['linear'], ['zoom'], 9, 10, 14, 12], 'symbol-spacing': 320, 'text-max-angle': 30};
  const labelPaint = {'text-color': p.depth1, 'text-halo-color': p.bg, 'text-halo-width': 1.2};
  return {
    sources: {[DEPTH_CONTOURS_SOURCE]: {type: 'geojson', data, attribution: layerEntry(REGISTRY_ID).attribution} as MapLibre.SourceSpecification},
    layers: [
      {id: DEPTH_EDGE, type: 'line', source: DEPTH_CONTOURS_SOURCE, filter: ['==', ['get', 'kind'], 'survey-edge'], layout: {'line-join': 'round'},
        paint: {'line-color': p.muted, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 14, 1.4], 'line-dasharray': [2, 2], 'line-opacity': 0.8}},
      {id: DEPTH_LINE, type: 'line', source: DEPTH_CONTOURS_SOURCE, filter: contour, layout: {'line-join': 'round', 'line-cap': 'round'},
        paint: {'line-color': p.depth1,
          'line-width': ['interpolate', ['linear'], ['zoom'], 8, ['case', index, 0.9, 0.4], 14, ['case', index, 1.6, 0.8]],
          'line-opacity': ['case', index, 0.85, 0.55]}},
      {id: DEPTH_HIT, type: 'line', source: DEPTH_CONTOURS_SOURCE, paint: {'line-color': p.depth1, 'line-width': 12, 'line-opacity': 0}},
      {id: DEPTH_LABEL, type: 'symbol', source: DEPTH_CONTOURS_SOURCE, filter: ['all', contour, index], layout: label, paint: labelPaint},
      {id: DEPTH_LABEL_MINOR, type: 'symbol', source: DEPTH_CONTOURS_SOURCE, minzoom: DETAIL_ZOOM, filter: ['all', contour, ['!', index]], layout: label, paint: labelPaint},
    ] as MapLibre.LayerSpecification[],
  };
}

/** The card for a clicked line, from its own properties and its listed survey: depth, interval, survey, date and datum. */
export function contourMark(properties: Record<string, unknown> | null | undefined, sources: readonly ContourSource[]): ChartMark | null {
  const p = properties ?? {}, s = sources.find(x => x.source_id === p.source_id);
  if (!s || !KINDS.includes(text(p.kind))) return null;
  const source = `${s.name} · ${s.attribution || 'survey grid'} · surveyed ${s.survey_date} · ${s.vertical_datum}`;
  const basis = layerEntry(REGISTRY_ID).basis;
  const terms = /^https:\/\//.test(s.url) ? [{href: s.url, label: 'Survey data release'}] : undefined;
  if (p.kind === 'survey-edge') return {
    id: `depth-contours:${s.source_id}:edge`, name: 'Survey edge', kind: 'Where the reviewed survey grid stops',
    reading: 'No reviewed grid continues past this line, so no contours are drawn beyond it; that is missing data, not flat water.',
    source, basis, ...(terms ? {terms} : {}),
  };
  const depth = Number(p.depth_ft);
  if (!Number.isInteger(depth) || depth <= 0) return null;
  return {
    id: `depth-contours:${s.source_id}:${depth}`, name: `${depth} ft depth contour`,
    kind: depth % INDEX_FT === 0 ? `Index contour · every ${INDEX_FT} ft` : `Depth contour · every ${INTERVAL_FT} ft`,
    reading: `${depth} ft below the survey's ${s.vertical_datum}, traced from 16 m averaged blocks of the survey grid; not a sounding or a chart depth.`,
    source, basis, ...(terms ? {terms} : {}),
  };
}

export interface DepthContourOptions {
  engine: ReadonlySignal<Engine | null>;
  fetchFn?: typeof fetch; page?: () => string; palette?: () => Palette; now?: () => number;
}

type Loaded = {region: string; path: string; result: ContourAssessment | 'none'};

/** Loads, checks and draws the region's contours; created with the Chart (web/app/MapStage.tsx `layers`). */
export function createDepthContours({engine, fetchFn = (...a) => fetch(...a), page = () => location.href, palette = () => readPalette(), now = () => Date.now()}: DepthContourOptions) {
  const loaded = signal<Loaded | null>(null);
  let asked = '', detailRegion: string | null = null, drawn = false, drawnOn: Engine | null = null, alive = true;
  async function load(id: string, path: string): Promise<void> {
    let result: Loaded['result'];
    try {
      const response = await fetchFn(new URL(path, page()).href, {signal: AbortSignal.timeout(20000)});
      result = response.status === 404 ? 'none' : !response.ok ? {status: 'failed', data: null, sources: [], expires: null}
        : assessContours(await response.json(), id, new Date(now()).toISOString().slice(0, 10));
    } catch { result = {status: 'failed', data: null, sources: [], expires: null}; }
    if (alive && region.peek() === id && asked === path) loaded.value = {region: id, path, result};
  }
  const disposers = [
    // The overview until the camera reaches the detail zoom, then the full contours for the rest of the visit.
    effect(() => {
      const e = engine.value, id = region.value, c = camera.value;
      if (!e || !id || !c) return;
      const path = contoursFor(id, c.zoom, detailRegion === id);
      if (path === depthContoursURL(id)) detailRegion = id;
      if (path === asked) return;
      // A region that publishes none is not asked again for its full form.
      const l = loaded.peek();
      if (l && l.region === id && l.result === 'none') return;
      asked = path;
      if (!l || l.region !== id) contourState.value = {status: 'loading', note: NOTES.loading, sources: []};
      void load(id, path);
    }),
    effect(() => {
      const l = loaded.value, id = region.value;
      if (!l || l.region !== id) return;
      const r = l.result;
      contourState.value = r === 'none' ? {status: 'none', note: NOTES.none, sources: []}
        : {status: r.status, note: r.status === 'drawn' ? '' : NOTES[r.status], sources: r.sources};
    }),
    effect(() => {
      const e = engine.value, l = loaded.value, id = region.value;
      if (!e) return;
      const data = l && l.region === id && l.result !== 'none' && l.result.status === 'drawn' ? l.result.data : null;
      if (!data) { if (drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, null); drawn = false; drawnOn = e; return; }
      // § 9 draw order: above the water temperature and swell fields, under the protected areas.
      if (!drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, contoursOverlay(palette(), data), MPA_FILL);
      e.setData(DEPTH_CONTOURS_SOURCE, data as never);
      drawn = true; drawnOn = e;
    }),
  ];
  return {
    destroy() { alive = false; for (const dispose of disposers) dispose(); contourState.value = IDLE; },
    pick: {layers: [DEPTH_HIT] as const, ordered: true, mark: (_layer: string, properties: Record<string, unknown> | null): ChartMark | null => {
      const l = loaded.peek();
      return l && l.result !== 'none' && l.result.status === 'drawn' ? contourMark(properties, l.result.sources) : null;
    }},
  };
}
