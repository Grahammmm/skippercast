// The landing's readout (FE-07, design § 7, D4): wind, swell and water from
// the default region's live conditions feed (NDBC buoys, every 30 minutes)
// and tide from the NOAA CO-OPS water level the v1 page also reads. Each
// reading carries its source, its age and a stale state judged at `now`, so
// a reading that ages on screen turns stale; a missing one says so and is
// never filled from another station.
//
// Erasable syntax only: Node tests import this file by type stripping.

export const DEFAULT_REGION = 'morro-bay';
/** The default region's name (its region.json `name`, equal by test), shown until that loads: the readout names the place it reads (#422). */
export const DEFAULT_PLACE = 'Morro Bay & Avila';
/** "Morro Bay & Avila area"; a name that already ends in "area" is kept as it is. */
export const placeLabel = (name: string): string => /\barea$/i.test(name.trim()) ? name.trim() : `${name.trim()} area`;
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
interface Source {name?: string; status?: string; max_age_hours?: number; data?: {station?: string; units?: Record<string, string>; observations?: Row[]}}
interface Feed {schema_version?: number; generated_at?: string; sources?: Record<string, Source>}

const time = (value: unknown): number => typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? Date.parse(value) : NaN;
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const POINTS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
/** 16-point compass name for degrees true. */
export const compass = (deg: number): string => POINTS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]!;

/** "about 56 nm WNW of Morro Bay harbor" for NDBC `station`, or null when the region lacks either position. */
export function fromHarbor(region: RegionStations, station: string | undefined): string | null {
  const h = region.harbor, b = region.intelligence?.verification_stations?.find(s => s.id === station);
  if (!h?.name || !finite(h.latitude) || !finite(h.longitude) || !b || !finite(b.latitude) || !finite(b.longitude)) return null;
  const rad = Math.PI / 180, p1 = h.latitude * rad, p2 = b.latitude * rad, dl = (b.longitude - h.longitude) * rad;
  const nm = 2 * Math.asin(Math.sqrt(Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2)) * 3440.065;
  const bearing = Math.atan2(Math.sin(dl) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl)) / rad;
  return `about ${Math.round(nm)} nm ${compass(bearing)} of ${h.name} harbor`;
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
function judged(station: string, at: number | null, ok: boolean, limitH: number | null, now: number): {source: string; stale: boolean} {
  if (at === null || !Number.isFinite(at)) return {source: `${station} · unavailable`, stale: true};
  const stale = !ok || (limitH !== null && now - at > limitH * 3600000) || at - now > 5 * 60000;
  return {source: `${station} · ${ageText(now - at)}`, stale};
}

/** Wind, swell and water from the conditions feed; the region names the buoys when the feed is missing and places them against its harbor. */
export function buoyReadings(feed: unknown, region: RegionStations = {}, now = Date.now()): Reading[] {
  const f = (feed as Feed)?.schema_version === 1 ? feed as Feed : null;
  const stations = region.stations ?? {};
  const src = (key: string) => f?.sources?.[key];
  const stationId = (key: string, fallback?: string) => src(key)?.data?.station ?? fallback;
  const station = (key: string, fallback?: string) => `NDBC ${stationId(key, fallback) ?? '—'}`;
  const ok = (key: string) => src(key)?.status === 'ok';
  /** The source's own age limit; none is assumed when the feed gives none. */
  const limit = (key: string): number | null => finite(src(key)?.max_age_hours) ? src(key)!.max_age_hours! : null;
  const name = (key: string, fallback: string, buoy?: string) => {
    const where = fromHarbor(region, stationId(key, buoy));
    return `the ${src(key)?.name ?? fallback} buoy${where ? `, ${where}` : ''}`;
  };

  const wind = newest(src('offshore'), 'WSPD', 'm/s');
  const gust = wind && finite(wind.row.GST) ? Math.round((wind.row.GST as number) * 1.943844) : null;
  const windFrom = wind && finite(wind.row.WDIR) ? compass(wind.row.WDIR as number) : null;
  const swell = newest(src('diablo-spectrum'), 'SwH', 'm');
  const period = swell && finite(swell.row.SwP) ? `${Math.round(swell.row.SwP as number)} s` : null;
  const water = newest(src('diablo'), 'WTMP', 'degC');
  const rule = (key: string) => { const h = limit(key); return h === null ? 'the feed gives no age limit, so only the age is shown' : `stale after ${h} h`; };
  return [
    {id: 'wind', label: 'Wind', ...(wind ? {reading: String(Math.round((wind.row.WSPD as number) * 1.943844)), unit: 'kt'} : {reading: 'No reading'}),
      detail: [windFrom, gust !== null ? `gusts ${gust}` : null].filter(Boolean).join(' · ') || undefined,
      ...judged(station('offshore', stations.offshore_buoy), wind?.at ?? null, ok('offshore'), limit('offshore'), now),
      basis: `Observed wind at ${name('offshore', 'offshore', stations.offshore_buoy)}, out at sea: not a harbor or launch reading. Averaged over 8 minutes, with the peak gust; ${rule('offshore')}.`},
    {id: 'swell', label: 'Swell', ...(swell ? {reading: ((swell.row.SwH as number) * 3.28084).toFixed(1), unit: 'ft'} : {reading: 'No reading'}),
      detail: [period, swell && typeof swell.row.SwD === 'string' && /^[NSEW]{1,3}$/.test(swell.row.SwD) ? swell.row.SwD : null].filter(Boolean).join(' · ') || undefined,
      ...judged(station('diablo-spectrum', stations.nearshore_buoy), swell?.at ?? null, ok('diablo-spectrum'), limit('diablo-spectrum'), now),
      basis: `Swell height, period and direction from the wave spectrum at ${name('diablo', 'nearshore', stations.nearshore_buoy)}; wind waves are left out; ${rule('diablo-spectrum')}.`},
    {id: 'water', label: 'Water', ...(water ? {reading: String(Math.round((water.row.WTMP as number) * 1.8 + 32)), unit: '°F'} : {reading: 'No reading'}),
      ...judged(station('diablo', stations.nearshore_buoy), water?.at ?? null, ok('diablo'), limit('diablo'), now),
      basis: `Surface water temperature measured at ${name('diablo', 'nearshore', stations.nearshore_buoy)}; ${rule('diablo')}.`},
  ];
}

/** CO-OPS water level ("2026-10-08 01:30" in GMT), as the URL below asks for it. */
const coopsTime = (t: unknown): number => typeof t === 'string' && /^\d{4}-\d\d-\d\d \d\d:\d\d$/.test(t) ? Date.parse(t.replace(' ', 'T') + ':00Z') : NaN;
export const TIDE_LIMIT_H = 1;
export const tideURL = (station: string): string =>
  `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&application=SkipperCast&station=${encodeURIComponent(station)}&range=2&datum=MLLW&time_zone=gmt&units=english&format=json`;

/** Tide: the latest observed water level and whether it rose over the last two hours; `note` is the region's own caveat for the station. */
export function tideReading(response: unknown, station: string, stationName = 'the tide station', now = Date.now(), note?: string): Reading {
  const rows = ((response as {data?: {t?: unknown; v?: unknown}[]})?.data ?? [])
    .map(r => ({at: coopsTime(r?.t), v: typeof r?.v === 'string' && r.v.trim() ? Number(r.v) : NaN}))
    .filter(r => Number.isFinite(r.at) && Number.isFinite(r.v)).sort((a, b) => a.at - b.at);
  const last = rows.at(-1), first = rows[0];
  const trend = last && first && last.at - first.at >= 30 * 60000 ? (last.v - first.v > 0.05 ? 'rising' : last.v - first.v < -0.05 ? 'falling' : 'slack') : undefined;
  return {
    id: 'tide', label: 'Tide', ...(last ? {reading: last.v.toFixed(1), unit: 'ft'} : {reading: 'No reading'}), detail: trend,
    ...judged(`NOAA ${station}`, last?.at ?? null, true, TIDE_LIMIT_H, now),
    basis: `Observed water level at ${stationName}, in feet above mean lower low water, every 6 minutes; stale after ${TIDE_LIMIT_H} h.${note?.trim() ? ` ${note.trim()}` : ''}`,
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
export async function loadReadout(fetchFn: typeof fetch = fetch, region = DEFAULT_REGION, now: () => number = Date.now): Promise<Readout> {
  const json = async (url: string): Promise<unknown> => {
    const response = await fetchFn(url, {signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw Error(`${url} ${response.status}`);
    return response.json();
  };
  const info = await json(`regions/${encodeURIComponent(region)}/region.json`).catch(() => ({})) as RegionStations;
  const station = info.stations?.tide ?? '9412110';
  const [feed, tide] = await Promise.all([json(feedPath(info.conditions_feed, region)).catch(() => null), json(tideURL(station)).catch(() => null)]);
  const at = now();
  return {readings: [...buoyReadings(feed, info, at), tideReading(tide, station, info.stations?.tide_name, at, info.stations?.tide_note)], feed: feedState(feed, at),
    place: typeof info.name === 'string' && info.name.trim() ? info.name.trim() : DEFAULT_PLACE};
}
