// MYB-2: which boat the comfort rating is for, and what the model can claim
// for it. The comfort model (dist/boat-handling.js, web/score.ts) is a
// planing-hull rule-of-thumb heuristic tuned on one 23 ft deep-V; no document,
// test or receipt in this repository validates it over any boat-length range
// (docs/boat-profile.md: calibration against real trips is future work). So
// this file claims no validated range. BOAT_NOTE_RANGE_FT (within 20 percent
// of 23 ft) is a presentation threshold chosen for MYB-2, not a validation
// claim: outside it the screen says what the model is instead of
// extrapolating silently. The model itself is unchanged.
//
// Erasable syntax only: Node tests import this file by type stripping.

/** The boat every threshold was tuned on (dist/boat-handling.js REFERENCE.loa_ft). */
export const REFERENCE_LOA_FT = 23;
/** Within 20 percent of the reference length: a presentation threshold, not a validated range. */
export const BOAT_NOTE_RANGE_FT: Readonly<{min: number; max: number}> = Object.freeze({min: 18.4, max: 27.6});
/** Shown for a saved boat outside BOAT_NOTE_RANGE_FT. */
export const BOAT_MODEL_NOTE = 'Ratings are a planing-hull rule-of-thumb model tuned on a 23 ft boat, not a sea-keeping calculation.';
/** The rating's subject with no saved boat. */
export const REFERENCE_BOAT_NAME = 'the reference 23 ft boat';

export type SavedBoatLike = {name?: unknown; loa_ft?: unknown} | null | undefined;

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** null inside BOAT_NOTE_RANGE_FT or with no known length (the factors then use the reference length); BOAT_MODEL_NOTE outside it. */
export function boatRangeNote(loaFt: unknown): string | null {
  if (!finite(loaFt)) return null;
  return loaFt >= BOAT_NOTE_RANGE_FT.min && loaFt <= BOAT_NOTE_RANGE_FT.max ? null : BOAT_MODEL_NOTE;
}

/** The saved boat's name, else "your <n> ft boat", else the reference boat. The first-use step's automatic "<n> ft boat" name counts as no name. */
export function boatBasisName(boat: SavedBoatLike): string {
  if (!boat) return REFERENCE_BOAT_NAME;
  const name = typeof boat.name === 'string' ? boat.name.trim() : '';
  if (name && !/^\d+(\.\d+)? ft boat$/.test(name)) return name;
  return finite(boat.loa_ft) ? `your ${Number(boat.loa_ft.toFixed(1))} ft boat` : 'your boat';
}
