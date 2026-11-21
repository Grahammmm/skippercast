import type {Eddy} from './eddies-feed.ts';

type Point = {lon: number; lat: number};

export type EddyReading = {
  kind: 'eddy';
  sense: Eddy['sense'];
  diameterKm: number;
  frameTime: string;
  runHourUtc: number | null;
  leadHours: number | null;
  basis: 'model';
} | {kind: 'none'};

function contains(outline: Eddy['outline'], lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = outline.length - 1; i < outline.length; j = i++) {
    const [x0, y0] = outline[j]!;
    const [x1, y1] = outline[i]!;
    const cross = (x1 - x0) * (lat - y0) - (y1 - y0) * (lon - x0);
    if (cross === 0 && lon >= Math.min(x0, x1) && lon <= Math.max(x0, x1)
      && lat >= Math.min(y0, y1) && lat <= Math.max(y0, y1)) return true;

    // Straddling with a strict comparison counts a shared vertex only once
    // per crossing and excludes horizontal edges. The cross sign tests
    // whether the intersection lies to the right without dividing by dy.
    if ((y0 > lat) !== (y1 > lat) && (y1 > y0 ? cross > 0 : cross < 0)) inside = !inside;
  }
  return inside;
}

export function eddyAt(eddies: readonly Eddy[], at: Point): Eddy | null {
  const {lon, lat} = at;
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;

  let best: Eddy | null = null;
  for (const eddy of eddies) {
    if ((!best || eddy.diameterKm < best.diameterKm) && contains(eddy.outline, lon, lat)) best = eddy;
  }
  return best;
}

export function eddyReading(
  tile: {frameTime: string; eddies: readonly Eddy[]}, issuedAt: string, at: Point,
): EddyReading {
  try {
    const eddy = eddyAt(tile.eddies, at);
    if (!eddy) return {kind: 'none'};

    const {frameTime} = tile;
    const issuedMs = Date.parse(issuedAt);
    const hasRun = Number.isFinite(issuedMs);
    return {
      kind: 'eddy',
      sense: eddy.sense,
      diameterKm: Math.round(eddy.diameterKm),
      frameTime,
      runHourUtc: hasRun ? new Date(issuedMs).getUTCHours() : null,
      leadHours: hasRun ? Math.round((Date.parse(frameTime) - issuedMs) / 3_600_000) : null,
      basis: 'model',
    };
  } catch {
    // A non-JSON caller can still supply a throwing getter at the read boundary.
    return {kind: 'none'};
  }
}
