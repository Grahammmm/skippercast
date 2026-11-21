import {chlorophyllFresh, type ChlorophyllObservation} from './habitat-feed.ts';
import {cellIndex, sampleAt, type HabitatCellIndex} from './habitat-sample.ts';

export type ChlorophyllReading =
  | {kind: 'value'; valueMgM3: number; sampleAt: string; ageMs: number; product: string; cell: {lat: number; lon: number}}
  | {kind: 'none'; reason: 'gap' | 'outside' | 'stale' | 'bad-grid'};

/** Build the native-cell index once for this observation. */
export function chlorophyllReader(o: ChlorophyllObservation): (at: {lat: number; lon: number}, now: Date) => ChlorophyllReading {
  let index: HabitatCellIndex;
  try {
    index = cellIndex(o.cells.map(({lat, lon, value}) => [lat, lon, value]), o.resolution,
      ['latitude', 'longitude', 'chlorophyll_mg_m3']);
  } catch {
    return () => ({kind: 'none', reason: 'bad-grid'});
  }

  return (at, now) => {
    if (!chlorophyllFresh(o, now)) return {kind: 'none', reason: 'stale'};
    const reading = sampleAt(index, at.lat, at.lon);
    if ('reason' in reading) return {kind: 'none', reason: reading.reason};
    if (reading.value === null) return {kind: 'none', reason: 'gap'};
    return {
      kind: 'value', valueMgM3: reading.value, sampleAt: o.sampleAt,
      ageMs: now.getTime() - Date.parse(o.sampleAt), product: o.product, cell: {...reading.cell},
    };
  };
}
