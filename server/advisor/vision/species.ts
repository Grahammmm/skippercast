// The species the fish-ID step may name (docs/plans/text-advisor/07-vision.md
// § Claude provider and § EXIF and derived images): catalog/species.json keys
// plus catalog/advisor/species-extra.json keys, narrowed to a region's targets
// (regions/<id>/region.json `species`, expanded through catalog/targets.json),
// each with its look-alike cues from catalog/advisor/lookalikes.json. Pure: the
// JSON is bundled at build time, nothing is fetched.
import catalog from '../../../catalog/species.json' with {type: 'json'};
import targets from '../../../catalog/targets.json' with {type: 'json'};
import extra from '../../../catalog/advisor/species-extra.json' with {type: 'json'};
import lookalikes from '../../../catalog/advisor/lookalikes.json' with {type: 'json'};
import protectedList from '../../../catalog/advisor/protected.json' with {type: 'json'};

export interface VisionSpecies {key: string; name: string; cues: string[]; lookalikes: string[]}
export interface ProtectedSpecies {key: string; must_release: boolean; note: string; source: string}

interface ExtraEntry {key: string; name: string; parent: string | null; target?: string; same_as_parent?: boolean}
interface LookalikeEntry {cues: string[]; cues_es?: string[]; lookalikes: string[]; source: string}

const EXTRA = extra.species as ExtraEntry[];
const CUES = lookalikes.species as Record<string, LookalikeEntry>;
const TARGETS = targets.targets as Record<string, {source_species: string[]}>;
const CATALOG = new Map(catalog.species.map(s => [s.id, s.name] as const));

/** A synonym key (same_as_parent) -> its catalog key, e.g. california-halibut -> halibut. */
const SYNONYMS = new Map(EXTRA.filter(e => e.same_as_parent && e.parent).map(e => [e.key, e.parent!] as const));

/** The catalog key for a synonym, the key itself otherwise. */
export const canonicalSpecies = (key: string): string => SYNONYMS.get(key) ?? key;

/** Every key the advisor recognises (catalog and extra, synonyms canonicalised away). */
export const ALL_SPECIES_KEYS: ReadonlySet<string> = new Set([...CATALOG.keys(), ...EXTRA.filter(e => !e.same_as_parent).map(e => e.key)]);

export const PROTECTED: readonly ProtectedSpecies[] = Object.freeze(protectedList.species.map(p => ({...p})));

/** Cues for a key, falling back to a synonym's entry (halibut uses california-halibut's). */
function cuesFor(key: string): LookalikeEntry | null {
  if (CUES[key]) return CUES[key]!;
  for (const [synonym, parent] of SYNONYMS) if (parent === key && CUES[synonym]) return CUES[synonym]!;
  return null;
}

function entry(key: string): VisionSpecies {
  const name = CATALOG.get(key) ?? EXTRA.find(e => e.key === key)?.name ?? key;
  const cues = cuesFor(key);
  return {key, name, cues: cues ? [...cues.cues] : [], lookalikes: cues ? cues.lookalikes.map(canonicalSpecies).filter(k => k !== key) : []};
}

/**
 * The species list for a region's targets (region.json `species`), in a
 * stable order: catalog keys first, then their sub-species and groups. With no
 * targets (an unknown region), every key the advisor recognises.
 */
export function speciesForTargets(regionTargets: readonly string[] | null | undefined): VisionSpecies[] {
  const keys: string[] = [];
  const add = (k: string) => { if (!keys.includes(k)) keys.push(k); };
  if (!regionTargets || !regionTargets.length) {
    for (const k of ALL_SPECIES_KEYS) add(k);
  } else {
    const base = new Set<string>();
    for (const t of regionTargets) for (const s of TARGETS[t]?.source_species ?? (CATALOG.has(t) ? [t] : [])) base.add(s);
    for (const k of base) add(k);
    for (const e of EXTRA) if (!e.same_as_parent && ((e.parent && base.has(e.parent)) || (e.target && regionTargets.includes(e.target)))) add(e.key);
  }
  return keys.map(entry);
}

/**
 * TA-I2: the catalog key a report line is filed under (05 § count board: "reds"/
 * "vermilion" -> rockfish, the skipper's label kept): a species-extra key's
 * catalog parent, the key itself otherwise (cabezon and kelp greenling have no
 * catalog parent and stay as they are).
 */
export function reportSpeciesKey(key: string): string {
  const k = canonicalSpecies(key);
  return EXTRA.find(e => e.key === k && !e.same_as_parent)?.parent ?? k;
}

/** TA-I3: the display name of a species key (catalog or species-extra), or null. */
export function speciesName(key: string | null | undefined): string | null {
  if (!key) return null;
  const k = canonicalSpecies(key);
  return CATALOG.get(k) ?? EXTRA.find(e => e.key === k)?.name ?? null;
}

/**
 * TA-I3: the look-alike cues (catalog/advisor/lookalikes.json) of a species key, [] when it has none.
 * TA-A6: 'es' gives the Spanish cues (`cues_es`, same order as the English), [] when a species has none.
 */
export const speciesCues = (key: string | null | undefined, language: 'en' | 'es' = 'en'): string[] => {
  const entry = key ? cuesFor(canonicalSpecies(key)) : null;
  if (!entry) return [];
  return [...(language === 'es' ? (entry.cues_es?.length === entry.cues.length ? entry.cues_es : []) : entry.cues)];
};
