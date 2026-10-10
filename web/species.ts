// Targets per profile (FE-30, design § 8): the command bar's target list is
// the profile's default and fixed species, then the region's species search
// plans whose method fits the profile (web/profile.ts speciesForProfile over
// regions/<id>/search-plans.json), then, where the region has coastal terrain,
// packages/coast's own targets (habitat-types.ts speciesOptions) that no
// listed id already names through coastTarget. This mirrors v1's
// sharedTargetOptions (dist/coast-targets.js), which v2 may not import. A
// target the link names that the list lacks stays first and explicit.
//
// Erasable syntax only: tests/test_species_profile.mjs imports it by type stripping.
import {signal} from '@preact/signals';
import {speciesOptions} from '../packages/coast/src/habitat-types.ts';
import {coastTarget, hasCoastTerrain} from './coast-context.ts';
import {METHOD_RULES, PROFILE_TABLE, speciesForProfile, type PlanLike, type Profile} from './profile.ts';

/** One search plan as the target list reads it (`search-plans.json` `profiles[id]`). */
export interface Plan extends PlanLike {readonly name?: string}
export interface TargetOption {readonly id: string; readonly label: string}

/** The region's search plans, keyed by region so another region's never lists. */
export const regionPlans = signal<{region: string; plans: Readonly<Record<string, Plan>>} | null>(null);

/** Load `regions/<id>/search-plans.json`; a failure leaves the profile's own species. */
export async function loadPlans(id: string, fetchFn: typeof fetch = fetch): Promise<void> {
  try {
    const response = await fetchFn(`regions/${encodeURIComponent(id)}/search-plans.json`);
    if (!response.ok) return;
    const json = await response.json() as {region_id?: unknown; profiles?: unknown};
    const plans = json.profiles && typeof json.profiles === 'object' && !Array.isArray(json.profiles) ? json.profiles as Record<string, Plan> : null;
    if (plans && json.region_id === id) regionPlans.value = {region: id, plans};
  } catch { /* the profile's own species stay listed */ }
}

/**
 * The coast targets a profile offers: shore takes the sandy-shore species (METHOD_RULES), boat and
 * spear the reef targets the renderer scores (a fit field); 'all' is the renderer's own overview.
 */
export function coastTargetsFor(profile: Profile): TargetOption[] {
  const method = PROFILE_TABLE[profile].method;
  return speciesOptions.filter(o => o.id !== 'all' && (method === 'shore' ? METHOD_RULES.shore.species.includes(o.id) : o.field !== null))
    .map(o => ({id: o.id, label: o.label}));
}

const title = (id: string): string => id.split('-').map(w => w ? w[0]!.toUpperCase() + w.slice(1) : w).join(' ');

/** The target list for `profile` in `region` with `plans`, labelled; `current` first when the list lacks it. */
export function targetsFor(profile: Profile, region: string | null, plans: Readonly<Record<string, Plan>>, current: string | null = null): TargetOption[] {
  const coast = region && hasCoastTerrain(region) ? coastTargetsFor(profile) : [];
  const label = (id: string): string => plans[id]?.name ?? speciesOptions.find(o => o.id === (coastTarget(id) ?? id))?.label ?? title(id);
  const list = speciesForProfile(plans, profile).map(id => ({id, label: label(id)}));
  const named = new Set(list.map(t => coastTarget(t.id) ?? t.id));
  for (const t of coast) if (!named.has(t.id)) { list.push(t); named.add(t.id); }
  return current && !list.some(t => t.id === current) ? [{id: current, label: title(current)}, ...list] : list;
}
