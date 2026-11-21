// FE14a: HAB-1 polygons are seafloor context, not fishing targets, depth
// qualification or ranked habitat. This module neither loads nor enables a layer.
import type {FilterSpecification, LayerSpecification} from 'maplibre-gl';
import type {Palette, PaletteKey} from './palette.ts';

const SOURCE = 'habitat-context';
const CHART_MIN_ZOOM = 10;
// Chart camera zoom is MapLibre zoom + 1 (engine.ts).
const MIN_ZOOM = CHART_MIN_ZOOM - 1;
const SWATCHES = {unknown: 'mapBoundary', rock: 'habRock', mixed: 'habMixed', sediment: 'habSoft', kelp: 'habKelp'} as const satisfies Record<string, PaletteKey>;
const CLASS_LABELS = {unknown: 'Unknown', rock: 'Rock', mixed: 'Mixed', sediment: 'Sediment', kelp: 'Kelp'} as const;
const CLASSES = Object.keys(SWATCHES) as (keyof typeof SWATCHES)[];
const EVIDENCE = ['historical', 'predicted', 'measured'] as const;
export type HabitatClass = keyof typeof SWATCHES;
export type HabitatEvidence = typeof EVIDENCE[number];

type Geometry = {type: 'Polygon'; coordinates: number[][][]} | {type: 'MultiPolygon'; coordinates: number[][][][]};
export interface HabitatContextProperties {
  readonly class: HabitatClass;
  readonly evidence: HabitatEvidence;
  readonly source_id: string;
  readonly date?: string;
  readonly nonexport: true;
  readonly fishing_target: false;
  readonly fishing_export: false;
  readonly depth_qualified: false;
  readonly military_access?: 'verified' | 'unverified';
  readonly military_hold?: boolean;
  readonly closure_hold?: boolean;
}
export interface HabitatContextFeature {
  readonly type: 'Feature';
  readonly id: string;
  readonly geometry: Geometry;
  readonly properties: HabitatContextProperties;
}
interface DecodedHabitatContext {
  readonly collection: {type: 'FeatureCollection'; features: HabitatContextFeature[]} | null;
  /** Null index identifies a collection-level error. No raw source text enters reasons. */
  readonly refused: readonly {index: number | null; reason: string}[];
}

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
const bounded = (value: unknown, limit: number): value is number => typeof value === 'number' && Math.abs(value) <= limit;

// Check the 2D RFC 7946 shape without rewriting rings or filling holes. HAB-1
// owns full topology validation and clips against its reviewed exclusion snapshot.
function ring(value: unknown): value is number[][] {
  if (!Array.isArray(value) || value.length < 4 || value.includes(undefined) || !value.every(pt =>
    Array.isArray(pt) && pt.length === 2 && bounded(pt[0], 180) && bounded(pt[1], 90))) return false;
  const [x, y] = value[0]!, [lastX, lastY] = value.at(-1)!;
  if (x !== lastX || y !== lastY) return false;
  let area = 0;
  for (let i = 1; i < value.length; i++) {
    const [ax, ay] = value[i - 1]!, [bx, by] = value[i]!;
    area += (ax - x) * (by - y) - (bx - x) * (ay - y);
  }
  return area !== 0;
}
const polygon = (value: unknown): value is number[][][] =>
  Array.isArray(value) && value.length > 0 && !value.includes(undefined) && value.every(ring);
function geometry(value: unknown): Geometry | null {
  if (!record(value) || 'crs' in value) return null;
  const {type, coordinates} = value;
  if (type === 'Polygon' && polygon(coordinates)) return {type, coordinates};
  if (type === 'MultiPolygon' && Array.isArray(coordinates) && coordinates.length &&
      !coordinates.includes(undefined) && coordinates.every(polygon)) return {type, coordinates};
  return null;
}

function datedHistory(value: string): boolean {
  const parts = value.split(' to ');
  return parts.length <= 2 && parts.every(day => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false;
    const time = Date.parse(day);
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === day;
  }) && (parts.length === 1 || parts[0]! <= parts[1]!);
}

function decodeFeature(value: unknown, sources: ReadonlySet<string>): HabitatContextFeature | string {
  if (!record(value) || value.type !== 'Feature' || 'crs' in value || !record(value.properties)) return 'Expected a GeoJSON Feature with properties';
  const shape = geometry(value.geometry);
  if (!shape) return 'Expected a 2D WGS84 polygon or multipolygon with closed, nondegenerate rings';
  const p = value.properties;
  const {id, source_id, source_class, source_date: date,
    military_access, military_hold, closure_hold} = p;
  const kind = CLASSES.find(k => k === p.habitat_kind), evidence = EVIDENCE.find(e => e === p.evidence_class);
  if (!text(id) || id !== value.id) return 'Feature and property ids must match';
  if (!kind) return 'Unsupported habitat_kind';
  if (!evidence) return 'Unsupported evidence_class';
  if (!text(source_id) || !sources.has(source_id)) return 'Unknown source_id';
  if (!text(source_class) && !(Array.isArray(source_class) && source_class.length && source_class.every(text))) return 'Invalid source_class';
  // Measured survey dates are producer metadata (which may be a range or note).
  // Historical context must carry a calendar date or an ordered date range.
  if ((date !== null && !text(date)) || (evidence === 'historical' && (!text(date) || !datedHistory(date)))) return 'Invalid source_date';
  if (p.fishing_target !== false || p.fishing_export !== false || p.depth_qualified !== false ||
      ('nonexport' in p && p.nonexport !== true)) return 'Expected nonexportable, non-depth-qualified context';
  if ((military_access !== undefined && military_access !== 'verified' && military_access !== 'unverified') ||
      ('military_hold' in p && typeof military_hold !== 'boolean') ||
      ('closure_hold' in p && typeof closure_hold !== 'boolean')) return 'Invalid military or closure flag';
  return {type: 'Feature', id, geometry: shape, properties: {
    class: kind, evidence, source_id,
    ...(date === null ? {} : {date}),
    nonexport: true, fishing_target: false, fishing_export: false, depth_qualified: false,
    ...(military_access === undefined ? {} : {military_access}),
    ...(typeof military_hold === 'boolean' ? {military_hold} : {}),
    ...(typeof closure_hold === 'boolean' ? {closure_hold} : {}),
  }};
}

/** Decode an already reviewed HAB-1 v1 file. Refuse malformed rows by input index;
 * a malformed envelope is distinct from a valid collection with no features.
 * Source ids are lineage only; this isn't a rights, freshness or release gate.
 */
export function decodeHabitatContext(geojson: unknown): DecodedHabitatContext {
  const invalid = (reason: string): DecodedHabitatContext => ({collection: null, refused: [{index: null, reason}]});
  if (!record(geojson) || geojson.type !== 'FeatureCollection' || 'crs' in geojson ||
      geojson.schema_version !== 1 || geojson.layer !== 'habitat' || !text(geojson.region_id) ||
      geojson.disclaimer !== 'NOT FOR NAVIGATION' || !Array.isArray(geojson.sources) || !Array.isArray(geojson.features)) {
    return invalid('Expected HAB-1 v1 habitat FeatureCollection');
  }
  const sources = new Set<string>();
  for (const source of geojson.sources) {
    if (!record(source) || !text(source.id) || sources.has(source.id)) return invalid('Invalid or duplicate source id');
    sources.add(source.id);
  }
  const collection = {type: 'FeatureCollection' as const, features: [] as HabitatContextFeature[]};
  const refused = [];
  for (const [index, feature] of geojson.features.entries()) {
    const decoded = decodeFeature(feature, sources);
    if (typeof decoded === 'string') refused.push({index, reason: decoded});
    else collection.features.push(decoded);
  }
  return {collection, refused};
}

const PAINT = {
  measured: {fill: 0.26, line: 0.85},
  predicted: {fill: 0.11, line: 0.42},
  historical: {fill: 0.08, line: 0.85},
} as const;

/** Use the decoded collection as a GeoJSON source at registryEntry.sources[0]. */
export function habitatContextLayers(palette: Palette): LayerSpecification[] {
  const fills: LayerSpecification[] = [], outlines: LayerSpecification[] = [];
  for (const evidence of EVIDENCE) {
    for (const kind of CLASSES) {
      const id = `${SOURCE}-${evidence}-${kind}`, color = palette[SWATCHES[kind]];
      const filter: FilterSpecification = ['all', ['==', ['get', 'class'], kind], ['==', ['get', 'evidence'], evidence],
        ['!=', ['get', 'military_access'], 'unverified'], ['!=', ['get', 'military_hold'], true], ['!=', ['get', 'closure_hold'], true]];
      const common = {source: SOURCE, minzoom: MIN_ZOOM, filter};
      fills.push({...common, id: `${id}-fill`, type: 'fill', paint: {'fill-color': color,
        'fill-opacity': PAINT[evidence].fill, 'fill-antialias': false}});
      outlines.push({...common, id: `${id}-line`, type: 'line', paint: {'line-color': color,
        'line-opacity': PAINT[evidence].line, 'line-width': 1.25, ...(evidence === 'historical' ? {'line-dasharray': [3, 2]} : {})}});
    }
  }
  return [...fills, ...outlines];
}

/** Only colours are theme-dependent; keep the evidence opacity/dash when restyling. */
export function themePaint(palette: Palette): readonly {layer: string; property: string; value: string}[] {
  return habitatContextLayers(palette).flatMap(layer => {
    if (layer.type === 'fill' && typeof layer.paint?.['fill-color'] === 'string')
      return [{layer: layer.id, property: 'fill-color', value: layer.paint['fill-color']}];
    if (layer.type === 'line' && typeof layer.paint?.['line-color'] === 'string')
      return [{layer: layer.id, property: 'line-color', value: layer.paint['line-color']}];
    return [];
  });
}

/** LAYERS-WIRE owns registration, loading and UI copy integration. */
export const registryEntry = {
  id: SOURCE, label: 'Seafloor type', control: 'seafloor', presentations: ['chart'],
  gate: `zoom ≥ ${CHART_MIN_ZOOM}`, sources: [SOURCE], time: ['static'], task: 'FE14a',
  basis: 'Measured, predicted and dated historical seafloor context, without fishing suitability ratings.',
  legend: CLASSES.map(kind => ({label: CLASS_LABELS[kind], swatch: SWATCHES[kind]})),
} as const;
