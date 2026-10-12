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
import {naipSource} from '../../packages/coast/src/map-sources.ts';
import {base} from '../state.ts';
import {ENC_LAYER, unavailable} from './chart.ts';
import type {Engine, Overlay} from './engine.ts';

/** The one catalog source an aerial base may name (catalog/sources.json, FE-45). */
export const AERIAL_CATALOG_ID = 'usgs-naip';
/** § 9: raster at 0.92 opacity, desaturated, so the chart's own colours stay the strongest. */
export const AERIAL_OPACITY = 0.92;
export const AERIAL_SATURATION = -0.4;
const REGISTRY_ID = 'aerial';

/** A region's aerial base as its package records it: catalog source, acquisition window, check date and note. */
export interface AerialBase {
  readonly source: typeof AERIAL_CATALOG_ID;
  readonly first: string;
  readonly last: string;
  readonly checkedAt: string;
  readonly note: string;
}

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
/** region.json's `basemap.aerial`, or null where the region offers none or the record is not usgs-naip with ordered dates. */
export function aerialBase(region: unknown): AerialBase | null {
  const a = (region as {basemap?: {aerial?: {source?: unknown; checked_at?: unknown; acquired?: {first?: unknown; last?: unknown}; note?: unknown}}} | null)?.basemap?.aerial;
  const first = a?.acquired?.first, last = a?.acquired?.last, checked = a?.checked_at, note = a?.note;
  if (a?.source !== AERIAL_CATALOG_ID || typeof first !== 'string' || typeof last !== 'string' || typeof checked !== 'string' || typeof note !== 'string') return null;
  if (![first, last, checked].every(d => DATE.test(d)) || first > last || last > checked) return null;
  return {source: AERIAL_CATALOG_ID, first, last, checkedAt: checked, note};
}

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

/** The base's one raster source (naipSource()'s template, so its fixed USGS host only) and its layer. */
export function aerialOverlay(a: AerialBase): Overlay {
  const id = aerialId(a);
  return {
    sources: {[id]: {...naipSource(), attribution: aerialAttribution(a)}},
    layers: [{id, type: 'raster', source: id, paint: {'raster-opacity': AERIAL_OPACITY, 'raster-saturation': AERIAL_SATURATION}}],
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
  let shown: Overlay | null = null, shownOn: Engine | null = null;
  const disposers = [
    effect(() => { aerialOffer.value = offer(); }),
    effect(() => {
      const e = engine.value, o = overlay.value;
      if (!e || (o === shown && (e === shownOn || o === null))) return;
      e.setOverlay(REGISTRY_ID, o, ENC_LAYER);
      shown = o; shownOn = e;
    }),
    // Turned off, on again or another region: a base a tile error marked unavailable is tried again.
    effect(() => {
      void drawn.value;
      if (unavailable.peek().includes(REGISTRY_ID)) unavailable.value = unavailable.peek().filter(l => l !== REGISTRY_ID);
    }),
  ];
  return {
    destroy() {
      for (const dispose of disposers) dispose();
      aerialOffer.value = null;
    },
  };
}
