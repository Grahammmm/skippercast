// Kelp canopy layer (MB-17a): what the map may say about kelp, and how it is drawn. Pure; it
// never fetches. The registry row (layers.ts), the legend key, the catalogue strings and the
// source's minzoom/maxzoom (the producer, src/skippercast/relief/kelp.py, tiles z13-z16) are
// the later LAYERS-WIRE / MB-11b wiring; this module is what they call.
//
// POINTER CONTRACT (decided by the map plan; KELP-3 produces it later, this module only reads it).
// `catalog/relief/kelp.json`, parsed by the caller and handed in through `resolveKelp` or, when it
// has to be read first, through an injected resolver (`loadKelp`), so a test never fetches:
//   {schema: 'sc-kelp-pointer/1', status: 'reviewed', private: false, sha256, bytes, url,
//    products: [{sensor: 'Planet 3 m' | 'Landsat 30 m', season, year, quarter?}]}
// - `private` must be exactly `false` and `status` exactly `'reviewed'` (relief-data.ts refuses the
//   same way); `sha256` is 64 lowercase hex, `bytes` a positive integer, `url` an https URL.
// - Planet products are the annual September map: `season: 'september'`, `quarter` omitted or 3.
// - Landsat products are quarters: `season` is winter, spring, summer or fall for Q1-Q4 (Kelpwatch's
//   own scheme); `quarter`, when given, must agree with it.
// - The tiles are one vector layer `kelp` whose features carry `season`, `year`, `sensor`.
//
// WORDING (DATA-LIVE-ROUTING §4, KELP-ACCESS §4 and §6). The label is "Kelp canopy seen <season>
// <year>" plus " (3 m)" or " (30 m)": a satellite pass, never "live" and never "current". A view
// more than two quarters old keeps its season but adds "not updated since <date>" and an "out of
// date" tag. No source is named on the map (G 11-18); credits live on the Sources page.
//
// OFF BY DEFAULT (KELP-ACCESS §6, MB-17a). The newest view wins (a Planet September wins a tie with
// a Landsat quarter: it is the better-looking canopy); the two are never blended. The layer is off
// by default when the newest view is a Planet September more than two quarters old (Planet-only
// and stale), or any view more than four quarters old. `offReason` says why.
//
// Erasable syntax only: tests/test_kelp.mjs imports this file by type stripping.
import type {ExpressionSpecification} from 'maplibre-gl';
import type {Palette} from './palette.ts';

export const KELP_SOURCE = 'kelp';
export const KELP_SOURCE_LAYER = 'kelp';
export const KELP_DOTS = 'kelp-dots';
export const KELP_OUTLINE = 'kelp-outline';
/** The dot pattern's image id (`themePatterns` replaces it in place on a theme change). */
export const KELP_DOTS_IMAGE = 'kelp-dots-pattern';
export const KELP_DOTS_PIXEL_RATIO = 2;
export const KELP_POINTER_SCHEMA = 'sc-kelp-pointer/1';

/** The 2016 CDFW survey stays history: it is never a fallback for recent canopy (KELP-ACCESS §6). For LAYERS-WIRE. */
export const KELP_HISTORICAL_2016 = Object.freeze({id: 'kelp-historical-2016', label: 'Kelp canopy 2016 (historical)', defaultOn: false});

export type KelpSensor = 'Planet 3 m' | 'Landsat 30 m';
export type KelpSeason = 'september' | 'winter' | 'spring' | 'summer' | 'fall';
export type KelpRefusal = 'missing' | 'unreadable' | 'schema' | 'private' | 'unreviewed' | 'identity' | 'products' | 'clock';
export interface KelpProduct {
  readonly sensor: KelpSensor; readonly season: KelpSeason; readonly year: number;
  /** 1-4; a Planet September is quarter 3. */
  readonly quarter: 1 | 2 | 3 | 4;
  readonly resolution: '3 m' | '30 m';
}
export interface KelpLayer {
  readonly sha256: string; readonly bytes: number; readonly url: string;
  readonly products: readonly KelpProduct[];
  /** The newest view: the one the label and the date describe. */
  readonly newest: KelpProduct;
  /** "Kelp canopy seen <season> <year> (<resolution>)", plus " — not updated since <date>" when stale. */
  readonly label: string;
  /** Last day of the newest view's season (YYYY-MM-DD): the date of the newest observation in the build. */
  readonly observedThrough: string;
  /** Whole quarters between the newest view's quarter and `now`'s quarter. */
  readonly quartersBehind: number;
  /** More than two quarters behind. A stale layer is never called current. */
  readonly stale: boolean;
  /** 'out of date' when stale. */
  readonly tag: 'out of date' | null;
  readonly defaultOn: boolean;
  /** Why the layer starts off; null when it starts on. */
  readonly offReason: string | null;
}
export type KelpResolution =
  | {readonly status: 'ready'; readonly layer: KelpLayer}
  | {readonly status: 'unavailable'; readonly reason: KelpRefusal; readonly note: string};

export const KELP_UNAVAILABLE_NOTE = 'Kelp canopy is unavailable.';
/** More than this many quarters behind: shown with its date, tagged out of date. */
export const KELP_STALE_QUARTERS = 2;
/** More than this many quarters behind: off by default (KELP-ACCESS §6). */
export const KELP_OFF_QUARTERS = 4;

const SHA256 = /^[a-f0-9]{64}$/;
const SEASON_OF_QUARTER = ['winter', 'spring', 'summer', 'fall'] as const;
const LAST_DAY = ['03-31', '06-30', '09-30', '12-31'] as const;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const refused = (reason: KelpRefusal): KelpResolution => ({status: 'unavailable', reason, note: KELP_UNAVAILABLE_NOTE});

function product(value: unknown): KelpProduct | undefined {
  if (!record(value)) return;
  const {sensor, season, year, quarter} = value;
  if (typeof year !== 'number' || !Number.isInteger(year) || year < 1984 || year > 2100) return;
  if (sensor === 'Planet 3 m') {
    if (season !== 'september' || (quarter !== undefined && quarter !== 3)) return;
    return {sensor, season, year, quarter: 3, resolution: '3 m'};
  }
  if (sensor !== 'Landsat 30 m') return;
  const index = SEASON_OF_QUARTER.findIndex(name => name === season);
  if (index < 0 || (quarter !== undefined && quarter !== index + 1)) return;
  return {sensor, season: SEASON_OF_QUARTER[index]!, year, quarter: (index + 1) as 1 | 2 | 3 | 4, resolution: '30 m'};
}

const quarterIndex = (year: number, quarter: number): number => year * 4 + quarter - 1;
const seasonWord = (season: KelpSeason): string => season === 'september' ? 'September' : season;

/**
 * Validate the parsed pointer and say what the layer may claim. Pure and total: anything that is
 * not a reviewed, public, identified pointer with at least one valid product is `unavailable`
 * with a reason (never an empty layer). `now` is the clock the staleness is measured against.
 */
export function resolveKelp(pointer: unknown, now: Date): KelpResolution {
  if (pointer == null) return refused('missing');
  if (!(now instanceof Date) || !Number.isFinite(now.getTime())) return refused('clock');
  if (!record(pointer)) return refused('schema');
  if (pointer.private !== false) return refused('private');
  if (pointer.status !== 'reviewed') return refused('unreviewed');
  if (pointer.schema !== KELP_POINTER_SCHEMA) return refused('schema');
  const {sha256, bytes, url} = pointer;
  if (typeof sha256 !== 'string' || !SHA256.test(sha256) || typeof bytes !== 'number' || !Number.isSafeInteger(bytes) || bytes <= 0 || typeof url !== 'string') return refused('identity');
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password) return refused('identity');
  } catch { return refused('identity'); }
  if (!Array.isArray(pointer.products) || !pointer.products.length) return refused('products');
  const products: KelpProduct[] = [];
  for (const row of pointer.products) {
    const p = product(row);
    if (!p) return refused('products');
    products.push(p);
  }
  const clock = quarterIndex(now.getUTCFullYear(), Math.floor(now.getUTCMonth() / 3) + 1);
  // Newest quarter wins; a Planet September wins a tie with a Landsat quarter.
  const newest = products.reduce((best, p) => {
    const a = quarterIndex(p.year, p.quarter), b = quarterIndex(best.year, best.quarter);
    return a > b || (a === b && p.sensor === 'Planet 3 m' && best.sensor !== 'Planet 3 m') ? p : best;
  });
  const quartersBehind = clock - quarterIndex(newest.year, newest.quarter);
  if (quartersBehind < 0) return refused('products'); // a view from the future is a bad pointer, not fresh data
  const stale = quartersBehind > KELP_STALE_QUARTERS;
  const observedThrough = `${newest.year}-${LAST_DAY[newest.quarter - 1]}`;
  const seen = `Kelp canopy seen ${seasonWord(newest.season)} ${newest.year} (${newest.resolution})`;
  let offReason: string | null = null;
  if (quartersBehind > KELP_OFF_QUARTERS) offReason = 'Off by default: the newest view is more than four quarters old.';
  else if (stale && newest.sensor === 'Planet 3 m') offReason = 'Off by default: the newest 3 m view is more than two quarters old.';
  return {status: 'ready', layer: Object.freeze({
    sha256, bytes, url, products: Object.freeze(products), newest, observedThrough, quartersBehind, stale,
    label: stale ? `${seen} — not updated since ${observedThrough}` : seen,
    tag: stale ? 'out of date' as const : null, defaultOn: offReason === null, offReason,
  })};
}

/**
 * Read the pointer through the caller's resolver, then `resolveKelp`. Never throws: an absent
 * pointer is `missing`, a resolver that fails is `unreadable`; both are unavailable, not empty.
 */
export async function loadKelp(resolver: () => Promise<unknown> | unknown, now: Date): Promise<KelpResolution> {
  let pointer: unknown;
  try { pointer = await resolver(); } catch { return refused('unreadable'); }
  return resolveKelp(pointer, now);
}

export interface KelpLayerSpec {
  readonly id: string; readonly type: 'fill' | 'line'; readonly source: string; readonly 'source-layer': string;
  readonly layout?: Record<string, unknown>; readonly paint: Record<string, unknown>;
}

/** Dots, then the outline. Colours come from the `--hab-kelp` role; both draw nothing without tiles. */
export function kelpLayers(p: Palette): KelpLayerSpec[] {
  const width: ExpressionSpecification = ['interpolate', ['linear'], ['zoom'], 13, 0.6, 16, 1.4];
  return [
    // The image itself is the theme's colour (`themePatterns`), so a switch replaces it in place.
    {id: KELP_DOTS, type: 'fill', source: KELP_SOURCE, 'source-layer': KELP_SOURCE_LAYER,
      paint: {'fill-pattern': KELP_DOTS_IMAGE, 'fill-opacity': 0.9, 'fill-antialias': false}},
    {id: KELP_OUTLINE, type: 'line', source: KELP_SOURCE, 'source-layer': KELP_SOURCE_LAYER, layout: {'line-join': 'round'},
      paint: {'line-color': p.habKelp, 'line-width': width, 'line-opacity': 0.9}},
  ];
}

/** MAP-REPLAN-3 structural contract: every paint edit a theme change needs, as plain data. */
export function themePaint(p: Palette): readonly {layer: string; property: string; value: unknown}[] {
  return [{layer: KELP_OUTLINE, property: 'line-color', value: p.habKelp}];
}

/** A seamless 10 CSS-px dot pattern in the theme's kelp colour; null when there is no canvas to draw it. */
export function kelpDots(p: Pick<Palette, 'habKelp'>): ImageData | null {
  const size = 10, scale = KELP_DOTS_PIXEL_RATIO;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size * scale;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.scale(scale, scale);
  ctx.fillStyle = p.habKelp;
  // Two offset dots per tile, so rows interleave; the edge dots wrap with their neighbours.
  for (const [x, y] of [[2.5, 2.5], [7.5, 7.5]] as const) {
    ctx.beginPath();
    ctx.arc(x, y, 1.1, 0, Math.PI * 2);
    ctx.fill();
  }
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

/** MAP-REPLAN-3 structural contract: pattern images, replaced in place on a theme change. */
export function themePatterns(p: Palette): readonly {id: string; image: ImageData; pixelRatio: number}[] {
  const image = kelpDots(p);
  return image ? [{id: KELP_DOTS_IMAGE, image, pixelRatio: KELP_DOTS_PIXEL_RATIO}] : [];
}
