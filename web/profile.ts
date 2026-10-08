// Boat / Shore / Spear profile semantics (FE-04, design § 8), ported from
// fish's experience.ts, daily.ts and opportunity.ts as data so that tests
// cover the table without the DOM. The brief (FE-30), the layer rail (FE-11)
// and the command bar read it; nothing here promises fish.
//
// Erasable syntax only: Node tests import this file by type stripping.

export const PROFILES = ['boat', 'shore', 'spear'] as const;
export type Profile = typeof PROFILES[number];

/** How a species search plan is fished; a plan may carry several. */
export const METHODS = ['boat', 'shore', 'dive'] as const;
export type Method = typeof METHODS[number];

/** Layer rail ids (§ 9) that `web/map/layers.ts` registers. */
export const RAIL_IDS = ['seafloor', 'currents', 'water-temp', 'swell', 'fleet', 'clouds'] as const;
export type RailId = typeof RAIL_IDS[number];

export interface ProfileSemantics {
  readonly id: Profile;
  readonly label: string;
  /** Species id selected when the profile changes (§ 8 "Default target"). */
  readonly defaultTarget: string;
  /** Marks and candidates deeper than this are left out; null means no limit. */
  readonly maxDepthFt: number | null;
  /** Search plans with this method make the profile's species list. */
  readonly method: Method;
  /** Species listed first whether or not the region has a plan for them. */
  readonly fixedSpecies: readonly string[];
  /** "Where to look" ranking (§ 8). */
  readonly whereToLook: 'reef-fit' | 'shore-runs' | 'reef-shallow';
  /** Which swell reading the brief's tile shows. */
  readonly swellTile: 'offshore' | 'nearshore';
  readonly defaultLayers: readonly RailId[];
  /** The one caveat the brief shows for this profile. */
  readonly caveat: string;
}

export const PROFILE_TABLE: Readonly<Record<Profile, ProfileSemantics>> = {
  boat: {
    id: 'boat', label: 'Boat', defaultTarget: 'lingcod', maxDepthFt: 300, method: 'boat', fixedSpecies: [],
    whereToLook: 'reef-fit', swellTile: 'offshore', defaultLayers: ['seafloor', 'currents'],
    caveat: 'Habitat describes a place to look; fish presence is unverified.',
  },
  shore: {
    id: 'shore', label: 'Shore', defaultTarget: 'surfperch', maxDepthFt: null, method: 'shore', fixedSpecies: ['surfperch', 'halibut'],
    whereToLook: 'shore-runs', swellTile: 'nearshore', defaultLayers: ['swell', 'water-temp'],
    caveat: 'Offshore seas do not measure breakers at your beach; check surf, access and water quality.',
  },
  spear: {
    id: 'spear', label: 'Spear', defaultTarget: 'cabezon-shallow-reef', maxDepthFt: 60, method: 'dive', fixedSpecies: [],
    whereToLook: 'reef-shallow', swellTile: 'nearshore', defaultLayers: ['seafloor', 'swell'],
    caveat: 'In-water visibility is unverified; surface currents cannot clear a dive.',
  },
};

export const DEFAULT_PROFILE: Profile = 'boat';

export function isProfile(value: unknown): value is Profile {
  return typeof value === 'string' && (PROFILES as readonly string[]).includes(value);
}

export const profileSemantics = (profile: Profile): ProfileSemantics => PROFILE_TABLE[profile];

/** The fields of a species search plan (`search-plans.json` `profiles[id]`) the method filter reads. */
export interface PlanLike {
  readonly kind?: string;
  readonly control_mode?: string;
  /** Explicit methods win over the kind rules when a plan carries them. */
  readonly methods?: readonly string[];
}

/**
 * Methods a plan supports when it names none (§ 8 "Search plans"). Every
 * published plan is written for a boat; shore plans are the sandy-shore
 * species; a dive plan is a bottom-fished reef or habitat plan.
 */
export const METHOD_RULES: Readonly<Record<Method, {readonly kinds: readonly string[]; readonly controlModes: readonly string[]; readonly species: readonly string[]}>> = {
  boat: {kinds: ['reef', 'habitat', 'soft', 'pelagic', 'offshore'], controlModes: [], species: []},
  shore: {kinds: [], controlModes: [], species: ['surfperch', 'halibut']},
  dive: {kinds: ['reef', 'habitat'], controlModes: ['bottom'], species: ['cabezon-shallow-reef']},
};

/** The methods plan `id` supports. */
export function planMethods(id: string, plan: PlanLike): Method[] {
  const named = plan.methods;
  if (named) return METHODS.filter(m => named.includes(m));
  return METHODS.filter(m => {
    const rule = METHOD_RULES[m];
    if (rule.species.includes(id)) return true;
    if (!rule.kinds.includes(plan.kind ?? '')) return false;
    return rule.controlModes.length === 0 || rule.controlModes.includes(plan.control_mode ?? '');
  });
}

/** Plan ids a profile offers, default target first, then the fixed species, then the region's plans in order. */
export function speciesForProfile(plans: Readonly<Record<string, PlanLike>>, profile: Profile): string[] {
  const p = PROFILE_TABLE[profile];
  const ids = [p.defaultTarget, ...p.fixedSpecies];
  for (const [id, plan] of Object.entries(plans)) if (planMethods(id, plan).includes(p.method)) ids.push(id);
  return ids.filter((id, i) => ids.indexOf(id) === i);
}

/** The terrain renderer's deepest limit, which packages/coast `experience.ts` applies where a profile sets none. */
export const TERRAIN_DEPTH_CEILING_FT = 300;

/**
 * The depth limit the terrain renderer takes for `profile` (`setDepthLimit`):
 * the profile's own limit, else the ceiling. tests/test_profile.mjs pins it to
 * `experience.ts` `maxDepth`, so the two tables cannot drift.
 */
export function terrainDepthLimitFt(profile: Profile): number {
  return PROFILE_TABLE[profile].maxDepthFt ?? TERRAIN_DEPTH_CEILING_FT;
}

/** Whether a mark or candidate at `depthFt` is inside the profile's limit; unknown depth stays in. */
export function withinDepth(profile: Profile, depthFt: number | null | undefined): boolean {
  const limit = PROFILE_TABLE[profile].maxDepthFt;
  return limit === null || depthFt == null || !Number.isFinite(depthFt) || depthFt <= limit;
}
