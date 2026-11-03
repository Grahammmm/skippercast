// MYB-1: the optional boat length and comfort limits asked once, inside the
// first-use "How do you fish?" step (web/landing/ProfileStep.tsx and
// web/app/FirstRun.tsx). Choosing a profile still finishes the step; this
// only saves what was typed first, on this device (the boat under
// dist/boat-handling.js BOAT_KEY, the limits through web/limits.ts). Blank
// fields change nothing, and a storage failure never blocks the choice.
// There is no account-side boat store yet, so a signed-in visitor's boat is
// kept the same way.
//
// Erasable syntax only: Node tests import this file by type stripping.
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

/**
 * Save what the first-use step's boat fields hold, before the profile choice
 * proceeds. Returns whether a boat was written and one-line notices (a limit
 * that was clamped, or a storage failure). Never throws.
 */
export function saveFirstUse(entry: FirstUseEntry, storage: StoreStorage | null = browserStorage()): FirstUseResult {
  const notices: string[] = [];
  let boat = false, failed = false;
  if (!blank(entry.lengthFt)) {
    try { boat = saveLength(String(entry.lengthFt), storage); } catch { failed = true; }
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

// The step closes (map) or the page navigates (landing) as soon as a profile
// is chosen, so the notices are shown after it, by the map's FirstRun: the
// landing carries them to /map in session storage, or — when storage is
// refused there too — as ?boat-notice=failed, which names only the fixed
// failure line (an address never supplies notice text).
export const NOTICE_KEY = 'skippercast-first-use-notice';
export const NOTICE_PARAM = 'boat-notice';
export type NoticeStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function browserSession(): NoticeStorage | null {
  try { return typeof sessionStorage === 'undefined' ? null : sessionStorage; } catch { return null; }
}

/** `url` carrying `notices` to the page it opens. Never throws. */
export function carryNotices(url: string, notices: readonly string[], session: NoticeStorage | null = browserSession()): string {
  if (!notices.length) return url;
  try {
    if (!session) throw new Error('no session storage');
    session.setItem(NOTICE_KEY, JSON.stringify(notices));
    return url;
  } catch {
    const next = new URL(url);
    next.searchParams.set(NOTICE_PARAM, 'failed');
    return next.href;
  }
}

/** The notices carried to `href`, read once (the stored copy is removed). Never throws. */
export function takeNotices(href: string, session: NoticeStorage | null = browserSession()): string[] {
  const held: string[] = [];
  try {
    const raw = session?.getItem(NOTICE_KEY);
    if (raw) {
      session!.removeItem(NOTICE_KEY);
      const list: unknown = JSON.parse(raw);
      if (Array.isArray(list)) for (const item of list.slice(0, 4)) if (typeof item === 'string') held.push(item);
    }
  } catch { /* nothing carried */ }
  try {
    if (new URL(href).searchParams.get(NOTICE_PARAM) === 'failed' && !held.includes(ENTRY_COPY.failed)) held.push(ENTRY_COPY.failed);
  } catch { /* not a URL */ }
  return held;
}

/** `href` without the carried-notice parameter, so a reload or a shared link does not repeat it. */
export function withoutNotice(href: string): string {
  const url = new URL(href);
  url.searchParams.delete(NOTICE_PARAM);
  return url.href;
}
