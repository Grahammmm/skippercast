// Boat profile and handling factors. Pure, dependency-free and shared by the
// browser (ratings, profile sheet) and the Worker (validating AI lookups).
//
// SkipperCast's comfort and control thresholds were tuned on one boat: a 23 ft,
// ~4,500 lb loaded, 20-degree deep-V walkaround. A saved profile scales those
// thresholds by length, weight for length, hull shape and layout. The model is a
// disclosed heuristic from planing-hull rules of thumb, not a sea-keeping
// calculation, and it does not certify a boat for any condition.

export const BOAT_KEY = 'skippercast-boat-v1';

export const HULLS = {
  'deep-v': 'Deep-V (about 19° deadrise or more)',
  'modified-v': 'Modified-V (about 12–18°)',
  'flat': 'Flat or shallow-V (under 12°)',
  'catamaran': 'Power catamaran',
  'displacement': 'Displacement or semi-displacement',
};
export const LAYOUTS = {
  'center-console': 'Center console',
  'dual-console': 'Dual console',
  'walkaround': 'Walkaround / cuddy',
  'pilothouse': 'Pilothouse / cabin',
  'skiff': 'Open skiff or bowrider',
};

// The boat the original thresholds were tuned on.
export const REFERENCE = {name: 'Reference 23 ft deep-V walkaround', loa_ft: 23, beam_ft: 8.5,
  displacement_lb: 4500, deadrise_deg: 20, hull: 'deep-v', layout: 'walkaround', cruise_kn: 20};

const LIMITS = {loa_ft: [8, 70], beam_ft: [3, 24], displacement_lb: [150, 60000], dry_weight_lb: [100, 50000],
  deadrise_deg: [0, 30], cruise_kn: [2, 60], max_hp: [0, 3000], fuel_gal: [0, 1500]};

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const num = (v, [lo, hi]) => (typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi ? v : null);

/** Validate a profile (from a person or an AI lookup); unknown or implausible values become null. */
export function normalizeBoat(input = {}) {
  const out = {name: typeof input.name === 'string' ? input.name.trim().slice(0, 80) : ''};
  for (const [key, range] of Object.entries(LIMITS)) out[key] = num(input[key] === '' ? null : Number(input[key] ?? NaN), range);
  out.hull = HULLS[input.hull] ? input.hull : null;
  out.layout = LAYOUTS[input.layout] ? input.layout : null;
  if (out.beam_ft && out.loa_ft && out.beam_ft > out.loa_ft * 0.6) out.beam_ft = null;
  if (!out.displacement_lb && out.dry_weight_lb) out.displacement_lb = Math.round(out.dry_weight_lb * 1.3);  // fuel, crew, gear
  if (!out.hull && out.deadrise_deg != null) out.hull = out.deadrise_deg >= 19 ? 'deep-v' : out.deadrise_deg >= 12 ? 'modified-v' : 'flat';
  return out;
}

function hullFactor(boat) {
  if (boat.hull === 'catamaran') return 1.08;
  const deadrise = boat.deadrise_deg ?? {'deep-v': 20, 'modified-v': 15, 'flat': 8, 'displacement': 20}[boat.hull] ?? 18;
  if (boat.hull === 'displacement') return 1.0;
  return deadrise >= 19 ? 1.0 : deadrise >= 12 ? 0.88 + (deadrise - 12) * 0.017 : 0.75 + deadrise * 0.01;
}
const layoutFactor = boat => ({'pilothouse': 1.05, 'walkaround': 1.0, 'dual-console': 0.98, 'center-console': 0.97, 'skiff': 0.9})[boat.layout] ?? 1.0;

function raw(boat) {
  const loa = boat.loa_ft ?? REFERENCE.loa_ft, ratio = loa / REFERENCE.loa_ft;
  const expected = REFERENCE.displacement_lb * ratio ** 3;          // same weight for length as the reference
  const displacement = boat.displacement_lb ?? expected;
  const heavy = clamp((displacement / expected) ** 0.15, 0.85, 1.15);  // heavier for its length rides a little better
  return {
    sea: ratio ** 0.9 * heavy * hullFactor(boat) * layoutFactor(boat),
    wind: (displacement / REFERENCE.displacement_lb) ** 0.2 * ratio ** 0.3,   // drift control: windage vs mass
    ratio,
  };
}
const REF = raw(REFERENCE);

/**
 * Multipliers on the tuned thresholds: `sea` scales wave heights (and divides
 * their penalty slopes), `wind` does the same for wind and gust, `chopPeriod`
 * is the period below which chop is short and steep for this length.
 * The reference boat, or no profile, returns exactly {sea: 1, wind: 1, chopPeriod: 6}.
 */
export function boatFactors(boat) {
  if (!boat) return {sea: 1, wind: 1, chopPeriod: 6, custom: false};
  const b = normalizeBoat(boat), r = raw(b);
  return {sea: clamp(r.sea / REF.sea, 0.45, 2.6), wind: clamp(r.wind / REF.wind, 0.6, 1.8),
    chopPeriod: Math.round(6 * Math.sqrt(r.ratio) * 10) / 10, custom: true};
}

/** Plain-language thresholds for a profile, for the sheet and rating notes. */
export function describeFactors(f) {
  const r1 = v => Math.round(v * 10) / 10;
  return {seas: r1(1.5 * f.sea), chop: r1(0.4 * f.sea), wind: r1(4 * f.wind), gust: r1(7 * f.wind), chopPeriod: f.chopPeriod};
}

export function savedBoat() {
  try {
    const value = JSON.parse(globalThis.localStorage?.getItem(BOAT_KEY) || 'null');
    return value && value.schema_version === 1 ? value : null;
  } catch { return null; }
}

let active;
/** Factors for the saved boat, or the reference when none is saved. */
export function activeBoatFactors() {
  if (active === undefined) active = boatFactors(savedBoat()?.boat || null);
  return active;
}
