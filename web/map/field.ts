// Field textures (FE-16, docs/plans/front-end/design.md § 9): a packages/coast
// surface field (web/map/surface-field.js) painted as RGBA pixels for a MapLibre
// image source, so the GPU draws it under the chart's other layers. Water temp
// uses it now; Swell's height field (FE-17) next.
//
// - Support only: a pixel takes a colour only where `field.sample` answers, that
//   is inside a complete quad of source cells. Gaps and everything past the grid
//   stay transparent, and the edge of every gap is feathered inward, never out
//   (fish's fieldImage), so no colour is written where there is no data.
// - Web Mercator rows: each row's latitude is the inverse Mercator of its centre,
//   so the pixels lie linearly between the four corners, as MapLibre draws them.
// - CPU-light: about CELL_PIXELS pixels per source cell on the long side (at
//   most MAX_TEXTURE, at least MIN_TEXTURE; the GPU smooths the rest). Each of
//   the field's complete quads paints the pixels whose centres it holds,
//   bilinearly from its four corner samples: what `field.sample` answers there
//   (tests/test_field_texture.mjs compares every pixel), without a lookup per
//   pixel. Colours come from a table built once with packages/coast
//   `fieldColor`; the feather is a two-pass chamfer distance. Morro Bay's
//   analysis (1,971 samples at 0.02°) paints 456 × 441 pixels in about 15 ms
//   (Node, warm), once per analysis.
//
// Isolines of a field (Water temp's contours, Swell's period lines) join
// packages/coast `fieldContours`' two-point segments into lines per level.
//
// Erasable syntax only: tests/test_field_texture.mjs imports it by type stripping.
import {fieldColor, fieldContours, type FieldPoint, type SurfaceField} from './surface-field.js';

export const MAX_TEXTURE = 1024;
export const MIN_TEXTURE = 64;
export const CELL_PIXELS = 8;
/** Entries in the colour table: 1/255 of the legend's range apart. */
export const TABLE_SIZE = 256;

/** An image source's corners: top left, top right, bottom right, bottom left, as [lon, lat]. */
export type Corners = [[number, number], [number, number], [number, number], [number, number]];
export interface FieldTexture {
  readonly width: number;
  readonly height: number;
  /** Straight (not premultiplied) RGBA, row by row from the north edge. */
  readonly data: Uint8ClampedArray<ArrayBuffer>;
  readonly coordinates: Corners;
}

const mercator = (lat: number): number => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
const latitude = (y: number): number => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180 / Math.PI;

/** `size` RGB triples evenly from the cold to the warm end of `ramp`, each packages/coast `fieldColor`. */
export function colourTable(ramp: readonly string[], size = TABLE_SIZE): Uint8Array {
  const table = new Uint8Array(size * 3);
  for (let i = 0; i < size; i++) table.set(fieldColor(i / (size - 1), 0, 1, [...ramp]), i * 3);
  return table;
}

/** Pixels across and down: square in Web Mercator, about CELL_PIXELS per cell on the long side. */
export function textureSize(field: Pick<SurfaceField, 'bounds' | 'step'>): {width: number; height: number} {
  const [west, south, east, north] = field.bounds, [dx, dy] = field.step;
  const aspect = (east - west) * Math.PI / 180 / (mercator(north) - mercator(south)), wide = aspect >= 1;
  const side = Math.min(MAX_TEXTURE, Math.max(MIN_TEXTURE, Math.round((wide ? (east - west) / dx : (north - south) / dy) * CELL_PIXELS)));
  const other = Math.min(MAX_TEXTURE, Math.max(1, Math.round(wide ? side / aspect : side * aspect)));
  return wide ? {width: side, height: other} : {width: other, height: side};
}

/** Scales each pixel's alpha by its distance to the nearest gap or edge, up to `radius` pixels. */
function feather(data: Uint8ClampedArray, width: number, height: number, radius: number): void {
  const d = new Float32Array(width * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const i = y * width + x;
    d[i] = data[i * 4 + 3] ? Math.min(radius, x + 1, y + 1, width - x, height - y) : 0;
    if (x) d[i] = Math.min(d[i]!, d[i - 1]! + 1);
    if (y) d[i] = Math.min(d[i]!, d[i - width]! + 1);
  }
  for (let y = height - 1; y >= 0; y--) for (let x = width - 1; x >= 0; x--) {
    const i = y * width + x;
    if (x < width - 1) d[i] = Math.min(d[i]!, d[i + 1]! + 1);
    if (y < height - 1) d[i] = Math.min(d[i]!, d[i + width]! + 1);
    data[i * 4 + 3] = Math.round(data[i * 4 + 3]! * Math.min(1, d[i]! / radius));
  }
}

/**
 * `field` coloured on `ramp` (hex colours, cold to warm) between `range`'s ends by `value` of each
 * interpolated sample (clamped at the ends), transparent wherever the field has no support.
 */
export function fieldTexture(field: SurfaceField, range: readonly [number, number], ramp: readonly string[], value: (v: number[]) => number): FieldTexture {
  const {width, height} = textureSize(field), [west, south, east, north] = field.bounds, [low, high] = range;
  const top = mercator(north), bottom = mercator(south), span = Math.max(high - low, 1e-9), table = colourTable(ramp);
  const data = new Uint8ClampedArray(width * height * 4), v = new Array<number>(field.dimensions).fill(0);
  const column = (lon: number): number => (lon - west) / (east - west) * width - 0.5;
  const row = (lat: number): number => (top - mercator(lat)) / (top - bottom) * height - 0.5;
  const lats = Array.from({length: height}, (_, y) => latitude(top - (y + 0.5) / height * (top - bottom)));
  for (const q of field.quads) {
    const [sw, se, ne, nw] = q.corners as [FieldPoint, FieldPoint, FieldPoint, FieldPoint];
    const x1 = Math.min(width - 1, Math.floor(column(q.east))), y1 = Math.min(height - 1, Math.floor(row(q.south)));
    for (let y = Math.max(0, Math.ceil(row(q.north))); y <= y1; y++) {
      const ty = (lats[y]! - q.south) / (q.north - q.south);
      for (let x = Math.max(0, Math.ceil(column(q.west))); x <= x1; x++) {
        const tx = (west + (x + 0.5) / width * (east - west) - q.west) / (q.east - q.west);
        const a = (1 - tx) * (1 - ty), b = tx * (1 - ty), c = tx * ty, d = (1 - tx) * ty;
        for (let k = 0; k < v.length; k++) v[k] = sw.values[k]! * a + se.values[k]! * b + ne.values[k]! * c + nw.values[k]! * d;
        const t = Math.round(Math.max(0, Math.min(1, (value(v) - low) / span)) * (TABLE_SIZE - 1)) * 3, i = (y * width + x) * 4;
        data[i] = table[t]!; data[i + 1] = table[t + 1]!; data[i + 2] = table[t + 2]!; data[i + 3] = 255;
      }
    }
  }
  // Fish's radius: about a quarter of a cell, never under 2 px.
  feather(data, width, height, Math.max(2, Math.min(width * field.step[0] / (east - west), height * field.step[1] / (north - south)) * 0.23));
  return {width, height, data, coordinates: [[west, north], [east, north], [east, south], [west, south]]};
}

export type Isoline = {type: 'Feature'; properties: {level: number; label: string; major: boolean}; geometry: {type: 'LineString'; coordinates: number[][]}};
const end = (p: number[]): string => `${Math.round(p[0]! * 1e7)},${Math.round(p[1]! * 1e7)}`;
/**
 * packages/coast `fieldContours` of the field's first value at `levels` (complete quads only), its two-point
 * segments joined into lines per level so a label fits along them; each line takes `properties(level)`.
 */
export function isolines(field: SurfaceField, levels: readonly number[], properties: (level: number) => {label: string; major: boolean}): {type: 'FeatureCollection'; features: Isoline[]} {
  const byLevel = new Map<number, number[][][]>();
  for (const f of fieldContours(field, [...levels]).features) {
    const list = byLevel.get(f.properties.level) ?? [];
    list.push(f.geometry.coordinates);
    byLevel.set(f.properties.level, list);
  }
  const features: Isoline[] = [];
  for (const [level, segments] of byLevel) {
    const ends = new Map<string, number[]>(), used = new Uint8Array(segments.length);
    segments.forEach((s, i) => { for (const p of s) ends.set(end(p), [...ends.get(end(p)) ?? [], i]); });
    const other = (s: number[][], at: number[]): number[] => end(s[0]!) === end(at) ? s[1]! : s[0]!;
    const grow = (line: number[][]): void => {
      for (let j = ends.get(end(line.at(-1)!))?.find(i => !used[i]); j !== undefined; j = ends.get(end(line.at(-1)!))?.find(i => !used[i])) {
        used[j] = 1;
        line.push(other(segments[j]!, line.at(-1)!));
      }
    };
    segments.forEach((s, i) => {
      if (used[i]) return;
      used[i] = 1;
      const ahead = [...s], behind = [s[0]!];
      grow(ahead); grow(behind);
      features.push({type: 'Feature', properties: {level, ...properties(level)}, geometry: {type: 'LineString', coordinates: [...behind.slice(1).reverse(), ...ahead]}});
    });
  }
  return {type: 'FeatureCollection', features};
}
