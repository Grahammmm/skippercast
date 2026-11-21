import type {GpxWaypoint as Waypoint} from './gpx-waypoints.ts';

export type {Waypoint};
export type ImportPlan = {save: Waypoint[]; duplicates: Waypoint[]; invalid: Waypoint[]};
export type SaveReport = {saved: number; failed: {index: number; name: string; error: string}[]};

type Position = {lat: number; lon: number};
const positionKey = ({lat, lon}: Position): string => `${lat.toFixed(5)},${lon.toFixed(5)}`;

export function planGpxImport(existing: readonly Position[], candidates: readonly Waypoint[]): ImportPlan {
  const plan: ImportPlan = {save: [], duplicates: [], invalid: []};
  const seen = new Set(existing.map(positionKey));
  for (const waypoint of candidates) {
    const {lat, lon} = waypoint;
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      plan.invalid.push(waypoint);
      continue;
    }
    const key = positionKey(waypoint);
    if (seen.has(key)) {
      plan.duplicates.push(waypoint);
    } else {
      seen.add(key);
      plan.save.push(waypoint);
    }
  }
  return plan;
}

function errorText(reason: unknown): string {
  try {
    if (reason instanceof Error && typeof reason.message === 'string') return reason.message;
    return String(reason);
  } catch {
    // A rejection value can itself throw when inspected or converted to text.
    return 'Unknown error';
  }
}

export async function saveSequentially(
  items: readonly Waypoint[],
  save: (w: Waypoint) => Promise<unknown>,
  onProgress?: (done: number, total: number) => void,
): Promise<SaveReport> {
  const report: SaveReport = {saved: 0, failed: []};
  for (const [index, waypoint] of items.entries()) {
    try {
      await save(waypoint);
      report.saved++;
    } catch (reason) {
      report.failed.push({index, name: waypoint.name, error: errorText(reason)});
    }
    try {
      onProgress?.(index + 1, items.length);
    } catch {
      // Progress is observational; its failure does not affect saves or the report.
    }
  }
  return report;
}
