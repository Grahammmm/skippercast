// Names to ids for the data tools: the model may pass a species or port in the
// person's words. TA-A0 needs only species keys and the contact's region;
// TA-E2 adds the alias and synonym tables (catalog/advisor/port-aliases.json,
// species-synonyms.json).
import {ALL_SPECIES_KEYS, canonicalSpecies} from '../vision/species.ts';
import {portRegion} from '../links.ts';
import type {AdvisorContactRow, AdvisorSettings} from '../types.ts';

/** The region for a contact: its home port's, else ADVISOR_REGION_DEFAULT. */
export const contactRegion = (contact: Pick<AdvisorContactRow, 'home_port'>, settings: Pick<AdvisorSettings, 'regionDefault'>): string =>
  portRegion(contact.home_port) ?? settings.regionDefault;

/** A species key from a key or name the model passed, or null. */
export function resolveSpecies(text: string | null | undefined): {key: string} | null {
  const raw = String(text ?? '').trim().toLowerCase().replace(/\s+/g, '-');
  if (!raw) return null;
  const key = canonicalSpecies(raw);
  return ALL_SPECIES_KEYS.has(key) ? {key} : null;
}
