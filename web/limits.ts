// Your own limits (issue #542): comfort limits per profile, kept on this
// device only (localStorage, STORAGE_KEYS.limits) and never sent. The model,
// defaults, bounds and clamping are packages/coast/src/limits.ts; the brief
// passes the active profile's limits to buildDaily. Separate from the
// signed-in preferences (server/preferences.ts) on purpose.
//
// When storage fails (private mode, quota, blocked) the limits still hold for
// the page's life in the signal, and a fresh page starts from the defaults.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {signal} from '@preact/signals';
import {clampLimits, defaultLimits, sameLimits, type ComfortLimits} from '../packages/coast/src/limits.ts';
import {PROFILES, type Profile} from './profile.ts';
import {readStored, STORAGE_KEYS, writeStored} from './state.ts';

export type {ComfortLimits};
export type SavedLimits = Partial<Record<Profile, ComfortLimits>>;

/** The user's saved limits by profile; a profile missing here uses its defaults. */
export const savedLimits = signal<SavedLimits>({});

/** Parse stored JSON: each listed profile's limits clamped, anything else dropped. */
export function parseLimits(raw: string | null): SavedLimits {
  if (!raw) return {};
  let json: unknown;
  try { json = JSON.parse(raw); } catch { return {}; }
  if (!json || typeof json !== 'object' || Array.isArray(json)) return {};
  const out: SavedLimits = {};
  for (const p of PROFILES) {
    const value = (json as Record<string, unknown>)[p];
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const limits = clampLimits(p, value as Record<string, unknown>);
      if (!sameLimits(p, limits, defaultLimits(p))) out[p] = limits;
    }
  }
  return out;
}

/** Load the saved limits from storage into the signal. */
export function loadLimits(): SavedLimits {
  savedLimits.value = parseLimits(readStored(STORAGE_KEYS.limits));
  return savedLimits.peek();
}

/** The limits `profile` uses: the saved ones, else the defaults. */
export function limitsFor(profile: Profile, saved: SavedLimits = savedLimits.value): ComfortLimits {
  return saved[profile] ?? defaultLimits(profile);
}

/** Whether `profile` uses limits of the user's own. */
export const hasOwnLimits = (profile: Profile, saved: SavedLimits = savedLimits.value): boolean => !!saved[profile];

function persist(next: SavedLimits): void {
  savedLimits.value = next;
  writeStored(STORAGE_KEYS.limits, JSON.stringify(next));
}

/** Save `limits` for `profile`, clamped; limits equal to the defaults clear the entry. Returns what was saved. */
export function saveLimits(profile: Profile, limits: Partial<Record<keyof ComfortLimits, unknown>>): ComfortLimits {
  const clamped = clampLimits(profile, limits);
  const next: SavedLimits = {...savedLimits.peek()};
  if (sameLimits(profile, clamped, defaultLimits(profile))) delete next[profile];
  else next[profile] = clamped;
  persist(next);
  return clamped;
}

/** Back to the defaults for `profile`. */
export function resetLimits(profile: Profile): void {
  const next: SavedLimits = {...savedLimits.peek()};
  delete next[profile];
  persist(next);
}
