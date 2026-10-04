// Names to ids for the data tools (06 § what's biting portForQuestion, 05 §
// registration and counts): the model may pass a species or port in the
// person's words ("lings", "Avila", "mañana"), so every data tool resolves its
// input here. Ports: a catalog/home-ports.json id or name, then
// catalog/advisor/port-aliases.json; species: a catalog or species-extra key or
// name, then catalog/advisor/species-synonyms.json. Matching is whole-word,
// case- and accent-insensitive, longest phrase first.
import ports from '../../../catalog/home-ports.json' with {type: 'json'};
import aliases from '../../../catalog/advisor/port-aliases.json' with {type: 'json'};
import synonyms from '../../../catalog/advisor/species-synonyms.json' with {type: 'json'};
import catalog from '../../../catalog/species.json' with {type: 'json'};
import extra from '../../../catalog/advisor/species-extra.json' with {type: 'json'};
import {ALL_SPECIES_KEYS, canonicalSpecies} from '../vision/species.ts';
import {portRegion} from '../links.ts';
import type {AdvisorContactRow, AdvisorSettings} from '../types.ts';

/** Lower case, accents removed, punctuation to spaces, single-spaced. */
export const fold = (text: string | null | undefined): string => String(text ?? '').normalize('NFD').replace(/\p{M}+/gu, '').toLowerCase()
  .replace(/[^a-z0-9]+/g, ' ').trim();

type Table = [phrase: string, id: string][];
/** Longest phrase first, so "pacific halibut" beats "halibut" and "port san luis" beats "san luis". */
const sorted = (rows: Table): Table => rows.filter(([p]) => p).sort((a, b) => b[0].length - a[0].length || a[0].localeCompare(b[0]));
const find = (table: Table, text: string): string | null => {
  const hay = ` ${fold(text)} `;
  for (const [phrase, id] of table) if (hay.includes(` ${phrase} `)) return id;
  return null;
};

const PORT_ALIASES = aliases.ports as Record<string, {aliases: string[]; landing_names: string[]}>;
const PORT_TABLE: Table = sorted([
  ...ports.ports.flatMap(p => [[fold(p.id), p.id], [fold(p.name), p.id], ...p.name.split('·').map(part => [fold(part), p.id])] as Table),
  ...Object.entries(PORT_ALIASES).flatMap(([id, a]) => a.aliases.map(x => [fold(x), id]) as Table),
]);
/** The landing-report port names (dist/bite-evidence.js reports[].port) for a port id. */
export const landingNames = (port: string): string[] => PORT_ALIASES[port]?.landing_names ?? [];

const SPECIES_TABLE: Table = sorted([
  ...catalog.species.flatMap(s => [[fold(s.id), s.id], [fold(s.name), s.id]] as Table),
  ...(extra.species as {key: string; name: string}[]).flatMap(e => [[fold(e.key), canonicalSpecies(e.key)], [fold(e.name), canonicalSpecies(e.key)]] as Table),
  ...Object.entries(synonyms.species as Record<string, {en: string[]; es: string[]}>).flatMap(([id, s]) => [...s.en, ...s.es].map(w => [fold(w), id]) as Table),
]);

/** The region for a contact: its home port's, else ADVISOR_REGION_DEFAULT. */
export const contactRegion = (contact: Pick<AdvisorContactRow, 'home_port'>, settings: Pick<AdvisorSettings, 'regionDefault'>): string =>
  portRegion(contact.home_port) ?? settings.regionDefault;

/** A port id named in `text` (an id, catalog name or alias), or null. */
export function findPort(text: string | null | undefined): string | null { return find(PORT_TABLE, String(text ?? '')); }

/**
 * The port a question is about (06 portForQuestion): one named in the text,
 * else the contact's home port, else the first port of ADVISOR_REGION_DEFAULT.
 * `from` says which.
 */
export function resolvePort(text: string | null | undefined, contact: Pick<AdvisorContactRow, 'home_port'> | null, settings?: Pick<AdvisorSettings, 'regionDefault'>): {port: string; from: 'text' | 'home_port' | 'default'} | null {
  const named = findPort(text);
  if (named) return {port: named, from: 'text'};
  if (contact?.home_port && portRegion(contact.home_port)) return {port: contact.home_port, from: 'home_port'};
  const region = settings?.regionDefault;
  const first = region ? ports.ports.find(p => p.region === region)?.id : null;
  return first ? {port: first, from: 'default'} : null;
}

/** A species key from a key, name or local word ("lings", "reds", "cabbies", "lenguado"), or null. */
export function resolveSpecies(text: string | null | undefined): {key: string} | null {
  const raw = String(text ?? '').trim().toLowerCase();
  if (!raw) return null;
  const direct = canonicalSpecies(raw.replace(/\s+/g, '-'));
  if (ALL_SPECIES_KEYS.has(direct)) return {key: direct};
  const found = find(SPECIES_TABLE, raw);
  return found ? {key: found} : null;
}

/**
 * TA-I2: a species key only when the whole text is a species word ("lings",
 * "vermilion rockfish", "colorados"), never a word inside a longer phrase, so a
 * correction like "lings 14" matches and "any reds over 5" does not.
 */
export function exactSpecies(text: string | null | undefined): {key: string} | null {
  const folded = fold(text);
  if (!folded) return null;
  const direct = canonicalSpecies(folded.replace(/ /g, '-'));
  if (ALL_SPECIES_KEYS.has(direct)) return {key: direct};
  for (const [phrase, id] of SPECIES_TABLE) if (phrase === folded) return {key: id};
  return null;
}
