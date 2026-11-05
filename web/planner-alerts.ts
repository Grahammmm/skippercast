// SC1822-04: the planner's plan as a private trip alert. The projection from the plan to POST /api/trips's body (allowlist only: snapshot-local
// stop ids, empty notes, no source record), the region target and forecast-area rules, the checks that refuse a plan instead of trimming it, and
// the bounded request. The planner (web/planner.ts) supplies the resolved, screened stops; nothing here reads storage, a note or the network
// except the one POST. Erasable syntax only: the node tests import this file by type stripping.
import {distanceNm} from '../dist/spot-ranking.js';
import {api, dateRange, formProblem, profileTripDefaults, tripBody, tripBoat, tripDefaults, type BoatFactors, type Limits, type TripBoat} from './alerts.ts';

export type AlertRegion = {id: string; timezone: string; species?: string[]; forecast_points?: {id: string; name: string; latitude: number; longitude: number}[]};
/** One stop of the snapshot, in plan order: the launch (when included) is last and marked. */
export type AlertStop = {id: string; name: string; lat: number; lon: number; launch?: boolean};
/** The planner's settings for one attempt (web/limits.ts and dist/boat-handling.js): the profile, whether Boat has its own limits, the profile's limits, the boat factors and saved boat. */
export type AlertSettings = {profile: string; ownBoatLimits: boolean; limits: {wind: number; gust: number; seas: number}; factors: BoatFactors; boat: {name?: unknown} | null};
export type AlertLegs = {legs: {from: string; to: string; nm: number; runMin: number | null; basis: 'water' | 'straight'; screen?: unknown}[]; skipped: string[]};
export type AlertInput = {
  region: AlertRegion; now: number; date: string; stops: AlertStop[]; unresolved: boolean; species: string; settings: AlertSettings;
  legs: (stops: AlertStop[]) => AlertLegs; refused: (stop: AlertStop) => boolean;
};
export type AlertPreview = {date: string; area: string; target: string; groupNote: string; hours: string; limits: Limits; boat: string; stops: number; legs: number; legList: {from: string; to: string; nm: number; minutes: number; basis: 'water' | 'straight'; screen: unknown}[]};
export type AlertPlan = {ok: true; body: Record<string, unknown>; preview: AlertPreview} | {ok: false; message: string; code: 'date' | 'plan' | 'region'};

export const MSG = {
  date: 'Choose a fishing date from today to seven days ahead in this region to save alerts.',
  unresolved: 'Some selected stops are unavailable. Review your plan before saving alerts.',
  none: 'Select at least one stop to save alerts.',
  many: 'Trip alerts can save up to 12 stops, including the launch. Uncheck stops before saving.',
  screen: 'A selected stop is inside, near, or not checked against protected areas. Review the plan before saving alerts.',
  area: 'No forecast area is available for these stops.',
  target: 'This region does not offer alerts for the plan’s target.',
  legs: 'Set a valid cruise speed and review the leg distances before saving alerts.',
  big: 'This plan is too large to save with alerts. Reduce the selected stops.',
  changed: 'Your plan or account changed. Review it and try again.',
  settings: 'Your boat and limits could not be read. Try again.',
  done: 'Trip saved with this plan. Checks run about every 30 minutes. Notifications require device permission; read assessments in Saved-trip alerts.',
  conflict: 'You already have 20 active trips. Delete an upcoming trip in Saved-trip alerts before saving another.',
  invalid: 'This trip could not be saved. Check its date, area, targets and limits, then try again.',
  auth: 'Sign in again to save trip alerts.',
  unknown: 'Could not confirm this trip was saved. Check Saved-trip alerts before trying again.',
  again: 'This plan is already saved. Change the plan, date or limits to save another.',
} as const;
export const GROUP_NOTE = 'This region groups lingcod and rockfish alerts under Reef.';
export const AREA_NOTE = 'Nearest to the first stop; alerts assess this area, not conditions at every stop.';
export const WINDOW = {depart: '07:00', return_by: '13:00', hours: [7, 8, 9, 10, 11, 12]} as const;
const MAX_STOPS = 12, MAX_LEGS = 13, PLAN_BYTES = 16384, BODY_BYTES = 24576;

/** A display name without control characters, at most 80 UTF-16 units and never ending in half a surrogate pair. */
export function cleanName(raw: unknown, fallback: string): string {
  let s = (typeof raw === 'string' ? raw : '').replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 80);
  if (/[\ud800-\udbff]$/.test(s)) s = s.slice(0, -1);
  if (/^[\udc00-\udfff]/.test(s)) s = s.slice(1);
  return s.trim() || fallback;
}

/** The target ids the region lists for the planner's choice: the exact id, or lingcod/rockfish grouped under the listed reef; null when neither. */
export function alertTarget(region: AlertRegion, species: string): {id: string; grouped: boolean} | null {
  const listed = region.species ?? [];
  if (listed.includes(species)) return {id: species, grouped: false};
  if ((species === 'lingcod' || species === 'rockfish') && listed.includes('reef')) return {id: 'reef', grouped: true};
  return null;
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
/** The region's forecast point nearest `first`; only listed points with a nonempty id and valid WGS84 position qualify, a tie keeps the published order. */
export function nearestArea(region: AlertRegion, first: {lat: number; lon: number}): {id: string; name: string} | null {
  let best: {id: string; name: string} | null = null, bestNm = Infinity;
  for (const p of region.forecast_points ?? []) {
    if (!p || typeof p.id !== 'string' || !p.id || !finite(p.latitude) || !finite(p.longitude) || Math.abs(p.latitude) > 90 || Math.abs(p.longitude) > 180) continue;
    const nm = distanceNm({latitude: first.lat, longitude: first.lon}, {latitude: p.latitude, longitude: p.longitude}) as number;
    if (Number.isFinite(nm) && nm < bestNm) { best = {id: p.id, name: typeof p.name === 'string' && p.name ? p.name : p.id}; bestNm = nm; }
  }
  return best;
}

const bytes = (v: unknown): number => new TextEncoder().encode(JSON.stringify(v)).length;
const validStop = (s: AlertStop): boolean => finite(s.lat) && Math.abs(s.lat) <= 90 && finite(s.lon) && Math.abs(s.lon) <= 180;
const no = (message: string, code: 'date' | 'plan' | 'region' = 'plan'): AlertPlan => ({ok: false, message, code});

/** The request for the plan, or the one plain sentence that says why it cannot be saved. Pure: never trims, reorders or substitutes anything. */
export function buildAlertPlan(i: AlertInput): AlertPlan {
  const {region} = i;
  if (!region.species || !region.forecast_points) return no('', 'region');
  const range = dateRange(region.timezone, i.now);
  if (formProblem({date: i.date, point: '', start_hour: 7, end_hour: 13, wind_limit: 1, gust_limit: 1, sea_limit: 1}, range)) return no(MSG.date, 'date');
  if (i.unresolved) return no(MSG.unresolved);
  if (!i.stops.length) return no(MSG.none);
  if (i.stops.length > MAX_STOPS) return no(MSG.many);
  if (i.stops.some(s => !validStop(s))) return no(MSG.unresolved);
  if (i.stops.some(s => i.refused(s))) return no(MSG.screen);
  const target = alertTarget(region, i.species);
  if (!target) return no(MSG.target);
  const firstStop = i.stops.find(s => !s.launch) ?? i.stops[0]!, area = nearestArea(region, firstStop);
  if (!area) return no(MSG.area);

  const spots = i.stops.map((s, n) => ({id: `stop-${n + 1}`, name: cleanName(s.name, `Stop ${n + 1}`), lat: s.lat, lon: s.lon, order: n, notes: '', depth_ft: null}));
  const launch = i.stops.findIndex(s => s.launch);
  const computed = i.legs(i.stops);
  if (computed.skipped.length || computed.legs.length > MAX_LEGS) return no(MSG.legs);
  const legs = [], legList: AlertPreview['legList'] = [];
  for (const l of computed.legs) {
    if (!finite(l.nm) || l.nm < 0 || l.nm > 300 || !finite(l.runMin) || l.runMin < 0 || l.runMin > 1440) return no(MSG.legs);
    const from = cleanName(l.from, 'Stop'), to = cleanName(l.to, 'Stop');
    legs.push({from, to, nm: l.nm, minutes: l.runMin}); legList.push({from, to, nm: l.nm, minutes: l.runMin, basis: l.basis, screen: l.screen});
  }

  const s = i.settings, own = s.profile === 'boat' && s.ownBoatLimits;
  const limits = own || s.profile !== 'boat' ? profileTripDefaults(s.limits) : tripDefaults(s.factors);
  const boat: TripBoat | null = s.profile === 'boat' ? tripBoat(s.factors, s.boat) : null;
  const form = {date: i.date, point: area.id, start_hour: 7, end_hour: 13, wind_limit: limits.wind, gust_limit: limits.gust, sea_limit: limits.sea};
  if (formProblem(form, range)) return no(MSG.invalid);
  const plan = {spots, legs, window: {depart: WINDOW.depart, return_by: WINDOW.return_by, hours: [...WINDOW.hours]}, exports: []};
  const body = {...tripBody(form, region.id, target.id, null), boat, launch_point: launch >= 0 ? spots[launch]!.id : null, targets: [target.id], status: 'planned', plan};
  if (bytes(plan) > PLAN_BYTES || bytes(body) > BODY_BYTES) return no(MSG.big);
  const source = s.profile !== 'boat' ? 'Limits from your profile limits' : own ? 'Limits from your Boat limits, unscaled' : boat ? `Limits from your saved boat${boat.name ? ` (${boat.name})` : ''}` : 'Limits from the reference 23 ft boat';
  return {ok: true, body, preview: {date: i.date, area: area.name, target: target.id, groupNote: target.grouped ? GROUP_NOTE : '', hours: '07:00–13:00', limits, boat: source, stops: spots.length, legs: legs.length, legList}};
}

/** The sentence for a finished request: only a 201 with a nonempty id is success. */
export function resultMessage(status: number, data: unknown): {ok: boolean; message: string} {
  const id = (data as {id?: unknown} | null)?.id;
  if (status === 201) return typeof id === 'string' && id ? {ok: true, message: MSG.done} : {ok: false, message: MSG.unknown};
  if (status === 409) return {ok: false, message: MSG.conflict};
  if (status === 400) return {ok: false, message: MSG.invalid};
  if (status === 401 || status === 403) return {ok: false, message: MSG.auth};
  return {ok: false, message: MSG.unknown};
}

/** One POST /api/trips, same origin, no cache, aborted after 20 s or when `ctl` is; never retried (a timeout may have saved). Server text is never shown. */
export async function postTrip(body: unknown, fetchFn: typeof fetch, ctl: AbortController): Promise<{ok: boolean; message: string}> {
  let status = 0;
  const tracked: typeof fetch = async (input, init) => { const r = await fetchFn(input, init); status = r.status; return r; };
  const timer = setTimeout(() => ctl.abort(), 20000);
  try {
    const data = await api('trips', {method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: ctl.signal, body: JSON.stringify(body)}, tracked);
    return resultMessage(status, data);
  } catch { return resultMessage(status === 201 ? 0 : status, null); } finally { clearTimeout(timer); }
}
