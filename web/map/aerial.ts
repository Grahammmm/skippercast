// Aerial base (FE-23, docs/plans/front-end/design.md § 8, § 9, § 11): the USDA
// NAIP natural-colour mosaic served by USGS, an optional Chart base like
// FE-11's ENC chart (`?base=aerial`), offered only where the region's package
// names it (region.json `basemap.aerial`, FE-45). The tile template, its one
// fixed USGS host and the credit are packages/coast's naipSource(); this file
// names no host and no date.
// - Dated imagery, never current conditions: the on-map credit and the rail's
//   note carry the acquisition window the region's package records ("flown
//   13–29 May 2022"), and the basis says the tiles are a dated mosaic. Open
//   water has no imagery (USGS returns transparent tiles there).
// - Nothing is requested until the base is chosen: the source exists only
//   while it is drawn (Engine.setOverlay, which waits for FE-14's style.load
//   gate), and a region without the flag never adds it.
// - Draw order (§ 9): above the basemap, under the ENC chart and so under every
//   field, mark and the coastline glow.
// - The first view is cheap (R4-SC-09): where the page says so (`sharp`), a new draw first asks each tile at a quarter
//   of its pixels; once the map has first settled the full image is laid over that preview, which goes when the map
//   next settles. Softer for the first seconds, never blank.
//
// Erasable syntax only: tests/test_aerial_layer.mjs imports this file by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import {naipSource, type NaipFormat} from '../../packages/coast/src/map-sources.ts';
import {base} from '../state.ts';
import {ENC_LAYER, unavailable} from './chart.ts';
import type {Engine, Overlay} from './engine.ts';

import {aerialBase, type AerialBase} from '../aerial-base.ts';
export {AERIAL_CATALOG_ID, aerialBase, type AerialBase} from '../aerial-base.ts';
/** § 9: where Aerial is an optional base, raster at 0.92 opacity and desaturated, so the chart's own colours stay the strongest. */
export const AERIAL_OPACITY = 0.92;
export const AERIAL_SATURATION = -0.4;
/** Where the region's package opens on Aerial (`basemap.default`) the imagery is the picture: full opacity, lightly desaturated. */
export const AERIAL_DEFAULT_OPACITY = 1;
export const AERIAL_DEFAULT_SATURATION = -0.15;
const REGISTRY_ID = 'aerial';

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const day = (iso: string): {d: number; m: string; y: string} => {
  const [, y = '', m = '', d = ''] = DATE.exec(iso) ?? [];
  return {d: Number(d), m: MONTHS[Number(m) - 1] ?? '', y};
};
/** The acquisition window as the label reads it: "flown 13–29 May 2022", "flown 30 May – 2 Jun 2022". */
export function flownText(a: Pick<AerialBase, 'first' | 'last'>): string {
  const s = day(a.first), e = day(a.last), end = `${e.d} ${e.m} ${e.y}`;
  if (a.first === a.last) return `flown ${end}`;
  if (s.y === e.y && s.m === e.m) return `flown ${s.d}–${end}`;
  return `flown ${s.d} ${s.m}${s.y === e.y ? '' : ` ${s.y}`} – ${end}`;
}

/** The credit MapLibre shows while the base is drawn: naipSource()'s own, then the imagery's dates. */
export const aerialAttribution = (a: AerialBase): string => `${naipSource().attribution} · ${flownText(a)}`;

/** Source and layer id; the window is part of it, so another region's dates replace the credit. */
export const aerialId = (a: AerialBase): string => `aerial:${a.first}/${a.last}`;

/**
 * R4-SC-09: the first view's image edge in pixels. Each 512 px tile is first asked at 256 x 256, a quarter of the pixels,
 * so the opening view's four Morro Bay tiles are about a quarter of the bytes (measured 280 KB against 1.14 MB); the
 * same tile grid, host and dates, drawn softer until the full image is laid over it.
 */
export const PREVIEW_SIZE = 256;
const FULL_SIZE = '&size=512,512&';
/** How the base is drawn: the preview alone (first view), the full image laid over the preview, or the full image alone. */
export type AerialStage = 'preview' | 'both' | 'full';
const softStage = signal(false);
/**
 * R4-SC-09: the drawn aerial base is still the preview (alone or under the arriving full image) and has not failed for
 * good. The Chart's first view is still being refined, so its host stays aria-busy (web/app/MapStage.tsx).
 */
export const aerialSoft = computed(() => softStage.value && !unavailable.value.includes(REGISTRY_ID));
/** naipSource()'s template at PREVIEW_SIZE, or null if the template no longer names its 512 px size. */
export function previewTiles(format?: NaipFormat): string[] | null {
  const {tiles} = naipSource(format);
  return tiles.every(t => t.includes(FULL_SIZE)) ? tiles.map(t => t.replace(FULL_SIZE, `&size=${PREVIEW_SIZE},${PREVIEW_SIZE}&`)) : null;
}

/**
 * The base's raster source (naipSource()'s template, so its fixed USGS host only) and its layer. SC1407-07: the
 * png32 fallback (the only `format` passed) has its own source and layer id, so replacing the overlay replaces the source, and a late error from
 * the retired jpgpng source no longer names a layer the engine draws. R4-SC-09: `stage` 'preview' draws the PREVIEW_SIZE
 * source (its own id, `:preview`) alone; 'both' lays the full source over it, so nothing goes blank while the full tiles arrive.
 */
export function aerialOverlay(a: AerialBase, format?: NaipFormat, stage: AerialStage = 'full'): Overlay {
  const id = aerialId(a) + (format ? `:${format}` : ''), preview = stage === 'full' ? null : previewTiles(format);
  const paint = a.byDefault
    ? {'raster-opacity': AERIAL_DEFAULT_OPACITY, 'raster-saturation': AERIAL_DEFAULT_SATURATION}
    : {'raster-opacity': AERIAL_OPACITY, 'raster-saturation': AERIAL_SATURATION};
  const source = {...naipSource(format), attribution: aerialAttribution(a)}, pid = `${id}:preview`;
  const sources: Record<string, typeof source> = {}, layers: Overlay['layers'][number][] = [];
  if (preview) { sources[pid] = {...source, tiles: preview}; layers.push({id: pid, type: 'raster', source: pid, paint}); }
  if (!preview || stage === 'both') { sources[id] = source; layers.push({id, type: 'raster', source: id, paint}); }
  return {stopOnError: true, sources, layers};
}

/** The current region's aerial base, while a Chart exists to draw it; the rail offers Aerial only then. */
export const aerialOffer = signal<AerialBase | null>(null);

/** SCB-12: give the brief a head start, not ownership of map readiness. A held coast
 * report must not hold imagery/publication feedback for the verdict's 20 s deadline. */
export const IMAGERY_HEAD_START_MS = 5_000;
export function createImageryStartup(settled: () => boolean): {ready: ReadonlySignal<boolean>; destroy(): void} {
  const ready = signal(false);
  const timer = setTimeout(() => { ready.value = true; }, IMAGERY_HEAD_START_MS);
  const dispose = effect(() => { if (settled()) { ready.value = true; clearTimeout(timer); } });
  return {ready, destroy() { dispose(); clearTimeout(timer); }};
}

/**
 * R4-SC-09: after the map's first settled view, how long the full aerial image waits for the seafloor's first view to land
 * before it shares the link anyway. The seafloor's tiles are the first view's other large download; the full image only sharpens it.
 */
export const SHARP_WAIT_MAX_MS = 10_000;
/**
 * R4-SC-09: ready once the map has first settled (`firstIdle`) and either nothing else of the first view is still
 * loading (`busy` reads false) or SHARP_WAIT_MAX_MS has passed since that first settle. Latched: it never re-holds.
 */
export function createSharpStart(firstIdle: () => boolean, busy: () => boolean): {ready: ReadonlySignal<boolean>; destroy(): void} {
  const ready = signal(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  const dispose = effect(() => {
    if (ready.value || !firstIdle()) return;
    if (!busy()) { ready.value = true; clearTimeout(timer); return; }
    timer ??= setTimeout(() => { ready.value = true; }, SHARP_WAIT_MAX_MS);
  });
  return {ready, destroy() { dispose(); clearTimeout(timer); }};
}

export interface AerialOptions {
  engine: ReadonlySignal<Engine | null>;
  /** The current region's aerial base (RegionInfo.aerial), null where none is offered; a signal read here is followed. */
  offer: () => AerialBase | null;
  /**
   * R4-SC-09: while this reads false a new draw starts with the PREVIEW_SIZE image; once it reads true (latched) the full
   * image is laid over the preview, and the preview is dropped when the map next settles. Omitted: the full image at once.
   */
  sharp?: () => boolean;
}

export function createAerial({engine, offer, sharp}: AerialOptions): {destroy(): void} {
  const drawn = computed(() => { const a = offer(); return a && base.value === 'aerial' ? a : null; });
  const sharpened = signal(!sharp);
  // What is drawn now: on which engine, for which base, in which format and stage. SC1407-07: every new draw (another
  // region, engine, or the base chosen again) starts at jpgpng, and a failure of the png32 form is not retried.
  let shown: {a: AerialBase; e: Engine; format?: NaipFormat; stage: AerialStage; overlay: Overlay} | null = null;
  let unwatch = (): void => {};
  const put = (a: AerialBase, e: Engine, format: NaipFormat | undefined, stage: AerialStage): void => {
    unwatch(); unwatch = () => {};
    const overlay = aerialOverlay(a, format, stage);
    e.setOverlay(REGISTRY_ID, overlay, ENC_LAYER);
    shown = {a, e, format, stage, overlay};
    softStage.value = stage !== 'full';
    // The full image laid over the preview: once the map settles, its tiles are in, and the preview goes.
    if (stage === 'both') {
      const off = e.view?.on('idle', () => {
        off?.();
        if (shown?.overlay !== overlay || unavailable.peek().includes(REGISTRY_ID)) return;
        put(a, e, format, 'full');
        try { performance.mark('skippercast-aerial-sharp'); } catch { /* no timing API */ }
      });
      unwatch = () => off?.();
    }
  };
  const clear = () => { unavailable.value = unavailable.peek().filter(l => l !== REGISTRY_ID); };
  const disposers = [
    effect(() => { aerialOffer.value = offer(); }),
    effect(() => { if (sharp?.()) sharpened.value = true; }),
    effect(() => {
      const e = engine.value, a = drawn.value;
      if (!e) return;
      if (!a) { if (shown) { unwatch(); e.setOverlay(REGISTRY_ID, null, ENC_LAYER); shown = null; softStage.value = false; } return; }
      if (shown?.a === a && shown.e === e) return;
      put(a, e, undefined, !sharpened.peek() && previewTiles() ? 'preview' : 'full');
    }),
    // Turned off, on again, another region or engine: a base a tile error marked unavailable is tried again, jpgpng first.
    effect(() => {
      void drawn.value; void engine.value;
      if (unavailable.peek().includes(REGISTRY_ID)) clear();
    }),
    // The first failure of a jpgpng draw (the service may refuse the mixed format) swaps in the png32 form once, at the
    // same stage (R4-SC-09: a first view stays a preview); a failure of that form stays unavailable. Only Aerial's own
    // flag is cleared, and only while Aerial is drawn.
    effect(() => {
      if (!unavailable.value.includes(REGISTRY_ID) || !shown || shown.format || shown.e !== engine.peek() || shown.a !== drawn.peek()) return;
      put(shown.a, shown.e, 'png32', shown.stage);
      clear();
    }),
    // R4-SC-09: the first view is in; lay the full image over the preview (never over a base that failed for good).
    effect(() => {
      if (!sharpened.value || shown?.stage !== 'preview' || shown.e !== engine.peek() || unavailable.peek().includes(REGISTRY_ID)) return;
      put(shown.a, shown.e, shown.format, 'both');
    }),
  ];
  return {
    destroy() {
      for (const dispose of disposers) dispose();
      unwatch();
      softStage.value = false;
      aerialOffer.value = null;
    },
  };
}
