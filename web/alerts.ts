// Saved-trip alerts and private comfort feedback (US-R5, #602): the logic the
// account menu's alerts dialog (web/app/TripAlerts.tsx) runs. Ported from v1's
// dist/trip-alerts.js with the same /api/ calls and request bodies, so trips,
// assessments, push subscriptions and feedback already saved in D1 read and
// write unchanged.
//
// Erasable syntax only: the node tests import this file by type stripping.

import {DEFAULT_ZONE} from './zone.ts';
import {t, type Language, type StringId} from './i18n.ts';

/** A message this module wrote itself, carried with its catalogue id so the sheet can show it in the language chosen when it is drawn. `.message` stays the English text. */
export class AlertCopyError extends Error {
  id: StringId;
  constructor(id: StringId) { super(t(id, 'en')); this.id = id; }
}

/** A boat's comfort factors (dist/boat-handling.js `boatFactors`). */
export type BoatFactors = {sea: number; wind: number; chopPeriod?: number; custom?: boolean};
export type TripBoat = {name: string; sea: number; wind: number; chop_period: number | undefined};
export type Limits = {wind: number; gust: number; sea: number};

/** Default comfort limits for the reference boat, scaled by the saved boat's factors and clamped to what the server accepts. */
export function tripDefaults(factors: BoatFactors = {sea: 1, wind: 1, custom: false}): Limits {
  const clamp = (v: number, lo: number, hi: number, step: number) => Math.min(hi, Math.max(lo, Math.round(v / step) * step));
  const wind = clamp(8 * factors.wind, 1, 30, 1), gust = Math.max(wind, clamp(12 * factors.wind, 1, 40, 1));
  return {wind, gust, sea: clamp(3 * factors.sea, .5, 10, .5)};
}

/** Profile comfort limits mapped to the trip form's accepted ranges and steps. */
export function profileTripDefaults(limits: {wind: number; gust: number; seas: number}): Limits {
  const reference = tripDefaults();
  const clamp = (v: number, fallback: number, lo: number, hi: number, step: number) =>
    Math.min(hi, Math.max(lo, Math.round((Number.isFinite(v) ? v : fallback) / step) * step));
  const wind = clamp(limits.wind, reference.wind, 1, 30, 1);
  return {wind, gust: Math.max(wind, clamp(limits.gust, reference.gust, 1, 40, 1)), sea: clamp(limits.seas, reference.sea, .5, 10, .5)};
}

/** The boat saved with the trip, or null for the reference boat. */
export function tripBoat(factors: BoatFactors | null | undefined, boat: {name?: unknown} | null | undefined): TripBoat | null {
  if (!factors?.custom) return null;
  return {name: typeof boat?.name === 'string' ? boat.name.slice(0, 80) : '', sea: factors.sea, wind: factors.wind, chop_period: factors.chopPeriod};
}

/** A JSON call to /api/; the server's error text, or a plain fallback, on failure. */
export async function api<T = Record<string, unknown>>(path: string, options: RequestInit = {}, fetchFn: typeof fetch = fetch): Promise<T> {
  const r = await fetchFn('/api/' + path, {signal: AbortSignal.timeout(20000), ...options, headers: {'Content-Type': 'application/json', ...options.headers as Record<string, string>}});
  let data: {error?: string} & Record<string, unknown>;
  try { data = await r.json() as typeof data; } catch { throw new AlertCopyError('alerts.err.personal'); }
  if (!r.ok) throw data.error ? Error(data.error) : new AlertCopyError('alerts.err.request');
  return data as T;
}

/** Tomorrow in the region's zone, as the date input's value: today's zone date (dateRange's min) plus one calendar day, so DST nights do not skip or repeat a day. */
export const alertDate = (timeZone: string, now: number = Date.now()): string => new Date(Date.parse(dateRange(timeZone, now).min + 'T12:00:00Z') + 86400000).toISOString().slice(0, 10);

export type RegionAlerts = {
  id: string; timezone: string; species: string[];
  forecast_points: {id: string; name: string}[];
  target_options?: {id: string; name: string; group?: string}[];
};
export type SpeciesOption = {id: string; name: string; group: string};

/** The alert species: the region's listed species with their names, starting on the app's target when the region lists it. */
export function alertSpecies(region: RegionAlerts, target: string | null, lang: Language = 'en'): {options: SpeciesOption[]; value: string} {
  const named = new Map((region.target_options ?? []).map(o => [o.id, o]));
  const options = region.species.map(id => ({id, name: named.get(id)?.name ?? id, group: named.get(id)?.group ?? t('alerts.other', lang)}));
  return {options, value: target && region.species.includes(target) ? target : region.species[0] ?? ''};
}

export type AlertForm = {date: string; point: string; start_hour: number; end_hour: number; wind_limit: number; gust_limit: number; sea_limit: number};
/** POST /api/trips's body: the form, the region, the species and the saved boat when there is one. */
export const tripBody = (form: AlertForm, region: string, species: string, boat: TripBoat | null) => ({...form, region, species, ...(boat ? {boat} : {})});

/** The trip dates the server accepts: today to seven calendar days ahead in the region's zone (server/trips.ts plusDays). */
export const dateRange = (timeZone: string, now: number = Date.now()): {min: string; max: string} => {
  const min = new Intl.DateTimeFormat('en-CA', {timeZone}).format(new Date(now));
  return {min, max: new Date(Date.parse(min + 'T12:00:00Z') + 7 * 86400000).toISOString().slice(0, 10)};
};

/** What the server would refuse first, in plain words, or null; checked before the form is sent. */
export function formProblemId(form: AlertForm, range: {min: string; max: string}): StringId | null {
  const day = /^\d{4}-\d{2}-\d{2}$/.test(form.date) ? Date.parse(form.date + 'T12:00:00Z') : NaN;
  if (!Number.isFinite(day) || new Date(day).toISOString().slice(0, 10) !== form.date || form.date < range.min || form.date > range.max)
    return 'alerts.problem.date';
  if (!(form.end_hour > form.start_hour)) return 'alerts.problem.window';
  if (!(form.gust_limit >= form.wind_limit)) return 'alerts.problem.gust';
  return null;
}
/** The same first problem in words, in `lang`; English by default. */
export function formProblem(form: AlertForm, range: {min: string; max: string}, lang: Language = 'en'): string | null {
  const id = formProblemId(form, range);
  return id ? t(id, lang) : null;
}

/** v2 has no forecast hour beside the dialog, so feedback carries no forecast context, as before. */
export const comfortBody = (region: string, rating: number, phase: string) =>
  ({region, rating, phase, wind: null, sea: null, period: null, heading: null, point: null});

export type SavedTrip = {id: string; region?: string; date: string; point: string; species: string; start_hour: number; end_hour: number; boat_name?: string | null; boat_sea?: number | null; wind_limit?: number; gust_limit?: number; sea_limit?: number; targets?: unknown; plan?: unknown};
/** What a saved trip lets the form reuse. `omitted` names what was left out, in order: area, species, hours, limits. */
export type ReuseOmission = 'area' | 'species' | 'hours' | 'limits';
export type Reuse = {fields: Partial<Omit<AlertForm, 'date'>>; species: string | null; omitted: ReuseOmission[]};
const inRange = (v: unknown, lo: number, hi: number, step: number): v is number => typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi && Number.isInteger(v / step);

/**
 * The parts of a saved trip the alert form can start from again, as stored (never scaled, rounded or clamped), without its date.
 * The area counts only from this region and while the region still lists it; the species only while the region lists it.
 * Hours and wind/gust copy as valid pairs, the sea limit alone; anything else is left out and named. Pure: nothing is read or changed.
 */
export function reuseTrip(trip: SavedTrip, region: RegionAlerts): Reuse {
  const fields: Reuse['fields'] = {}, omitted: ReuseOmission[] = [];
  let species: string | null = null;
  if (trip.region === region.id && typeof trip.point === 'string' && region.forecast_points.some(p => p.id === trip.point)) fields.point = trip.point;
  else omitted.push('area');
  if (typeof trip.species === 'string' && region.species.includes(trip.species)) species = trip.species;
  else omitted.push('species');
  const {start_hour: s, end_hour: e, wind_limit: w, gust_limit: g, sea_limit: sea} = trip;
  if (inRange(s, 0, 22, 1) && inRange(e, 1, 23, 1) && e > s) { fields.start_hour = s; fields.end_hour = e; } else omitted.push('hours');
  let lost = false;
  if (inRange(w, 1, 30, 1) && inRange(g, 1, 40, 1) && g >= w) { fields.wind_limit = w; fields.gust_limit = g; } else lost = true;
  if (inRange(sea, .5, 10, .5)) fields.sea_limit = sea; else lost = true;
  if (lost) omitted.push('limits');
  return {fields, species, omitted};
}

/** How many of the three limits a reuse copied: all, some or none. */
export const reusedLimits = (fields: Reuse['fields']): 'all' | 'some' | 'none' => {
  const n = [fields.wind_limit, fields.gust_limit, fields.sea_limit].filter(v => v !== undefined).length;
  return n === 3 ? 'all' : n ? 'some' : 'none';
};

/** The alert form as the fill needs it: its named controls (a real HTMLFormElement's `elements` fits). */
export type FillableForm = {elements: {namedItem(name: string): {value: string; focus?(): void} | null}};
/** Puts a reuse's fields into the form's own controls, leaves the date empty for the person to choose and focuses it. Touches only the form: no request, no storage. */
export function fillAlertForm(form: FillableForm, reuse: Reuse): void {
  for (const [name, value] of Object.entries(reuse.fields)) { const control = form.elements.namedItem(name); if (control) control.value = String(value); }
  const date = form.elements.namedItem('date');
  if (date) { date.value = ''; date.focus?.(); }
}

const OMITTED_TEXT: Readonly<Record<ReuseOmission, StringId>> = {
  area: 'alerts.reuse.area', species: 'alerts.reuse.species', hours: 'alerts.reuse.hours', limits: 'alerts.reuse.limits',
};
/** The status after Use again: what was copied and, in order, what was left out. */
export const reuseStatus = (omitted: readonly ReuseOmission[], lang: Language = 'en'): string => [t('alerts.reuse.copied', lang), ...omitted.map(o => t(OMITTED_TEXT[o], lang))].join(' ');

/** The limits note once they came from a saved trip, replacing the profile/boat wording; the boat part says the current boat is what alerts use. */
export const reuseLimitsNote = (date: string, copied: 'all' | 'some', boat: boolean, lang: Language = 'en'): string =>
  `${t(copied === 'all' ? 'alerts.reuse.all' : 'alerts.reuse.some', lang, {date})} ${t(boat ? 'alerts.reuse.boat' : 'alerts.reuse.noBoat', lang)}`;

export type AlertEvent = {id: string | number; trip_id?: string; kind: string; status: string; message: string; created_at?: string};
export type Feedback = {observed_at: string; rating: number; context: string};

/** The recap's minimal projection of one private catch-log row (the signed-in GET /api/catch-log answer): no coordinates, note, owner, method or species. */
export type CatchLogEntry = {id: string; trip_id: string | null; started_at: string; outcome: 'fish' | 'blank' | 'unknown'; count: number};

/** The well-formed rows of a GET /api/catch-log answer, reduced to CatchLogEntry in the answer's order; anything else gives []. */
export function catchLogEntries(answer: unknown): CatchLogEntry[] {
  const rows = (answer as {entries?: unknown} | null)?.entries;
  if (!Array.isArray(rows)) return [];
  const kept: CatchLogEntry[] = [];
  for (const row of rows as Record<string, unknown>[]) {
    if (!row || typeof row.id !== 'string' || typeof row.started_at !== 'string') continue;
    const {outcome, count} = row;
    if (outcome !== 'fish' && outcome !== 'blank' && outcome !== 'unknown') continue;
    if (typeof count !== 'number' || !Number.isInteger(count) || count < 0) continue;
    kept.push({id: row.id, trip_id: typeof row.trip_id === 'string' && row.trip_id ? row.trip_id : null, started_at: row.started_at, outcome, count});
  }
  return kept;
}

/** At most this many sequential GET /api/catch-log requests (each up to 200 rows) per recap read: a fixed bound on the dialog's work, never derived from a date. */
export const RECAP_PAGE_CAP = 10;
export type RecapCatchLog = {entries: CatchLogEntry[]; complete: boolean};

/**
 * The recap's whole catch log: GET /api/catch-log, then each page's opaque X-SC-Catch-Log-Next-Cursor, up to RECAP_PAGE_CAP pages.
 * `complete` is true only when a well-formed page said X-SC-Catch-Log-Has-More: false and no row was dropped. A failed page, a bad header,
 * a repeated cursor or the cap stops the read with what was read so far and complete false. It never stops because of a time: entries join a
 * trip by exact trip id, whatever their started_at. Never rejects; aborting `signal` ends the read (incomplete) without further requests.
 */
export async function readRecapCatchLog(fetchFn: typeof fetch = fetch, signal?: AbortSignal): Promise<RecapCatchLog> {
  const entries: CatchLogEntry[] = [], seen = new Set<string>(), used = new Set<string>();
  let cursor: string | null = null, rejected = false;
  for (let page = 0; page < RECAP_PAGE_CAP; page++) {
    if (signal?.aborted) return {entries, complete: false};
    const controller = new AbortController(), stop = () => controller.abort(), timer = setTimeout(stop, 20000);
    signal?.addEventListener('abort', stop);
    let response: Response, answer: unknown;
    try {
      response = await fetchFn('/api/catch-log' + (cursor === null ? '' : `?cursor=${encodeURIComponent(cursor)}`), {signal: controller.signal, headers: {'Content-Type': 'application/json'}});
      answer = await response.json();
    } catch { return {entries, complete: false}; } finally { clearTimeout(timer); signal?.removeEventListener('abort', stop); }
    if (signal?.aborted || !response.ok) return {entries, complete: false};
    const rows = (answer as {entries?: unknown} | null)?.entries;
    if (!Array.isArray(rows)) return {entries, complete: false};
    const kept = catchLogEntries(answer);
    if (kept.length !== rows.length) rejected = true;
    for (const entry of kept) if (!seen.has(entry.id)) { seen.add(entry.id); entries.push(entry); }
    const more = response.headers.get('X-SC-Catch-Log-Has-More');
    if (more === 'false') return {entries, complete: !rejected};
    const next = response.headers.get('X-SC-Catch-Log-Next-Cursor');
    if (more !== 'true' || !next || used.has(next)) return {entries, complete: false};
    used.add(next);
    cursor = next;
  }
  return {entries, complete: false};
}

/** Group private records by Pacific trip date; later array entries win within each assessment kind. Catch-log rows join only by exact trip id. */
export function tripRecaps(trips: SavedTrip[], events: AlertEvent[], feedback: Feedback[], today: string, entries: CatchLogEntry[] = []): {
  upcoming: SavedTrip[]; past: {trip: SavedTrip; final: AlertEvent | null; reports: Feedback[]; catches: CatchLogEntry[]}[];
} {
  const logged = new Map<string, CatchLogEntry[]>();
  for (const entry of entries) if (entry.trip_id) logged.set(entry.trip_id, [...(logged.get(entry.trip_id) ?? []), entry]);
  const days = new Intl.DateTimeFormat('en-CA', {timeZone: DEFAULT_ZONE});
  const reports = new Map<string, Feedback[]>();
  for (const report of feedback) {
    const at = new Date(report.observed_at);
    if (!Number.isFinite(at.getTime())) continue;
    const day = days.format(at);
    reports.set(day, [...(reports.get(day) ?? []), report]);
  }
  const finals = new Map<string, AlertEvent>(), missed = new Map<string, AlertEvent>();
  for (const event of events) {
    if (!event.trip_id) continue;
    if (event.kind === 'final') finals.set(event.trip_id, event);
    else if (event.kind === 'missed-final') missed.set(event.trip_id, event);
  }
  return {
    upcoming: trips.filter(t => t.date >= today).sort((a, b) => a.date.localeCompare(b.date)),
    past: trips.filter(t => t.date < today).sort((a, b) => b.date.localeCompare(a.date)).map(trip => ({
      trip, final: finals.get(trip.id) ?? missed.get(trip.id) ?? null, reports: reports.get(trip.date) ?? [], catches: logged.get(trip.id) ?? [],
    })),
  };
}

export type AlertNames = {point: Map<string, string>; species: Map<string, string>};
/** The region's area and species names by id (species named as in the alert species list). */
export const alertNames = (region: RegionAlerts): AlertNames => ({
  point: new Map(region.forecast_points.map(p => [p.id, p.name])),
  species: new Map(alertSpecies(region, null).options.map(o => [o.id, o.name])),
});

/** The saved trip's line: "2026-11-02 · Point Sur · Rockfish · 7:00–13:00" with names (raw ids without them or when unknown), with the saved boat when it has one. */
export const tripLine = (trip: SavedTrip, names?: AlertNames, lang: Language = 'en'): string =>
  `${trip.date} · ${names?.point.get(trip.point) ?? trip.point} · ${names?.species.get(trip.species) ?? trip.species} · ${trip.start_hour}:00–${trip.end_hour}:00${trip.boat_sea ? ` · ${trip.boat_name || t('alerts.savedBoat', lang)}` : ''}`;

/** What a saved trip's stored plan shows: target names, stop names in saved order and summed leg totals. Never positions, notes or ids. */
export type TripPlanSummary =
  | {kind: 'saved'; targets: string[]; stops: string[]; totals: {nm: string; minutes: string} | null}
  | {kind: 'unavailable'};

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const fixed5 = (units: number) => String(units / 100000);

/** The plan saved with a trip (SC1822-04), read from the parsed GET answer: null without one, 'unavailable' when it is malformed (no partial totals). */
export function tripPlanSummary(trip: SavedTrip, names?: AlertNames, lang: Language = 'en'): TripPlanSummary | null {
  const plan = trip.plan;
  if (plan === undefined || plan === null) return null;
  if (!isObj(plan) || !Array.isArray(plan.spots) || !Array.isArray(plan.legs)) return {kind: 'unavailable'};
  const spots: {name: string; order: number; i: number}[] = [];
  for (const [i, s] of plan.spots.entries()) {
    if (!isObj(s) || typeof s.name !== 'string' || typeof s.order !== 'number' || !Number.isInteger(s.order) || s.order < 0) return {kind: 'unavailable'};
    spots.push({name: s.name, order: s.order, i});
  }
  let nm = 0, minutes = 0;
  for (const l of plan.legs) {
    if (!isObj(l) || typeof l.nm !== 'number' || typeof l.minutes !== 'number' || !Number.isFinite(l.nm) || !Number.isFinite(l.minutes) || l.nm < 0 || l.minutes < 0) return {kind: 'unavailable'};
    nm += Math.round(l.nm * 100000); minutes += Math.round(l.minutes * 100000);
  }
  const ids = Array.isArray(trip.targets) && trip.targets.length && trip.targets.every(t => typeof t === 'string') ? trip.targets as string[] : [trip.species];
  return {kind: 'saved',
    targets: ids.map(id => names?.species.get(id) ?? id),
    stops: spots.sort((a, b) => a.order - b.order || a.i - b.i).map(s => s.name.trim() ? s.name : t('alerts.unnamedStop', lang)),
    totals: plan.legs.length ? {nm: fixed5(nm), minutes: fixed5(minutes)} : null};
}

/** The assessment kinds and delivery statuses server/trips.ts writes, in plain words: finite maps from the server's own keys to catalogue ids. */
const KIND_ID: Readonly<Record<string, StringId>> = {
  initial: 'alerts.kind.initial', update: 'alerts.kind.update', retraction: 'alerts.kind.retraction', final: 'alerts.kind.final', 'missed-final': 'alerts.kind.missedFinal',
};
const STATUS_ID: Readonly<Record<string, StringId>> = {
  pending: 'alerts.delivery.pending', accepted: 'alerts.delivery.accepted', uncertain: 'alerts.delivery.uncertain', held: 'alerts.delivery.held',
  'in-app': 'alerts.delivery.inApp', delivered: 'alerts.delivery.delivered', read: 'alerts.delivery.read',
};
const words = (ids: Readonly<Record<string, StringId>>, lang: Language): Readonly<Record<string, string>> => Object.fromEntries(Object.entries(ids).map(([key, id]) => [key, t(id, lang)]));
/** The English labels, kept for callers that read the tables. */
export const KIND_LABEL: Readonly<Record<string, string>> = words(KIND_ID, 'en');
export const STATUS_LABEL: Readonly<Record<string, string>> = words(STATUS_ID, 'en');
const label = (ids: Readonly<Record<string, StringId>>, key: string, lang: Language): string => (Object.hasOwn(ids, key) ? t(ids[key]!, lang) : key);
/** The assessment kind or delivery status in `lang`; an unknown key (or an inherited name) prints as written. */
export const kindLabel = (key: string, lang: Language = 'en'): string => label(KIND_ID, key, lang);
export const statusLabel = (key: string, lang: Language = 'en'): string => label(STATUS_ID, key, lang);
/** The assessment's heading: "Day-before assessment · shown here"; an unknown kind or status prints as written. */
export const eventLine = (e: AlertEvent, lang: Language = 'en'): string => `${kindLabel(e.kind, lang)} · ${statusLabel(e.status, lang)}`;

/** The newest event GET /api/trips returned for this exact trip (the list is newest first), or null when none of the returned events is its own. */
export function latestTripEvent(events: readonly AlertEvent[], tripId: string): AlertEvent | null {
  if (typeof tripId !== 'string' || !tripId) return null;
  return events.find(e => e.trip_id === tripId) ?? null;
}

/** The limits the trip was saved with, as stored: "Saved limits: wind 9 kt · gust 14 kt · sea 2.5 ft"; a field that is not a finite number reads "not recorded". */
export function savedTripLimits(trip: SavedTrip, lang: Language = 'en'): string {
  const v = (x: unknown, unit: string): string => (typeof x === 'number' && Number.isFinite(x) ? `${x} ${unit}` : t('alerts.notRecorded', lang));
  return t('alerts.limits', lang, {wind: v(trip.wind_limit, 'kt'), gust: v(trip.gust_limit, 'kt'), sea: v(trip.sea_limit, 'ft')});
}

/** The assessment's time in the region's zone, or "Time unavailable" when it has no usable timestamp. */
export function assessmentTimeOrNull(e: AlertEvent, timeZone: string = DEFAULT_ZONE, lang: Language = 'en'): string | null {
  const d = typeof e.created_at === 'string' && e.created_at ? new Date(e.created_at) : null;
  if (!d || Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat(lang === 'es' ? 'es' : 'en-GB', {timeZone, year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'short'}).format(d);
}
export const assessmentTime = (e: AlertEvent, timeZone: string = DEFAULT_ZONE, lang: Language = 'en'): string => assessmentTimeOrNull(e, timeZone, lang) ?? t('alerts.timeUnavailable', lang);

/** The feedback's phase, or '' when its stored context does not parse; outbound, fishing and return in `lang`, anything else as stored. */
export function feedbackPhase(f: Feedback, lang: Language = 'en'): string {
  try {
    const p = (JSON.parse(f.context) as {phase?: unknown})?.phase;
    return typeof p === 'string' ? (lang === 'es' && Object.hasOwn(PHASE_ID, p) ? t(PHASE_ID[p]!, lang) : p) : '';
  } catch { return ''; }
}
const PHASE_ID: Readonly<Record<string, StringId>> = {outbound: 'alerts.comfort.outbound', fishing: 'alerts.comfort.fishing', return: 'alerts.comfort.return'};

/** The VAPID key from base64url to bytes. */
export const b64 = (s: string): Uint8Array<ArrayBuffer> =>
  Uint8Array.from(atob(s.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0));

/** Subscribe this device to the account's push and register it with the server. */
export async function enablePush(publicKey: string | null | undefined): Promise<void> {
  if (!('serviceWorker' in navigator) || !('PushManager' in globalThis) || !publicKey) throw new AlertCopyError('alerts.err.push');
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw new AlertCopyError('alerts.err.pushDenied');
  const registration = await navigator.serviceWorker.register('/sw.js');
  await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription() ?? await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: b64(publicKey)});
  await api('subscription', {method: 'POST', body: JSON.stringify(subscription.toJSON())});
}

/** How a stop request ended: the browser subscription was removed, this device had none, or the server stopped but the browser could not unsubscribe. */
export type StopResult = 'stopped' | 'none' | 'partial';
type PushNavigator = {serviceWorker?: {getRegistration(scope?: string): Promise<{pushManager: {getSubscription(): Promise<{endpoint: string; unsubscribe(): Promise<boolean>} | null>}} | undefined>}};

/** This browser's existing push subscription, found without registering a worker, asking permission or subscribing. */
const localSubscription = async (nav: PushNavigator) => (await nav.serviceWorker?.getRegistration('/sw.js'))?.pushManager.getSubscription() ?? null;
const unsubscribed = async (subscription: {unsubscribe(): Promise<boolean>}): Promise<StopResult> => {
  try { return (await subscription.unsubscribe()) ? 'stopped' : 'partial'; } catch { return 'partial'; }
};

/** Stop notifications on this device only: the server removes this endpoint's row, then this browser unsubscribes. Other devices keep theirs. */
export async function disablePush(fetchFn: typeof fetch = fetch, nav: PushNavigator = navigator): Promise<StopResult> {
  const subscription = await localSubscription(nav);
  if (!subscription) return 'none';
  let status = 0;
  const tracked: typeof fetch = async (input, init) => { const r = await fetchFn(input, init); status = r.status; return r; };
  try { await api('subscription', {method: 'DELETE', body: JSON.stringify({endpoint: subscription.endpoint})}, tracked); } catch (error) {
    // 404: the server already holds no row for this endpoint, so only the browser is left to clean up. Any other failure keeps the subscription for a retry.
    if (status !== 404) throw error;
  }
  return unsubscribed(subscription);
}

/** Stop notifications on every device of this account: the server removes all the caller's rows, then this browser unsubscribes if it has a subscription. */
export async function disableAllPush(fetchFn: typeof fetch = fetch, nav: PushNavigator = navigator): Promise<StopResult> {
  await api('subscription', {method: 'DELETE', body: JSON.stringify({all: true})}, fetchFn);
  try {
    const subscription = await localSubscription(nav);
    return subscription ? await unsubscribed(subscription) : 'stopped';
  } catch { return 'partial'; }
}

/** The catalogue id of the status line for a finished stop, from the scope the person chose. */
export const stopStatusId = (scope: 'device' | 'all', result: StopResult): StringId =>
  result === 'none' ? 'alerts.stop.none' : result === 'partial' ? 'alerts.stop.partial' : scope === 'all' ? 'alerts.stop.all' : 'alerts.stop.device';
/** The status line for a finished stop, in `lang` (English by default). */
export const stopStatus = (scope: 'device' | 'all', result: StopResult, lang: Language = 'en'): string => t(stopStatusId(scope, result), lang);

/** One stop action for the sheet: runs the chosen scope and returns the catalogue id of the status line to show. Errors propagate to the sheet's error line. */
export async function stopNotificationsId(scope: 'device' | 'all', fetchFn: typeof fetch = fetch, nav: PushNavigator = navigator): Promise<StringId> {
  return stopStatusId(scope, await (scope === 'all' ? disableAllPush : disablePush)(fetchFn, nav));
}
/** The same action with the status line in English. */
export async function stopNotifications(scope: 'device' | 'all', fetchFn: typeof fetch = fetch, nav: PushNavigator = navigator): Promise<string> {
  return t(await stopNotificationsId(scope, fetchFn, nav), 'en');
}
