// The Chart basemap style (docs/plans/front-end/design.md § 4; FE-72): a quiet
// Protomaps vector basemap recoloured from the tokens. Land, water, parks, a
// state line and roads at high zoom only; town, water, harbor and road labels
// from zoom 9 (MapLibre zoom, 512 px tiles); no points of interest, so no
// sprite sheet. Every colour is a role picked from a Palette (web/map/palette.ts)
// and transparency is an *-opacity paint property, never a mixed colour, so
// tests/test_map_style.mjs can prove that no colour is written here.
// Variants: `day` for the app's Chart, `night` for the landing's live map (FE-25).
import type {Palette} from './palette.ts';

export const BASEMAP_ATTRIBUTION = '© OpenStreetMap contributors, © Protomaps';
export const BASEMAP_SOURCE = 'basemap';
/** Self-hosted glyphs: DM Sans Medium SDF ranges (scripts/basemap/build_glyphs.py). */
export const LABEL_FONT = 'dm-sans-medium';
export const LABEL_MIN_ZOOM = 9;

/** FE-10's pointer to the current basemap archive, under the page's /feeds/ route. */
export const BASEMAP_MANIFEST = 'feeds/tiles/basemap/manifest.json';
const ARCHIVE_KEY = /^tiles\/basemap\/[A-Za-z0-9._-]{1,120}\.pmtiles$/;

/** The basemap archive's absolute URL from the manifest, or null when there is no valid manifest. */
export async function basemapArchive(fetchFn: typeof fetch, page: string): Promise<string | null> {
  try {
    const response = await fetchFn(new URL(BASEMAP_MANIFEST, page).href, {signal: AbortSignal.timeout(15000)});
    if (!response.ok) return null;
    const manifest = await response.json() as {key?: unknown};
    return typeof manifest.key === 'string' && ARCHIVE_KEY.test(manifest.key) ? new URL(`feeds/${manifest.key}`, page).href : null;
  } catch { return null; }
}

export type BasemapVariant = 'day' | 'night';
export interface BasemapOptions {
  /** Absolute URL of the Protomaps extract (FE-10), read through the pmtiles:// protocol. */
  archive: string;
  /** Absolute URL of the published dist/basemap/ folder, ending in '/'. */
  assets: string;
  variant?: BasemapVariant;
}

/** The subset of the MapLibre style specification this module writes. */
export interface BasemapLayer {
  id: string;
  type: 'background' | 'fill' | 'line' | 'symbol';
  source?: string;
  'source-layer'?: string;
  minzoom?: number;
  filter?: unknown[];
  layout?: Record<string, unknown>;
  paint?: Record<string, unknown>;
}
export interface BasemapStyle {
  version: 8;
  name: string;
  glyphs: string;
  sources: Record<string, {type: 'vector'; url: string; attribution: string}>;
  layers: BasemapLayer[];
}

/** Colour roles for one variant, every value taken from the palette. */
export function basemapRoles(p: Palette, variant: BasemapVariant = 'day') {
  const night = variant === 'night';
  return {
    water: night ? p.bgDeep : p.bg,
    land: night ? p.bg : p.panel,
    park: p.panel2,
    boundary: p.line,
    road: night ? p.panel : p.line,
    roadMinor: p.panel2,
    label: p.muted,
    halo: night ? p.bgDeep : p.bg,
  };
}

const kind = (...kinds: string[]) => ['in', ['get', 'kind'], ['literal', kinds]];
const geometry = (type: 'Point' | 'LineString' | 'Polygon') => ['==', ['geometry-type'], type];
const ramp = (...stops: number[]) => ['interpolate', ['linear'], ['zoom'], ...stops];

/** The basemap style for `variant`, coloured from `palette`. */
export function basemapStyle(palette: Palette, {archive, assets, variant = 'day'}: BasemapOptions): BasemapStyle {
  const c = basemapRoles(palette, variant);
  const day = variant === 'day';
  const from = (id: string, sourceLayer: string, rest: Omit<BasemapLayer, 'id' | 'source' | 'source-layer'>): BasemapLayer =>
    ({id, source: BASEMAP_SOURCE, 'source-layer': sourceLayer, ...rest});
  const label = (size: unknown[], extra: Record<string, unknown> = {}) => ({
    layout: {'text-field': ['get', 'name'], 'text-font': [LABEL_FONT], 'text-size': size, 'text-max-width': 8, ...extra},
    paint: {'text-color': c.label, 'text-halo-color': c.halo, 'text-halo-width': 1.2, 'text-opacity': day ? 1 : 0.8},
  });
  const road = (id: string, kinds: string[], minzoom: number, color: string, width: unknown[]): BasemapLayer =>
    from(id, 'roads', {type: 'line', minzoom, filter: ['all', geometry('LineString'), kind(...kinds)],
      layout: {'line-cap': 'round', 'line-join': 'round'},
      paint: {'line-color': color, 'line-width': width, 'line-opacity': day ? 1 : 0.6}});

  const layers: (BasemapLayer | false)[] = [
    {id: 'background', type: 'background', paint: {'background-color': c.water}},
    from('earth', 'earth', {type: 'fill', paint: {'fill-color': c.land}}),
    day && from('parks', 'landuse', {type: 'fill', minzoom: 8, filter: kind('park', 'national_park', 'nature_reserve', 'protected_area'),
      paint: {'fill-color': c.park, 'fill-opacity': 0.6}}),
    from('water', 'water', {type: 'fill', filter: geometry('Polygon'), paint: {'fill-color': c.water}}),
    from('rivers', 'water', {type: 'line', minzoom: 10, filter: ['all', geometry('LineString'), kind('river', 'stream', 'canal')],
      paint: {'line-color': c.water, 'line-width': ramp(10, 0.5, 15, 2)}}),
    day && from('boundaries', 'boundaries', {type: 'line', filter: kind('country', 'region'),
      paint: {'line-color': c.boundary, 'line-width': 1, 'line-dasharray': [3, 2]}}),
    road('roads-highway', ['highway'], 10, c.road, ramp(10, 0.6, 15, 3)),
    day && road('roads-major', ['major_road'], 11, c.road, ramp(11, 0.5, 15, 2)),
    day && road('roads-minor', ['minor_road'], 13, c.roadMinor, ramp(13, 0.5, 16, 1.5)),
    day && from('labels-water', 'water', {type: 'symbol', minzoom: LABEL_MIN_ZOOM,
      filter: ['all', geometry('Point'), ['has', 'name']], ...label(ramp(9, 11, 14, 13), {'text-letter-spacing': 0.08})}),
    day && from('labels-roads', 'roads', {type: 'symbol', minzoom: 13, filter: ['all', kind('highway', 'major_road'), ['has', 'name']],
      ...label(ramp(13, 10, 16, 12), {'symbol-placement': 'line'})}),
    day && from('labels-harbor', 'pois', {type: 'symbol', minzoom: 12, filter: ['all', kind('marina'), ['has', 'name']],
      ...label(ramp(12, 11, 16, 13))}),
    from('labels-places', 'places', {type: 'symbol', minzoom: LABEL_MIN_ZOOM, filter: ['all', kind('locality'), ['has', 'name']],
      ...label(ramp(9, 11, 14, 15), {'symbol-sort-key': ['coalesce', ['get', 'min_zoom'], 99]})}),
  ];
  return {
    version: 8,
    name: `SkipperCast basemap (${variant})`,
    glyphs: `${assets}glyphs/{fontstack}/{range}.pbf`,
    sources: {[BASEMAP_SOURCE]: {type: 'vector', url: `pmtiles://${archive}`, attribution: BASEMAP_ATTRIBUTION}},
    layers: layers.filter((layer): layer is BasemapLayer => layer !== false),
  };
}
