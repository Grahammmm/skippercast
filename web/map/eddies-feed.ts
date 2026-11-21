// Content validation for a decoded wcofs-eddies tile. Transport and hash checks belong to the loader.
export const MAX_EDDIES = 200;
export const MAX_OUTLINE_POINTS = 2000;

export type Eddy = {
  outline: [number, number][];
  sense: 'cw' | 'ccw';
  diameterKm: number;
  owMin: number;
};

export type EddiesParse =
  | {ok: true; frameTime: string; eddies: Eddy[]}
  | {ok: false; error: string};

const FRAME_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z$/;
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export function parseEddiesTile(raw: unknown): EddiesParse {
  let path = 'tile';
  const reject = (): EddiesParse => ({ok: false, error: path});
  try {
    if (!record(raw)) return reject();
    const proto = Object.getPrototypeOf(raw);
    if (proto !== Object.prototype && proto !== null) return reject();

    path = 'frame_time';
    const frameTime = raw.frame_time;
    if (typeof frameTime !== 'string' || !FRAME_TIME.test(frameTime) || !finite(Date.parse(frameTime))) return reject();

    path = 'features';
    const features = raw.features;
    if (!Array.isArray(features)) return reject();
    const featureCount = features.length;
    if (!Number.isInteger(featureCount) || featureCount < 0 || featureCount > MAX_EDDIES) return reject();

    const eddies: Eddy[] = [];
    for (let i = 0; i < featureCount; i++) {
      const featurePath = `features[${i}]`;
      path = featurePath;
      const feature: unknown = features[i];
      if (!record(feature)) return reject();

      const outlinePath = `${featurePath}.outline`;
      path = outlinePath;
      const points = feature.outline;
      if (!Array.isArray(points)) return reject();
      const pointCount = points.length;
      if (!Number.isInteger(pointCount) || pointCount < 4 || pointCount > MAX_OUTLINE_POINTS) return reject();
      const outline: Eddy['outline'] = [];
      // Indexed reads also validate holes, which array iteration methods like every can skip.
      for (let j = 0; j < pointCount; j++) {
        path = `${outlinePath}[${j}]`;
        const point: unknown = points[j];
        if (!Array.isArray(point) || point.length !== 2) return reject();
        const lon: unknown = point[0], lat: unknown = point[1];
        if (!finite(lon) || lon < -180 || lon > 180 || !finite(lat) || lat < -90 || lat > 90) return reject();
        outline.push([lon, lat]);
      }
      path = outlinePath;
      const first = outline[0]!, last = outline[pointCount - 1]!;
      if (first[0] !== last[0] || first[1] !== last[1]) return reject();

      path = `${featurePath}.sense`;
      const sense = feature.sense;
      if (sense !== 'cw' && sense !== 'ccw') return reject();
      path = `${featurePath}.diameter_km`;
      const diameterKm = feature.diameter_km;
      if (!finite(diameterKm) || diameterKm <= 0) return reject();
      path = `${featurePath}.ow_min`;
      const owMin = feature.ow_min;
      if (!finite(owMin) || owMin >= 0) return reject();
      eddies.push({outline, sense, diameterKm, owMin});
    }
    return {ok: true, frameTime, eddies};
  } catch {
    // Non-JSON callers can supply throwing accessors or proxies. Keep the failing path.
    return reject();
  }
}
