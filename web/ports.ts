// Home ports for the v2 entry flow (FE-08, design § 7): the directory served
// as data/home-ports.json, name matching and ranking, the nearest-port rule,
// the addresses a choice leads to, and the browser preference. The storage
// key and the 75 nm rule are dist/home-port.js's, so v1 and v2 share the
// saved port; v1 keeps its own copy until FE-61. Match positions are
// approximate harbor centres for on-device matching, never waypoints.
// Home memory (FE-83, design § 3A.3) is one home for v1, v2 and /coast:
// save, read and forget follow dist/home-port.js since #396, with the
// packages/coast preference key and cookie imported, never copied.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {forgetPreferenceHeader, HOME_PLACE_KEY, readPreferences, validPreferences, type HomePreferences} from '../packages/coast/src/coast3d/preferences.ts';
import {isProfile, type Profile} from './profile.ts';
import {STORAGE_KEYS, type StoreStorage} from './state.ts';

/** Must equal HOME_PORT_KEY in dist/home-port.js: v1 reads the port v2 saved. */
export const HOME_PORT_KEY = 'skippercast-home-port-v1';
/** Must equal FIRST_RUN_KEY in dist/home-port.js: forgetting the home restarts v1's first run too. */
export const FIRST_RUN_KEY = 'skippercast-first-run-v1';
export {HOME_PLACE_KEY};
export const PORTS_URL = 'data/home-ports.json';
/** Ports listed before any search, as in v1. */
export const FEATURED: readonly string[] = ['morro-bay', 'san-diego', 'monterey', 'ventura', 'santa-cruz', 'bodega-bay'];
/** The 75 nm rule: a position farther than this from every port matches none. */
export const MAX_MATCH_NM = 75;
/** Parameters a port choice replaces; everything else in the address (ui, utm) stays. */
const AREA_KEYS = ['region', 'coast', 'view', 'focus', 'spot', 'habitat', 'place', 'target', 'area'] as const;

export interface Port {
  readonly id: string;
  readonly name: string;
  readonly region: string;
  readonly region_name?: string;
  readonly status: 'active' | 'preview';
  readonly forecast_point: string;
  readonly forecast_name: string;
  /** [latitude, longitude] of the approximate harbor centre. */
  readonly match: readonly [number, number];
}

export const COPY = {
  question: 'Where are you launching?',
  placeholder: 'Try Morro Bay, Ventura, San Diego…',
  finding: 'Finding a nearby port…',
  unsupported: 'Location is unavailable. Search for a port instead.',
  unavailable: 'Location was unavailable. Search for a port instead.',
  none: 'No listed port is nearby. Search or explore the coast.',
  empty: 'No matching port yet. Try a nearby harbor or explore the coast.',
  privacy: 'Your choice stays in this browser. Location matching is approximate; forecast map centers are not harbor entrances or navigation waypoints.',
  forget: 'Forget saved home',
  forgotten: 'Saved home removed. This visit stays at the current selection.',
  found: (port: Port): string => `Closest listed port: ${port.name}. Select it below to continue.`,
  detail: (port: Port): string => `${port.status === 'active' ? 'Mapped area' : 'Regional preview'} · ${port.forecast_name}`,
} as const;

const fold = (text: string): string => text.toLocaleLowerCase();

/**
 * Ports whose name contains `query` (v1's match), ranked: a name that starts
 * with it, then a word that starts with it, then any other match; ties keep
 * the directory's order. An empty query matches every port.
 */
export function matchPorts(ports: readonly Port[], query: string): Port[] {
  const q = fold(query.trim());
  if (!q) return [...ports];
  const rank = (port: Port): number => {
    const name = fold(port.name);
    if (name.startsWith(q)) return 0;
    if (name.split(/[^a-z0-9]+/).some(word => word.startsWith(q))) return 1;
    return name.includes(q) ? 2 : -1;
  };
  return ports.map((port, i) => ({port, i, rank: rank(port)})).filter(e => e.rank >= 0)
    .sort((a, b) => a.rank - b.rank || a.i - b.i).map(e => e.port);
}

/** The list the chooser shows: matches for a query, else the featured ports until "See all". */
export function listPorts(ports: readonly Port[], query: string, showAll = false): Port[] {
  const matches = matchPorts(ports, query);
  return query.trim() || showAll ? matches : matches.filter(port => FEATURED.includes(port.id));
}

/** The nearest port within `maxNm` of a position (v1's rule, great-circle nautical miles), or null. */
export function closestPort(ports: readonly Port[], latitude: number, longitude: number, maxNm = MAX_MATCH_NM): Port | null {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  const rad = Math.PI / 180;
  const nm = ([lat, lon]: readonly [number, number]): number => {
    const h = Math.sin((lat - latitude) * rad / 2) ** 2 + Math.cos(latitude * rad) * Math.cos(lat * rad) * Math.sin((lon - longitude) * rad / 2) ** 2;
    return 3440.065 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
  };
  const best = ports.map(port => ({port, nm: nm(port.match)})).sort((a, b) => a.nm - b.nm)[0];
  return best && best.nm <= maxNm ? best.port : null;
}

/** The port the app shows for `region`: the saved one when it is in that region, else the first listed there. */
export function currentPort(ports: readonly Port[], region: string | null, savedId: string | null): Port | null {
  if (!region) return null;
  const inRegion = ports.filter(port => port.region === region);
  return inRegion.find(port => port.id === savedId) ?? inRegion[0] ?? null;
}

/** The app with `params` replacing the area keys; ui and any unrelated parameter stay. */
function appURL(href: string, params: Record<string, string | undefined>): string {
  const url = new URL(href);
  url.pathname = '/map'; url.hash = '';
  for (const key of AREA_KEYS) url.searchParams.delete(key);
  for (const [key, value] of Object.entries(params)) if (value) url.searchParams.set(key, value);
  return url.href;
}
/** The app at `port`: /map?region=…(&profile=…). */
export const portURL = (href: string, port: Port, profile?: Profile | null): string =>
  appURL(href, {region: port.region, profile: isProfile(profile) ? profile : undefined});
/** "Explore the coast": the app over the central coast with no port. */
export const exploreURL = (href: string): string => appURL(href, {coast: 'central'});

/** The landing, keeping the ui switch so a preview stays in v2. */
export function landingURL(href: string): string {
  const url = new URL(href), ui = url.searchParams.get('ui');
  url.pathname = '/'; url.hash = ''; url.search = '';
  if (ui) url.searchParams.set('ui', ui);
  return url.href;
}

/** Storage the home memory uses; removeItem is optional so a minimal stand-in still reads and saves. */
export type HomeStorage = StoreStorage & {removeItem?(key: string): void};
/** `document`, or a test's stand-in: where the /coast preference cookie lives. */
export type CookieJar = {cookie: string};
/** A saved home: a listed port, or a /coast place with its fishing mode. */
export type Home = {port: Port} | {native: HomePreferences};

function browserStorage(): HomeStorage | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage; } catch { return null; }
}
function browserCookies(): CookieJar | null {
  try { return typeof document === 'undefined' ? null : document; } catch { return null; }
}
const secureContext = (): boolean => globalThis.location?.protocol === 'https:';
const read = (storage: HomeStorage | null, key: string): string | null => { try { return storage?.getItem(key) ?? null; } catch { return null; } };
const cookieText = (jar: CookieJar | null): string => { try { return jar?.cookie ?? ''; } catch { return ''; } };
/** The /coast place preference in storage, when valid. */
function savedPlace(storage: HomeStorage | null): HomePreferences | null {
  try { const saved: unknown = JSON.parse(read(storage, HOME_PLACE_KEY) ?? 'null'); return validPreferences(saved) ? saved : null; } catch { return null; }
}

export function savedPortId(storage: HomeStorage | null = browserStorage()): string | null {
  return read(storage, HOME_PORT_KEY);
}
/**
 * Remember the port as the one home, as v1 does: the shared key, with the
 * /coast place preference and cookie cleared so no reader finds an older
 * home. A blocked storage still lets the session navigate.
 */
export function savePort(id: string, storage: HomeStorage | null = browserStorage(), jar: CookieJar | null = browserCookies(), secure = secureContext()): boolean {
  let saved = false;
  try { storage?.setItem(HOME_PORT_KEY, id); storage?.removeItem?.(HOME_PLACE_KEY); saved = storage !== null; } catch { saved = false; }
  try { if (jar) jar.cookie = forgetPreferenceHeader(secure); } catch { /* The choice still applies to this visit. */ }
  return saved;
}
/** Forget the home everywhere v1 and /coast keep it: port, place, profile, v1's first run and the cookie. */
export function forgetHome(storage: HomeStorage | null = browserStorage(), jar: CookieJar | null = browserCookies(), secure = secureContext()): void {
  for (const key of [HOME_PORT_KEY, HOME_PLACE_KEY, STORAGE_KEYS.profile, FIRST_RUN_KEY]) try { storage?.removeItem?.(key); } catch { /* blocked */ }
  try { if (jar) jar.cookie = forgetPreferenceHeader(secure); } catch { /* blocked */ }
}
/** Whether any reader would find a saved home (what "Forget saved home" removes). */
export function hasSavedHome(storage: HomeStorage | null = browserStorage(), jar: CookieJar | null = browserCookies()): boolean {
  return read(storage, HOME_PORT_KEY) !== null || savedPlace(storage) !== null || readPreferences(cookieText(jar)) !== null;
}
/** The fishing mode a /coast home was saved with (storage, then the cookie), or null. */
export function savedHomeMode(storage: HomeStorage | null = browserStorage(), jar: CookieJar | null = browserCookies()): Profile | null {
  return (savedPlace(storage) ?? readPreferences(cookieText(jar)))?.mode ?? null;
}

/**
 * v1's resolveHome: a saved listed port, else the /coast place in storage,
 * else the legacy cookie, migrated to storage. The stored profile is the
 * current mode, as in v1 and /coast.
 */
export function resolveHome(ports: readonly Port[], storage: HomeStorage | null = browserStorage(), cookies = ''): Home | null {
  const stored = read(storage, STORAGE_KEYS.profile), mode = isProfile(stored) ? stored : null;
  const current = (p: HomePreferences): HomePreferences => mode ? {...p, mode} : p;
  const id = read(storage, HOME_PORT_KEY), port = ports.find(item => item.id === id);
  if (port) return {port};
  const place = savedPlace(storage);
  if (place) return {native: current(place)};
  const legacy = readPreferences(cookies);
  if (!legacy) return null;
  try { storage?.setItem(HOME_PLACE_KEY, JSON.stringify(legacy)); if (!mode) storage?.setItem(STORAGE_KEYS.profile, legacy.mode); } catch { /* The visit still opens the home. */ }
  return {native: current(legacy)};
}
/** Where a home opens: the port's app, the /coast place's app (the address's own profile wins), or the landing. */
export function homeURL(href: string, home: Home | null): string {
  if (!home) return landingURL(href);
  if ('port' in home) return portURL(href, home.port);
  return appURL(href, {place: home.native.place, profile: new URL(href).searchParams.has('profile') ? undefined : home.native.mode});
}
/**
 * /map with no area: the saved home's address, else the landing. The
 * directory loads only for a saved port, and the cookie is read only when
 * no saved port won (v1's order). A shared link never reaches this.
 */
export async function savedHomeURL(href: string, storage: HomeStorage | null = browserStorage(), jar: CookieJar | null = browserCookies(), load: () => Promise<readonly Port[]> = loadPorts): Promise<string> {
  const id = savedPortId(storage);
  const ports = id ? await load().catch(() => [] as Port[]) : [];
  return homeURL(href, resolveHome(ports, storage, ports.some(port => port.id === id) ? '' : cookieText(jar)));
}

/** Whether `data` is the directory's schema, with every port's match position. */
export function isDirectory(data: unknown): data is {schema_version: 1; ports: Port[]} {
  const d = data as {schema_version?: unknown; ports?: unknown};
  return !!d && d.schema_version === 1 && Array.isArray(d.ports) && d.ports.length > 0 &&
    d.ports.every(p => p && typeof p.id === 'string' && typeof p.name === 'string' && typeof p.region === 'string' &&
      Array.isArray(p.match) && p.match.length === 2 && p.match.every((n: unknown) => Number.isFinite(n)));
}

let directory: Promise<Port[]> | null = null;
/** The port directory, fetched once per page; a failure clears the cache so the next open retries. */
export function loadPorts(fetchFn: typeof fetch = fetch): Promise<Port[]> {
  directory ??= (async () => {
    const response = await fetchFn(PORTS_URL, {signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw Error('Port choices are unavailable');
    const data: unknown = await response.json();
    if (!isDirectory(data)) throw Error('Invalid port directory');
    return data.ports;
  })();
  directory.catch(() => { directory = null; });
  return directory;
}

export type Located = {ok: true; port: Port} | {ok: false; reason: 'unsupported' | 'unavailable' | 'none'};
/** v1's geolocation call: low accuracy, 10 s, a five-minute-old fix is fine; the position never leaves the device. */
export const GEO_OPTIONS: PositionOptions = {enableHighAccuracy: false, timeout: 10000, maximumAge: 300000};

/** The nearest listed port to the device, or why there is none. */
export function locatePort(ports: readonly Port[], geolocation: Geolocation | null | undefined = globalThis.navigator?.geolocation): Promise<Located> {
  if (!geolocation) return Promise.resolve({ok: false, reason: 'unsupported'});
  return new Promise(resolve => geolocation.getCurrentPosition(
    position => { const port = closestPort(ports, position.coords.latitude, position.coords.longitude); resolve(port ? {ok: true, port} : {ok: false, reason: 'none'}); },
    () => resolve({ok: false, reason: 'unavailable'}), GEO_OPTIONS));
}
