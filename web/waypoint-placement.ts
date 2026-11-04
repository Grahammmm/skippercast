// One explicitly armed Chart click; no storage, account writes or geographic inference.
import {signal} from '@preact/signals';
import {placeRefused, screenPlace, type PlaceVerdict} from '../dist/geo-screen.js';

export const waypointPlacement = signal<string | null>(null);
export type Placed = {latitude: number; longitude: number; screen: PlaceVerdict};
/** The verdict of the last click this placement refused (not checked, inside a closure, or within the planning margin of one); cleared on begin, cancel and a completed placement. */
export const placementRefused = signal<PlaceVerdict | null>(null);
let accept: ((at: Placed) => void) | null = null;
export function cancelWaypointPlacement(): void { waypointPlacement.value = null; placementRefused.value = null; accept = null; }
export function beginWaypointPlacement(region: string, pick: NonNullable<typeof accept>): void {
  accept = pick;
  placementRefused.value = null;
  waypointPlacement.value = region;
}
/** BF-closures-everywhere: the plain-text line a refused verdict adds (rendered as a text child, so a closure's name is never markup); null when it is not refused. */
export function verdictLine(v: PlaceVerdict): string | null {
  if (!placeRefused(v)) return null;
  if (!v.screened) return 'Protected areas not checked';
  if (v.inside) return `Inside ${v.name ?? 'a protected area'}`;
  return `${Math.round(v.distanceM ?? 0)} m from ${v.name ?? 'a protected area'}`;
}
/**
 * True when this click was consumed by an armed placement in the same region. `screen` is the Chart's current-region protected-area screen
 * (null when it is not loaded, stale or another region's). A click that is not checked, inside a closure or within the planning margin of
 * one is refused: placement stays armed and the callback is not called. Any other click completes the placement once.
 */
export function placeWaypoint(region: string | null, at: {lat: number; lon: number} | null, screen: unknown = null): boolean {
  if (!waypointPlacement.peek()) return false;
  if (waypointPlacement.peek() !== region) { cancelWaypointPlacement(); return false; }
  if (!at || !Number.isFinite(at.lat) || Math.abs(at.lat) > 90 || !Number.isFinite(at.lon) || Math.abs(at.lon) > 180) return false;
  const verdict = screenPlace(screen, {latitude: at.lat, longitude: at.lon});
  if (placeRefused(verdict)) { placementRefused.value = verdict; return true; }
  const pick = accept;
  cancelWaypointPlacement();
  pick?.({latitude: at.lat, longitude: at.lon, screen: verdict});
  return true;
}
