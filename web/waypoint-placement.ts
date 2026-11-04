// One explicitly armed Chart click; no storage, account writes or geographic inference.
import {signal} from '@preact/signals';
import {screenPlace, type PlaceVerdict} from '../dist/geo-screen.js';

export const waypointPlacement = signal<string | null>(null);
export type Placed = {latitude: number; longitude: number; screen: PlaceVerdict};
/** The verdict of the last click this placement refused because it fell inside a closure; cleared by the next accepted click. */
export const placementRefused = signal<PlaceVerdict | null>(null);
let accept: ((at: Placed) => void) | null = null;
export function cancelWaypointPlacement(): void { waypointPlacement.value = null; accept = null; }
export function beginWaypointPlacement(region: string, pick: NonNullable<typeof accept>): void {
  accept = pick;
  waypointPlacement.value = region;
}
/** True only when this click completes an armed placement in the same region. */
export function placeWaypoint(region: string | null, at: {lat: number; lon: number} | null, screen: unknown = null): boolean {
  if (!waypointPlacement.peek()) return false;
  if (waypointPlacement.peek() !== region) { cancelWaypointPlacement(); return false; }
  if (!at || !Number.isFinite(at.lat) || Math.abs(at.lat) > 90 || !Number.isFinite(at.lon) || Math.abs(at.lon) > 180) return false;
  const verdict = screenPlace(screen, {latitude: at.lat, longitude: at.lon});
  // Inside a closure: refused, and placement stays armed so the next click can try elsewhere. Not checked is carried, not refused (a plan, not an export).
  if (verdict.inside) { placementRefused.value = verdict; return true; }
  placementRefused.value = null;
  const pick = accept;
  cancelWaypointPlacement();
  pick?.({latitude: at.lat, longitude: at.lon, screen: verdict});
  return true;
}
