// Targets per profile (FE-30, design § 8): the command bar's target list is
// the profile's default and fixed species, then the region's species search
// plans whose method fits the profile (web/profile.ts speciesForProfile over
// regions/<id>/search-plans.json, read from its #617 index), then, where the region has coastal terrain,
// packages/coast's own targets (habitat-types.ts speciesOptions) that no
// listed id already names through coastTarget. This mirrors v1's
// sharedTargetOptions (dist/coast-targets.js), which v2 may not import. A
// target the link names that the list lacks stays first and explicit.
// CI6-02: each target carries a state the picker shows beside its name, from the region's data
// (TargetState): ranked by mapped habitat, search plan only, or not researched in this region.
//
// Erasable syntax only: tests/test_species_profile.mjs imports it by type stripping.
import {effect, signal} from '@preact/signals';
import {region} from './state.ts';
import {speciesOptions} from '../packages/coast/src/habitat-types.ts';
import {coastTarget, hasCoastTerrain} from './coast-context.ts';
import {METHOD_RULES, PROFILE_TABLE, speciesForProfile, type PlanLike, type Profile} from './profile.ts';
import {planIndexURL} from './startup-forms.ts';

/** One search plan as the target list reads it (`search-plans.json` `profiles[id]`). */
export interface Plan extends PlanLike {readonly name?: string}
/**
 * Where a target comes from (FE-54): a SkipperCast search plan, the profile's own species with no
 * plan here, a coast habitat target the terrain scores, or the link's own target. The menu groups
 * them and never merges their scores. `other` holds the targets the region names as outside its
 * researched list (region.json `map.unavailable_targets`); the menu lists them but cannot select them.
 */
export type TargetGroup = 'plan' | 'profile' | 'coast' | 'link' | 'other';
/**
 * What the region has for a target (CI6-02), derived from its data, never written per species:
 * - `ranked`: "Where to look" ranks places for it here (web/ranking.ts): a reef target (its plan's
 *   `kind` is reef, or the coast renderer scores it) where the region has coastal terrain or survey
 *   atlas marks, in a profile that ranks places;
 * - `plan`: the region has a search plan for it and nothing ranks places for it;
 * - `unresearched`: the region names it in `map.unavailable_targets`, or it is not in the region's
 *   researched target list (no plan) and nothing ranks it.
 */
export type TargetState = 'ranked' | 'plan' | 'unresearched';
/** The picker's words for each state. No state says anything about fish. */
export const TARGET_STATE_TEXT: Readonly<Record<TargetState, string>> = {
  ranked: 'ranked by mapped habitat', plan: 'search plan only', unresearched: 'not researched in this region',
};
/** A target as the menu lists it; `state` is null while the data that decides it is still loading. */
export interface TargetOption {readonly id: string; readonly label: string; readonly group?: TargetGroup; readonly state?: TargetState | null}

/** The region's search plans, keyed by region so another region's never lists. */
export const regionPlans = signal<{region: string; plans: Readonly<Record<string, Plan>>} | null>(null);
/** The region's `map.unavailable_targets` (target id → reason), published by the region read (web/app/App.tsx loadRegion). */
export const regionUnavailable = signal<{region: string; targets: Readonly<Record<string, string>>} | null>(null);
/** How many survey atlas marks the region's Chart loaded (web/map/marks.ts); null until they load. */
export const regionAtlas = signal<{region: string; marks: number} | null>(null);

/** region.json `map.unavailable_targets` as id → reason; anything malformed is left out. */
export function unavailableTargets(json: unknown): Record<string, string> {
  const raw = (json as {map?: {unavailable_targets?: unknown}} | null)?.map?.unavailable_targets;
  const out: Record<string, string> = {};
  if (raw && typeof raw === 'object' && !Array.isArray(raw))
    for (const [id, reason] of Object.entries(raw)) if (typeof reason === 'string') out[id] = reason;
  return out;
}

export const PLAN_READ_TIMEOUT_MS = 10_000;
let planGeneration = 0;
let planRequest: AbortController | null = null;
effect(() => {
  const id = region.value;
  planGeneration++;
  planRequest?.abort();
  planRequest = null;
  if (regionPlans.peek()?.region !== id) regionPlans.value = null;
  if (regionUnavailable.peek()?.region !== id) regionUnavailable.value = null;
  if (regionAtlas.peek()?.region !== id) regionAtlas.value = null;
});

/** A search plan file's profiles when it is `id`'s; null otherwise. */
async function readPlans(url: string, id: string, fetchFn: typeof fetch, signal: AbortSignal): Promise<Record<string, Plan> | null> {
  try {
    const response = await fetchFn(url, {signal});
    if (!response.ok) return null;
    const json = await response.json() as {region_id?: unknown; profiles?: unknown};
    const plans = json.profiles && typeof json.profiles === 'object' && !Array.isArray(json.profiles) ? json.profiles as Record<string, Plan> : null;
    return plans && json.region_id === id ? plans : null;
  } catch { return null; }
}

/**
 * Load the region's plan profiles: its search-plan index (#617, web/startup-forms.ts; the profiles without
 * the plans' geometry), else `regions/<id>/search-plans.json`; a failure leaves the profile's own species.
 */
export async function loadPlans(id: string, fetchFn: typeof fetch = fetch): Promise<void> {
  // Explicit callers may load any keyed region; a selection change still invalidates that read.
  const selectedRegion = region.peek();
  const generation = ++planGeneration;
  planRequest?.abort();
  const controller = planRequest = new AbortController();
  let rejectAborted: (() => void) | undefined;
  const aborted = new Promise<never>((_resolve, reject) => {
    rejectAborted = () => reject(new Error('Plan read cancelled or timed out'));
    controller.signal.addEventListener('abort', rejectAborted, {once: true});
  });
  const timer = setTimeout(() => controller.abort(), PLAN_READ_TIMEOUT_MS);
  try {
    const read = async (): Promise<Record<string, Plan> | null> => {
      const index = await readPlans(planIndexURL(id), id, fetchFn, controller.signal);
      return index ?? (controller.signal.aborted ? null : await readPlans(`regions/${encodeURIComponent(id)}/search-plans.json`, id, fetchFn, controller.signal));
    };
    const plans = await Promise.race([read(), aborted]);
    if (plans && generation === planGeneration && selectedRegion === region.peek()) regionPlans.value = {region: id, plans};
  } catch { /* The profile's own targets remain available on failure or timeout. */ }
  finally {
    clearTimeout(timer);
    if (rejectAborted) controller.signal.removeEventListener('abort', rejectAborted);
    if (planRequest === controller) planRequest = null;
  }
}

/**
 * The coast targets a profile offers: shore takes the sandy-shore species (METHOD_RULES), boat and
 * spear the reef targets the renderer scores (a fit field); 'all' is the renderer's own overview.
 */
export function coastTargetsFor(profile: Profile): TargetOption[] {
  const method = PROFILE_TABLE[profile].method;
  return speciesOptions.filter(o => o.id !== 'all' && (method === 'shore' ? METHOD_RULES.shore.species.includes(o.id) : o.field !== null))
    .map(o => ({id: o.id, label: o.label, group: 'coast' as const}));
}

const title = (id: string): string => id.split('-').map(w => w ? w[0]!.toUpperCase() + w.slice(1) : w).join(' ');

/**
 * The region facts a target's state reads. `unavailable` is region.json `map.unavailable_targets`;
 * `plansLoaded` is false until the region's plans load (a target nothing ranks then has no state yet);
 * `ranks` says whether the region has places to rank: coastal terrain or survey atlas marks.
 */
export interface TargetCoverage {
  readonly unavailable?: Readonly<Record<string, string>>;
  readonly plansLoaded?: boolean;
  readonly ranks?: boolean;
}

/**
 * Whether "Where to look" ranks places for `id` given places to rank: its plan's `kind` is reef, or
 * the coast renderer scores it (a fit field, or the all-reef overview). This is the reef habitat
 * family web/map/habitat.ts `habitatFamily` ranks; tests/test_species_profile.mjs pins the two together.
 */
export function reefRanked(id: string, plans: Readonly<Record<string, Plan>>): boolean {
  if (Object.hasOwn(plans, id) && plans[id]!.kind === 'reef') return true;
  const option = speciesOptions.find(o => o.id === (coastTarget(id) ?? id));
  return !!option && (option.field !== null || option.id === 'all');
}

/** The state of `id` for `profile` in a region with `plans` and `coverage` (TargetState); null while it is undecided. */
export function targetState(id: string, profile: Profile, plans: Readonly<Record<string, Plan>>, coverage: TargetCoverage = {}): TargetState | null {
  if (coverage.unavailable && Object.hasOwn(coverage.unavailable, id)) return 'unresearched';
  if (coverage.ranks && PROFILE_TABLE[profile].whereToLook !== 'shore-runs' && reefRanked(id, plans)) return 'ranked';
  if (coverage.plansLoaded === false) return null;
  return Object.hasOwn(plans, id) ? 'plan' : 'unresearched';
}

/**
 * The target list for `profile` in `region` with `plans`, labelled and given its state; `current` first
 * when the list lacks it. `coverage.ranks` defaults to whether the region has coastal terrain.
 */
export function targetsFor(profile: Profile, region: string | null, plans: Readonly<Record<string, Plan>>, current: string | null = null, coverage: TargetCoverage = {}): TargetOption[] {
  const terrain = !!region && hasCoastTerrain(region);
  const cover: TargetCoverage = {...coverage, ranks: coverage.ranks ?? terrain};
  const coast = terrain ? coastTargetsFor(profile) : [];
  const label = (id: string): string => plans[id]?.name ?? speciesOptions.find(o => o.id === (coastTarget(id) ?? id))?.label ?? title(id);
  const list: TargetOption[] = speciesForProfile(plans, profile).map(id => ({id, label: label(id), group: Object.hasOwn(plans, id) ? 'plan' : 'profile'}));
  const named = new Set(list.map(t => coastTarget(t.id) ?? t.id));
  for (const t of coast) if (!named.has(t.id)) { list.push(t); named.add(t.id); }
  const all = current && !list.some(t => t.id === current) ? [{id: current, label: title(current), group: 'link' as const}, ...list] : list;
  return all.map(t => ({...t, state: targetState(t.id, profile, plans, cover)}));
}

/** The region's unavailable targets that `list` does not already hold: listed in the `other` group, never selectable. */
export function unresearchedTargets(list: readonly TargetOption[], unavailable: Readonly<Record<string, string>>): TargetOption[] {
  const listed = new Set(list.map(t => t.id));
  return Object.keys(unavailable).filter(id => !listed.has(id)).map(id => ({id, label: title(id), group: 'other' as const, state: 'unresearched' as const}));
}

/** What a menu option reads: the target's name, then its state once known ("Chinook salmon · search plan only"). */
export const optionText = (t: TargetOption): string => t.state ? `${t.label} · ${TARGET_STATE_TEXT[t.state]}` : t.label;

/**
 * The menu's groups in order: the link's target, the profile's own species with no plan here (its default
 * first), the plans, the coast targets, then the targets the region has not researched.
 */
export function targetGroups(list: readonly TargetOption[], profileLabel: string): {readonly label: string; readonly options: readonly TargetOption[]}[] {
  const heads: Readonly<Record<TargetGroup, string>> = {link: 'From the link', plan: `Search plans · ${profileLabel}`, profile: `${profileLabel} targets`, coast: 'Coast habitat targets', other: 'Other targets'};
  return (['link', 'profile', 'plan', 'coast', 'other'] as const).map(g => ({label: heads[g], options: list.filter(t => (t.group ?? 'profile') === g)})).filter(g => g.options.length);
}

/** The region's coverage facts as loaded: its unavailable targets, whether its plans loaded, and whether it has places to rank. */
export function regionCoverage(region: string | null): TargetCoverage {
  const unavailable = regionUnavailable.value, atlas = regionAtlas.value, plans = regionPlans.value;
  return {
    unavailable: unavailable && unavailable.region === region ? unavailable.targets : {},
    plansLoaded: !!plans && plans.region === region,
    ranks: !!region && (hasCoastTerrain(region) || (!!atlas && atlas.region === region && atlas.marks > 0)),
  };
}

/** The target list for `profile` in `region` with the region's loaded plans: what the command bar and the rail both list. */
export function regionTargets(profile: Profile, region: string | null, current: string | null): TargetOption[] {
  const loaded = regionPlans.value;
  return targetsFor(profile, region, loaded && loaded.region === region ? loaded.plans : {}, current, regionCoverage(region));
}

/** The command bar's and the rail's menu: the region's targets, then its unavailable targets, in their groups. */
export function regionMenu(profile: Profile, region: string | null, current: string | null, list: readonly TargetOption[] = regionTargets(profile, region, current)) {
  return targetGroups([...list, ...unresearchedTargets(list, regionCoverage(region).unavailable ?? {})], PROFILE_TABLE[profile].label);
}

/** The current target's label in `region` (the command bar's own words), for the legend's density line (#620). */
export function targetLabel(profile: Profile, region: string | null, current: string | null): string {
  const id = current ?? PROFILE_TABLE[profile].defaultTarget;
  return regionTargets(profile, region, current).find(t => t.id === id)?.label ?? title(id);
}
