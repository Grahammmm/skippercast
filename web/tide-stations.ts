// User-selected tide displays. These never replace the reviewed tide inputs
// to bar/shore assessments. NOAA's directory is loaded only on chooser use
// (or to restore a choice), not on the default first paint.
import {dateKey} from '../packages/coast/src/daily.ts';
import type {TideEvent, TidePoint} from '../packages/coast/src/types.ts';
import type {Brief, BriefTile} from './brief/types.ts';
import {tidePredictionURL} from './station-label.ts';
import {tideTrend, TREND_MATCH_MS} from './tides.ts';

export const TIDE_DIRECTORY_URL = 'https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions';
export interface TideStation {id: string; name: string; lat: number; lng: number; type: 'R' | 'S'}
export interface TideRegion {id: string; bounds: readonly number[]; station: string; name: string}
export interface TideReading {station: TideStation; points: TidePoint[]; events: TideEvent[]; fetchedAt: string; failed: boolean}
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
export const tideChoiceKey = (region: string): string => `skippercast-tide-station-v1.${region}`;
export const tideSavedKey = (region: string): string => `skippercast-tide-stations-v2.${region}`;
export const MAX_SAVED_TIDE_STATIONS = 3;
export interface SavedTideStations {saved: string[]; active: string | null}
type TideStorage = Pick<Storage, 'getItem'> & Partial<Pick<Storage, 'setItem' | 'removeItem'>>;
const validId = (id: unknown): id is string => typeof id === 'string' && /^\d{7}$/.test(id);
function validSaved(value: unknown): value is SavedTideStations {
  return record(value) && Array.isArray(value.saved) && value.saved.length <= MAX_SAVED_TIDE_STATIONS
    && value.saved.every(validId) && new Set(value.saved).size === value.saved.length
    && (value.active === null || validId(value.active) && value.saved.includes(value.active));
}
export function readSavedTideStations(region: string, storage?: TideStorage): SavedTideStations {
  const empty = (): SavedTideStations => ({saved: [], active: null});
  try {
    const store = storage ?? globalThis.localStorage, raw = store?.getItem(tideSavedKey(region));
    if (raw !== null && raw !== undefined) {
      const value: unknown = JSON.parse(raw);
      return validSaved(value) ? {saved: [...value.saved], active: value.active} : empty();
    }
    const legacy = store?.getItem(tideChoiceKey(region));
    if (!validId(legacy)) return empty();
    const migrated = {saved: [legacy], active: legacy};
    // Commit the replacement before removing the old key; blocked storage keeps
    // the legacy choice recoverable and still usable for this visit.
    try {
      if (store?.setItem) {
        store.setItem(tideSavedKey(region), JSON.stringify(migrated));
        store.removeItem?.(tideChoiceKey(region));
      }
    } catch { /* Preserve the legacy key on a failed replacement write. */ }
    return migrated;
  } catch { return empty(); }
}
export function saveSavedTideStations(region: string, value: SavedTideStations, storage?: Pick<Storage, 'setItem'>): void {
  if (!validSaved(value)) return;
  try { (storage ?? globalThis.localStorage)?.setItem(tideSavedKey(region), JSON.stringify(value)); }
  catch { /* A blocked store does not prevent this visit's selection. */ }
}
export function readTideChoice(region: string, storage?: TideStorage): string | null {
  return readSavedTideStations(region, storage).active;
}
export function saveTideChoice(region: string, id: string | null, storage?: Pick<Storage, 'setItem'>): void {
  saveSavedTideStations(region, {saved: validId(id) ? [id] : [], active: validId(id) ? id : null}, storage);
}
export function tideRegion(id: string, value: unknown): TideRegion | null {
  if (!record(value) || !record(value.stations) || !Array.isArray(value.bounds) || value.bounds.length !== 4 || !value.bounds.every(Number.isFinite)) return null;
  const station = value.stations.tide;
  return typeof station === 'string' && /^\d{7}$/.test(station)
    ? {id, bounds: value.bounds as number[], station, name: String(value.stations.tide_name ?? station)} : null;
}
export function stationsInRegion(body: unknown, bounds: readonly number[]): TideStation[] {
  if (!record(body) || !Array.isArray(body.stations) || bounds.length !== 4 || !bounds.every(Number.isFinite)) return [];
  const [west, south, east, north] = bounds as [number, number, number, number];
  const stations = new Map<string, TideStation>();
  for (const row of body.stations) {
    if (!record(row) || typeof row.id !== 'string' || !/^\d{7}$/.test(row.id) || typeof row.name !== 'string'
      || typeof row.lat !== 'number' || typeof row.lng !== 'number' || !Number.isFinite(row.lat) || !Number.isFinite(row.lng)
      || (row.type !== 'R' && row.type !== 'S')) continue;
    if (row.lat < south || row.lat > north || row.lng < west || row.lng > east) continue;
    stations.set(row.id, {id: row.id, name: row.name, lat: row.lat, lng: row.lng, type: row.type});
  }
  return [...stations.values()].sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}
/** Great-circle proximity to the chosen harbor, never device location. */
export function nearestTideStation(stations: readonly TideStation[], port: readonly [number, number]): TideStation | null {
  if (!port.every(Number.isFinite)) return null;
  const rad = Math.PI / 180, [lat, lng] = port;
  const distance = (s: TideStation) => Math.sin((s.lat - lat) * rad / 2) ** 2 + Math.cos(lat * rad) * Math.cos(s.lat * rad) * Math.sin((s.lng - lng) * rad / 2) ** 2;
  return [...stations].sort((a, b) => distance(a) - distance(b) || a.id.localeCompare(b.id))[0] ?? null;
}
/** Keep the parameters aligned with dist/marine-data.js and sw.js datasetKey. */
export function tidePredictionsURL(station: string, interval: '6' | 'hilo', now = Date.now()): string {
  const date = (n: number) => new Date(n).toISOString().slice(0, 10).replaceAll('-', '');
  return 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?' + new URLSearchParams({product: 'predictions', application: 'SkipperCast', station,
    begin_date: date(now - 86400000), end_date: date(now + 8 * 86400000), datum: 'MLLW', time_zone: 'gmt', interval, units: 'english', format: 'json'});
}
export function tidePackURLs(station: TideStation, now = Date.now()): string[] {
  return [TIDE_DIRECTORY_URL, tidePredictionsURL(station.id, 'hilo', now), ...(station.type === 'R' ? [tidePredictionsURL(station.id, '6', now)] : [])];
}
export function parseTidePredictions(body: unknown): {points: TidePoint[]; events: TideEvent[]} {
  const points: TidePoint[] = [], events: TideEvent[] = [];
  if (!record(body) || !Array.isArray(body.predictions) || body.error) return {points, events};
  for (const row of body.predictions) {
    if (!record(row) || typeof row.t !== 'string' || !/^\d{4}-\d\d-\d\d \d\d:\d\d$/.test(row.t) || typeof row.v !== 'string' || !row.v.trim()) continue;
    const time = Date.parse(row.t.replace(' ', 'T') + ':00Z'), heightFt = Number(row.v);
    if (!Number.isFinite(time) || !Number.isFinite(heightFt)) continue;
    const point = {at: new Date(time).toISOString(), heightFt};
    if (row.type === 'H' || row.type === 'L') events.push({...point, type: row.type});
    else if (row.type === undefined) points.push(point);
  }
  points.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  events.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return {points, events};
}
/** Save validated, live answers. NOAA can return an error body with HTTP 200. */
export async function saveTidePack(urls: readonly string[], put: (key: string, body: ArrayBuffer, headers: Headers) => Promise<void>, signal: AbortSignal, fetcher: typeof fetch = fetch): Promise<void> {
  for (const url of urls) {
    const response = await fetcher(url, {credentials: 'omit', cache: 'no-cache', signal});
    if (!response.ok || response.headers.has('X-SC-Offline')) throw new Error('Chosen tide station could not be saved from a live response. Saved regions are unchanged.');
    const body = await response.arrayBuffer(), json: unknown = JSON.parse(new TextDecoder().decode(body));
    const interval = new URL(url).searchParams.get('interval');
    const parsed = parseTidePredictions(json);
    if (url === TIDE_DIRECTORY_URL ? !record(json) || !Array.isArray(json.stations) : !(interval === 'hilo' ? parsed.events.length : parsed.points.length))
      throw new Error('Chosen tide predictions are unavailable. Saved regions are unchanged.');
    await put(url, body, response.headers);
  }
}
export async function loadTideReading(station: TideStation, fetcher: typeof fetch = fetch, now = Date.now()): Promise<TideReading> {
  const intervals: ('6' | 'hilo')[] = station.type === 'R' ? ['hilo', '6'] : ['hilo'];
  const results = await Promise.all(intervals.map(async interval => {
    try {
      const response = await fetcher(tidePredictionsURL(station.id, interval, now), {credentials: 'omit', signal: AbortSignal.timeout(20000)});
      if (!response.ok) return null;
      const parsed = parseTidePredictions(await response.json());
      if (!(interval === 'hilo' ? parsed.events.length : parsed.points.length)) return null;
      const clock = response.headers.get('X-SC-Offline') ?? new Date(now).toISOString();
      if (!Number.isFinite(Date.parse(clock))) return null;
      return {...parsed, clock};
    } catch { return null; }
  }));
  const clocks = results.flatMap(r => r ? [r.clock] : []).sort();
  return {station, points: results.flatMap(r => r?.points ?? []), events: results.flatMap(r => r?.events ?? []),
    fetchedAt: clocks[0] ?? new Date(now).toISOString(), failed: results.some(r => !r)};
}
/** Display overlay only: assessments, windows and their reference station stay intact. */
export function withTideSelection(brief: Brief, station: {id: string; name: string}, reading: TideReading | null, timezone: string, now: Date, at?: string | null): Brief {
  const pivot = at && Number.isFinite(Date.parse(at)) ? Date.parse(at) : now.getTime();
  const points = (reading?.points ?? []).filter(p => dateKey(p.at, timezone) === brief.date);
  const events = (reading?.events ?? []).filter(p => dateKey(p.at, timezone) === brief.date);
  const point = points.find(p => Math.abs(Date.parse(p.at) - pivot) <= TREND_MATCH_MS);
  const next = events.find(p => Date.parse(p.at) >= pivot);
  const value = point?.heightFt ?? next?.heightFt ?? null;
  const ageMs = reading ? now.getTime() - Date.parse(reading.fetchedAt) : null;
  const limitMs = 36 * 3600000;
  const tile: BriefTile = {id: 'tide', label: 'Tide', value: value === null ? null : Number(value.toFixed(1)), unit: 'ft',
    detail: [point ? tideTrend(points, pivot) : next ? `next ${next.type === 'H' ? 'high' : 'low'}` : 'Predictions unavailable', station.name, 'MLLW'].filter(Boolean).join(' · '),
    source: `NOAA ${station.id} ${station.name}`, sourceUrl: tidePredictionURL(station.id), at: reading?.fetchedAt ?? null, ageMs, limitMs,
    state: value === null || ageMs === null ? 'unavailable' : reading?.failed || ageMs > limitMs || ageMs < -3600000 ? 'stale' : 'fresh'};
  return {...brief, tiles: brief.tiles.map(t => t.id === 'tide' ? tile : t), tides: points, tideEvents: events, tideDatum: 'MLLW'};
}
