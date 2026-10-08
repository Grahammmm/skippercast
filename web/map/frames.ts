// Frame selection for the dock's hour (FE-12, design § 9): a thin wrapper over
// packages/coast's gates, never a copy. A layer asks here which native frame,
// if any, it may draw for the selected hour; a null answer leaves it blank and
// the rail shows "no fresh frame" with the last valid time.
//
// - Forecast currents (WCOFS): the native frame nearest the hour within 90
//   minutes, from a cycle issued at most 36 hours ago (selectCurrentFrame).
// - Observed currents (HF radar): the latest frame at or before the hour, at
//   most 6 hours old, never for a future hour (selectCurrentFrame).
// - Clouds (GOES): listed acquisition times only, each inside cloudSource's
//   90-minute age gate, on today's local day only. conditions/goes-times.json
//   (FE-44) lists about two hours of frames, so the window is applied here,
//   frame by frame; a future or past day shows no cloud loop.
//
// Erasable syntax only: tests/test_frames.mjs imports this file by type stripping.
import {cloudSource, selectCurrentFrame} from '../../packages/coast/src/map-sources.ts';
import type {CloudImage, CurrentField, CurrentFrame} from '../../packages/coast/src/ocean-types.ts';
import {isCurrentLayer, selectedCurrent} from '../../packages/coast/src/state/current-layer.ts';
import {localParts} from '../hour.ts';

export type {CloudImage, CurrentField, CurrentFrame};

/** The native current frame for `at`, or null outside its gate (packages/coast `selectCurrentFrame`). */
export const currentFrame = (field: CurrentField, at: Date, now: Date): CurrentFrame | null => selectCurrentFrame(field, at, now);

/**
 * The frame of exactly the chosen source (`?current=`) for `at`: `off`, an unlisted choice, a
 * missing or duplicated product all give null, and no other source stands in (`selectedCurrent`).
 */
export function chosenCurrent(fields: unknown, choice: string, at: Date, now: Date): {field: CurrentField; frame: CurrentFrame; expiresAt: number} | null {
  return isCurrentLayer(choice) ? selectedCurrent(fields, choice, at, now) : null;
}

const time = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));

/** A GOES time index as goes-times.json publishes it, or null when its shape is not a CloudImage. */
export function cloudImage(value: unknown): CloudImage | null {
  if (value === null || typeof value !== 'object') return null;
  const v = value as Partial<Record<keyof CloudImage, unknown>>;
  const times = Array.isArray(v.availableTimes) ? v.availableTimes : [];
  if (v.id !== 'goes-longwave' || v.kind !== 'observation' || v.layer !== 'goes_longwave_imagery' || !time(v.observedAt) || !time(v.fetchedAt)
    || !times.length || !times.every(time) || !times.includes(v.observedAt) || typeof v.attribution !== 'string') return null;
  return value as CloudImage;
}

/**
 * The acquisition times a cloud loop may show for the dock's `selected` hour at `now`, oldest
 * first: none unless `selected` falls on today's local day in `tz`, and only times that pass
 * cloudSource's own gate (at most 90 minutes old, at most 5 minutes ahead, listed).
 */
export function cloudFrames(cloud: CloudImage | null, selected: Date, now: Date, tz: string): string[] {
  if (!cloud || localParts(selected, tz).day !== localParts(now, tz).day) return [];
  return [...new Set(cloud.availableTimes)].filter(at => cloudTiles(cloud, at, now) !== null).sort((a, b) => Date.parse(a) - Date.parse(b));
}

/** The WMS raster source pinned to acquisition time `at`, or null outside the gate (packages/coast `cloudSource`). */
export const cloudTiles = (cloud: CloudImage, at: string, now: Date): ReturnType<typeof cloudSource> => cloudSource({...cloud, observedAt: at}, now);
