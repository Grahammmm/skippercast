// MYB-1: the optional boat length and comfort limits asked once, on first
// use. SC-LANDING-ORDER: they are asked after "How do you fish?", and only
// when the answer is Boat (web/app/FirstRun.tsx BoatEntry): the map's card
// asks it at once, and the landing's profile step (web/landing/ProfileStep.tsx)
// opens the map asking it (carryAsk). Saving writes what was typed, on this
// device (the boat under dist/boat-handling.js BOAT_KEY, the limits through
// web/limits.ts). Blank fields change nothing, and a storage failure is said,
// never thrown. There is no account-side boat store yet, so a signed-in
// visitor's boat is kept the same way.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {signal} from '@preact/signals';
import {BOAT_KEY, normalizeBoat} from '../dist/boat-handling.js';
import {loadLimits, limitsFor, saveLimits, savedLimits} from './limits.ts';
import {num, t, type Language} from './i18n.ts';
import type {Profile} from './profile.ts';
import {readStored, STORAGE_KEYS, type StoreStorage} from './state.ts';

/** The optional-field copy in `lang` (SC0707-06: catalogue values; English by default). */
export const entryCopy = (lang: Language = 'en') => ({
  legend: t('boatEntry.legend', lang),
  line: t('boatEntry.line', lang),
  length: t('boatEntry.length', lang),
  lengthHint: t('boatEntry.lengthHint', lang),
  wind: t('boatEntry.wind', lang),
  seas: t('boatEntry.seas', lang),
  limitsHint: t('boatEntry.limitsHint', lang),
  failed: t('boatEntry.failed', lang),
}) as const;

/** The three optional fields, by input name, in the order both screens show them, labelled in `lang`. */
export const entryFields = (lang: Language = 'en') => {
  const copy = entryCopy(lang);
  return [['lengthFt', copy.length], ['wind', copy.wind], ['seas', copy.seas]] as const;
};

/** English-compatible values for existing imports and tests. */
export const ENTRY_COPY = entryCopy('en');
export const ENTRY_FIELDS = entryFields('en');

export type FirstUseEntry = {lengthFt?: string; wind?: string; seas?: string; profile: Profile};
export type FirstUseResult = {boat: boolean; notices: string[]};

type Boat = Record<string, unknown> & {loa_ft: number | null; name: string};
const normalize = normalizeBoat as (input: Record<string, unknown>) => Boat;
const blank = (value: unknown): boolean => value === undefined || value === null || String(value).trim() === '';
const autoName = (name: unknown): boolean => typeof name === 'string' && /^\d+(\.\d+)? ft boat$/.test(name);

export function browserStorage(): StoreStorage | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage; } catch { return null; }
}

/** Save the length (8-70 ft, else nothing) into the stored boat, keeping its other fields. Throws when storage fails. */
function saveLength(value: string, storage: StoreStorage | null): boolean {
  const loa = normalize({loa_ft: value.trim()}).loa_ft;
  if (loa === null) return false;
  if (!storage) throw new Error('no storage');
  const name = `${loa} ft boat`;
  let saved: {boat: Record<string, unknown>} | null = null;
  // A failed read must not look like an empty store: let it throw, so the saved boat is never overwritten.
  const raw = storage.getItem(BOAT_KEY);
  // Only a genuinely empty key gets defaults. Any other value that is not a readable v1 boat (malformed JSON, a
  // newer schema) is left byte for byte as it is: throw, so the caller says the boat was not saved (F13-07).
  if (raw !== null && raw.trim() !== '') {
    let stored: {schema_version?: unknown; boat?: unknown} | null;
    try { stored = JSON.parse(raw); } catch { throw new Error('unreadable saved boat'); }
    // The envelope and its boat must both be plain records: an array is typeof 'object' but is not a boat.
    const record = (value: unknown): boolean => typeof value === 'object' && value !== null && !Array.isArray(value);
    if (!record(stored) || stored!.schema_version !== 1 || !record(stored!.boat)) throw new Error('unreadable saved boat');
    saved = stored as {boat: Record<string, unknown>};
  }
  const next = saved
    ? {...saved, boat: {...saved.boat, loa_ft: loa, ...(autoName(saved.boat.name) ? {name} : {})}}
    : {schema_version: 1, boat: normalize({name, loa_ft: loa}), query: '', preset: null, saved_at: new Date().toISOString(), lookup: null};
  storage.setItem(BOAT_KEY, JSON.stringify(next));
  return true;
}

/** Bumped when the first-use step writes a boat, so a verdict already on screen re-rates for it without a reload (web/brief/Brief.tsx currentVerdict). */
export const boatSaved = signal(0);

/**
 * Save what the first-use boat fields hold, for the profile just chosen.
 * Returns whether a boat was written and one-line notices (a limit that was
 * clamped, or a storage failure). Never throws.
 */
export function saveFirstUse(entry: FirstUseEntry, storage: StoreStorage | null = browserStorage(), lang: Language = 'en'): FirstUseResult {
  const notices: string[] = [];
  let boat = false, failed = false;
  if (!blank(entry.lengthFt)) {
    try { boat = saveLength(String(entry.lengthFt), storage); } catch { failed = true; }
    if (boat) boatSaved.value++;
  }
  if (!blank(entry.wind) || !blank(entry.seas)) {
    try {
      loadLimits();
      const typed: {wind?: string; seas?: string} = {};
      if (!blank(entry.wind)) typed.wind = String(entry.wind);
      if (!blank(entry.seas)) typed.seas = String(entry.seas);
      const saved = saveLimits(entry.profile, {...limitsFor(entry.profile), ...typed});
      // writeStored swallows a failed write: read it back to tell.
      if (readStored(STORAGE_KEYS.limits) !== JSON.stringify(savedLimits.peek())) failed = true;
      for (const field of ['wind', 'seas'] as const) {
        const raw = typed[field];
        if (raw !== undefined && Number(raw) !== saved[field]) notices.push(t(field === 'wind' ? 'boatEntry.windSaved' : 'boatEntry.seasSaved', lang, {n: num(saved[field], lang)}));
      }
    } catch { failed = true; }
  }
  if (failed) notices.push(t('boatEntry.failed', lang));
  return {boat, notices};
}

export {ASK_KEY, ASK_PARAM, browserSession, carryAsk, takeAsk, withoutAsk, type AskStorage} from './boat-ask.ts';
