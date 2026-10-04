// get_species (docs/plans/text-advisor/04-advisor-engine.md § Tools, 06 § fish ID
// step 4): what the catalogs say about a species: catalog/species.json claims
// (each with its source and confidence), its depth note, look-alikes with their
// cues from catalog/advisor/lookalikes.json, and the release note from
// catalog/advisor/protected.json. A sub-species (vermilion) gets its parent
// group's claims. No rule, no catch claim: rules come only from get_rules.
import type {AdvisorTool} from './tool.ts';
import catalog from '../../../catalog/species.json' with {type: 'json'};
import extra from '../../../catalog/advisor/species-extra.json' with {type: 'json'};
import lookalikes from '../../../catalog/advisor/lookalikes.json' with {type: 'json'};
import {PROTECTED, canonicalSpecies} from '../vision/species.ts';
import {resolveSpecies} from '../answers/resolve.ts';

interface Claim {claim: string; source_url: string; confidence?: string}
interface CatalogSpecies {id: string; name: string; scientific_name?: string; claims?: Claim[]; depth_strategy?: string}
interface Extra {key: string; name: string; scientific_name?: string; parent: string | null}
const SPECIES = new Map((catalog.species as CatalogSpecies[]).map(s => [s.id, s] as const));
const EXTRA = new Map((extra.species as Extra[]).map(e => [e.key, e] as const));
const CUES = lookalikes.species as Record<string, {cues: string[]; lookalikes: string[]; source: string}>;
const nameOf = (key: string): string => SPECIES.get(key)?.name ?? EXTRA.get(key)?.name ?? key;

/** Cues for a key, or for a synonym that shares it (halibut uses california-halibut's). */
function cuesFor(key: string): {cues: string[]; lookalikes: string[]; source: string} | null {
  if (CUES[key]) return CUES[key]!;
  const synonym = Object.keys(CUES).find(k => canonicalSpecies(k) === key);
  return synonym ? CUES[synonym]! : null;
}

export const getSpecies: AdvisorTool = {
  name: 'get_species',
  description: "What SkipperCast knows about a species: habitat, depth, season notes and look-alikes with how to tell them apart.",
  input_schema: {type: 'object', additionalProperties: false, required: ['species_key'], properties: {species_key: {type: 'string'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'species',
  async run(input) {
    const key = resolveSpecies(String(input.species_key ?? ''))?.key;
    if (!key) return {result: {error: 'unknown species', asked: String(input.species_key ?? '').slice(0, 40)}};
    const own = SPECIES.get(key), parentKey = EXTRA.get(key)?.parent ?? null, parent = parentKey ? SPECIES.get(parentKey) : undefined;
    const source = own ?? parent;
    const cue = cuesFor(key);
    const prot = PROTECTED.find(p => p.key === key);
    return {result: {
      species_key: key, name: nameOf(key), scientific_name: own?.scientific_name ?? EXTRA.get(key)?.scientific_name ?? null,
      group: parentKey && parentKey !== key ? {species_key: parentKey, name: nameOf(parentKey)} : null,
      claims: (source?.claims ?? []).slice(0, 3).map(c => ({claim: c.claim, source: c.source_url, confidence: c.confidence ?? null, about: source === own ? key : parentKey})),
      depth_note: source?.depth_strategy ?? null,
      identify: cue ? {cues: cue.cues, source: cue.source} : null,
      lookalikes: (cue?.lookalikes ?? []).map(canonicalSpecies).filter(k => k !== key).map(k => ({species_key: k, name: nameOf(k), cues: cuesFor(k)?.cues ?? []})),
      protected: prot ? {must_release: prot.must_release, note: prot.note, source: prot.source} : null,
      rules: 'Not here: call get_rules for size, bag and season.',
      link: `{{link:species:${key}}}`,
    }};
  },
};
