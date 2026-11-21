import type { ForecastPoint } from './types.ts';

type SelectedPoint = {
  pointId: string;
  lat: number;
  lon: number;
  via: 'trip-point' | 'region-default';
  basis: 'region';
};

type RegionalPoint = SelectedPoint | { missing: 'no forecast point' };

export function regionalPoint(
  region: { forecast_points: readonly ForecastPoint[] },
  tripPoint: string | null,
): RegionalPoint {
  try {
    const points = region && typeof region === 'object' ? region.forecast_points : undefined;
    if (!Array.isArray(points)) return { missing: 'no forecast point' };
    const length = points.length;
    if (!Number.isInteger(length) || length < 0 || length > 0xffffffff) {
      return { missing: 'no forecast point' };
    }

    let fallback: SelectedPoint | undefined;
    for (let index = 0; index < length; index++) {
      try {
        const point: ForecastPoint | undefined = points[index];
        if (!point || typeof point !== 'object') continue;
        const { id, latitude: lat, longitude: lon } = point;
        if (typeof id !== 'string' || !Number.isFinite(lat) || Math.abs(lat) > 90 ||
          !Number.isFinite(lon) || Math.abs(lon) > 180) continue;

        if (id === tripPoint) return { pointId: id, lat, lon, via: 'trip-point', basis: 'region' };
        fallback ??= { pointId: id, lat, lon, via: 'region-default', basis: 'region' };
        if (tripPoint === null) break;
      } catch {
        // An unreadable slot or point does not invalidate its neighbours.
      }
    }
    if (fallback) return fallback;
  } catch {
    // An unreadable region or point list has no usable forecast point.
  }
  return { missing: 'no forecast point' };
}

export const POSITION_ONLY_LAYERS = ['water_temp', 'contrast', 'chlorophyll', 'front_nm', 'current'] as const;

export function positionlessLayers(): Record<(typeof POSITION_ONLY_LAYERS)[number], { missing: 'no position' }> {
  return {
    water_temp: { missing: 'no position' },
    contrast: { missing: 'no position' },
    chlorophyll: { missing: 'no position' },
    front_nm: { missing: 'no position' },
    current: { missing: 'no position' },
  };
}
