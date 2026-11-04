// SC0022-08: the harbour-bar hazard hold for get_conditions. The Boat brief (web/brief/verdict.ts barHazard) holds a
// Comfortable word at Marginal when the bar estimate reads hazardous inside the window and names the hour; the advisor
// reads no bar, so on a Morro Bay boat day it could say comfortable while the brief said marginal. This applies the SAME
// shared estimate (packages/coast bar-conditions barHours, offshore basis, no nearshore site) to the hours the advisor
// already reads: the intelligence feed's GFS / GFS-Wave rows (as web/conditions.ts briefForecast maps them) and the
// daily feed's tide predictions (as web/brief/model.ts maps them). Nothing is fetched and no threshold is copied.
//
// An estimate, never a status: the check names a hazardous hour or says the bar was not (fully) judged, and carries the
// standing BAR_CHECK line. It never says the bar is open, closed or safe (prompts/system.ts).
import ports from '../../../catalog/home-ports.json' with {type: 'json'};
import {BAR_CHECK, barHours, entranceFor} from '../../../packages/coast/src/bar-conditions.ts';
import type {ForecastHour, TideEvent} from '../../../packages/coast/src/types.ts';
import {COMFORT_WORD} from './comfort.ts';
import {ALERT_CHECK_UNAVAILABLE, readHour, UNRATED_HOURS} from './conditions.ts';
import type {DayConditions, Window} from './conditions.ts';
import {localParts} from './time.ts';
import type {Region} from '../../types.ts';

/** The four regulated bars of 33 CFR 165.1196, by home-port id (no other port gets a bar, however near it is in the same region). */
const BAR_PORTS: ReadonlySet<string> = new Set(['morro-bay', 'humboldt-bay', 'noyo-harbor', 'crescent-city']);
const PORT_ROW = new Map(ports.ports.map(p => [p.id, p] as const));

export interface BarCheck {
  date: string; entrance: string; basis: 'offshore';
  /** True only when every selected hour had a known swell, a known tide phase and a band; it never means safe, open or clear to cross. */
  judged: boolean;
  /** The earliest hour (ISO) the bar estimate reads hazardous in the window, or null. */
  hazardous_at: string | null;
  note: string;
}
export interface BarInput {intel: unknown; daily: unknown; region: Region; port: string; pointId: string; date: string; window: Window}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const OFFSET_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?(Z|[+-]\d{2}:\d{2})$/;

/** The daily feed's tide highs and lows (all of them, so a bracket across midnight works); nothing when the source is not ok. */
function tideEvents(daily: unknown): TideEvent[] {
  const tides = isRecord(daily) && isRecord(daily.sources) ? daily.sources.tides : null;
  if (!isRecord(tides) || tides.status !== 'ok' || !isRecord(tides.data) || !Array.isArray(tides.data.predictions)) return [];
  const events: TideEvent[] = [];
  for (const row of tides.data.predictions as unknown[]) {
    if (!isRecord(row) || !finite(row.height_ft) || (row.type !== 'H' && row.type !== 'L') || typeof row.time !== 'string' || !OFFSET_TIME.test(row.time)) continue;
    events.push({at: row.time, heightFt: row.height_ft, type: row.type});
  }
  return events;
}

/** The window's hours at the port's forecast point as ForecastHour, mapped as web/conditions.ts does (never a daily rounded range). */
function windowHours(intel: unknown, region: Region, pointId: string, date: string, window: Window): ForecastHour[] {
  const point = region.forecast_points.findIndex(p => p.id === pointId);
  if (!isRecord(intel) || intel.region_id !== region.id || point < 0) return [];
  const feed = intel as {forecast?: {models?: {gfs_global?: {data?: ({hourly?: {time?: unknown}} | null)[]}}}};
  const times = feed.forecast?.models?.gfs_global?.data?.[point]?.hourly?.time;
  if (!Array.isArray(times)) return [];
  return times.filter((t: unknown): t is number => {
    if (!finite(t)) return false;
    const p = localParts(t * 1000, region.timezone);
    return p.date === date && p.hour >= window.start && p.hour <= window.end;
  }).map(t => {
    const h = readHour(feed, point, t);
    const sea = finite(h.sea_period) && h.sea_period > 0, swell = finite(h.swell_period) && h.swell_period > 0;
    return {
      at: new Date(t * 1000).toISOString(), windKnots: h.wind, gustKnots: h.gust !== null && h.wind !== null && h.gust >= h.wind ? h.gust : null,
      windDirectionDeg: h.wind_from,
      waveFt: sea ? h.sea : null, wavePeriodS: sea ? h.sea_period : null,
      swellFt: swell ? h.swell : null, swellPeriodS: swell ? h.swell_period : null,
    };
  });
}

/** The bar check for one trip date at a regulated port, or null for any other port (no new output at all). */
export function advisorBarCheck(input: BarInput): BarCheck | null {
  const {region, port, pointId, date} = input;
  if (!BAR_PORTS.has(port)) return null;
  const row = PORT_ROW.get(port);
  if (!row || row.region !== region.id || row.forecast_point !== pointId) return null;
  const entrance = entranceFor(region.id, region.id);
  if (!entrance) return null;
  const hours = windowHours(input.intel, region, pointId, date, input.window);
  const bar = barHours({hours, site: undefined, entrance, tideEvents: tideEvents(input.daily)});
  const hit = bar.filter(h => h.band === 'Hazardous').map(h => Date.parse(h.at)).sort((a, b) => a - b)[0];
  const missing: string[] = [];
  if (!bar.length) missing.push('forecast hours');
  else {
    if (bar.some(h => h.swell.heightFt === null)) missing.push('forecast swell');
    if (bar.some(h => h.tide.stage === null)) missing.push('tide phase');
  }
  const judged = bar.length > 0 && bar.every(h => h.swell.heightFt !== null && h.tide.stage !== null && h.band !== 'Unknown');
  const windUnknown = entrance.seawardDeg === null || hours.length === 0 || hours.some(h => h.windKnots === null || h.windDirectionDeg === null);
  const lead = judged ? 'Offshore bar estimate; nearshore conditions were not judged.'
    : `The bar was not fully judged from the available inputs${missing.length ? ` (missing: ${missing.join(' and ')})` : ''}.`;
  return {date, entrance: entrance.name, basis: 'offshore', judged, hazardous_at: hit === undefined ? null : new Date(hit).toISOString(),
    note: [lead, windUnknown ? 'Wind against the ebb was not judged.' : null, BAR_CHECK].filter(Boolean).join(' ')};
}

const clockText = (ms: number, tz: string): string => { const h = localParts(ms, tz).hour; return h === 12 ? 'noon' : h === 0 ? 'midnight' : `${h % 12} ${h < 12 ? 'am' : 'pm'}`; };
const LONG_PERIOD = 'long-period swell';

/**
 * The day as the bar allows (web/brief/verdict.ts): an available Comfortable day with a hazardous bar hour reads Bumpy and
 * names the local hour; a Bumpy day held for long-period swell, unrated hours or a missing alert check keeps those reasons and gains the bar's. Every other day, and
 * every measurement, is returned as it was. A hold never makes a day calmer.
 */
export function withBarHold(day: DayConditions, check: BarCheck | null | undefined, tz: string): DayConditions {
  if (!check?.hazardous_at || !day.available) return day;
  const held = day.comfort_held, reason = `the bar estimate reads hazardous at ${clockText(Date.parse(check.hazardous_at), tz)}`;
  if (day.comfort === COMFORT_WORD.go) return {...day, comfort: COMFORT_WORD.marginal, comfort_held: reason};
  if (day.comfort === COMFORT_WORD.marginal && held && (held.startsWith(LONG_PERIOD) || UNRATED_HOURS.test(held) || held.startsWith(ALERT_CHECK_UNAVAILABLE)) && !held.includes(reason)) return {...day, comfort_held: `${held}; ${reason}`};
  return day;
}
