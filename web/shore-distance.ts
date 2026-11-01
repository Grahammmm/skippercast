// Distance from shore for Spear from shore (#644, slice 5 part 2): the
// straight-line distance from a reef's point to the nearest mapped shoreline,
// in yards, read from the region's overview shoreline (dist/regions/<id>/
// shoreline-overview.geojson, the NOAA CUSP lines the Chart draws when zoomed
// out). The overview is simplified, so the distance is approximate and says so;
// it is not a swim route and says nothing about entry, surf or currents.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {signal} from '@preact/signals';
import {chartFileListed} from './chart-files.ts';
import {sharedFetch} from './shared-fetch.ts';

/** The loaded lines ([lon, lat] each) for a region; null before or without them. */
export const shoreLines = signal<{readonly region: string; readonly lines: readonly (readonly number[])[][] | null} | null>(null);

/** The LineString and MultiLineString coordinates of a GeoJSON FeatureCollection. */
export function linesOf(json: unknown): number[][][] {
  const features = (json as {features?: unknown} | null)?.features;
  if (!Array.isArray(features)) return [];
  return features.flatMap((f: {geometry?: {type?: string; coordinates?: unknown}}) => {
    const g = f?.geometry;
    if (g?.type === 'LineString' && Array.isArray(g.coordinates)) return [g.coordinates as number[][]];
    if (g?.type === 'MultiLineString' && Array.isArray(g.coordinates)) return g.coordinates as number[][][];
    return [];
  }).filter(l => l.length > 1 && l.every(p => Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1])));
}

const YD_PER_DEG_LAT = 111_320 / 0.9144;

/** Yards from `p` to the nearest segment of `lines`, on a local flat projection around `p`; null without lines. */
export function yardsFromShore(p: {latitude: number; longitude: number}, lines: readonly (readonly number[])[][]): number | null {
  const kx = YD_PER_DEG_LAT * Math.cos(p.latitude * Math.PI / 180), ky = YD_PER_DEG_LAT;
  let best = Infinity;
  for (const line of lines) {
    for (let i = 1; i < line.length; i++) {
      const ax = (line[i - 1]![0]! - p.longitude) * kx, ay = (line[i - 1]![1]! - p.latitude) * ky;
      const bx = (line[i]![0]! - p.longitude) * kx, by = (line[i]![1]! - p.latitude) * ky;
      const dx = bx - ax, dy = by - ay, len = dx * dx + dy * dy;
      const t = len ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len)) : 0;
      const d = Math.hypot(ax + t * dx, ay + t * dy);
      if (d < best) best = d;
    }
  }
  return Number.isFinite(best) ? best : null;
}

type Lines = readonly (readonly number[])[][] | null;
// One read per region, kept for revisits; only the region asked for last publishes, so a late answer for a
// region already left never replaces the current one.
const asked = new Map<string, Promise<Lines>>();
let latest: string | null = null;
/** Load `region`'s overview shoreline once and publish it on every visit; a failure leaves `lines` null, so no distance is claimed. */
export async function loadShoreLines(region: string, page: string = location.href, fetchFn: typeof fetch = sharedFetch): Promise<void> {
  latest = region;
  // A region whose region.json omits the overview gets no request and no distance (RF0935-1); no memo, so a later list can load it.
  if (!chartFileListed(region, 'shoreline-overview.geojson')) {
    if (shoreLines.peek()?.region !== region || shoreLines.peek()?.lines !== null) shoreLines.value = {region, lines: null};
    return;
  }
  let read = asked.get(region);
  if (!read) {
    // A thrown fetch, 429 or 5xx is not remembered, so the next visit asks again; a 404 or invalid file is.
    let transient = false;
    const mine = read = (async (): Promise<Lines> => {
      let r: Response;
      try { r = await fetchFn(new URL(`regions/${encodeURIComponent(region)}/shoreline-overview.geojson`, page).href); } catch { transient = true; return null; }
      transient = r.status === 429 || (r.status >= 500 && r.status <= 599);
      if (r.ok) try { const l = linesOf(await r.json()); return l.length ? l : null; } catch { /* invalid: none */ }
      return null;
    })();
    asked.set(region, mine);
    // Forget only this read: a newer one (after a reset) stays.
    void mine.then(() => { if (transient && asked.get(region) === mine) asked.delete(region); });
  }
  const lines = await read;
  if (latest === region && (shoreLines.peek()?.region !== region || shoreLines.peek()?.lines !== lines)) shoreLines.value = {region, lines};
}
export const resetShoreLines = (): void => { asked.clear(); latest = null; shoreLines.value = null; };
