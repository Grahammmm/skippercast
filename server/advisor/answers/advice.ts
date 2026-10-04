// Rigging and area advice behind get_strategy (docs/plans/text-advisor/06-angler-answers.md
// § rigging and area advice; AD-1, AD-2, principle 7). Sources: the method
// catalogs (catalog/primary-strategies.json, catalog/search-methods.json,
// catalog/targets.json, catalog/species.json) and, for places, only the named
// public grounds in catalog/advisor/public-grounds.json (taken from
// dist/data/charter-grounds.json labels). The region's search-plans.json spot
// names are offered to the filter too, and every name that is not on the
// allowlist is dropped. Nothing here carries a coordinate, a radius or a
// waypoint, and publicOnly() strips any number that looks like one.
import primary from '../../../catalog/primary-strategies.json' with {type: 'json'};
import methods from '../../../catalog/search-methods.json' with {type: 'json'};
import targets from '../../../catalog/targets.json' with {type: 'json'};
import catalog from '../../../catalog/species.json' with {type: 'json'};
import grounds from '../../../catalog/advisor/public-grounds.json' with {type: 'json'};
import extra from '../../../catalog/advisor/species-extra.json' with {type: 'json'};

export type AreaKind = 'reef' | 'bank' | 'edge';
export interface PublicGround {name: string; charter_ground_id: string; kind: AreaKind; species: string[]; general_depth_ft: [number, number]; description: string}
export interface Area {name: string; kind: AreaKind; general_depth_ft: [number, number]; description: string}
export interface Strategy {
  species_key: string; target: string; region: string;
  rig: string | null; bait_or_lure: string | null; line: string | null; weight: string | null;
  depth_band_ft: [number, number] | null; depth_note: string | null; season_note: string | null;
  how: string[]; areas: Area[]; general_area: string | null; source_notes: string[];
}

interface Primary {priority?: string; rig?: string; steps?: string[]; adjust?: string; variants?: {name: string; focus?: string; presentation?: string}[]; method_sources?: {title: string; url: string}[]}
interface Method {name?: string; presentation?: string; timing?: string; search_for?: string; habitat?: string; tactics_basis?: string; source_links?: unknown[]}
const PRIMARY = primary.species as Record<string, Primary>;
const METHODS = methods.species as Record<string, Method>;
const TARGETS = targets.targets as Record<string, {source_species: string[]}>;
const SPECIES = new Map((catalog.species as {id: string; name: string; depth_strategy?: string}[]).map(s => [s.id, s] as const));
const PARENT = new Map((extra.species as {key: string; parent: string | null}[]).filter(e => e.parent).map(e => [e.key, e.parent!] as const));
export const PUBLIC_GROUNDS = grounds.regions as unknown as Record<string, PublicGround[]>;

/** The catalog target whose methods cover a species: itself, its group (lingcod -> reef), or its parent's group (vermilion -> reef). */
export function targetFor(speciesKey: string): string | null {
  const key = PARENT.get(speciesKey) ?? speciesKey;
  if (PRIMARY[key] || METHODS[key]) return key;
  for (const [id, t] of Object.entries(TARGETS)) if (t.source_species.includes(key) && (PRIMARY[id] || METHODS[id])) return id;
  return null;
}

// Coordinate-like text: decimal degrees (35.1794), a degree sign, degrees-minutes (35 10.5 N), loran-ish digit runs.
export const COORDINATE = /\d{2}\.\d{3,}|°|\b\d{2,3}\s*[°º]?\s*\d{1,2}(?:\.\d+)?\s*['′]\s*[NSEW]?\b|\b\d{5}\.\d\b/;
/** Drop any sentence that carries a coordinate-like number (a belt-and-braces check on catalog text). */
export function publicOnly(text: string | null | undefined): string | null {
  if (!text) return null;
  const kept = String(text).split(/(?<=[.!?])\s+/).filter(s => !COORDINATE.test(s)).join(' ').trim();
  return kept || null;
}

/** The allowlisted public grounds for a region and species; any other name in `candidates` (search-plan spot names) is dropped. */
export function publicAreas(region: string, speciesKey: string, candidates: readonly string[] = []): Area[] {
  const allowed = PUBLIC_GROUNDS[region] ?? [];
  const species = new Set([speciesKey, PARENT.get(speciesKey) ?? speciesKey, ...(TARGETS[speciesKey]?.source_species ?? [])]);
  const byName = new Map(allowed.map(g => [g.name.toLowerCase(), g] as const));
  const named = candidates.map(n => byName.get(String(n).toLowerCase())).filter((g): g is PublicGround => Boolean(g));
  const out: Area[] = [];
  for (const g of [...named, ...allowed]) {
    if (!g.species.some(s => species.has(s)) || out.some(a => a.name === g.name)) continue;
    out.push({name: g.name, kind: g.kind, general_depth_ft: [g.general_depth_ft[0], g.general_depth_ft[1]], description: publicOnly(g.description) ?? ''});
  }
  return out;
}

const sentence = (text: string | undefined, pattern: RegExp): string | null => {
  const hit = String(text ?? '').split(/(?<=[.!?])\s+/).find(s => pattern.test(s));
  return hit ? hit.trim() : null;
};

/** get_strategy's answer for a species in a region, from the catalogs and the allowlist only. */
export function strategyFor(speciesKey: string, region: string, planNames: readonly string[] = []): Strategy | null {
  const target = targetFor(speciesKey);
  if (!target) return null;
  const p = PRIMARY[target] ?? {}, m = METHODS[target] ?? {};
  const variant = p.variants?.find(v => v.name.toLowerCase() === (SPECIES.get(speciesKey)?.name ?? speciesKey).toLowerCase() || v.name.toLowerCase() === speciesKey);
  const areas = publicAreas(region, speciesKey, planNames);
  const lo = areas.length ? Math.min(...areas.map(a => a.general_depth_ft[0])) : null, hi = areas.length ? Math.max(...areas.map(a => a.general_depth_ft[1])) : null;
  const depthOf = SPECIES.get(PARENT.get(speciesKey) ?? speciesKey) ?? SPECIES.get(TARGETS[target]?.source_species[0] ?? '');
  return {
    species_key: speciesKey, target, region,
    rig: publicOnly(p.rig),
    bait_or_lure: publicOnly(variant?.presentation ?? m.presentation),
    line: publicOnly(sentence(p.rig, /\b(?:line|braid|mono|fluoro|leader)\b/i)),
    weight: publicOnly(sentence(p.rig, /\b(?:weight|sinker|ounce|oz)\b/i) ?? sentence(p.adjust, /\b(?:weight|sinker)\b/i)),
    depth_band_ft: lo !== null && hi !== null ? [lo, hi] : null,
    depth_note: publicOnly(depthOf?.depth_strategy),
    season_note: publicOnly(m.timing),
    how: [p.priority, ...(p.steps ?? []).slice(0, 3), variant?.focus].map(publicOnly).filter((s): s is string => Boolean(s)),
    areas,
    general_area: publicOnly(m.search_for ?? m.habitat),
    source_notes: [m.tactics_basis, ...(p.method_sources ?? []).map(s => `${s.title}: ${s.url}`)].map(publicOnly).filter((s): s is string => Boolean(s)).slice(0, 3),
  };
}
