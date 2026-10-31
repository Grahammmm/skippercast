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
import {chartFileListed, chartFilesPending} from '../chart-files.ts';
import type {ChartMark} from './coastline.ts';
import {ZOOM_OFFSET, type Engine, type Overlay} from './engine.ts';
import {DEPTH_CONTOURS_SOURCE, layerEntry} from './layers.ts';
import {MPA_FILL} from './mpa.ts';
import {readPalette, type Palette} from './palette.ts';
import {camera} from './stage.ts';
import {LABEL_FONT} from './style.ts';

const REGISTRY_ID = 'depth-contours';
/** EC6 (docs/seafloor-ec.md): where the survey could not be verified, a muted area under a dashed outline. */
export const DEPTH_UNRESOLVED_FILL = 'depth-contours-unresolved-fill';
export const DEPTH_UNRESOLVED_LINE = 'depth-contours-unresolved-line';
export const DEPTH_EDGE = 'depth-contours-edge';
export const DEPTH_LINE = 'depth-contours-line';
/** A transparent wide line over every contour, edge and unresolved outline: the click target (the area's fill is one too). */
export const DEPTH_HIT = 'depth-contours-hit';
/** Labels on the index contours at every zoom, and on the others from DETAIL_ZOOM. */
export const DEPTH_LABEL = 'depth-contours-label';
export const DEPTH_LABEL_MINOR = 'depth-contours-label-minor';
/** The overlay's bottom layer: the fields below it (water temperature, swell) draw under it (§ 9 order). */
export const DEPTH_BOTTOM = DEPTH_UNRESOLVED_FILL;
/** The MapLibre zoom the full contours load from (depth_contours.py OVERVIEW_MAX_ZOOM); `?view=` zooms are ZOOM_OFFSET more. */
export const DETAIL_ZOOM = 12;
/** depth_contours.py INTERVAL_FT and INDEX_FT. */
export const INTERVAL_FT = 30;
export const INDEX_FT = 150;
const KINDS = ['contour', 'survey-edge', 'unresolved-area'];
/** seafloor_ec.py PROVENANCE_CLASSES and UNRESOLVED_REASONS. */
const PROVENANCE = ['measured', 'filled', 'verified'];
const REASONS = ['hole', 'conflict', 'ring-range', 'datum-suspect', 'nodata'];

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
/** A bound survey the file does not draw, with its catalog review_status (provenance `sources_omitted`). */
export interface OmittedSource {readonly source_id: string; readonly review_status: string}
/** drawn: checked and current; none: the region publishes none; withheld: past its age limit; failed: did not load or failed its check. */
export type ContourStatus = 'idle' | 'loading' | 'drawn' | 'none' | 'withheld' | 'failed';
export interface ContourAssessment {
  readonly status: 'drawn' | 'withheld' | 'failed';
  readonly data: ContourCollection | null;
  readonly sources: readonly ContourSource[];
  readonly expires: string | null;
  readonly omitted: readonly OmittedSource[];
}
export interface ContourState {
  readonly status: ContourStatus; readonly note: string; readonly sources: readonly ContourSource[]; readonly omitted: readonly OmittedSource[];
}

export const NOTES = {
  none: '',
  withheld: 'Depth contours withheld: their source review is past its one-year age limit.',
  failed: 'Depth contours did not load, so none are drawn.',
  loading: 'Loading depth contours.',
} as const;
const IDLE: ContourState = Object.freeze({status: 'idle', note: '', sources: [], omitted: []});
const FAILED: ContourAssessment = Object.freeze({status: 'failed', data: null, sources: [], expires: null, omitted: []});
const PHRASE = new Map([['candidate', 'not yet reviewed'], ['restricted', 'restricted']]);

/** What a drawn file leaves out: its bound surveys that are not approved, then any approved ones it did not trace ('' if none are unapproved). */
export function omittedNote(omitted: readonly OmittedSource[]): string {
  const unreviewed = omitted.filter(o => o.review_status !== 'approved'), untraced = omitted.filter(o => o.review_status === 'approved');
  const n = unreviewed.length, m = untraced.length;
  if (!n) return '';
  const items = unreviewed.map(o => `${o.source_id} (${PHRASE.get(o.review_status) ?? o.review_status})`).join(', ');
  return `${n} bound survey${n === 1 ? '' : 's'} not drawn: ${items}.`
    + (m ? ` ${m} reviewed survey${m === 1 ? '' : 's'} not traced in this file: ${untraced.map(o => o.source_id).join(', ')}.` : '');
}
/** What the legend shows for the contours. */
export const contourState = signal<ContourState>(IDLE);

const obj = (v: unknown): Json | null => v && typeof v === 'object' && !Array.isArray(v) ? v as Json : null;
const text = (v: unknown): string => typeof v === 'string' ? v.trim() : '';
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const points = (l: unknown, min: number): l is unknown[][] =>
  Array.isArray(l) && l.length >= min && l.every(p => Array.isArray(p) && p.length >= 2 && p.every(n => Number.isFinite(n)));
const line = (g: Json | null): boolean => {
  const type = text(g?.type), c = g?.coordinates, ok = (l: unknown): boolean => points(l, 2);
  return type === 'LineString' ? ok(c) : type === 'MultiLineString' && Array.isArray(c) && c.length > 0 && c.every(ok);
};
/** A (Multi)Polygon whose every ring has at least 4 finite points and ends where it starts. */
const area = (g: Json | null): boolean => {
  // The renderer receives the original geometry and requires canonical GeoJSON type names.
  const type = g?.type, c = g?.coordinates;
  const ring = (r: unknown): boolean => points(r, 4) && JSON.stringify(r[0]) === JSON.stringify(r.at(-1));
  const rings = (p: unknown): boolean => Array.isArray(p) && p.length > 0 && p.every(ring);
  return type === 'Polygon' ? rings(c) : type === 'MultiPolygon' && Array.isArray(c) && c.length > 0 && c.every(rings);
};

/**
 * Check a published contour file for `id` at `today` (YYYY-MM-DD, UTC): its region, feet, the 30 ft interval, a
 * listed source with survey date and datum on every line, line geometry, and `review_expires`. Past that date
 * the contours are withheld; any other gap fails the whole file (nothing partial draws).
 */
export function assessContours(data: unknown, id: string, today: string): ContourAssessment {
  const failed = FAILED;
  const d = obj(data), p = obj(d?.provenance), list = d?.features;
  if (d?.type !== 'FeatureCollection' || !p || p.region_id !== id || p.units !== 'ft' || p.interval_ft !== INTERVAL_FT || !Array.isArray(list)) return failed;
  const expires = text(p.review_expires);
  if (!DAY.test(expires)) return failed;
  const sources = (Array.isArray(p.sources) ? p.sources : []).map(obj).filter((s): s is Json => !!s).map(s => ({
    source_id: text(s.source_id), name: text(s.name), url: text(s.url), attribution: text(s.attribution),
    survey_date: text(s.survey_date), vertical_datum: text(s.vertical_datum)}));
  if (!sources.length || sources.some(s => !s.source_id || !s.name || !s.survey_date || !s.vertical_datum)) return failed;
  // The bound surveys this file leaves out: required, each named with its review status (an empty list is valid).
  const omitted = Array.isArray(p.sources_omitted)
    ? p.sources_omitted.map(o => ({source_id: text(obj(o)?.source_id), review_status: text(obj(o)?.review_status)})) : null;
  if (!omitted || omitted.some(o => !o.source_id || !o.review_status)) return failed;
  const byId = new Map(sources.map(s => [s.source_id, s]));
  const valid = list.every(f => {
    const props = obj(obj(f)?.properties), s = byId.get(text(props?.source_id));
    // The kind is matched exactly, as the layer filters match it: a padded kind would pass here and draw nowhere.
    if (!props || !s || !KINDS.includes(props.kind as string) || props.survey_date !== s.survey_date || props.vertical_datum !== s.vertical_datum) return false;
    const depth = props.depth_ft;
    if (props.kind === 'contour' && !(Number.isInteger(depth) && (depth as number) > 0 && (depth as number) % INTERVAL_FT === 0)) return false;
    if (props.provenance !== undefined && !PROVENANCE.includes(props.provenance as string)) return false;
    // An unresolved area is a polygon with a known reason; only a conflict carries the shallower reading.
    if (props.kind !== 'unresolved-area') return line(obj(obj(f)?.geometry));
    const hint = props.shoal_hint_ft, conflict = props.reason === 'conflict';
    if (!REASONS.includes(props.reason as string)) return false;
    if (conflict ? !(Number.isInteger(hint) && (hint as number) > 0) : hint !== undefined) return false;
    return area(obj(obj(f)?.geometry));
  });
  if (!valid) return failed;
  if (today > expires) return {status: 'withheld', data: null, sources, expires, omitted};
  return {status: 'drawn', data: {type: 'FeatureCollection', features: list as Json[]}, sources, expires, omitted};
}

/** Unresolved areas (muted, dashed outline), survey edge (dashed), contours (index heavier, verified heavier still,
 * filled dashed), the click target, then the labels in feet. */
export function contoursOverlay(p: Palette, data: ContourCollection): Overlay {
  const contour = ['==', ['get', 'kind'], 'contour'], index = ['==', ['get', 'index'], true];
  const unresolved = ['==', ['get', 'kind'], 'unresolved-area'];
  const heavier = (w: unknown) => ['*', w, ['case', ['==', ['get', 'provenance'], 'verified'], 1.25, 1]];
  const label = {'symbol-placement': 'line', 'text-field': ['concat', ['to-string', ['get', 'depth_ft']], ' ft'], 'text-font': [LABEL_FONT],
    'text-size': ['interpolate', ['linear'], ['zoom'], 9, 10, 14, 12], 'symbol-spacing': 320, 'text-max-angle': 30};
  const labelPaint = {'text-color': p.depth1, 'text-halo-color': p.bg, 'text-halo-width': 1.2};
  return {
    sources: {[DEPTH_CONTOURS_SOURCE]: {type: 'geojson', data, attribution: layerEntry(REGISTRY_ID).attribution} as MapLibre.SourceSpecification},
    layers: [
      {id: DEPTH_UNRESOLVED_FILL, type: 'fill', source: DEPTH_CONTOURS_SOURCE, filter: unresolved, paint: {'fill-color': p.muted, 'fill-opacity': 0.18}},
      {id: DEPTH_UNRESOLVED_LINE, type: 'line', source: DEPTH_CONTOURS_SOURCE, filter: unresolved, layout: {'line-join': 'round'},
        paint: {'line-color': p.muted, 'line-width': 1, 'line-dasharray': [1, 2]}},
      {id: DEPTH_EDGE, type: 'line', source: DEPTH_CONTOURS_SOURCE, filter: ['==', ['get', 'kind'], 'survey-edge'], layout: {'line-join': 'round'},
        paint: {'line-color': p.muted, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 14, 1.4], 'line-dasharray': [2, 2], 'line-opacity': 0.8}},
      {id: DEPTH_LINE, type: 'line', source: DEPTH_CONTOURS_SOURCE, filter: contour, layout: {'line-join': 'round', 'line-cap': 'round'},
        paint: {'line-color': p.depth1,
          // A zoom curve must stay the outermost expression, so the verified factor multiplies each stop.
          'line-width': ['interpolate', ['linear'], ['zoom'], 8, heavier(['case', index, 0.9, 0.4]), 14, heavier(['case', index, 1.6, 0.8])],
          'line-dasharray': ['case', ['==', ['get', 'provenance'], 'filled'], ['literal', [4, 3]], ['literal', [1, 0]]],
          'line-opacity': ['case', index, 0.85, 0.55]}},
      {id: DEPTH_HIT, type: 'line', source: DEPTH_CONTOURS_SOURCE, paint: {'line-color': p.depth1, 'line-width': 12, 'line-opacity': 0}},
      {id: DEPTH_LABEL, type: 'symbol', source: DEPTH_CONTOURS_SOURCE, filter: ['all', contour, index], layout: label, paint: labelPaint},
      {id: DEPTH_LABEL_MINOR, type: 'symbol', source: DEPTH_CONTOURS_SOURCE, minzoom: DETAIL_ZOOM, filter: ['all', contour, ['!', index]], layout: label, paint: labelPaint},
    ] as MapLibre.LayerSpecification[],
  };
}

/** What a contour run's provenance adds to its card, and the card's reading for each unresolved reason (EC6). */
const PROVENANCE_READING = new Map([
  ['filled', ' Dashed: a small gap here was filled with the shallowest neighbouring depth; not measured at this spot.'],
  ['verified', ' Two independent surveys agree here within the published tolerance.']]);
const UNRESOLVED_READING = new Map([
  ['hole', 'The survey has no usable measurement here; the gap is too large to fill safely.'],
  ['conflict', 'Two surveys disagree here; the shallower reading is <shoal_hint_ft> ft. Treat as a possible shoal.'],
  ['ring-range', 'A small gap on a steep or rough bottom; not filled.'],
  ['datum-suspect', 'The two surveys may use different vertical datums; not compared.'],
  ['nodata', 'No data.']]);

/** The card for a clicked line, from its own properties and its listed survey: depth, interval, survey, date and datum,
 * then any bound survey the file does not draw (`omittedNote`). */
export function contourMark(properties: Record<string, unknown> | null | undefined, sources: readonly ContourSource[], omitted: readonly OmittedSource[] = []): ChartMark | null {
  const p = properties ?? {}, s = sources.find(x => x.source_id === p.source_id);
  if (!s || !KINDS.includes(p.kind as string)) return null;
  const source = `${s.name} · ${s.attribution || 'survey grid'} · surveyed ${s.survey_date} · ${s.vertical_datum}`;
  const basis = layerEntry(REGISTRY_ID).basis;
  const terms = /^https:\/\//.test(s.url) ? [{href: s.url, label: 'Survey data release'}] : undefined;
  const note = omittedNote(omitted), more = note ? ` ${note}` : '';
  if (p.kind === 'unresolved-area') {
    const hint = Number(p.shoal_hint_ft), reason = String(p.reason), reading = UNRESOLVED_READING.get(reason);
    if (!reading || (reason === 'conflict' && !(Number.isInteger(hint) && hint > 0))) return null;
    return {
      id: `depth-contours:${s.source_id}:unresolved:${reason}`, name: 'Unverified / no data', kind: 'Where the survey could not be verified',
      reading: `${reading.replace('<shoal_hint_ft>', String(hint))}${more}`, source, basis, ...(terms ? {terms} : {}),
    };
  }
  if (p.kind === 'survey-edge') return {
    id: `depth-contours:${s.source_id}:edge`, name: 'Survey edge', kind: 'Where the reviewed survey grid stops',
    reading: `No reviewed grid continues past this line, so no contours are drawn beyond it; that is missing data, not flat water.${more}`,
    source, basis, ...(terms ? {terms} : {}),
  };
  const depth = Number(p.depth_ft);
  if (!Number.isInteger(depth) || depth <= 0) return null;
  return {
    id: `depth-contours:${s.source_id}:${depth}`, name: `${depth} ft depth contour`,
    kind: depth % INDEX_FT === 0 ? `Index contour · every ${INDEX_FT} ft` : `Depth contour · every ${INTERVAL_FT} ft`,
    reading: `${depth} ft below the survey's ${s.vertical_datum}, traced from 16 m averaged blocks of the survey grid; not a sounding or a chart depth.${PROVENANCE_READING.get(p.provenance as string) ?? ''}${more}`,
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
      result = response.status === 404 ? 'none' : !response.ok ? FAILED
        : assessContours(await response.json(), id, new Date(now()).toISOString().slice(0, 10));
    } catch { result = FAILED; }
    if (alive && region.peek() === id && asked === path) loaded.value = {region: id, path, result};
  }
  const disposers = [
    // The overview until the camera reaches the detail zoom, then the full contours for the rest of the visit.
    effect(() => {
      const e = engine.value, id = region.value, c = camera.value;
      if (!e || !id || !c) return;
      // RF0850-2: nothing is asked while this region's region.json is loading; the effect runs again once its list is known.
      if (chartFilesPending(id)) { if (loaded.peek()?.region !== id) contourState.value = {status: 'loading', note: NOTES.loading, sources: [], omitted: []}; return; }
      const path = contoursFor(id, c.zoom, detailRegion === id);
      if (path === depthContoursURL(id)) detailRegion = id;
      if (path === asked) return;
      // A region that publishes none is not asked again for its full form.
      const l = loaded.peek();
      if (l && l.region === id && l.result === 'none') return;
      // RF0850-2: a file the loaded region.json does not list settles as none, as its 404 would, with no request.
      if (!chartFileListed(id, path.slice(path.lastIndexOf('/') + 1))) { asked = path; loaded.value = {region: id, path, result: 'none'}; return; }
      asked = path;
      if (!l || l.region !== id) contourState.value = {status: 'loading', note: NOTES.loading, sources: [], omitted: []};
      void load(id, path);
    }),
    effect(() => {
      const l = loaded.value, id = region.value;
      if (!l || l.region !== id) return;
      const r = l.result;
      contourState.value = r === 'none' ? {status: 'none', note: NOTES.none, sources: [], omitted: []}
        : {status: r.status, note: r.status === 'drawn' ? omittedNote(r.omitted) : NOTES[r.status], sources: r.sources, omitted: r.omitted};
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
    pick: {layers: [DEPTH_HIT, DEPTH_UNRESOLVED_FILL] as const, ordered: true, mark: (_layer: string, properties: Record<string, unknown> | null): ChartMark | null => {
      const l = loaded.peek();
      return l && l.result !== 'none' && l.result.status === 'drawn' ? contourMark(properties, l.result.sources, l.result.omitted) : null;
    }},
  };
}
