// App state store (P4-01b): signals for the place, target, time and selection,
// with the URL as the source of truth for region, coast, view, target and hour.
//
// Plain TypeScript with erasable syntax only, so the Node tests can import it
// (through the dist/*.js modules that use it) by type stripping.
//
// Region changes and reloads. The app's modules still read the region once at
// start (region.js, app.js and everything they load), so once boot.js has
// loaded them (lockRegion()), a change of region or coast is a full page load.
// Before that, and for any change that keeps the region (a port in the same
// region, a map view, a target, an hour), navigate() updates the URL with the
// History API and the signals, and nothing reloads. That decision lives here
// only: when a module learns to follow region changes, lift it here.
import {batch, signal} from '@preact/signals';

/** URL parameters the store owns. `target` is the species/target id. */
export const URL_KEYS = ['region', 'coast', 'view', 'target', 'hour'] as const;
export type UrlKey = typeof URL_KEYS[number];
export type UrlState = Record<UrlKey, string | null> & {selection: string | null};
export type Units = 'nautical';

export const region = signal<string | null>(null);
export const coast = signal<string | null>(null);
/** Map view "latitude,longitude,zoom" as written in ?view=. */
export const view = signal<string | null>(null);
export const species = signal<string | null>(null);
/** Selected forecast hour, ISO UTC ("2026-09-30T15:00Z"); null means now. */
export const hour = signal<string | null>(null);
/** The spot a shared link points at (?spot= or ?focus=). */
export const selection = signal<string | null>(null);
/** Knots, feet and nautical miles: the app's only unit system today. */
export const units = signal<Units>('nautical');

let locked: {region: string | null; coast: string | null} | null = null;

/** The store's parameters in `href`. */
export function readURL(href: string): UrlState {
  const params = new URL(href).searchParams;
  return {
    region: params.get('region'), coast: params.get('coast'), view: params.get('view'),
    target: params.get('target'), hour: params.get('hour'),
    selection: params.get('spot') || params.get('focus'),
  };
}

/** `href` with `patch` applied: a string sets a parameter, null removes it. */
export function withParams(href: string, patch: Partial<Record<UrlKey, string | null>>): string {
  const url = new URL(href);
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) continue;
    if (value === null || value === '') url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  }
  return url.href;
}

/** Set the signals from `href` (default: the current address). */
export function syncFromURL(href: string = location.href): UrlState {
  const state = readURL(href);
  batch(() => {
    region.value = state.region; coast.value = state.coast; view.value = state.view;
    species.value = state.target; hour.value = state.hour; selection.value = state.selection;
  });
  return state;
}

/** Called by boot.js once region-bound modules load; region changes reload after this. */
export function lockRegion(href: string = location.href): void {
  const {region: r, coast: c} = readURL(href);
  locked = {region: r, coast: c};
}
export const regionLocked = (): boolean => locked !== null;

/** Whether moving from `from` to `to` needs a full page load. */
export function needsReload(from: string, to: string, lock = locked): boolean {
  if (!lock) return false;
  const a = new URL(from), b = new URL(to);
  if (a.origin !== b.origin || a.pathname !== b.pathname) return true;
  const next = readURL(to);
  return next.region !== lock.region || next.coast !== lock.coast;
}

export type Navigation = 'in-place' | 'reload';

/**
 * Go to `href`. Reloads when the region or coast changes after lockRegion();
 * otherwise updates history (push, or replace with {replace: true}) and the
 * signals, and fires hashchange when the hash changes, as a load would show
 * that view.
 */
export function navigate(href: string | URL, {replace = false}: {replace?: boolean} = {}): Navigation {
  const next = new URL(String(href), location.href).href;
  const previous = location.href;
  if (needsReload(previous, next)) {
    if (replace) location.replace(next); else location.assign(next);
    return 'reload';
  }
  if (replace) history.replaceState(history.state, '', next); else history.pushState(null, '', next);
  // Show the new view first, so a map that was hidden has its size before it moves.
  if (new URL(previous).hash !== new URL(next).hash) dispatchEvent(new HashChangeEvent('hashchange', {oldURL: previous, newURL: next}));
  syncFromURL(next);
  return 'in-place';
}

/** Replace store parameters in the current address without a history entry. */
export function setParams(patch: Partial<Record<UrlKey, string | null>>): Navigation {
  return navigate(withParams(location.href, patch), {replace: true});
}

let started = false;
/** Read the address now and follow Back/Forward (reloading if the region changed). */
export function startURLSync(): void {
  if (started || typeof window === 'undefined') return;
  started = true;
  syncFromURL();
  addEventListener('popstate', () => {
    const state = readURL(location.href);
    if (locked && (state.region !== locked.region || state.coast !== locked.coast)) { location.reload(); return; }
    syncFromURL();
  });
}

/** "2026-09-30T15:00Z" for an epoch in seconds; null for an invalid time. */
export function hourParam(epochSeconds: number): string | null {
  if (!Number.isFinite(epochSeconds)) return null;
  return new Date(Math.floor(epochSeconds / 3600) * 3600 * 1000).toISOString().slice(0, 16) + 'Z';
}

/** Epoch seconds of an ?hour= value, or null when it is not a whole UTC hour. */
export function parseHour(value: string | null): number | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}T\d{2}:00Z$/.test(value)) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms / 1000 : null;
}
