import type {GpxWaypoint as Waypoint} from './gpx-waypoints.ts';

export const SCREEN_MAX_AGE_MS = 36 * 3_600_000;
export const SCREEN_MAX_AHEAD_MS = 5 * 60_000;

type Screen = {
  verdict: (place: {latitude: number; longitude: number}) => unknown;
  refused: (v: any) => boolean;
  checkedAt: number;
};
type Reason = 'inside' | 'near' | 'unchecked';
export type GpxScreen =
  | {ok: false; error: 'screen-unavailable' | 'screen-stale'}
  | {ok: true; clear: Waypoint[]; refused: {waypoint: Waypoint; reason: Reason}[]};

/** Apply the caller's protected-area verdict and refusal rule before offering any import candidates. */
export function screenGpxCandidates(waypoints: readonly Waypoint[], screen: Screen | null, now: number): GpxScreen {
  let verdict: Screen['verdict'], refused: Screen['refused'];
  try {
    if (!screen) return {ok: false, error: 'screen-unavailable'};
    ({verdict, refused} = screen);
    if (typeof verdict !== 'function' || typeof refused !== 'function') return {ok: false, error: 'screen-unavailable'};
  } catch {
    return {ok: false, error: 'screen-unavailable'};
  }

  try {
    const {checkedAt} = screen;
    if (!Number.isFinite(checkedAt) || !Number.isFinite(now) || now - checkedAt > SCREEN_MAX_AGE_MS || checkedAt - now > SCREEN_MAX_AHEAD_MS) {
      return {ok: false, error: 'screen-stale'};
    }
  } catch {
    return {ok: false, error: 'screen-stale'};
  }

  const result: GpxScreen = {ok: true, clear: [], refused: []};
  for (const waypoint of waypoints) {
    let reason: Reason = 'unchecked';
    try {
      const verdictValue = verdict.call(screen, {latitude: waypoint.lat, longitude: waypoint.lon});
      if (verdictValue !== null && typeof verdictValue === 'object') {
        if (!refused.call(screen, verdictValue)) {
          result.clear.push(waypoint);
          continue;
        }
        const v = verdictValue as {inside?: unknown; screened?: unknown};
        reason = v.inside === true ? 'inside' : v.screened === true ? 'near' : 'unchecked';
      }
    } catch {
      // A failed check affects only this waypoint, never the rest of the batch.
    }
    result.refused.push({waypoint, reason});
  }
  return result;
}
