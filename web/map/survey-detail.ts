// MB-09 already clips all detail, including tier none, to mapping-zone water.
// Never infer unsurveyed water from an absent tile, unknown tier or empty file.
import type {ExpressionSpecification, FilterSpecification, LayerSpecification} from 'maplibre-gl';
import type {SourceData} from './engine.ts';
import type {Palette} from './palette.ts';
import {LABEL_FONT} from './style.ts';

const measuredLabel = {'1m-measured': '1 m measured', '2m': '2 m', '5m': '5 m'} as const;
type MeasuredTier = keyof typeof measuredLabel;
type Tier = MeasuredTier | 'estimated' | 'none';
const maximumGrid = {'1m-measured': 1, '2m': 2, '5m': 5} as const;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && !!value.trim();
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const measured = (tier: unknown): tier is MeasuredTier => typeof tier === 'string' && Object.hasOwn(measuredLabel, tier);

type FootprintProperties = {tier: Tier; grid_m?: number; source?: string; sourceId?: string;
  grid_tier?: '4-16m-compiled'; date?: string; label: string};

/** The renderer follows the producer's per-cell tier, not the nominal grid size. */
function surveyDetailText(p: Record<string, unknown>): string | null {
  if (p.tier === 'none') return 'No survey';
  if (!finite(p.grid_m) || p.grid_m <= 0 || !text(p.source)) return null;
  if (p.tier === 'estimated') return `estimated (${p.grid_m} m grid, ${p.source})`;
  return measured(p.tier) && p.grid_m <= maximumGrid[p.tier] ? measuredLabel[p.tier] : null;
}

/** MB-09 writes Polygon or MultiPolygon with holes. Retain the actual geometry,
 * not its envelope, and reject an invalid collection rather than guessing. */
export function decodeSurveyDetail(region: string, value: unknown, reviewedSources: ReadonlySet<string>): Exclude<SourceData, string> | null {
  if (!record(value) || value.type !== 'FeatureCollection' || value.region !== region ||
      value.navigation !== 'NOT FOR NAVIGATION' || !Array.isArray(value.features)) return null;
  const features = [];
  for (const feature of value.features) {
    if (!record(feature) || feature.type !== 'Feature' || !record(feature.properties) || !record(feature.geometry)) return null;
    const {properties: p, geometry: g} = feature;
    const label = surveyDetailText(p);
    if (label === null || !Array.isArray(p.sources)) return null;
    const id: unknown = p.sources[0];
    if (p.tier === 'none' ? p.sources.length !== 0 : p.sources.length !== 1 || typeof id !== 'string' || !reviewedSources.has(id)) return null;
    // MB-09 represents compiled grids as estimated, never as a separate
    // measured tier. Reject a contradictory payload instead of promoting it.
    if (p.grid_tier !== undefined && (p.grid_tier !== '4-16m-compiled' || p.tier !== 'estimated')) return null;
    const coordinates = g.coordinates;
    function polygon(value: unknown): value is number[][][] {
      return Array.isArray(value) && value.length > 0 && value.every(ring =>
        Array.isArray(ring) && ring.length >= 4 && ring.every(pt => Array.isArray(pt) && pt.length === 2 &&
          finite(pt[0]) && Math.abs(pt[0]) <= 180 && finite(pt[1]) && Math.abs(pt[1]) <= 90) &&
        ring[0][0] === ring.at(-1)[0] && ring[0][1] === ring.at(-1)[1]);
    }
    const geometry = g.type === 'Polygon' && polygon(coordinates) ? {type: 'Polygon' as const, coordinates}
      : g.type === 'MultiPolygon' && Array.isArray(coordinates) && coordinates.length && coordinates.every(polygon)
        ? {type: 'MultiPolygon' as const, coordinates} : null;
    if (!geometry) return null;
    const properties: FootprintProperties = {tier: p.tier as Tier, label};
    if (p.tier !== 'none') {
      properties.source = p.source as string;
      properties.sourceId = id as string;
      properties.grid_m = p.grid_m as number;
      if (p.grid_tier === '4-16m-compiled') properties.grid_tier = p.grid_tier;
      if (text(p.date)) properties.date = p.date;
    }
    features.push({type: 'Feature' as const, geometry, properties});
  }
  return {type: 'FeatureCollection', features};
}

/** A seamless 10 CSS-px pattern; a 2x atlas image keeps the line legible on a phone. */
export const SURVEY_HATCH_PIXEL_RATIO = 2;
export function surveyHatch(palette: Pick<Palette, 'mapNosurvey'>, light: boolean): ImageData | null {
  const size = 10, scale = SURVEY_HATCH_PIXEL_RATIO;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size * scale;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.scale(scale, scale);
  ctx.strokeStyle = palette.mapNosurvey;
  ctx.lineWidth = light ? 1.4 : 1.2;
  ctx.beginPath();
  // Neighbour strokes anti-alias across the opposite corners of the image.
  for (const phase of [0, size, 2 * size]) {
    ctx.moveTo(-size, phase + size);
    ctx.lineTo(2 * size, phase - 2 * size);
  }
  ctx.stroke();
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

/** Bottom-to-top order, below the redraw of basemap land and parks. Only the
 * optional tint, outline and labels change visibility; the hatch is always on. */
export function surveyDetailLayers(source: string, id: string, pattern: string, p: Palette, light: boolean): LayerSpecification[] {
  const tier: ExpressionSpecification = ['get', 'tier'];
  const gap: FilterSpecification = ['==', tier, 'none'];
  const measuredOnly: FilterSpecification = ['in', tier, ['literal', Object.keys(measuredLabel)]];
  return [
    {id: `${id}-hatch`, source, type: 'fill', filter: gap,
      paint: {'fill-pattern': pattern, 'fill-opacity': 0.9, 'fill-antialias': false}},
    {id: `${id}-tint`, source, type: 'fill', filter: measuredOnly,
      paint: {'fill-color': ['match', tier, '2m', p.mapSurveyTint2, '5m', p.mapSurveyTint5, p.mapSurveyTint1],
        'fill-opacity': ['match', tier, '1m-measured', light ? 0.22 : 0.18, '2m', 0.14, '5m', light ? 0.08 : 0.10, 0]}},
    {id: `${id}-outline`, source, type: 'line',
      paint: {'line-color': p.mapSurveyInk, 'line-width': 1.4, 'line-dasharray': [4, 3]}},
    {id: `${id}-label`, source, type: 'symbol',
      layout: {'text-field': ['case', ['==', tier, 'estimated'], 'estimated', ['get', 'label']],
        'text-font': [LABEL_FONT], 'text-size': 11},
      paint: {'text-color': p.mapSurveyInk, 'text-halo-color': p.mapSurveyHalo, 'text-halo-width': 1.4}},
  ];
}
