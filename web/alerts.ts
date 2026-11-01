// Saved-trip alerts and private comfort feedback (US-R5, #602): the logic the
// account menu's alerts dialog (web/app/TripAlerts.tsx) runs. Ported from v1's
// dist/trip-alerts.js with the same /api/ calls and request bodies, so trips,
// assessments, push subscriptions and feedback already saved in D1 read and
// write unchanged.
//
// Erasable syntax only: the node tests import this file by type stripping.

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

/** Tomorrow in the region's zone, as the date input's value. */
export const alertDate = (timeZone: string, now: number = Date.now()): string => new Intl.DateTimeFormat('en-CA', {timeZone}).format(new Date(now + 86400000));

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

/** v2 has no forecast hour beside the dialog, so feedback carries no forecast context, as before. */
export const comfortBody = (region: string, rating: number, phase: string) =>
  ({region, rating, phase, wind: null, sea: null, period: null, heading: null, point: null});

export type SavedTrip = {id: string; date: string; point: string; species: string; start_hour: number; end_hour: number; boat_name?: string | null; boat_sea?: number | null};
export type AlertEvent = {id: string | number; kind: string; status: string; message: string};
export type Feedback = {observed_at: string; rating: number; context: string};

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
