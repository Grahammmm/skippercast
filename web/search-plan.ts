// MYB-3: the search plan "Where to look" shows for a target the picker labels "search plan only"
// (web/species.ts TargetState 'plan'), read from the region's already loaded plans (regionPlans),
// never another region's. Reviewed source text stays verbatim; Preact escapes it when rendered.
// Erasable syntax only: tests/test_search_plan.mjs imports it by type stripping.
import {sourceLinks, trustworthy, type Link} from './plan.ts';
import type {Plan} from './species.ts';

/** One line of a plan as the brief lists it: the plan file's field, the app's label for it and the file's own words. */
export interface PlanItem {readonly field: string; readonly label: string; readonly text: string}
export interface SearchPlan {readonly id: string; readonly name: string; readonly items: readonly PlanItem[]; readonly basis: string; readonly links: readonly Link[]}
type Loaded = {readonly region: string; readonly plans: Readonly<Record<string, Plan>>} | null | undefined;

const FIELDS = [['life_stage', 'Life stage'], ['search_for', 'What to search for'], ['habitat', 'Habitat'], ['presentation', 'How to fish it'],
  ['method', 'How to fish it'], ['timing', 'Timing'], ['condition_response', 'When conditions change'], ['caution', 'Caution']] as const;
const text = (s: unknown): s is string => typeof s === 'string' && s.trim().length > 0;

/**
 * The plan for `target` in `region` from the loaded `regionPlans` value; null while none is loaded, when the loaded
 * plans are another region's, when the region has no plan for it, or when the plan carries a numeric model (web/plan.ts).
 */
export function planFor(target: string | null | undefined, loaded: Loaded, region: string | null = loaded?.region ?? null): SearchPlan | null {
  if (!target || !loaded || !region || loaded.region !== region || !loaded.plans || !Object.hasOwn(loaded.plans, target)) return null;
  const p = loaded.plans[target]!;
  if (!p || typeof p !== 'object' || !trustworthy(p)) return null;
  const items: PlanItem[] = FIELDS.flatMap(([field, label]) => text(p[field]) ? [{field, label, text: p[field]}] : []);
  for (const c of Array.isArray(p.required_to_confirm) ? p.required_to_confirm : []) if (text(c)) items.push({field: 'required_to_confirm', label: 'Confirm on the day', text: c});
  return {id: target, name: text(p.name) ? p.name : target, items, basis: text(p.tactics_basis) ? p.tactics_basis : '', links: sourceLinks(p.source_links)};
}

/** The sentence added to the empty list when the target is plan-only but the region has no plan to show. */
export const noPlanText = (regionName: string | null | undefined): string => `No search plan for this species in ${regionName || 'this region'} yet.`;
