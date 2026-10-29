// The range to consider (#644, walkthrough slice 5; owner decision C, 2026-10-12):
// how far out, one way and in nautical miles, a Boat or Kayak user wants the
// app to look. Kept on this device only (localStorage, STORAGE_KEYS.reach),
// per profile, with no default: until the user types one, nothing is filtered
// and no ring draws. Nothing is derived from a boat model, fuel or horsepower.
//
// The range is a straight-line radius from the region's harbor (web/ranking.ts
// `harborOrigin`), the same distance the run time uses (web/brief/run.ts), so
// the real route is at least this long. The ring (web/map/reach.ts) and the
// "Where to look" filter (web/ranking.ts) read it; the trip planner starts its
// distance filter from the Boat range (web/trip.ts).
//
// Erasable syntax only: Node tests import this file by type stripping.
import {signal} from '@preact/signals';
import {ownSpearDepthFt, PROFILE_TABLE, type Profile} from './profile.ts';
import {readStored, STORAGE_KEYS, writeStored} from './state.ts';

export type ReachProfile = 'boat' | 'kayak';
export const REACH_PROFILES: readonly ReachProfile[] = ['boat', 'kayak'];
export const isReachProfile = (p: unknown): p is ReachProfile => p === 'boat' || p === 'kayak';

/** The range each profile may take (nm, one way); outside it, nothing is saved. */
export const REACH_BOUNDS: Readonly<Record<ReachProfile, {readonly min: number; readonly max: number; readonly step: number}>> = Object.freeze({
  boat: Object.freeze({min: 1, max: 60, step: 0.5}),
  kayak: Object.freeze({min: 0.5, max: 10, step: 0.5}),
});

export type SavedReach = Partial<Record<ReachProfile, number>>;
/** The ranges the user typed on this device; a profile missing here has none. */
export const reachRange = signal<SavedReach>({});

/** A range inside the profile's bounds rounded to its step, else null. A blank or unreadable value is null, never a default. */
export function parseReach(p: ReachProfile, value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN;
  const b = REACH_BOUNDS[p];
  if (!Number.isFinite(n) || n < b.min || n > b.max) return null;
  return Math.round(n / b.step) * b.step;
}

/** Parse stored JSON: each listed profile's range, anything else dropped. */
export function parseStoredReach(raw: string | null): SavedReach {
  let json: unknown;
  try { json = JSON.parse(raw ?? 'null'); } catch { return {}; }
  if (!json || typeof json !== 'object' || Array.isArray(json)) return {};
  const out: SavedReach = {};
  for (const p of REACH_PROFILES) {
    const nm = parseReach(p, (json as Record<string, unknown>)[p]);
    if (nm !== null) out[p] = nm;
  }
  return out;
}

/** Load the stored ranges into the signal. */
export function loadReach(): SavedReach {
  reachRange.value = parseStoredReach(readStored(STORAGE_KEYS.reach));
  return reachRange.peek();
}

/** Save a range for `p`; a blank or out-of-range value clears it. Returns what was saved. */
export function saveReach(p: ReachProfile, value: unknown): number | null {
  const nm = parseReach(p, value);
  const next: SavedReach = {...reachRange.peek()};
  if (nm === null) delete next[p]; else next[p] = nm;
  reachRange.value = next;
  writeStored(STORAGE_KEYS.reach, JSON.stringify(next));
  return nm;
}

/** The range `p` uses, or null: none saved, or a profile without one (Shore, Spear). */
export function reachFor(p: Profile, saved: SavedReach = reachRange.value): number | null {
  return isReachProfile(p) ? saved[p] ?? null : null;
}

/** Earth radius in nautical miles, as dist/spot-ranking.js `distanceNm` measures. */
const EARTH_NM = 3440.065;
const rad = (d: number) => d * Math.PI / 180, deg = (r: number) => r * 180 / Math.PI;

/**
 * The closed ring `nm` from `origin` on the sphere `distanceNm` uses, as [lon, lat] pairs: every point
 * is the same great-circle distance from the origin, so a place `distanceNm` puts inside the range
 * sits inside the ring.
 */
export function reachRing(origin: {latitude: number; longitude: number}, nm: number, steps = 128): number[][] {
  const d = nm / EARTH_NM, lat1 = rad(origin.latitude), lon1 = rad(origin.longitude);
  const ring: number[][] = [];
  for (let i = 0; i < steps; i++) {
    const brg = 2 * Math.PI * i / steps;
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brg));
    const lon2 = lon1 + Math.atan2(Math.sin(brg) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));
    ring.push([Number(deg(lon2).toFixed(6)), Number(deg(lat2).toFixed(6))]);
  }
  ring.push(ring[0]!);
  return ring;
}

/** "12 nm", "2.5 nm". */
export const nmText = (nm: number): string => `${Number(nm.toFixed(1))} nm`;

// Spear (#644, slice 5 part 2): the diver's own deepest dive, where they dive
// from, and how far from shore they will swim when diving from shore. Kept
// on this device; nothing set means the table's 60 ft and no shore filter.

/** The deepest dive a diver may set (ft); 60 ft is the table's default. */
export const SPEAR_DEPTH_BOUNDS = Object.freeze({min: 10, max: 100, step: 5});
/** The farthest swim from shore a diver may set (yards). */
export const SHORE_SWIM_BOUNDS = Object.freeze({min: 25, max: 2000, step: 25});
/** The table's Spear limit, which a saved depth equal to it clears. */
const PROFILE_SPEAR_DEFAULT = PROFILE_TABLE.spear.maxDepthFt;
export type DiveFrom = 'shore' | 'boat';
export interface SpearPlan {readonly from: DiveFrom | null; readonly shoreYd: number | null}
/** Where the diver dives from and the swim limit; the depth lives in profile.ts `ownSpearDepthFt`. */
export const spearPlan = signal<SpearPlan>({from: null, shoreYd: null});

const inBounds = (value: unknown, b: {min: number; max: number; step: number}): number | null => {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN;
  return Number.isFinite(n) && n >= b.min && n <= b.max ? Math.round(n / b.step) * b.step : null;
};
export const parseSpearDepth = (value: unknown): number | null => inBounds(value, SPEAR_DEPTH_BOUNDS);
export const parseShoreSwim = (value: unknown): number | null => inBounds(value, SHORE_SWIM_BOUNDS);
const parseFrom = (value: unknown): DiveFrom | null => value === 'shore' || value === 'boat' ? value : null;

/** Parse stored JSON into the depth (null: the table's) and the plan; anything unreadable is dropped. */
export function parseStoredSpear(raw: string | null): {depthFt: number | null; plan: SpearPlan} {
  let json: Record<string, unknown> = {};
  try { const v: unknown = JSON.parse(raw ?? 'null'); if (v && typeof v === 'object' && !Array.isArray(v)) json = v as Record<string, unknown>; } catch { /* unreadable */ }
  const depth = parseSpearDepth(json.depthFt);
  return {depthFt: depth === PROFILE_SPEAR_DEFAULT ? null : depth, plan: {from: parseFrom(json.from), shoreYd: parseShoreSwim(json.shoreYd)}};
}

/** Load the stored Spear inputs into the signals. */
export function loadSpear(): void {
  const {depthFt, plan} = parseStoredSpear(readStored(STORAGE_KEYS.spear));
  ownSpearDepthFt.value = depthFt;
  spearPlan.value = plan;
}

/** Save the Spear inputs: a depth equal to the default or out of range clears it; a blank swim clears it. Returns what was saved. */
export function saveSpear(input: {depthFt?: unknown; from?: unknown; shoreYd?: unknown}): {depthFt: number | null; plan: SpearPlan} {
  const depth = parseSpearDepth(input.depthFt);
  const depthFt = depth === PROFILE_SPEAR_DEFAULT ? null : depth;
  const plan: SpearPlan = {from: parseFrom(input.from), shoreYd: parseShoreSwim(input.shoreYd)};
  ownSpearDepthFt.value = depthFt;
  spearPlan.value = plan;
  writeStored(STORAGE_KEYS.spear, JSON.stringify({depthFt, ...plan}));
  return {depthFt, plan};
}

/** The swim limit that applies now: only when diving from shore with a limit set. */
export const shoreSwimLimit = (plan: SpearPlan = spearPlan.value): number | null => plan.from === 'shore' ? plan.shoreYd : null;

// Kayak (#644, slice 5 part 2): the launch the paddle starts from, one of the
// region's reviewed launch points (dist/regions/<id>/launch-points.json, web/launches.ts),
// per region, kept on this device. None chosen: the region's harbor.

/** The chosen launch id per region. */
export const launchChoice = signal<Readonly<Record<string, string>>>({});

export function parseStoredLaunch(raw: string | null): Record<string, string> {
  let json: unknown;
  try { json = JSON.parse(raw ?? 'null'); } catch { return {}; }
  if (!json || typeof json !== 'object' || Array.isArray(json)) return {};
  const ok = /^[a-z0-9-]{1,80}$/;
  return Object.fromEntries(Object.entries(json as Record<string, unknown>).filter((e): e is [string, string] => ok.test(e[0]) && typeof e[1] === 'string' && ok.test(e[1])));
}
export function loadLaunch(): void { launchChoice.value = parseStoredLaunch(readStored(STORAGE_KEYS.launch)); }
/** Save `id` as `region`'s launch; an empty id goes back to the harbor. */
export function saveLaunch(region: string, id: string): void {
  const next = {...launchChoice.peek()};
  if (id && /^[a-z0-9-]{1,80}$/.test(id)) next[region] = id; else delete next[region];
  launchChoice.value = next;
  writeStored(STORAGE_KEYS.launch, JSON.stringify(next));
}
