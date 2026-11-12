// SC-GPSOFFLINE-1: "where am I against the protected areas", from one position read the angler asks for.
// No DOM and no network here: the browser's Geolocation API is read once per tap (never watched, so there is no track), the answer is
// worked out on this device from the boundary data the planner's own screen already holds (dist/protected-areas.js, the same data the
// offline legal pack saves), and every verdict comes from geo-screen.js `screenPlace`, the screen the planner uses. Nothing is stored or sent.
// Erasable syntax only: Node tests import this file by type stripping.
import {PLANNING_MARGIN_M, distanceM, pointGeometry, screenPlace} from '../dist/geo-screen.js';

/** A fix this page can use: a finite WGS84 position and the accuracy radius the device reported (null when it reported none). */
export type Fix = {latitude: number; longitude: number; accuracyM: number | null};
export type Located = {ok: true; fix: Fix} | {ok: false; reason: 'unsupported' | 'denied' | 'unavailable'};
/** One fresh, high-accuracy read per tap; the page asks again only when the angler taps again. */
export const POSITION_OPTIONS: PositionOptions = {enableHighAccuracy: true, timeout: 20000, maximumAge: 0};
/** Accuracy worse than this (or not reported) is called out: the planning margin is 70 m, so a fix this loose cannot place a boat against a boundary. */
export const LOW_ACCURACY_M = 100;

/** The device position, once. Resolves (never rejects) with why there is none: no API, permission denied, or no fix (no signal, timeout, bad data). */
export function readPosition(geolocation: Pick<Geolocation, 'getCurrentPosition'> | null | undefined = globalThis.navigator?.geolocation): Promise<Located> {
  if (!geolocation) return Promise.resolve({ok: false, reason: 'unsupported'});
  return new Promise(resolve => {
    try {
      geolocation.getCurrentPosition(position => {
        const {latitude, longitude, accuracy} = position?.coords ?? {} as Partial<GeolocationCoordinates>;
        if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude!) > 90 || Math.abs(longitude!) > 180) { resolve({ok: false, reason: 'unavailable'}); return; }
        resolve({ok: true, fix: {latitude: latitude!, longitude: longitude!, accuracyM: Number.isFinite(accuracy) && accuracy! >= 0 ? accuracy! : null}});
      }, error => resolve({ok: false, reason: error?.code === 1 ? 'denied' : 'unavailable'}), POSITION_OPTIONS);
    } catch { resolve({ok: false, reason: 'unavailable'}); }
  });
}

/** What the planner's protected-area screen (dist/protected-areas.js) exposes to this check. */
export type HeldScreen = {
  heldBoundaries?(): {current: boolean; missing?: readonly string[]; clock?: Clock; checked_at: string | null; features: readonly {properties?: {NAME?: string; FULLNAME?: string}; geometry: unknown}[]} | null;
  coversGeometry?(geometry: unknown): boolean;
};
/** How the held boundaries' check times read now: within the 36-hour window, past it, dated in the future, or no readable date. */
export type Clock = 'ok' | 'old' | 'future' | 'unknown';

export type Reading =
  /** No boundary data on this device (nothing saved and no connection, or the screen could not load). Never "clear". */
  | {kind: 'no-boundaries'}
  /** The position lies outside the area the boundary file was asked for: not checked, never "clear". */
  | {kind: 'not-covered'; fix: Fix}
  /** Some configured boundary layer is not on this device, and nothing held puts the position inside or near a closure: "outside" and "nearest closure" would be claims about data we lack. */
  | {kind: 'incomplete'; fix: Fix; missing: readonly string[]; clock: Clock; checkedAt: string | null}
  | {kind: 'checked'; fix: Fix; where: 'inside' | 'near' | 'outside'; name: string | null; distanceM: number | null;
    lowAccuracy: boolean; /** Not current: a layer is missing, or the check times are old, in the future or unreadable. */ stale: boolean;
    /** Configured layers not on this device (so a closer or further closure may exist); empty when the data is whole. */ missing: readonly string[];
    clock: Clock; checkedAt: string | null};

/** geo-screen's search bound (its FAR_M, not exported): a closure whose box is further than this from the place is not measured there. */
const SEARCH_BOUND_M = 20000;
/** The nearest held closure to the fix with no search bound: the minimum finite distance (the first of equal ones), its name and metres to a tenth. */
function nearestHeld(fix: Fix, features: readonly {properties?: {NAME?: string; FULLNAME?: string}; geometry: unknown}[]): {name: string | null; distanceM: number} | null {
  const point = pointGeometry(fix.longitude, fix.latitude);
  let best: {name: string | null; d: number} | null = null;
  for (const f of features) {
    const d = distanceM(point, f.geometry);
    if (d !== null && Number.isFinite(d) && (!best || d < best.d)) best = {name: f.properties?.FULLNAME || f.properties?.NAME || null, d};
  }
  return best && {name: best.name, distanceM: Math.round(best.d * 10) / 10};
}

/**
 * inside: the point touches or lies in a closure. near: it is within the planning margin (geo-screen PLANNING_MARGIN_M) of one, counting the
 * reported accuracy as extra margin so a fix that could be across the line is never called outside. outside: otherwise.
 * `distanceM` is geo-screen's metres to the nearest closure (null when none is within its 20 km search).
 * With a layer missing, inside and near still stand (a closure we hold is a closure), but outside is refused (`incomplete`).
 */
export function readingFor(fix: Fix, screen: HeldScreen | null | undefined): Reading {
  const held = screen?.heldBoundaries?.();
  if (!screen || !held || !held.features.length) return {kind: 'no-boundaries'};
  const verdict = screenPlace({
    status: 'ready',
    boundaries: held.features.map(f => ({name: f.properties?.FULLNAME || f.properties?.NAME || null, geometry: f.geometry})),
    coversGeometry: (g: unknown) => screen.coversGeometry?.(g) === true,
  }, {latitude: fix.latitude, longitude: fix.longitude});
  if (!verdict.screened) return {kind: 'not-covered', fix};
  const reach = PLANNING_MARGIN_M + (fix.accuracyM ?? 0);
  // A reach that touches geo-screen's 20 km search bound would be cut short by it (a closer closure can sit past the bound, or beside a farther
  // one it did measure), so the nearest closure is measured again over every held feature, with the same helper, rounding and name fallback.
  const near = reach >= SEARCH_BOUND_M ? nearestHeld(fix, held.features) : null;
  const inside = verdict.inside || near?.distanceM === 0, name = near ? near.name : verdict.name, metres = near ? near.distanceM : verdict.distanceM;
  const where = inside ? 'inside' : metres !== null && metres <= reach ? 'near' : 'outside';
  const missing = held.missing ?? [], clock = held.clock ?? (held.current ? 'ok' : 'old');
  if (missing.length && where === 'outside') return {kind: 'incomplete', fix, missing, clock, checkedAt: held.checked_at};
  return {kind: 'checked', fix, where, name, distanceM: metres, lowAccuracy: fix.accuracyM === null || fix.accuracyM > LOW_ACCURACY_M,
    stale: !held.current, missing, clock, checkedAt: held.checked_at};
}

export type PositionResult = {located: {ok: false; reason: 'unsupported' | 'denied' | 'unavailable'}} | {located: {ok: true; fix: Fix}; reading: Reading};

/**
 * The whole opt-in check: ask for one position and start the boundary screen at the same time (a slow connection must not delay the fix),
 * then screen the position. `loadScreen` is the planner's own (web/trip.ts `loadProtectedScreen`); it may fail, which is `no-boundaries`.
 * The fix lives only in the returned value; nothing here writes it anywhere or sends it.
 */
export async function checkPosition(loadScreen: () => Promise<HeldScreen | null>, geolocation?: Pick<Geolocation, 'getCurrentPosition'> | null): Promise<PositionResult> {
  // Both start now; the loader's rejection is caught at once so a failure while the permission prompt is open is never unhandled.
  const reading = readPosition(geolocation), screen = loadScreen().catch(() => null);
  const located = await reading;
  // A failed read is already the answer: boundaries cannot change it, so they are not waited for (the loader finishes on its own).
  if (!located.ok) return {located};
  return {located, reading: readingFor(located.fix, await screen)};
}

/** Whether the legal pack saved this region's boundaries on this device: 'unknown' when the saved packs could not be listed. */
export type PackState = 'saved' | 'partial' | 'none' | 'unknown';
export function packState(packs: readonly {meta: {region_id: string; legal?: {complete: boolean; items: readonly {id: string; saved: boolean}[]}}}[] | null, regionId: string | null): PackState {
  if (!packs || !regionId) return 'unknown';
  const legal = packs.find(p => p.meta.region_id === regionId)?.meta.legal;
  if (!legal?.items.some(i => i.id === 'areas' && i.saved)) return 'none';
  return legal.complete ? 'saved' : 'partial';
}
