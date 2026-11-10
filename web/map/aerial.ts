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
 * The base's one raster source (naipSource()'s template, so its fixed USGS host only) and its layer. SC1407-07: the
 * png32 fallback has its own source and layer id, so replacing the overlay replaces the source, and a late error from
 * the retired jpgpng source no longer names a layer the engine draws.
 */
export function aerialOverlay(a: AerialBase, format?: NaipFormat): Overlay {
  const id = format === 'png32' ? `${aerialId(a)}:png32` : aerialId(a);
  return {
    sources: {[id]: {...naipSource(format), attribution: aerialAttribution(a)}},
    layers: [{id, type: 'raster', source: id, paint: a.byDefault
      ? {'raster-opacity': AERIAL_DEFAULT_OPACITY, 'raster-saturation': AERIAL_DEFAULT_SATURATION}
      : {'raster-opacity': AERIAL_OPACITY, 'raster-saturation': AERIAL_SATURATION}}],
  };
}

/** The current region's aerial base, while a Chart exists to draw it; the rail offers Aerial only then. */
export const aerialOffer = signal<AerialBase | null>(null);

export interface AerialOptions {
  engine: ReadonlySignal<Engine | null>;
  /** The current region's aerial base (RegionInfo.aerial), null where none is offered; a signal read here is followed. */
  offer: () => AerialBase | null;
}

export function createAerial({engine, offer}: AerialOptions): {destroy(): void} {
  const drawn = computed(() => { const a = offer(); return a && base.value === 'aerial' ? a : null; });
  const overlay = computed(() => drawn.value ? aerialOverlay(drawn.value) : null);
  // SC1407-07: once the png32 form is drawn, `shown` is no longer the overlay computed above; every new draw (another
  // region, engine, or the base chosen again) starts at jpgpng, and a failure of the png32 form is not retried.
  let shown: Overlay | null = null, shownOn: Engine | null = null;
  const clear = () => { unavailable.value = unavailable.peek().filter(l => l !== REGISTRY_ID); };
  const disposers = [
    effect(() => { aerialOffer.value = offer(); }),
    effect(() => {
      const e = engine.value, o = overlay.value;
      if (!e || (o === shown && (e === shownOn || o === null))) return;
      e.setOverlay(REGISTRY_ID, o, ENC_LAYER);
      shown = o; shownOn = e;
    }),
    // Turned off, on again, another region or engine: a base a tile error marked unavailable is tried again, jpgpng first.
    effect(() => {
      void drawn.value; void engine.value;
      if (unavailable.peek().includes(REGISTRY_ID)) clear();
    }),
    // The first failure of a jpgpng draw (the service may refuse the mixed format) swaps in the png32 form once; a
    // failure of that form stays unavailable. Only Aerial's own flag is cleared, and only while Aerial is drawn.
    effect(() => {
      const d = drawn.peek(), e = engine.peek();
      if (!unavailable.value.includes(REGISTRY_ID) || !d || !e || shownOn !== e || shown !== overlay.peek()) return;
      e.setOverlay(REGISTRY_ID, shown = aerialOverlay(d, 'png32'), ENC_LAYER);
      clear();
    }),
  ];
  return {
    destroy() {
      for (const dispose of disposers) dispose();
      aerialOffer.value = null;
    },
  };
}
