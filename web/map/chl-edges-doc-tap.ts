import {readChlEdges} from './chl-edges-feed.ts';
import {chlEdgeReading, type ChlEdgeReading} from './chl-edges-reading.ts';

export function chlEdgesDocTap(
  data: unknown, regionId: string, at: {lon: number; lat: number}, now: Date,
): ChlEdgeReading | {kind: 'invalid'} {
  const doc = readChlEdges(data, regionId);
  if (doc === null) return {kind: 'invalid'};
  try {
    return chlEdgeReading(doc, at, now);
  } catch {
    // A caller-supplied point or clock can throw even after the document is valid.
    return {kind: 'invalid'};
  }
}
