// One explicitly armed Chart click; no storage, account writes or geographic inference.
import {signal} from '@preact/signals';

export const waypointPlacement = signal<string | null>(null);
let accept: ((at: {latitude: number; longitude: number}) => void) | null = null;
export function cancelWaypointPlacement(): void { waypointPlacement.value = null; accept = null; }
export function beginWaypointPlacement(region: string, pick: NonNullable<typeof accept>): void {
  accept = pick;
  waypointPlacement.value = region;
}
/** True only when this click completes an armed placement in the same region. */
export function placeWaypoint(region: string | null, at: {lat: number; lon: number} | null): boolean {
  if (!waypointPlacement.peek()) return false;
  if (waypointPlacement.peek() !== region) { cancelWaypointPlacement(); return false; }
  if (!at || !Number.isFinite(at.lat) || Math.abs(at.lat) > 90 || !Number.isFinite(at.lon) || Math.abs(at.lon) > 180) return false;
  const pick = accept;
  cancelWaypointPlacement();
  pick?.({latitude: at.lat, longitude: at.lon});
  return true;
}
