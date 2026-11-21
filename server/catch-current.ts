import type {CurrentFrame} from '../packages/coast/src/ocean-types.ts';
import {cellIndex, sampleAt} from '../web/map/habitat-sample.ts';

export type CatchCurrent =
  | {kn: number; toward_deg: number; run: string; valid_at: string}
  | {missing: 'no frame' | 'no position' | 'bad grid' | 'outside coverage' | 'gap'};

/** Read the surface current for a catch entry from an already chosen frame. */
export function catchCurrent(input: {
  issuedAt: string | null;
  frame: CurrentFrame | null;
  resolution: readonly [number, number];
  lat: number | null;
  lon: number | null;
}): CatchCurrent {
  const {issuedAt, frame, resolution, lat, lon} = input;
  if (frame === null || issuedAt === null || !Number.isFinite(Date.parse(issuedAt))) return {missing: 'no frame'};
  if (lat === null || lon === null || !Number.isFinite(lat) || !Number.isFinite(lon)) return {missing: 'no position'};

  try {
    const rows = frame.cells.map((cell, i) => [cell.lat, cell.lon, i]);
    const sample = sampleAt(cellIndex(rows, resolution, ['latitude', 'longitude', 'row']), lat, lon);
    if (sample.value === null) {
      return {missing: 'reason' in sample && sample.reason === 'outside' ? 'outside coverage' : 'gap'};
    }
    // The sampled value is an index from the same cells array, not a current component.
    const cell = frame.cells[sample.value]!;
    const toward = Math.round(cell.towardDeg);
    return {
      kn: Math.round(cell.speedKnots * 10) / 10,
      toward_deg: toward === 360 ? 0 : toward,
      run: issuedAt,
      valid_at: frame.validAt,
    };
  } catch {
    return {missing: 'bad grid'};
  }
}
