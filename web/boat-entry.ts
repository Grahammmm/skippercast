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
import type {Profile} from './profile.ts';
import {readStored, STORAGE_KEYS, type StoreStorage} from './state.ts';

export const ENTRY_COPY = {
  legend: 'Your boat (optional)',
  line: 'Boat length makes every rating yours; the rest can wait.',
  length: 'Boat length (ft)',
  lengthHint: 'Boat length 8-70 ft',
  wind: 'Wind limit (kt)',
  seas: 'Seas limit (ft)',
  limitsHint: 'Blank keeps the default',
  failed: 'Could not save the boat in this browser.',
} as const;

/** The three optional fields, by input name, in the order both screens show them. */
export const ENTRY_FIELDS = [['lengthFt', ENTRY_COPY.length], ['wind', ENTRY_COPY.wind], ['seas', ENTRY_COPY.seas]] as const;

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
  try {
    const stored = JSON.parse(storage.getItem(BOAT_KEY) || 'null');
    if (stored && stored.schema_version === 1 && stored.boat && typeof stored.boat === 'object') saved = stored;
  } catch { saved = null; }
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
export function saveFirstUse(entry: FirstUseEntry, storage: StoreStorage | null = browserStorage()): FirstUseResult {
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
        if (raw !== undefined && Number(raw) !== saved[field]) notices.push(`${field === 'wind' ? 'Wind' : 'Seas'} limit saved as ${saved[field]} ${field === 'wind' ? 'kt' : 'ft'}.`);
      }
    } catch { failed = true; }
  }
  if (failed) notices.push(ENTRY_COPY.failed);
  return {boat, notices};
}

// The landing navigates as soon as a profile is chosen, so a Boat choice there
// asks for the boat on the map it opens, by the map's FirstRun: the landing
// marks it in session storage, or — when storage is refused — as
// ?boat-entry=ask, which the map reads once and drops from the address. The
// save's notices are then said on the map, where the boat is saved.
export const ASK_KEY = 'skippercast-first-use-boat';
export const ASK_PARAM = 'boat-entry';
export type AskStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function browserSession(): AskStorage | null {
  try { return typeof sessionStorage === 'undefined' ? null : sessionStorage; } catch { return null; }
}

/** `url` asking the page it opens for the boat. Never throws. */
export function carryAsk(url: string, session: AskStorage | null = browserSession()): string {
  try {
    if (!session) throw new Error('no session storage');
    session.setItem(ASK_KEY, 'ask');
    return url;
  } catch {
    const next = new URL(url);
    next.searchParams.set(ASK_PARAM, 'ask');
    return next.href;
  }
}

/** Whether `href` was opened asking for the boat, read once (the stored mark is removed). Never throws. */
export function takeAsk(href: string, session: AskStorage | null = browserSession()): boolean {
  let ask = false;
  try {
    if (session?.getItem(ASK_KEY)) { session.removeItem(ASK_KEY); ask = true; }
  } catch { /* nothing carried */ }
  try {
    if (new URL(href).searchParams.get(ASK_PARAM) === 'ask') ask = true;
  } catch { /* not a URL */ }
  return ask;
}

/** `href` without the carried ask, so a reload or a shared link does not repeat it. */
export function withoutAsk(href: string): string {
  const url = new URL(href);
  url.searchParams.delete(ASK_PARAM);
  return url.href;
}
