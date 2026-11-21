import type {ChartMark} from './coastline.ts';

export interface ReadingSource {
  readonly layer: string;
  readonly reading?: (at: {lon: number; lat: number}) => ChartMark | null;
  readonly reason?: () => string | null;
}

export interface FieldReading {
  readonly layer: string;
  readonly mark: ChartMark | null;
  readonly reason?: string;
}

export function readingsAt(sources: readonly ReadingSource[], at: {lon: number; lat: number}): FieldReading[] {
  const readings: FieldReading[] = [];
  const included = new Set<string>();
  const finitePoint = Number.isFinite(at.lon) && Number.isFinite(at.lat);

  for (const source of sources) {
    const {layer} = source;
    if (typeof source.reading !== 'function' || included.has(layer)) continue;
    included.add(layer);

    let mark: ChartMark | null = null;
    if (finitePoint) {
      try {
        const value = source.reading(at);
        if (value !== null && typeof value === 'object') mark = value;
      } catch {
        // One unavailable reading must not hide the other layers.
      }
    }

    let reason: string | null | undefined;
    if (mark === null) {
      try {
        reason = source.reason?.();
      } catch {
        // The source has no usable status to show.
      }
    }
    readings.push(typeof reason === 'string' && reason.length > 0 ? {layer, mark, reason} : {layer, mark});
  }
  return readings;
}

export function firstMark(readings: readonly FieldReading[]): ChartMark | null {
  return readings.find(({mark}) => mark !== null)?.mark ?? null;
}
