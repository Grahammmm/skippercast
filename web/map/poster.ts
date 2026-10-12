// The Chart's poster (#617): before MapLibre has loaded and drawn its first
// complete frame, the region's coast outline (regions/<id>/poster.svg, the
// overview shoreline as one Web Mercator path; src/skippercast/platform/
// startup_forms.py) is drawn over the empty Chart, aligned to the opening
// camera, so the coast shows while the map engine loads. It goes on the
// Chart's first idle or the first move, whichever comes first.
//
// The file is parsed, never inserted: only its numbers and one path's
// move/line commands are read, and web/app/MapStage.tsx draws its own <svg>.
// An inline path is not a Largest Contentful Paint candidate, so the LCP
// budgets keep measuring the map. Erasable syntax only: tests import this
// file by type stripping.
import {signal} from '@preact/signals';
import {ZOOM_OFFSET} from './engine.ts';

/** The region's poster, relative to the app page. */
export const posterURL = (region: string): string => `regions/${encodeURIComponent(region)}/poster.svg`;

/** A parsed poster: its path, its size in pixels at `zoom`, and the region corner its origin sits on. */
export interface Poster {
  readonly region: string; readonly path: string; readonly width: number; readonly height: number;
  readonly zoom: number; readonly west: number; readonly north: number;
}

/** The poster shown now; null before it loads, after the Chart has drawn, or when it failed. */
export const poster = signal<Poster | null>(null);

const NUMBER = /^-?\d+(?:\.\d+)?$/;
const PATH = /^[Ml0-9 \-]+$/;
const attr = (svg: string, name: string): string | null => new RegExp(`\\s${name}="([^"]*)"`).exec(svg)?.[1] ?? null;

/** The poster in `text` for `region`, or null for anything but the build's own shape. */
export function parsePoster(text: string, region: string): Poster | null {
  const head = /^<svg\s[^>]*>/.exec(text)?.[0];
  const d = /<path d="([^"]*)"\s*\/>/.exec(text)?.[1];
  if (!head || !d || !PATH.test(d)) return null;
  const box = attr(head, 'viewBox')?.split(' ') ?? [];
  const values = [box[2], box[3], attr(head, 'data-zoom'), attr(head, 'data-west'), attr(head, 'data-north')];
  if (box.length !== 4 || !values.every(v => v !== undefined && v !== null && NUMBER.test(v))) return null;
  const [width, height, zoom, west, north] = values.map(Number) as [number, number, number, number, number];
  if (!(width > 0 && height > 0) || Math.abs(north) > 85 || Math.abs(west) > 180) return null;
  return {region, path: d, width, height, zoom, west, north};
}

/** Web Mercator world pixels at `zoom` for 512-pixel tiles (MapLibre's), as the build writes them. */
export function mercator(longitude: number, latitude: number, zoom: number): [number, number] {
  const size = 512 * 2 ** zoom, sin = Math.sin(latitude * Math.PI / 180);
  return [(longitude + 180) / 360 * size, (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size];
}

/** Where the poster's origin lands in a `width` × `height` host for a `?view=` camera, and its scale. */
export function posterPlacement(p: Poster, camera: {latitude: number; longitude: number; zoom: number}, width: number, height: number) {
  const scale = 2 ** (camera.zoom - ZOOM_OFFSET - p.zoom);
  const [cx, cy] = mercator(camera.longitude, camera.latitude, p.zoom), [ox, oy] = mercator(p.west, p.north, p.zoom);
  return {x: width / 2 + (ox - cx) * scale, y: height / 2 + (oy - cy) * scale, scale};
}

/** Load `region`'s poster unless the Chart has drawn already (`done`); a missing or malformed file shows nothing. */
export async function loadPoster(region: string, page: string, done: () => boolean, fetchFn: typeof fetch = (...a) => fetch(...a)): Promise<void> {
  try {
    const response = await fetchFn(new URL(posterURL(region), page).href);
    const parsed = response.ok ? parsePoster(await response.text(), region) : null;
    if (parsed && !done()) { poster.value = parsed; try { performance.mark('skippercast-poster'); } catch { /* no timing API */ } }
  } catch { /* the empty Chart stays until it draws */ }
}
