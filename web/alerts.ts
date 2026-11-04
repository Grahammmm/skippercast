// Saved-trip alerts and private comfort feedback (US-R5, #602): the logic the
// account menu's alerts dialog (web/app/TripAlerts.tsx) runs. Ported from v1's
// dist/trip-alerts.js with the same /api/ calls and request bodies, so trips,
// assessments, push subscriptions and feedback already saved in D1 read and
// write unchanged.
//
// Erasable syntax only: the node tests import this file by type stripping.

import {DEFAULT_ZONE} from './zone.ts';

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
  try { data = await r.json() as typeof data; } catch { throw Error('Personal services are available on the published site.'); }
  if (!r.ok) throw Error(data.error || 'Could not complete this request.');
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
export function alertSpecies(region: RegionAlerts, target: string | null): {options: SpeciesOption[]; value: string} {
  const named = new Map((region.target_options ?? []).map(t => [t.id, t]));
  const options = region.species.map(id => ({id, name: named.get(id)?.name ?? id, group: named.get(id)?.group ?? 'Other'}));
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
export function formProblem(form: AlertForm, range: {min: string; max: string}): string | null {
  const day = /^\d{4}-\d{2}-\d{2}$/.test(form.date) ? Date.parse(form.date + 'T12:00:00Z') : NaN;
  if (!Number.isFinite(day) || new Date(day).toISOString().slice(0, 10) !== form.date || form.date < range.min || form.date > range.max)
    return 'Choose a date from today to seven days ahead.';
  if (!(form.end_hour > form.start_hour)) return 'The window must end after it starts.';
  if (!(form.gust_limit >= form.wind_limit)) return 'The gust limit cannot be lower than the wind limit.';
  return null;
}

/** v2 has no forecast hour beside the dialog, so feedback carries no forecast context, as before. */
export const comfortBody = (region: string, rating: number, phase: string) =>
  ({region, rating, phase, wind: null, sea: null, period: null, heading: null, point: null});

export type SavedTrip = {id: string; date: string; point: string; species: string; start_hour: number; end_hour: number; boat_name?: string | null; boat_sea?: number | null};
export type AlertEvent = {id: string | number; trip_id?: string; kind: string; status: string; message: string};
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
export const tripLine = (t: SavedTrip, names?: AlertNames): string =>
  `${t.date} · ${names?.point.get(t.point) ?? t.point} · ${names?.species.get(t.species) ?? t.species} · ${t.start_hour}:00–${t.end_hour}:00${t.boat_sea ? ` · ${t.boat_name || 'saved boat'}` : ''}`;

/** The assessment kinds and delivery statuses server/trips.ts writes, in plain words. */
export const KIND_LABEL: Readonly<Record<string, string>> = {
  initial: 'First assessment', update: 'Material change', retraction: 'Earlier alert withdrawn', final: 'Day-before assessment', 'missed-final': 'Day-before assessment missed',
};
export const STATUS_LABEL: Readonly<Record<string, string>> = {
  pending: 'sending', accepted: 'sent to your device', uncertain: 'delivery not confirmed', held: 'not delivered — read it here', 'in-app': 'shown here', delivered: 'delivered', read: 'read',
};
const label = (labels: Readonly<Record<string, string>>, key: string): string => (Object.hasOwn(labels, key) ? labels[key] : undefined) ?? key;
/** The assessment's heading: "Day-before assessment · shown here"; an unknown kind or status prints as written. */
export const eventLine = (e: AlertEvent): string => `${label(KIND_LABEL, e.kind)} · ${label(STATUS_LABEL, e.status)}`;

/** The feedback's phase, or '' when its stored context does not parse. */
export function feedbackPhase(f: Feedback): string {
  try { const p = (JSON.parse(f.context) as {phase?: unknown})?.phase; return typeof p === 'string' ? p : ''; } catch { return ''; }
}

/** The VAPID key from base64url to bytes. */
export const b64 = (s: string): Uint8Array<ArrayBuffer> =>
  Uint8Array.from(atob(s.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0));

/** Subscribe this device to the account's push and register it with the server. */
export async function enablePush(publicKey: string | null | undefined): Promise<void> {
  if (!('serviceWorker' in navigator) || !('PushManager' in globalThis) || !publicKey) throw Error('Notifications are not available here. On iPad/iPhone, add SkipperCast to the Home Screen and open it there.');
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw Error('Notifications were not enabled. You can still read assessments here.');
  const registration = await navigator.serviceWorker.register('/sw.js');
  await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription() ?? await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: b64(publicKey)});
  await api('subscription', {method: 'POST', body: JSON.stringify(subscription.toJSON())});
}

export async function disablePush(): Promise<void> {
  await api('subscription', {method: 'DELETE'});
  const registration = await navigator.serviceWorker?.getRegistration('/sw.js');
  await (await registration?.pushManager.getSubscription())?.unsubscribe();
}
