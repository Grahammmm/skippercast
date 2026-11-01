// The region's reviewed launch points (#644, Kayak launch): the platform build's
// dist/regions/<id>/launch-points.json (src/skippercast/platform/launch_points.py,
// sourced from the state's Boating Facilities database), loaded once per region
// when Kayak needs it. The listed position is the facility's, good for choosing a
// launch and estimating a straight-line distance; never a navigation waypoint.
// A missing or unreadable list leaves the harbor as the only start.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {signal} from '@preact/signals';
import {launchChoice} from './reach.ts';
import {sharedFetch} from './shared-fetch.ts';
import type {Origin} from './ranking.ts';

export interface LaunchPoint {readonly id: string; readonly name: string; readonly kind: string; readonly latitude: number; readonly longitude: number}
/** The loaded list: for which region, and its points (empty when none or unreadable). */
export const launchPoints = signal<{readonly region: string; readonly points: readonly LaunchPoint[]} | null>(null);

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
/** The valid points of a parsed launch-points.json for `region`. */
export function parseLaunchPoints(json: unknown, region: string): LaunchPoint[] {
  const list = (json as {region_id?: unknown; launch_points?: unknown} | null);
  if (!list || list.region_id !== region || !Array.isArray(list.launch_points)) return [];
  return list.launch_points.flatMap((p: Record<string, unknown>) => p && typeof p.id === 'string' && typeof p.name === 'string' && finite(p.latitude) && finite(p.longitude)
    && Math.abs(p.latitude) <= 90 && Math.abs(p.longitude) <= 180 && (p.region === undefined || p.region === region)
    ? [{id: p.id, name: p.name, kind: typeof p.kind === 'string' ? p.kind : 'launch', latitude: p.latitude, longitude: p.longitude}] : []);
}

// One read per region, kept for revisits; only the region asked for last publishes, so a late answer for a
// region already left never replaces the current one.
const asked = new Map<string, Promise<LaunchPoint[]>>();
let latest: string | null = null;
/** Load `region`'s list once and publish it on every visit; a failure leaves it empty. */
export async function loadLaunchPoints(region: string, page: string = location.href, fetchFn: typeof fetch = sharedFetch): Promise<void> {
  latest = region;
  let read = asked.get(region);
  if (!read) {
    // A thrown fetch, 429 or 5xx is not remembered, so the next visit asks again; a 404 or invalid file is.
    let transient = false;
    const mine = read = (async (): Promise<LaunchPoint[]> => {
      let r: Response;
      try { r = await fetchFn(new URL(`regions/${encodeURIComponent(region)}/launch-points.json`, page).href); } catch { transient = true; return []; }
      transient = r.status === 429 || (r.status >= 500 && r.status <= 599);
      if (r.ok) try { return parseLaunchPoints(await r.json(), region); } catch { /* invalid: the harbor */ }
      return [];
    })();
    asked.set(region, mine);
    // Forget only this read: a newer one (after a reset) stays.
    void mine.then(() => { if (transient && asked.get(region) === mine) asked.delete(region); });
  }
  const points = await read;
  if (latest === region && (launchPoints.peek()?.region !== region || launchPoints.peek()?.points !== points)) launchPoints.value = {region, points};
}

/** The chosen launch for `region` as a distance origin, or null (none chosen, not loaded, or no longer listed). */
export function launchOrigin(region: string | null, list = launchPoints.value, choice = launchChoice.value): Origin | null {
  const id = region ? choice[region] : undefined, l = list && list.region === region ? list.points.find(p => p.id === id) : undefined;
  return l ? {latitude: l.latitude, longitude: l.longitude, name: l.name} : null;
}

/** Test seam: forget which regions were asked for. */
export const resetLaunchPoints = (): void => { asked.clear(); latest = null; launchPoints.value = null; };
