// Clouds (FE-22, docs/plans/front-end/design.md § 9): a loop of observed GOES
// longwave infrared frames on the Chart. Each frame is a nowCOAST WMS image
// pinned to an acquisition time a published list names (packages/coast
// cloudSource through web/map/frames.ts); no time is ever made from the clock,
// and nothing is projected forward.
// - Times: FE-44's index (/feeds/conditions/goes-times.json), or the bound
//   report's ocean packet (FE-74 coastOcean, /api/coast/ocean) where one binds
//   and lists newer times. Both list nowCOAST's own time dimension.
// - Gate (frames.ts cloudFrames): each listed time at most 90 minutes old, and
//   only while the dock's hour falls on today's local day; another day shows
//   no loop. The loop shows the newest MAX_FRAMES of them.
// - Labels: the frame on screen carries its acquisition time and age (the
//   legend's Clouds row, web/app/Legend.tsx, with the loop toggle); the rail's
//   Clouds entry names the newest frame, or why none draws. Brightness is
//   infrared temperature: never a cloud-cover percentage, never visibility.
// - The loop stops while the page is hidden, the Chart is not shown or the
//   viewer holds it, and never plays under prefers-reduced-motion (the newest
//   frame stays).
//
// Erasable syntax only: tests/test_clouds_layer.mjs imports this file by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {coastOcean} from '../coast-data.ts';
import {dockTime, localParts} from '../hour.ts';
import {appView, day, hour, layers} from '../state.ts';
import {unavailable} from './chart.ts';
import {COASTLINE_GLOW} from './coastline.ts';
import {setRailNote} from './layers.ts';
import type {Engine, Overlay} from './engine.ts';
import {cloudFrames, cloudImage, cloudTiles, type CloudImage} from './frames.ts';
import {shownPresentation} from './stage.ts';

/** FE-44's index of GOES acquisition times, under the page's /feeds/ route. */
export const CLOUD_INDEX = 'feeds/conditions/goes-times.json';
/** The loop's length: the newest frames inside the gate (an hour at nowCOAST's five-minute cadence). */
export const MAX_FRAMES = 12;
export const FRAME_MS = 600;
/** The newest frame stays longer, so each pass ends on the latest observation. */
export const HOLD_MS = 2400;
/** The index changes each live cycle; it is read again this often while Clouds is on. */
export const INDEX_REFRESH_MS = 10 * 60_000;
/** Part-transparent and monochrome, so the chart reads through the sky (§ 9). */
export const CLOUD_OPACITY = 0.7;
export const NO_FRAMES = 'no frames for this area';
export const OTHER_DAY = 'observed frames show today only';
const MINUTE = 60_000;
const REGISTRY_ID = 'clouds' as const;

const formats = new Map<string, Intl.DateTimeFormat>();
/** "3:03 pm" in `tz`. */
export function clockText(at: string, tz: string): string {
  let f = formats.get(tz);
  if (!f) formats.set(tz, f = new Intl.DateTimeFormat('en-US', {timeZone: tz, hour: 'numeric', minute: '2-digit', hour12: true}));
  const p = Object.fromEntries(f.formatToParts(new Date(at)).map(part => [part.type, part.value]));
  return `${p.hour}:${p.minute} ${(p.dayPeriod ?? '').toLowerCase()}`;
}

/** A frame's label: when it was observed and how long ago, at `now`. */
export function frameLabel(at: string, now: Date, tz: string): string {
  const minutes = Math.round((now.getTime() - Date.parse(at)) / MINUTE);
  return `observed ${clockText(at, tz)} · ${minutes < 1 ? 'under 1 min' : `${minutes} min`} ago`;
}

/** The rail's note: the newest frame drawn, or why none draws. */
export function cloudStatus(cloud: CloudImage | null, frames: readonly string[], selected: Date, now: Date, tz: string): string {
  if (!cloud) return NO_FRAMES;
  if (localParts(selected, tz).day !== localParts(now, tz).day) return OTHER_DAY;
  const newest = frames.at(-1);
  if (newest) return frameLabel(newest, now, tz);
  const last = localParts(new Date(cloud.observedAt), tz).day;
  return `no fresh frame · last ${last === localParts(now, tz).day ? '' : `${last} `}${clockText(cloud.observedAt, tz)}`;
}

/** The newer of two time lists (by their newest acquisition time); `a` on a tie. */
const newer = (a: CloudImage | null, b: CloudImage | null): CloudImage | null =>
  !a ? b : !b ? a : Date.parse(b.observedAt) > Date.parse(a.observedAt) ? b : a;

/** FE-44's index, or null when it is missing or not a CloudImage. */
export async function cloudIndex(fetchFn: typeof fetch, page: string): Promise<CloudImage | null> {
  try {
    const response = await fetchFn(new URL(CLOUD_INDEX, page).href, {signal: AbortSignal.timeout(15000)});
    return response.ok ? cloudImage(await response.json()) : null;
  } catch { return null; }
}

/** One frame's source and layer id. */
export const frameId = (at: string): string => `clouds:${at}`;

/** One raster source and layer per listed frame inside the gate at `now`, all transparent until shown. */
export function cloudOverlay(cloud: CloudImage, frames: readonly string[], now: Date): Overlay {
  const sources: Record<string, MapLibre.SourceSpecification> = {};
  const drawn: MapLibre.LayerSpecification[] = [];
  for (const at of frames) {
    const source = cloudTiles(cloud, at, now);
    if (!source) continue;
    sources[frameId(at)] = source;
    drawn.push({id: frameId(at), type: 'raster', source: frameId(at), paint: {
      'raster-opacity': 0, 'raster-opacity-transition': {duration: 0}, 'raster-fade-duration': 0, 'raster-saturation': -1, 'raster-contrast': 0.2,
    }});
  }
  return {sources, layers: drawn};
}

/** The legend's label for the frame on screen, while the Chart shows it. */
export interface CloudStamp {readonly at: string; readonly label: string; readonly canLoop: boolean}
export const cloudStamp = signal<CloudStamp | null>(null);
/** The viewer's hold on the loop (the legend's toggle). */
export const cloudHeld = signal(false);

export interface CloudsOptions {
  engine: ReadonlySignal<Engine | null>;
  /** The region's zone, for the dock's day; a signal read here is followed. */
  zone: () => string;
  fetchFn?: typeof fetch;
  page?: () => string;
  now?: () => Date;
  doc?: Pick<Document, 'hidden' | 'addEventListener' | 'removeEventListener'>;
  motion?: Pick<MediaQueryList, 'matches' | 'addEventListener' | 'removeEventListener'> | null;
  /** The bound report's ocean packet cloud record; a signal read here is followed. */
  reported?: () => unknown;
}

export function createClouds(options: CloudsOptions): {destroy(): void} {
  const {engine, zone, fetchFn = (...a) => fetch(...a), page = () => location.href, now = () => new Date(), doc = document,
    motion = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null,
    reported = () => coastOcean.value?.data.cloud ?? null} = options;
  const index = signal<CloudImage | null>(null), read = signal(false), clock = signal(now());
  const hidden = signal(!!doc.hidden), reduced = signal(!!motion?.matches), step = signal(MAX_FRAMES);
  let alive = true, asked = -Infinity, reading = false;
  let loopTimer: ReturnType<typeof setTimeout> | undefined, clockTimer: ReturnType<typeof setInterval> | undefined;

  const on = computed(() => layers.value.includes(REGISTRY_ID));
  const cloud = computed(() => newer(cloudImage(reported()), index.value));
  const selected = computed(() => new Date(dockTime(day.value, hour.value, clock.value, zone()).at));
  const frames = computed(() => on.value ? cloudFrames(cloud.value, selected.value, clock.value, zone()).slice(-MAX_FRAMES) : []);
  const overlay = computed(() => cloud.value && frames.value.length ? cloudOverlay(cloud.value, frames.value, clock.value) : null);
  const canLoop = computed(() => frames.value.length > 1 && !reduced.value);
  const shown = computed(() => { const f = frames.value; return f.length ? f[reduced.value ? f.length - 1 : Math.min(step.value, f.length - 1)]! : null; });
  const playing = computed(() => canLoop.value && !cloudHeld.value && !hidden.value && shownPresentation.value === 'chart' && appView.value === 'coast');

  async function refresh(): Promise<void> {
    if (reading) return;
    reading = true; asked = now().getTime();
    const next = await cloudIndex(fetchFn, page());
    reading = false;
    if (!alive) return;
    // A failed read keeps the last good index, whose frames leave through the gate; an older one never replaces it.
    if (next) index.value = newer(index.peek(), next);
    read.value = true;
  }
  const tick = (): void => {
    const t = now();
    clock.value = t;
    if (t.getTime() - asked >= INDEX_REFRESH_MS) void refresh();
  };
  const visibility = (): void => { hidden.value = !!doc.hidden; };
  const motionChange = (): void => { reduced.value = !!motion?.matches; };
  doc.addEventListener('visibilitychange', visibility);
  motion?.addEventListener('change', motionChange);

  let drawn: Overlay | null = null, drawnOn: Engine | null = null;
  const disposers = [
    // The clock (ages, the 90-minute gate, the index refresh) runs while Clouds is on and the page is shown.
    effect(() => {
      clearInterval(clockTimer);
      if (!on.value || hidden.value) return;
      tick();
      clockTimer = setInterval(tick, MINUTE);
    }),
    // Oldest to newest, then the newest held; each step re-arms this effect.
    effect(() => {
      clearTimeout(loopTimer);
      if (!playing.value) return;
      const length = frames.value.length, current = Math.min(step.value, length - 1);
      loopTimer = setTimeout(() => { step.value = (current + 1) % length; }, current === length - 1 ? HOLD_MS : FRAME_MS);
    }),
    // One effect, so the frames exist before one of them is shown.
    effect(() => {
      const e = engine.value, o = overlay.value, at = shown.value;
      if (!e) return;
      if (o !== drawn || e !== drawnOn) { e.setOverlay(REGISTRY_ID, o, COASTLINE_GLOW); drawn = o; drawnOn = e; }
      for (const l of o?.layers ?? []) e.setRasterOpacity(l.id, at !== null && l.id === frameId(at) ? CLOUD_OPACITY : 0);
    }),
    effect(() => {
      const tz = zone(), at = shown.value, chart = shownPresentation.value === 'chart';
      cloudStamp.value = at && chart ? {at, label: frameLabel(at, clock.value, tz), canLoop: canLoop.value} : null;
      setRailNote(REGISTRY_ID, on.value && (read.value || cloud.value) ? cloudStatus(cloud.value, frames.value, selected.value, clock.value, tz) : '');
    }),
    // Off: the next loop starts on the newest frame, and a layer a tile error marked unavailable is retried.
    effect(() => {
      if (on.value) return;
      step.value = MAX_FRAMES;
      if (unavailable.peek().includes(REGISTRY_ID)) unavailable.value = unavailable.peek().filter(l => l !== REGISTRY_ID);
    }),
  ];
  return {
    destroy() {
      if (!alive) return;
      alive = false;
      clearTimeout(loopTimer); clearInterval(clockTimer);
      for (const dispose of disposers) dispose();
      doc.removeEventListener('visibilitychange', visibility);
      motion?.removeEventListener('change', motionChange);
      cloudStamp.value = null; setRailNote(REGISTRY_ID, '');
    },
  };
}
