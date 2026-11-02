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
// - Gridded model forecasts (FE-17's wave grid): the currents' forecast gate,
//   applied to the hours the model lists (forecastTime).
//
// Erasable syntax only: tests/test_frames.mjs imports this file by type stripping.
import {cloudSource, selectCurrentFrame} from '../../packages/coast/src/map-sources.ts';
import type {CloudImage, CurrentCell, CurrentField, CurrentFrame} from '../../packages/coast/src/ocean-types.ts';
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

// A listed hour of a model grid stands for the whole grid; which points have a sample is the reader's to
// judge. One placeholder cell per frame, since selectCurrentFrame never picks an empty one.
const LISTED = [{}] as unknown as CurrentCell[];
/**
 * The listed hour (epoch ms) of a gridded model forecast for `at`, through selectCurrentFrame's forecast
 * gate: a run issued at most 36 hours ago and retrieved at most 6 hours ago (each at most 5 minutes
 * ahead), and the listed time nearest `at` within 90 minutes, inside the listed span; else null.
 * `times`, `issuedAt` and `fetchedAt` are epoch ms.
 */
export function forecastTime(times: readonly number[], issuedAt: number, fetchedAt: number, at: Date, now: Date): number | null {
  if (!Number.isFinite(issuedAt) || !Number.isFinite(fetchedAt) || !times.every(Number.isFinite)) return null;
  const iso = (ms: number): string => new Date(ms).toISOString();
  const frames = [...times].sort((a, b) => a - b).map(t => ({validAt: iso(t), cells: LISTED}));
  const frame = selectCurrentFrame({kind: 'forecast', issuedAt: iso(issuedAt), fetchedAt: iso(fetchedAt), frames} as unknown as CurrentField, at, now);
  return frame ? Date.parse(frame.validAt) : null;
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

// A frame's bytes never change (it is pinned to one acquisition time), so its tiles load through this
// MapLibre protocol (SC2222-08): the handler returns only the bytes, MapLibre records no expiry and never
// refetches a frame when nowCOAST's short max-age lapses. Still fetch (connect-src), never img-src.
export const FRAME_PROTOCOL = 'nowcoast-frame';
const NOWCOAST = 'https://nowcoast.noaa.gov/', SCHEME = `${FRAME_PROTOCOL}://`;
/** A nowCOAST tile URL on FRAME_PROTOCOL, byte-identical after the scheme; any other origin unchanged. */
export const pinnedTileUrl = (url: string): string => url.startsWith(NOWCOAST) ? SCHEME + url.slice('https://'.length) : url;
const hostOf = (url: string): string => { try { return new URL(url).host; } catch { return ''; } };
/** The FRAME_PROTOCOL handler: only host nowcoast.noaa.gov, no credentials; a non-2xx rejects with its status. */
export function frameProtocol(fetchFn: typeof fetch = (...a) => fetch(...a)) {
  return async (params: {url: string}, abort: AbortController): Promise<{data: ArrayBuffer}> => {
    const url = `https://${params.url.slice(SCHEME.length)}`;
    if (!params.url.startsWith(SCHEME) || hostOf(url) !== 'nowcoast.noaa.gov') throw new Error('frame host');
    abort.signal.throwIfAborted();
    const response = await fetchFn(url, {signal: abort.signal, credentials: 'omit'});
    if (!response.ok) throw new Error(String(response.status));
    return {data: await response.arrayBuffer()};
  };
}
