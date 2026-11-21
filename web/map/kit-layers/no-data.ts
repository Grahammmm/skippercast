// MSKL-3: the shared module of a kit layer with no authorized live source yet (LAYERS-KIT-PLAN § 2, data follow-ups § 7).
// It draws nothing, never switches itself on (no profile default or preset turns it on) and its legend row says
// "<layer>: no data yet". A layer card replaces its own web/map/kit-layers/<id>.ts with the real layer; nothing else changes.
// No feed, fetch or source row exists for these layers, and none is added here.
//
// Erasable syntax only: tests/test_stacking.mjs imports it by type stripping.
import type {KitDataState, KitLayerId} from '../stacking.ts';

/** What the legend and the stacking engine read from a kit layer's module; a layer card's real module keeps this shape. */
export interface KitLayerModule {
  readonly id: KitLayerId;
  /** The data state the stacking engine and the legend read. */
  readonly state: KitDataState;
  /** Whether a profile default or a preset may switch it on (stacking.ts mayAutoEnable). */
  readonly autoEnable: boolean;
  /** The MapLibre overlay to draw, or null for none. */
  overlay(): object | null;
}

/** The "no data yet" module: draws nothing and never switches itself on. */
export const noDataLayer = (id: KitLayerId): KitLayerModule => Object.freeze({id, state: 'no-data', autoEnable: false, overlay: () => null});
