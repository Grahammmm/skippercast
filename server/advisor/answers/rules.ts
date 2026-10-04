// The rules table (docs/plans/text-advisor/02-data-model.md § advisor_rules,
// 06 § fish ID step 3, OP-6, principle 4). The only place the advisor reads a
// regulation from. A row is returned when it is 'active' or 'review' (never
// 'retired'); it is `stale` when it is in review or past its review_due date,
// and the prompt makes the model say "double-check" for a stale row. Rows are
// stored per jurisdiction (region '*', from scripts/advisor/import-rules.mjs)
// or for one region; a region-specific row comes first.
import {jurisdictionFor} from './regions.ts';
import {localDate} from './time.ts';
import extra from '../../../catalog/advisor/species-extra.json' with {type: 'json'};
import targets from '../../../catalog/targets.json' with {type: 'json'};

export interface RuleRow {
  id: string; region: string; jurisdiction: string; species_key: string; species_label: string;
  size_min_in: number | null; size_max_in: number | null; bag_limit: number | null; bag_notes: string | null;
  season_open: string | null; season_close: string | null; depth_limit_ft: number | null; area_notes: string | null; gear_notes: string | null;
  source_name: string; source_url: string; reviewed_at: string; review_due: string; status: 'active' | 'review' | 'retired';
  updated_by: string; updated_at: string;
}
/** A rule as the advisor may quote it. `applies_as: 'group'` marks the parent group's rule (rockfish for a vermilion). */
export interface Rule extends Omit<RuleRow, 'updated_by' | 'updated_at' | 'id'> {stale: boolean; applies_as: 'species' | 'group'}

type Extra = {key: string; parent: string | null; same_as_parent?: boolean};
const EXTRA = extra.species as Extra[];
const SYNONYM = new Map(EXTRA.filter(e => e.same_as_parent && e.parent).map(e => [e.key, e.parent!] as const));
const PARENT = new Map(EXTRA.filter(e => e.parent && !e.same_as_parent).map(e => [e.key, e.parent!] as const));
const GROUPS = targets.targets as Record<string, {source_species: string[]}>;

/** The keys a question about `speciesKey` covers: itself, its catalog parent, or a target group's species. */
export function ruleKeys(speciesKey: string): {species: string[]; group: string[]} {
  const raw = String(speciesKey ?? '').toLowerCase(), key = SYNONYM.get(raw) ?? raw;
  const parent = PARENT.get(key);
  if (parent) return {species: [key], group: [parent]};
  if (GROUPS[key] && !GROUPS[key]!.source_species.includes(key)) return {species: [...GROUPS[key]!.source_species], group: []};
  return {species: [key], group: []};
}

/** Stale: in review, or past its review_due date (YYYY-MM-DD, Pacific today). */
export const isStale = (row: Pick<RuleRow, 'status' | 'review_due'>, today: string): boolean => row.status !== 'active' || !(row.review_due >= today);

/**
 * Active and review rows for a species in a region (and the jurisdiction's
 * '*' rows), never retired. A sub-species also gets its parent group's rows,
 * marked applies_as 'group'. Region-specific rows first.
 */
export async function lookupRules(db: D1Database, args: {region: string; speciesKey: string; now?: number}): Promise<Rule[]> {
  const {species, group} = ruleKeys(args.speciesKey);
  const keys = [...species, ...group];
  if (!keys.length) return [];
  const jurisdiction = jurisdictionFor(args.region);
  const today = localDate(args.now ?? Date.now());
  const marks = keys.map(() => '?').join(',');
  const rows = (await db.prepare(`SELECT * FROM advisor_rules WHERE species_key IN (${marks}) AND status IN ('active','review')
      AND (region=? OR (region='*' AND jurisdiction=?)) ORDER BY CASE WHEN region='*' THEN 1 ELSE 0 END, species_key, species_label`)
    .bind(...keys, args.region, jurisdiction ?? '').all<RuleRow>()).results;
  return rows.map(({id: _id, updated_by: _by, updated_at: _at, ...row}) => ({...row, stale: isStale(row, today), applies_as: group.includes(row.species_key) ? 'group' : 'species'}));
}

/**
 * Put every active row of a jurisdiction back into review (the rule-change
 * watch hook, TA-A4): from then on each is quoted only with "double-check"
 * until an admin re-confirms it. Returns how many rows changed.
 */
export async function markJurisdictionForReview(db: D1Database, jurisdiction: string, now: number = Date.now(), by = 'rule-watch'): Promise<number> {
  const result = await db.prepare("UPDATE advisor_rules SET status='review', updated_by=?, updated_at=? WHERE jurisdiction=? AND status='active'")
    .bind(by, new Date(now).toISOString(), jurisdiction).run();
  return Number(result.meta?.changes ?? 0);
}
