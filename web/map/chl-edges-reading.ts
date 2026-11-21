import {chlEdgesShown, type ChlEdgesDoc} from './chl-edges-feed.ts';

type ChlEdge = ChlEdgesDoc['edges'][number];
type Point = {lon: number; lat: number};
type HiddenReason = Extract<ReturnType<typeof chlEdgesShown>, {show: false}>['reason'];

export type ChlEdgeReading =
  | {kind: 'hidden'; reason: HiddenReason}
  | {kind: 'none'}
  | {kind: 'edge'; id: string; distanceKm: number; strengthLog10PerCell: number; factorPerCell: number;
     bandHalfWidthKm: number; observedAt: string; product: string; basis: 'observed'};

/** Find the nearest edge whose own band covers the tap, in feed order on ties. */
export function chlEdgeAt(doc: ChlEdgesDoc, at: Point): {edge: ChlEdge; distanceKm: number} | null {
  const {lon, lat} = at;
  if (!Number.isFinite(lon) || !Number.isFinite(lat) || Math.abs(lon) > 180 || Math.abs(lat) > 90) return null;

  // Same tap-centred local kilometre frame as frontsMark.
  const ky = 111.195, kx = ky * Math.cos(lat * Math.PI / 180);
  let hit: {edge: ChlEdge; distanceKm: number} | null = null;
  for (const edge of doc.edges) {
    let distanceKm = Infinity;
    // Walk segments without spreading an arbitrarily long feed line onto the call stack.
    for (let i = 1; i < edge.line.length; i++) {
      const [aLon, aLat] = edge.line[i - 1]!, [bLon, bLat] = edge.line[i]!;
      const ax = (aLon - lon) * kx, ay = (aLat - lat) * ky;
      const bx = (bLon - lon) * kx, by = (bLat - lat) * ky;
      const dx = bx - ax, dy = by - ay;
      const t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) || 1)));
      distanceKm = Math.min(distanceKm, Math.hypot(ax + t * dx, ay + t * dy));
    }
    if (distanceKm <= Math.max(1, edge.bandHalfWidthKm) && (!hit || distanceKm < hit.distanceKm)) {
      hit = {edge, distanceKm};
    }
  }
  return hit;
}

export function chlEdgeReading(doc: ChlEdgesDoc, at: Point, now: Date): ChlEdgeReading {
  const shown = chlEdgesShown(doc, now);
  if (!shown.show) return {kind: 'hidden', reason: shown.reason};
  const hit = chlEdgeAt(doc, at);
  if (!hit) return {kind: 'none'};
  const {edge, distanceKm} = hit;
  return {
    kind: 'edge', id: edge.id, distanceKm: Number(distanceKm.toFixed(1)),
    strengthLog10PerCell: edge.strength, factorPerCell: Number((10 ** edge.strength).toFixed(1)),
    bandHalfWidthKm: edge.bandHalfWidthKm, observedAt: edge.observedAt, product: doc.product, basis: 'observed',
  };
}
