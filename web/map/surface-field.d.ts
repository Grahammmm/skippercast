// Types of web/map/surface-field.js (FE-15, FE-16): packages/coast/src/map/surface-field.ts's
// own signatures, restated so the web program never loads that source.
export type FieldPoint = {lon: number; lat: number; values: number[]};
export type FieldQuad = {west: number; south: number; east: number; north: number; corners: FieldPoint[]};
export type SurfaceField = {
  bounds: [number, number, number, number]; step: [number, number]; dimensions: number; quads: FieldQuad[];
  /** Bilinear inside a complete quad of source cells; null in a gap or outside the grid. */
  sample: (lon: number, lat: number) => number[] | null;
};
export type ContourFeature = {type: 'Feature'; properties: {level: number; label: string}; geometry: {type: 'LineString'; coordinates: number[][]}};
/** Display interpolation inside complete, adjacent source cells only; null when the grid is irregular or too coarse. */
export declare function surfaceField(points: FieldPoint[], opts?: {step?: [number, number]; maxStep?: [number, number]}): SurfaceField | null;
/** Speed in knots and the bearing the water moves toward, in degrees true, from eastward and northward m/s. */
export declare function vectorReading(values: number[]): {speedKnots: number; towardDeg: number};
/** RGB of `value` on `palette` (hex colours) between `low` and `high`, clamped at the ends. */
export declare function fieldColor(value: number, low: number, high: number, palette: string[]): [number, number, number];
/** The whole degrees around the values: floor of the minimum, ceiling of the maximum (at least one degree apart). */
export declare function temperatureRange(values: number[]): [number, number];
/** Two-point segments of each level through complete quads only (marching triangles with a centre fan). */
export declare function fieldContours(field: SurfaceField, levels: number[]): {type: 'FeatureCollection'; features: ContourFeature[]};
