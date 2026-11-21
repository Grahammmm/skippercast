import type {SSTPoint, SurfaceTemperature} from '../../packages/coast/src/spatial-types.ts';

/** The ready result of loadHistoryDay, after tile and coordinate verification. */
interface HistoryDayReady {
  readonly state: 'ready';
  readonly sampleAt: string;
  readonly fields: readonly string[];
  readonly resolution: readonly [number, number];
  readonly rows: readonly (readonly unknown[])[];
}

const numeric = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** Convert the selected observation without applying Today's age gate. */
export function historySurfaceTemperature(
  day: HistoryDayReady,
  {sourceId, fetchedAt, url, stride}: {sourceId: string; fetchedAt: string; url: string; stride: number},
): SurfaceTemperature | null {
  const t = day.fields.indexOf('temperature_c'), e = day.fields.indexOf('analysis_error_c');
  if (t < 0 || e < 0) return null;
  const [lat, lon] = day.resolution;
  if (lat !== lon) return null; // The surface field takes a single spacing.
  if (!Number.isFinite(stride) || stride < 1) return null;

  const points: SSTPoint[] = [];
  for (const r of day.rows) {
    const temp = r[t], error = r[e];
    if (numeric(temp) && numeric(error) && error >= 0)
      points.push({lon: r[1] as number, lat: r[0] as number, tempF: temp * 1.8 + 32, errorF: error * 1.8});
  }
  if (!points.length) return null;
  return {sourceId, analysedAt: day.sampleAt, fetchedAt, nativeResolutionDeg: lat,
    sampleSpacingDeg: lat * stride, points, url, kind: 'analysis'};
}
