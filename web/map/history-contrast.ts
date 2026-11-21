import type {ContrastSample} from './habitat-feed.ts';

export interface HistoryDayReady {
  readonly state: 'ready';
  readonly sampleAt: string;
  readonly fields: readonly string[];
  readonly resolution: readonly [number, number];
  readonly rows: readonly (readonly unknown[])[];
}

/** Convert a verified past analysis day without applying the current frame's freshness gate. */
export function historyContrast(day: HistoryDayReady): {gradients: false} | {gradients: true; samples: ContrastSample[]} {
  const t = day.fields.indexOf('temperature_c'), e = day.fields.indexOf('analysis_error_c');
  const g = day.fields.indexOf('temperature_gradient_c_per_km'), s = day.fields.indexOf('thermal_contrast_supported');
  if (t < 0 || e < 0 || g < 0 || s < 0) return {gradients: false};

  // Match regionalContrast: keep the tile's units and preserve rows with null readings.
  const value = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null;
  const samples = day.rows.map((r): ContrastSample => {
    const error = value(r[e]), flag = r[s];
    return {lat: r[0] as number, lon: r[1] as number, tempC: value(r[t]), errorC: error !== null && error >= 0 ? error : null, gradientCPerKm: value(r[g]),
      supported: flag === 1 || flag === true ? 1 : flag === 0 || flag === false ? 0 : null};
  });
  return {gradients: true, samples};
}
