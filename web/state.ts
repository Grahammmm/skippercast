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
//
// State v2 (FE-04, design § 8) adds profile, day, layers, area and base. The
// URL still wins; profile, layers and base also persist in localStorage and
// restore when the URL omits them. The v2 shell swaps region-bound sources
// itself, so configureStore({v2: true}) makes lockRegion() a no-op.
//
// Coast keys (FE-73, design § 3A.3): presentation, current and habitat, which
// v1's terrain modules already write, are signals here too. The parsers are
// the ones web/coast-context.ts and packages/coast use, so both shells read a
// link the same way.
import {batch, computed, signal} from '@preact/signals';
import {DEFAULT_PROFILE, isProfile, PROFILE_TABLE, type Profile} from './profile.ts';
import {canonicalHour, fishLink} from './fish-links.ts';
import {
  habitatURL, hasCoastTerrain, isCurrentLayer, presentationFromURL, type CurrentLayer, type Presentation,
} from './coast-context.ts';

/** Keys v1's coastal modules write; readURL reports one only when the URL names it, so v1 readers see the shape they had. */
export const COAST_KEYS = ['presentation', 'current', 'habitat'] as const;
export type CoastKey = typeof COAST_KEYS[number];
/** URL parameters the store owns. `target` is the species/target id. */
export const URL_KEYS = ['region', 'coast', 'view', 'target', 'hour', 'profile', 'day', 'layers', 'area', 'base', ...COAST_KEYS] as const;
export type UrlKey = typeof URL_KEYS[number];
export type UrlState = Record<Exclude<UrlKey, CoastKey>, string | null> & Partial<Record<CoastKey, string>> & {selection: string | null};
export type Units = 'nautical';

/** Masthead views (v2). `?view=` is shared with v1's map position "lat,lng,zoom". */
export const APP_VIEWS = ['coast', 'conditions', 'history', 'fleet', 'reports'] as const;
export type AppView = typeof APP_VIEWS[number];
export const BASES = ['night', 'chart', 'aerial'] as const;
export type Base = typeof BASES[number];
/** `?layers=none` writes an empty rail; an absent key means stored or profile defaults. */
export const NO_LAYERS = 'none';
export const STORAGE_KEYS = {
  profile: 'skippercast-profile-v1', layers: 'skippercast-layers-v1', base: 'skippercast-base-v1', presentation: 'skippercast-presentation-v1',
} as const;
/** `current` when ?current= names no listed source; the value stays in the URL (v1 rule, #402). */
export const UNSUPPORTED = 'unsupported';
export type CurrentChoice = CurrentLayer | typeof UNSUPPORTED;

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
export const profile = signal<Profile>(DEFAULT_PROFILE);
/** The masthead view when ?view= names one; v1 map positions leave it at coast. */
export const appView = signal<AppView>('coast');
/** Time dock day "YYYY-MM-DD"; null means today. */
export const day = signal<string | null>(null);
/** Rail ids switched on; resolved from the URL, then storage, then the profile. */
export const layers = signal<readonly string[]>(PROFILE_TABLE[DEFAULT_PROFILE].defaultLayers);
/** Coast or focus id for the command bar (?area=, else ?focus=). */
export const area = signal<string | null>(null);
export const base = signal<Base>('night');
/** The presentation the link or (v2) the last choice asks for; see stagePresentation for what the stage shows. */
export const presentation = signal<Presentation>('chart');
/** Surface-current source; off by default, UNSUPPORTED for an unlisted ?current=. */
export const current = signal<CurrentChoice>('off');
/** Coast habitat id (?habitat=), independent of the atlas spot in `selection`. */
export const habitat = signal<string | null>(null);

/** Terrain presentations fall back to chart where the region has no coast terrain; the URL keeps the request. */
export function presentationFor(requested: Presentation, regionId: string | null): Presentation {
  return requested === 'chart' || (regionId !== null && hasCoastTerrain(regionId)) ? requested : 'chart';
}
export const stagePresentation = computed<Presentation>(() => presentationFor(presentation.value, region.value));

let locked: {region: string | null; coast: string | null} | null = null;

/** The storage the store persists to; null disables persistence. */
export interface StoreStorage {getItem(key: string): string | null; setItem(key: string, value: string): void}
const options: {v2: boolean; storage: StoreStorage | null | undefined} = {v2: false, storage: undefined};

/** v2 never reloads on a region change; `storage` replaces localStorage (tests pass a Map-backed one). */
export function configureStore(patch: {v2?: boolean; storage?: StoreStorage | null}): void {
  if (patch.v2 !== undefined) options.v2 = patch.v2;
  if (patch.storage !== undefined) options.storage = patch.storage;
}

function storage(): StoreStorage | null {
  if (options.storage !== undefined) return options.storage;
  try { return typeof localStorage === 'undefined' ? null : localStorage; } catch { return null; }
}
function stored(key: string): string | null { try { return storage()?.getItem(key) ?? null; } catch { return null; } }
function store(key: string, value: string): void { try { storage()?.setItem(key, value); } catch { /* the URL still carries it */ } }

/** The store's parameters in `href`. */
export function readURL(href: string): UrlState {
  const params = (options.v2 ? fishLink(href) : new URL(href)).searchParams;
  const state: UrlState = {
    region: params.get('region'), coast: params.get('coast'), view: params.get('view'),
    target: params.get('target'), hour: params.get('hour'),
    profile: params.get('profile'), day: params.get('day'), layers: params.get('layers'),
    area: params.get('area') || params.get('focus'), base: params.get('base'),
    selection: params.get('spot') || params.get('focus'),
  };
  for (const key of COAST_KEYS) {
    const value = params.get(key);
    if (value !== null) state[key] = value;
  }
  return state;
}

// The coast parsers ask web/coast-context.ts about a probe link, so they accept exactly what v1 accepts.
const PROBE = 'https://skippercast.invalid/';

/** `chart`, `2d` or `3d`; null for anything presentationFromURL would not return as written. */
export function parsePresentation(value: string | null | undefined): Presentation | null {
  if (value == null) return null;
  const probe = new URL(PROBE);
  probe.searchParams.set('presentation', value);
  const shown = presentationFromURL(probe.href);
  return shown === value ? shown : null;
}
/** A listed surface-current source, `off` when the key is absent, UNSUPPORTED otherwise (an empty value included). */
export const parseCurrent = (value: string | null | undefined): CurrentChoice => value == null ? 'off' : isCurrentLayer(value) ? value : UNSUPPORTED;
/** The habitat id habitatURL keeps (`[A-Za-z0-9._:-]{1,160}`); null otherwise. */
export const parseHabitat = (value: string | null | undefined): string | null => value == null ? null : habitatURL(PROBE, value).searchParams.get('habitat');

export const isAppView = (value: unknown): value is AppView => typeof value === 'string' && (APP_VIEWS as readonly string[]).includes(value);
export const isBase = (value: unknown): value is Base => typeof value === 'string' && (BASES as readonly string[]).includes(value);

/** "YYYY-MM-DD" when it is a real calendar date; null otherwise. */
export function parseDay(value: string | null): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const ms = Date.parse(value + 'T00:00:00Z');
  return Number.isFinite(ms) && new Date(ms).toISOString().startsWith(value) ? value : null;
}

/** Rail ids in a ?layers= value ("none" is an empty rail); null when the value names no id. */
export function parseLayers(value: string | null): string[] | null {
  if (value === NO_LAYERS) return [];
  const ids = (value ?? '').split(',').map(s => s.trim()).filter(s => /^[a-z][a-z0-9-]*$/.test(s));
  return ids.length ? ids.filter((id, i) => ids.indexOf(id) === i) : null;
}
/** The ?layers= value for `ids`. */
export const layersParam = (ids: readonly string[]): string => ids.length ? ids.join(',') : NO_LAYERS;

/** The profile, layers and base `href` resolves to: URL, then storage, then the profile's defaults. */
export function resolveStored(state: UrlState): {profile: Profile; layers: readonly string[]; base: Base} {
  const first = <T extends string>(is: (v: unknown) => v is T, fallback: T, ...values: (string | null)[]): T => values.find(is) ?? fallback;
  const p = first(isProfile, DEFAULT_PROFILE, state.profile, stored(STORAGE_KEYS.profile));
  const l = parseLayers(state.layers) ?? parseLayers(stored(STORAGE_KEYS.layers)) ?? PROFILE_TABLE[p].defaultLayers;
  const b = first(isBase, 'night', state.base, stored(STORAGE_KEYS.base));
  return {profile: p, layers: l, base: b};
}

/**
 * The presentation `state` asks for: the URL, then (v2 only) the stored choice, then chart.
 * v1 writes chart by removing the key, so a v1 store neither reads nor writes the stored value;
 * v2 writes `presentation=chart` explicitly.
 */
export function resolvePresentation(state: UrlState): Presentation {
  return parsePresentation(state.presentation) ?? (options.v2 ? parsePresentation(stored(STORAGE_KEYS.presentation)) : null) ?? 'chart';
}

/** `href` with `patch` applied: a string sets a parameter, null removes it. An invalid habitat id removes it too. */
export function withParams(href: string, patch: Partial<Record<UrlKey, string | null>>): string {
  const clearGeography = [patch.region, patch.coast].some(value => value === null || value === '');
  const url = options.v2 ? fishLink(href, clearGeography) : new URL(href);
  for (const [key, given] of Object.entries(patch)) {
    if (given === undefined) continue;
    const value = key === 'habitat' ? parseHabitat(given) : given;
    if (value === null || value === '') url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  }
  return url.href;
}

/** Set the signals from `href` (default: the current address). */
export function syncFromURL(href: string = location.href): UrlState {
  const state = readURL(href);
  const kept = resolveStored(state);
  // A key the URL names is the user's latest choice: remember it for links that omit it.
  if (isProfile(state.profile)) store(STORAGE_KEYS.profile, kept.profile);
  if (parseLayers(state.layers)) store(STORAGE_KEYS.layers, layersParam(kept.layers));
  if (isBase(state.base)) store(STORAGE_KEYS.base, kept.base);
  const shown = resolvePresentation(state);
  if (options.v2 && parsePresentation(state.presentation)) store(STORAGE_KEYS.presentation, shown);
  batch(() => {
    region.value = state.region; coast.value = state.coast; view.value = state.view;
    species.value = state.target; hour.value = state.hour; selection.value = state.selection;
    profile.value = kept.profile; layers.value = kept.layers; base.value = kept.base;
    appView.value = isAppView(state.view) ? state.view : 'coast';
    day.value = parseDay(state.day); area.value = state.area;
    presentation.value = shown; current.value = parseCurrent(state.current); habitat.value = parseHabitat(state.habitat);
  });
  return state;
}

/** Called by boot.js once region-bound modules load; region changes reload after this. A v2 store ignores it. */
export function lockRegion(href: string = location.href): void {
  if (options.v2) return;
  const {region: r, coast: c} = readURL(href);
  locked = {region: r, coast: c};
}
export const regionLocked = (): boolean => locked !== null;

/** Whether moving from `from` to `to` needs a full page load. */
export function needsReload(from: string, to: string, lock = locked): boolean {
  const a = new URL(from), b = new URL(to);
  const otherPage = a.origin !== b.origin || a.pathname !== b.pathname;
  if (options.v2) return otherPage;
  if (!lock) return false;
  if (otherPage) return true;
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
  const canonical = canonicalHour(value);
  return canonical ? Date.parse(canonical) / 1000 : null;
}
