// Targets per profile (FE-30, design § 8): the command bar's target list is
// the profile's default and fixed species, then the region's species search
// plans whose method fits the profile (web/profile.ts speciesForProfile over
// regions/<id>/search-plans.json, read from its #617 index), then, where the region has coastal terrain,
// packages/coast's own targets (habitat-types.ts speciesOptions) that no
// listed id already names through coastTarget. This mirrors v1's
// sharedTargetOptions (dist/coast-targets.js), which v2 may not import. A
// target the link names that the list lacks stays first and explicit.
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
 * them and never merges their scores.
 */
export type TargetGroup = 'plan' | 'profile' | 'coast' | 'link';
export interface TargetOption {readonly id: string; readonly label: string; readonly group?: TargetGroup}

/** The region's search plans, keyed by region so another region's never lists. */
export const regionPlans = signal<{region: string; plans: Readonly<Record<string, Plan>>} | null>(null);

export const PLAN_READ_TIMEOUT_MS = 10_000;
let planGeneration = 0;
let planRequest: AbortController | null = null;
effect(() => {
  const id = region.value;
  planGeneration++;
  planRequest?.abort();
  planRequest = null;
  if (regionPlans.peek()?.region !== id) regionPlans.value = null;
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

/** The target list for `profile` in `region` with `plans`, labelled; `current` first when the list lacks it. */
export function targetsFor(profile: Profile, region: string | null, plans: Readonly<Record<string, Plan>>, current: string | null = null): TargetOption[] {
  const coast = region && hasCoastTerrain(region) ? coastTargetsFor(profile) : [];
  const label = (id: string): string => plans[id]?.name ?? speciesOptions.find(o => o.id === (coastTarget(id) ?? id))?.label ?? title(id);
  const list: TargetOption[] = speciesForProfile(plans, profile).map(id => ({id, label: label(id), group: Object.hasOwn(plans, id) ? 'plan' : 'profile'}));
  const named = new Set(list.map(t => coastTarget(t.id) ?? t.id));
  for (const t of coast) if (!named.has(t.id)) { list.push(t); named.add(t.id); }
  return current && !list.some(t => t.id === current) ? [{id: current, label: title(current), group: 'link'}, ...list] : list;
}

/** The menu's groups in order: the link's target, the profile's own species with no plan here (its default first), the plans, the coast targets. */
export function targetGroups(list: readonly TargetOption[], profileLabel: string): {readonly label: string; readonly options: readonly TargetOption[]}[] {
  const heads: Readonly<Record<TargetGroup, string>> = {link: 'From the link', plan: `Search plans · ${profileLabel}`, profile: `${profileLabel} targets`, coast: 'Coast habitat targets'};
  return (['link', 'profile', 'plan', 'coast'] as const).map(g => ({label: heads[g], options: list.filter(t => (t.group ?? 'profile') === g)})).filter(g => g.options.length);
}

/** The target list for `profile` in `region` with the region's loaded plans: what the command bar and the rail both list. */
export function regionTargets(profile: Profile, region: string | null, current: string | null): TargetOption[] {
  const loaded = regionPlans.value;
  return targetsFor(profile, region, loaded && loaded.region === region ? loaded.plans : {}, current);
}

/** The current target's label in `region` (the command bar's own words), for the legend's density line (#620). */
export function targetLabel(profile: Profile, region: string | null, current: string | null): string {
  const id = current ?? PROFILE_TABLE[profile].defaultTarget;
  return regionTargets(profile, region, current).find(t => t.id === id)?.label ?? title(id);
}
