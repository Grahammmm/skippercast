// The landing's readout (FE-07, design § 7, D4): wind, swell and water from
// the default region's live conditions feed (NDBC buoys, every 30 minutes)
// and tide from the NOAA CO-OPS water level the v1 page also reads. Each
// reading carries its source, its age and a stale state judged at `now`, so
// a reading that ages on screen turns stale; a missing one says so and is
// never filled from another station.
//
// A backup station (#554: source.station, source.fallback_for) is named as
// itself, "backup for" the primary, never under the primary's name.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {num, t, type Language} from '../i18n.ts';
import {sharedStation, sourceStation, stationText} from '../station-label.ts';
import {FT_PER_M, KT_PER_MS} from '../units.ts';

import {DEFAULT_REGION, DEFAULT_PLACE, placeLabel} from './place.ts';
export {DEFAULT_REGION, DEFAULT_PLACE, placeLabel} from './place.ts';
/** v1's rule (dist/live-conditions.js): a feed generated more than 90 minutes ago is late. */
export const FEED_LATE_MIN = 90;
const RAW = 'https://raw.githubusercontent.com/Grahammmm/skippercast/';

export type ReadingId = 'wind' | 'swell' | 'water' | 'tide';
export interface Reading {
  readonly id: ReadingId;
  readonly label: string;
  /** Formatted reading, or "No reading". */
  readonly reading: string;
  readonly unit?: string;
  readonly detail?: string;
  /** Station and age ("NDBC 46028 · 22 min"). */
  readonly source: string;
  readonly stale: boolean;
  /** The basis: product, place (with its distance from the harbor when the region gives both positions) and age rule. */
  readonly basis: string;
}
export interface FeedState {readonly age: string | null; readonly stale: boolean}

/** The parts of regions/<id>/region.json the readout needs. */
export interface RegionStations {
  readonly name?: string;
  readonly conditions_feed?: string;
  readonly stations?: {tide?: string; tide_name?: string; tide_note?: string; nearshore_buoy?: string; offshore_buoy?: string};
  readonly harbor?: {name?: string; latitude?: number; longitude?: number};
  readonly intelligence?: {verification_stations?: readonly {id?: string; latitude?: number; longitude?: number}[]};
}

type Row = Record<string, unknown>;
interface Source {name?: string; status?: string; station?: string; fallback_for?: string; max_age_hours?: number; data?: {station?: string; units?: Record<string, string>; observations?: Row[]}}
interface Feed {schema_version?: number; generated_at?: string; sources?: Record<string, Source>}

const time = (value: unknown): number => typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? Date.parse(value) : NaN;
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const POINTS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
/** 16-point compass name for degrees true. */
export const compass = (deg: number): string => POINTS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]!;

/** "about 56 nm WNW of Morro Bay harbor" for NDBC `station`, or null when the region lacks either position. SC0707-05: `lang` words it; the harbor's name stays as published. */
export function fromHarbor(region: RegionStations, station: string | undefined, lang: Language = 'en'): string | null {
  const h = region.harbor, b = region.intelligence?.verification_stations?.find(s => s.id === station);
  if (!h?.name || !finite(h.latitude) || !finite(h.longitude) || !b || !finite(b.latitude) || !finite(b.longitude)) return null;
  const rad = Math.PI / 180, p1 = h.latitude * rad, p2 = b.latitude * rad, dl = (b.longitude - h.longitude) * rad;
  const nm = 2 * Math.asin(Math.sqrt(Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2)) * 3440.065;
  const bearing = Math.atan2(Math.sin(dl) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl)) / rad;
  return t('landing.place.from', lang, {n: Math.round(nm), direction: compass(bearing), harbor: h.name});
}

/** "45 min", "2 h", "3 d": how old a reading is (web/confidence.ts's rule). */
export function ageText(ms: number): string {
  const minutes = Math.max(0, Math.floor(ms / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.floor(hours / 24)} d`;
}

/** The feed path the site serves for a region's conditions feed (dist/feeds.js's rule). */
export const feedPath = (url: string | undefined, region = DEFAULT_REGION): string =>
  url?.startsWith(RAW + 'conditions/') ? '/feeds/' + url.slice(RAW.length) : `/feeds/conditions/regions/${region}/latest.json`;

/** The newest observation row with `key` in `unit`, and its time. */
function newest(source: Source | undefined, key: string, unit: string): {row: Row; at: number} | null {
  const units = source?.data?.units ?? {};
  if (units[key] !== unit) return null;
  const rows = (source?.data?.observations ?? []).filter(r => r && (unit === '-' ? typeof r[key] === 'string' : finite(r[key]))).map(row => ({row, at: time(row.time)}));
  return rows.filter(r => Number.isFinite(r.at)).sort((a, b) => b.at - a.at)[0] ?? null;
}

/** Source line and stale state for an observation at `at` from `station`, `limitH` hours allowed (null: the source gave no limit, so age alone never marks it stale). */
function judged(station: string, at: number | null, ok: boolean, limitH: number | null, now: number, lang: Language): {source: string; stale: boolean} {
  if (at === null || !Number.isFinite(at)) return {source: `${station} · ${t('landing.reading.unavailable', lang)}`, stale: true};
  const stale = !ok || (limitH !== null && now - at > limitH * 3600000) || at - now > 5 * 60000;
  return {source: `${station} · ${ageText(now - at)}`, stale};
}

/** Wind, swell and water from the conditions feed; the region names the buoys when the feed is missing and places them against its harbor. */
export function buoyReadings(feed: unknown, region: RegionStations = {}, now = Date.now(), lang: Language = 'en'): Reading[] {
  const f = (feed as Feed)?.schema_version === 1 ? feed as Feed : null;
  const stations = region.stations ?? {};
  const src = (key: string) => f?.sources?.[key];
  const actual = (key: string, fallback?: string) => sourceStation(src(key), src(key)?.data?.station ?? fallback);
  const stationId = (key: string, fallback?: string) => actual(key, fallback)?.id ?? src(key)?.data?.station ?? fallback;
  const station = (key: string, fallback?: string) => { const s = actual(key, fallback); return `NDBC ${s ? stationText(s) : stationId(key, fallback) ?? '—'}`; };
  const ok = (key: string) => src(key)?.status === 'ok';
  /** The source's own age limit; none is assumed when the feed gives none. */
  const limit = (key: string): number | null => finite(src(key)?.max_age_hours) ? src(key)!.max_age_hours! : null;
  /** The buoy named in a basis: the region's name for `nameKey`, or for a backup the station `key` actually read. */
  const name = (key: string, fallback: 'offshore' | 'nearshore', buoy?: string, nameKey = key) => {
    const s = actual(key, buoy);
    if (s?.backupFor) {
      const where = fromHarbor(region, s.id, lang);
      return t('landing.buoy.backup', lang, {id: s.id, where: where ? `, ${where}` : '', primary: s.backupFor});
    }
    const where = fromHarbor(region, stationId(nameKey, buoy), lang);
    return t('landing.buoy.primary', lang, {name: src(nameKey)?.name ?? t(`landing.buoy.${fallback}`, lang), where: where ? `, ${where}` : ''});
  };
  // A backup can make two roles read one station: say so instead of implying two measurements.
  const same = (key: string, other: string, kind: 'water' | 'wind' | 'swell', buoy?: string, otherBuoy?: string) =>
    sharedStation(actual(key, buoy), actual(other, otherBuoy)) ? t('landing.basis.same', lang, {kind: t(`landing.basis.kind.${kind}`, lang)}) : '';

  const wind = newest(src('offshore'), 'WSPD', 'm/s');
  const gust = wind && finite(wind.row.GST) ? Math.round((wind.row.GST as number) * KT_PER_MS) : null;
  const windFrom = wind && finite(wind.row.WDIR) ? compass(wind.row.WDIR as number) : null;
  const swell = newest(src('diablo-spectrum'), 'SwH', 'm');
  const period = swell && finite(swell.row.SwP) ? `${Math.round(swell.row.SwP as number)} s` : null;
  /** One decimal: English as toFixed gives it, Spanish with its comma (num keeps at most one decimal). */
  const oneDecimal = (n: number): string => lang === 'es' ? num(Number(n.toFixed(1)), lang, 1) : n.toFixed(1);
  const none = t('landing.reading.none', lang);
  const water = newest(src('diablo'), 'WTMP', 'degC');
  const rule = (key: string) => { const h = limit(key); return h === null ? t('landing.basis.rule.none', lang) : t('landing.basis.rule.limit', lang, {h}); };
  return [
    {id: 'wind', label: t('tile.wind', lang), ...(wind ? {reading: String(Math.round((wind.row.WSPD as number) * KT_PER_MS)), unit: 'kt'} : {reading: none}),
      detail: [windFrom, gust !== null ? t('landing.reading.gusts', lang, {n: gust}) : null].filter(Boolean).join(' · ') || undefined,
      ...judged(station('offshore', stations.offshore_buoy), wind?.at ?? null, ok('offshore'), limit('offshore'), now, lang),
      basis: t('landing.basis.wind', lang, {station: name('offshore', 'offshore', stations.offshore_buoy), rule: rule('offshore'), same: same('offshore', 'diablo', 'water', stations.offshore_buoy, stations.nearshore_buoy)})},
    {id: 'swell', label: t('tile.swell', lang), ...(swell ? {reading: oneDecimal((swell.row.SwH as number) * FT_PER_M), unit: 'ft'} : {reading: none}),
      detail: [period, swell && typeof swell.row.SwD === 'string' && /^[NSEW]{1,3}$/.test(swell.row.SwD) ? swell.row.SwD : null].filter(Boolean).join(' · ') || undefined,
      ...judged(station('diablo-spectrum', stations.nearshore_buoy), swell?.at ?? null, ok('diablo-spectrum'), limit('diablo-spectrum'), now, lang),
      basis: t('landing.basis.swell', lang, {station: name('diablo-spectrum', 'nearshore', stations.nearshore_buoy, 'diablo'), rule: rule('diablo-spectrum'), same: same('diablo-spectrum', 'offshore', 'wind', stations.nearshore_buoy, stations.offshore_buoy)})},
    {id: 'water', label: t('tile.water', lang), ...(water ? {reading: String(Math.round((water.row.WTMP as number) * 1.8 + 32)), unit: '°F'} : {reading: none}),
      ...judged(station('diablo', stations.nearshore_buoy), water?.at ?? null, ok('diablo'), limit('diablo'), now, lang),
      basis: t('landing.basis.water', lang, {station: name('diablo', 'nearshore', stations.nearshore_buoy), rule: rule('diablo'), same: same('diablo', 'offshore', 'wind', stations.nearshore_buoy, stations.offshore_buoy)})},
  ];
}

/** CO-OPS water level ("2026-10-08 01:30" in GMT), as the URL below asks for it. */
const coopsTime = (t: unknown): number => typeof t === 'string' && /^\d{4}-\d\d-\d\d \d\d:\d\d$/.test(t) ? Date.parse(t.replace(' ', 'T') + ':00Z') : NaN;
export const TIDE_LIMIT_H = 1;
export const tideURL = (station: string): string =>
  `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&application=SkipperCast&station=${encodeURIComponent(station)}&range=2&datum=MLLW&time_zone=gmt&units=english&format=json`;

/** Tide: the latest observed water level and whether it rose over the last two hours; `note` is the region's own caveat for the station. */
export function tideReading(response: unknown, station: string, stationName?: string, now = Date.now(), note?: string, lang: Language = 'en'): Reading {
  const rows = ((response as {data?: {t?: unknown; v?: unknown}[]})?.data ?? [])
    .map(r => ({at: coopsTime(r?.t), v: typeof r?.v === 'string' && r.v.trim() ? Number(r.v) : NaN}))
    .filter(r => Number.isFinite(r.at) && Number.isFinite(r.v)).sort((a, b) => a.at - b.at);
  const last = rows.at(-1), first = rows[0];
  const trend = last && first && last.at - first.at >= 30 * 60000 ? (last.v - first.v > 0.05 ? 'rising' : last.v - first.v < -0.05 ? 'falling' : 'slack') : undefined;
  return {
    id: 'tide', label: t('tile.tide', lang), ...(last ? {reading: lang === 'es' ? num(Number(last.v.toFixed(1)), lang, 1) : last.v.toFixed(1), unit: 'ft'} : {reading: t('landing.reading.none', lang)}), detail: trend && t(`landing.reading.${trend}`, lang),
    ...judged(`NOAA ${station}`, last?.at ?? null, true, TIDE_LIMIT_H, now, lang),
    basis: t('landing.basis.tide', lang, {station: stationName === undefined ? t('landing.tide.station', lang) : stationName, h: TIDE_LIMIT_H, note: note?.trim() ? ` ${note.trim()}` : ''}),
  };
}

/** The feed's own clock: when it was generated, and whether that is past v1's 90-minute rule. */
export function feedState(feed: unknown, now = Date.now()): FeedState {
  const at = time((feed as Feed)?.generated_at);
  if (!Number.isFinite(at)) return {age: null, stale: true};
  return {age: ageText(now - at), stale: now - at > FEED_LATE_MIN * 60000};
}

export interface Readout {readonly readings: Reading[]; readonly feed: FeedState; /** The region the stations are read for (region.json `name`). */ readonly place?: string}

/** Load the default region's readings; every failure becomes an unavailable tile, never an error. */
export async function loadReadout(fetchFn: typeof fetch = fetch, region = DEFAULT_REGION, now: () => number = Date.now, lang: Language = 'en'): Promise<Readout> {
  const json = async (url: string): Promise<unknown> => {
    const response = await fetchFn(url, {signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw Error(`${url} ${response.status}`);
    return response.json();
  };
  const info = await json(`regions/${encodeURIComponent(region)}/region.json`).catch(() => ({})) as RegionStations;
  const station = info.stations?.tide ?? '9412110';
  const [feed, tide] = await Promise.all([json(feedPath(info.conditions_feed, region)).catch(() => null), json(tideURL(station)).catch(() => null)]);
  const at = now();
  return {readings: [...buoyReadings(feed, info, at, lang), tideReading(tide, station, info.stations?.tide_name, at, info.stations?.tide_note, lang)], feed: feedState(feed, at),
    place: typeof info.name === 'string' && info.name.trim() ? info.name.trim() : DEFAULT_PLACE};
}
