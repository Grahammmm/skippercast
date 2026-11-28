// Fishing-friend species knowledge base v1 (issue #3845, slice 2): reads the reviewed
// catalog/advisor/species-kb.json, where every fact names its source and an unknown stays
// null. Pure lookups for the later WHERE/WHEN slices; nothing on the reply path uses it yet.
import kb from '../../../catalog/advisor/species-kb.json' with {type: 'json'};

export type SourceKind = 'agency' | 'literature' | 'global-check';
export interface Fact<T = unknown> {value: T; unit: string; source_url: string; source_kind: SourceKind; checked_at: string}
export type Facts = Record<string, Fact | null>;
export interface Member {key: string; cdfw_row: string; regulations_ref: string; facts: Facts}
export interface SpeciesRecord {id: string; cdfw_row: string | null; regulations_ref: string; facts: Facts; members: Member[]}
export interface KbRecord {key: string; group: string | null; cdfw_row: string | null; regulations_ref: string; facts: Facts}

export const FEET_TO_M = 0.3048;
export const SPECIES_KB = kb as unknown as {schema_version: number; species: SpeciesRecord[]};

const BY_KEY = new Map<string, KbRecord>();
for (const s of SPECIES_KB.species) {
  BY_KEY.set(s.id, {key: s.id, group: null, cdfw_row: s.cdfw_row, regulations_ref: s.regulations_ref, facts: s.facts});
  for (const m of s.members) BY_KEY.set(m.key, {key: m.key, group: s.id, cdfw_row: m.cdfw_row, regulations_ref: m.regulations_ref, facts: m.facts});
}

/** The record for a species, a group (rockfish) or a group member (vermilion); null when the KB does not know it. */
export function kbFor(key: string): KbRecord | null {
  return BY_KEY.get(String(key ?? '').toLowerCase()) ?? null;
}

/** The cited primary depth range in metres ({min, max} rounded to 0.1 m), or null when no source gives one. */
export function depthBandM(key: string): {min: number; max: number; source_url: string} | null {
  const fact = kbFor(key)?.facts.primary_depth as Fact<[number, number]> | null | undefined;
  if (!fact) return null;
  const factor = fact.unit === 'ft' ? FEET_TO_M : fact.unit === 'm' ? 1 : null;
  if (factor === null) throw new Error(`species-kb: ${key} primary_depth has unknown unit ${fact.unit}`);
  const m = (v: number) => Math.round(v * factor * 10) / 10;
  return {min: m(fact.value[0]), max: m(fact.value[1]), source_url: fact.source_url};
}
