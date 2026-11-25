import type {ChlorophyllObservation} from './habitat-feed.ts';

// The ready variant returned by loadHistoryDay.
export interface HistoryDayReady {
  readonly state: 'ready';
  readonly sampleAt: string;
  readonly fields: readonly string[];
  readonly resolution: readonly [number, number];
  readonly rows: readonly (readonly unknown[])[];
}

const numeric = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** Convert a verified past frame without applying Today's freshness gate. */
export function historyChlorophyll(day: HistoryDayReady,
  source: {product: string; maxAgeMs: number; stride: number}): ChlorophyllObservation | null {
  const index = day.fields.indexOf('chlorophyll_mg_m3');
  if (index === -1 || source.stride !== 1) return null;

  const cells = day.rows.flatMap(r => {
    const value = r[index], lat = r[0] as number, lon = r[1] as number;
    return numeric(value) && value >= 0.001 && value <= 100 && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
      ? [{lat, lon, value}] : [];
  });
  return cells.length ? {product: source.product, sampleAt: day.sampleAt, maxAgeMs: source.maxAgeMs,
    resolution: day.resolution, cells} : null;
}
