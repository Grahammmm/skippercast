// Home-port wind and swell alert (SCFEAT-ALERT-1, competitor matrix recommendation 8): a person sets two
// thresholds once and the app compares them with the regional forecast it already loads (web/conditions.ts
// briefForecast). No account, no saved trip, no server push: the thresholds stay on this device, and the
// result carries a notification-ready object that nothing sends yet. A forecast comparison for planning,
// never a statement that a trip is safe or unsafe, and not for navigation.
//
// Erasable syntax only: the node tests import this file by type stripping.
import type {RegionalForecast} from './brief/types.ts';
import type {Units} from './unit-choice.ts';
import {M_PER_FT, WIND_SPEED} from './units.ts';

/** Device-only key for the two thresholds. */
export const PORT_ALERT_KEY = 'skippercast-port-alert-v1';
/** Hours ahead of the current whole hour that are compared. */
export const WINDOW_HOURS = 48;
/** The wind layer's own age gates (web/map/wind.ts, legend): a run older than 36 h or a retrieval older than 6 h is not current. */
export const MAX_RUN_AGE_HOURS = 36;
export const MAX_FETCH_AGE_HOURS = 6;
/** Allowed threshold ranges: sustained wind in knots, swell height in feet. */
export const BOUNDS = Object.freeze({windKt: {min: 1, max: 60}, swellFt: {min: 0.5, max: 30}});

export type Thresholds = {windKt: number; swellFt: number};
export type PortAlertStorage = {getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem?(key: string): void};
export type Exceedance = {kind: 'wind' | 'swell'; at: string; value: number};
export type PortAlert = {
  state: 'alert' | 'clear' | 'partial' | 'no-data' | 'stale';
  exceedances: Exceedance[];
  peak: {windKt: number | null; swellFt: number | null};
  hoursChecked: number;
  source: string | null;
  issuedAt: string | null;
  fetchedAt: string | null;
  /** What a later push could carry; null unless the state is "alert". Nothing here is sent. */
  notification: {tag: 'port-alert'; title: string; body: string} | null;
};

const HOUR_MS = 3_600_000;
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const within = (v: unknown, r: {min: number; max: number}): v is number => finite(v) && v >= r.min && v <= r.max;

function browserStorage(): PortAlertStorage | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage; } catch { return null; }
}

/** Stored JSON as thresholds, or null when either value is missing, not a number or out of range. */
export function parseThresholds(raw: string | null): Thresholds | null {
  if (!raw) return null;
  let json: unknown;
  try { json = JSON.parse(raw); } catch { return null; }
  if (!json || typeof json !== 'object' || Array.isArray(json)) return null;
  const {windKt, swellFt} = json as Record<string, unknown>;
  return within(windKt, BOUNDS.windKt) && within(swellFt, BOUNDS.swellFt) ? {windKt, swellFt} : null;
}

export function loadThresholds(storage: PortAlertStorage | null = browserStorage()): Thresholds | null {
  try { return parseThresholds(storage?.getItem(PORT_ALERT_KEY) ?? null); } catch { return null; }
}

/** Saves valid thresholds and returns them; out-of-range values save nothing and return null. A blocked store still returns them for this page. */
export function saveThresholds(thresholds: Thresholds, storage: PortAlertStorage | null = browserStorage()): Thresholds | null {
  const ok = parseThresholds(JSON.stringify(thresholds));
  if (!ok) return null;
  try { storage?.setItem(PORT_ALERT_KEY, JSON.stringify(ok)); } catch { /* kept for this visit only */ }
  return ok;
}

export function clearThresholds(storage: PortAlertStorage | null = browserStorage()): void {
  try { storage?.removeItem?.(PORT_ALERT_KEY); } catch { /* blocked */ }
}

/** Defaults shown when nothing is saved, in stored units. */
export const DEFAULT_LIMITS: Thresholds = Object.freeze({windKt: 15, swellFt: 6});
type Shown = {value: string; min: number; max: number; step: number};

/** A stored limit as the person's own wind and height units show it: knots and feet exactly as stored, others rounded (wind to 1, metres to 0.1). */
export const shownWind = (kt: number, u: Units): number => u.wind === 'kt' ? kt : Math.round(kt * WIND_SPEED[u.wind].factor);
export const shownSwell = (ft: number, u: Units): number => u.height === 'ft' ? ft : Number((ft * M_PER_FT).toFixed(1));

/** Field values, bounds and step in the chosen units. Bounds round inward, so anything the form accepts is inside BOUNDS. */
export function shownLimits(t: Thresholds | null, u: Units): {wind: Shown; swell: Shown} {
  const s = t ?? DEFAULT_LIMITS, f = WIND_SPEED[u.wind].factor;
  const wind = u.wind === 'kt' ? {min: BOUNDS.windKt.min, max: BOUNDS.windKt.max} : {min: Math.ceil(BOUNDS.windKt.min * f), max: Math.floor(BOUNDS.windKt.max * f)};
  const swell = u.height === 'ft' ? {min: BOUNDS.swellFt.min, max: BOUNDS.swellFt.max} : {min: Math.ceil(BOUNDS.swellFt.min * M_PER_FT * 10) / 10, max: Math.floor(BOUNDS.swellFt.max * M_PER_FT * 10) / 10};
  return {wind: {value: String(shownWind(s.windKt, u)), step: 1, ...wind}, swell: {value: String(u.height === 'ft' ? s.swellFt : shownSwell(s.swellFt, u).toFixed(1)), step: u.height === 'ft' ? 0.5 : 0.1, ...swell}};
}

/** Saves the submitted strings. A field equal to what was shown keeps its stored number bit for bit; an edited one converts once to knots or feet and is checked against BOUNDS there. */
export function limitsFromForm(fields: {wind: string; swell: string}, stored: Thresholds | null, u: Units, storage?: PortAlertStorage | null): Thresholds | null {
  const base = stored ?? DEFAULT_LIMITS, shown = shownLimits(stored, u);
  const num = (s: string) => s.trim() === '' ? NaN : Number(s);
  const windKt = fields.wind === shown.wind.value ? base.windKt : num(fields.wind) / WIND_SPEED[u.wind].factor;
  const swellFt = fields.swell === shown.swell.value ? base.swellFt : u.height === 'ft' ? num(fields.swell) : num(fields.swell) / M_PER_FT;
  return storage === undefined ? saveThresholds({windKt, swellFt}) : saveThresholds({windKt, swellFt}, storage);
}

/**
 * Compares the thresholds with the forecast's hours from the current whole hour to WINDOW_HOURS ahead.
 * A reading at or above its threshold is an exceedance. Old data never reads clear or alerts: a run older than
 * MAX_RUN_AGE_HOURS, a retrieval older than MAX_FETCH_AGE_HOURS or an unreadable clock is "stale"; no forecast or
 * no reading in the window is "no-data"; a missing wind or swell reading in any of the WINDOW_HOURS window hours (the whole variable, some hours, or hours the forecast does not list at all) with no exceedance is "partial", never "clear".
 */
export function evaluatePortAlert(limits: Thresholds, forecast: RegionalForecast | null, now: number = Date.now()): PortAlert {
  const base = {exceedances: [], peak: {windKt: null, swellFt: null}, hoursChecked: 0, source: forecast?.label ?? null, issuedAt: forecast?.issuedAt ?? null, fetchedAt: forecast?.fetchedAt ?? null, notification: null};
  if (!forecast) return {state: 'no-data', ...base};
  if (!Number.isFinite(now)) return {state: 'stale', ...base};
  const issued = Date.parse(forecast.issuedAt), fetched = Date.parse(forecast.fetchedAt);
  // A source clock more than 5 minutes ahead of evaluation is not a readable run (same skew rule as the map and brief forecast readers).
  const ahead = now + 5 * 60_000;
  if (!Number.isFinite(issued) || !Number.isFinite(fetched) || issued > ahead || fetched > ahead || now - issued > MAX_RUN_AGE_HOURS * HOUR_MS || now - fetched > MAX_FETCH_AGE_HOURS * HOUR_MS) return {state: 'stale', ...base};
  const start = Math.floor(now / HOUR_MS) * HOUR_MS, end = start + WINDOW_HOURS * HOUR_MS;
  const exceedances: Exceedance[] = [], peak: PortAlert['peak'] = {windKt: null, swellFt: null};
  const seen = new Set<string>();
  // Window slots (whole hours from `start`) that have a reading, per variable. Coverage is judged against the advertised
  // WINDOW_HOURS slots, so an hour the forecast leaves out entirely is a gap just like an hour with a null reading.
  const windSlots = new Set<number>(), swellSlots = new Set<number>();
  let hoursChecked = 0;
  // Each variable's exceedance is its EARLIEST qualifying instant in the window (not the peak, not the first row met):
  // rows are visited in ascending parsed-epoch order; the stable sort keeps source order for equal instants. forecast.hours is never reordered.
  const rows = forecast.hours.map(h => ({h, t: Date.parse(h.at)})).filter(r => !(!Number.isFinite(r.t) || r.t < start || r.t >= end)).sort((a, b) => a.t - b.t);
  for (const {h, t} of rows) {
    const slot = Math.floor((t - start) / HOUR_MS);
    // A negative wind or swell reading is impossible: missing evidence, exactly like null (zero stays a valid calm reading).
    const wind = finite(h.windKnots) && h.windKnots >= 0 ? h.windKnots : null, swell = finite(h.swellFt) && h.swellFt >= 0 ? h.swellFt : null;
    if (wind !== null) windSlots.add(slot);
    if (swell !== null) swellSlots.add(slot);
    if (wind === null && swell === null) continue;
    hoursChecked++;
    if (wind !== null) {
      peak.windKt = Math.max(peak.windKt ?? wind, wind);
      if (wind >= limits.windKt && !seen.has('wind')) { seen.add('wind'); exceedances.push({kind: 'wind', at: h.at, value: wind}); }
    }
    if (swell !== null) {
      peak.swellFt = Math.max(peak.swellFt ?? swell, swell);
      if (swell >= limits.swellFt && !seen.has('swell')) { seen.add('swell'); exceedances.push({kind: 'swell', at: h.at, value: swell}); }
    }
  }
  if (!hoursChecked) return {state: 'no-data', ...base};
  const found = {...base, exceedances, peak, hoursChecked};
  // A known exceedance still alerts. "Clear" needs a reading for BOTH variables in EVERY one of the WINDOW_HOURS hours: a short forecast, an absent hour or a null reading is an unknown hour, not evidence of calm.
  if (!exceedances.length) return {state: windSlots.size < WINDOW_HOURS || swellSlots.size < WINDOW_HOURS ? 'partial' : 'clear', ...found};
  const parts = exceedances.map(e => e.kind === 'wind' ? `wind ${e.value} kt (your limit ${limits.windKt} kt)` : `swell ${e.value} ft (your limit ${limits.swellFt} ft)`);
  return {state: 'alert', ...found, notification: {tag: 'port-alert', title: `${exceedances.map(e => e.kind === 'wind' ? 'Wind' : 'Swell').join(' and ')} forecast above your limit`, body: `Forecast ${parts.join('; ')} within ${WINDOW_HOURS} h. Model forecast for planning, not for navigation.`}};
}
