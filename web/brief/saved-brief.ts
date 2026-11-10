// SC-PERF-INSTANT-1: the last brief that loaded, kept on this device so a weak signal at the ramp does not
// leave the brief empty. What is kept is the brief's own inputs, the region's daily feed (the part the brief reads)
// and the regional forecast at its chosen point, each with the time this device fetched it; the verdict, tiles and
// labels are rebuilt from them at the time of showing, so the existing age rules (BF-stale-never-calmer) apply to a
// saved brief exactly as to a live one and a saved brief can never read calmer than live data would.
//
// Nothing personal is kept: no trip, spot, position, boat, limits or speed, and nothing is sent anywhere. One entry
// per device (the last region loaded). A missing, full, blocked or unreadable store is never an error: the brief
// simply loads as it did before.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {ConditionsForecast} from '../conditions.ts';
import type {RegionalDailyFeed} from './types.ts';
import {RUN_STALE_MS} from './verdict.ts';
import {localeOf, t, type Language} from '../i18n.ts';
import {validZone} from '../zone.ts';

export const SAVED_BRIEF_KEY = 'skippercast-lastbrief-v1';
/** A saved part dated further ahead than this (a device clock that moved back) is not trusted. */
const FUTURE_MS = 10 * 60_000;

export interface SavedStore {getItem(key: string): string | null; setItem(key: string, value: string): void}
/** A part of the brief with the epoch ms this device fetched it. */
export interface SavedPart<T> {readonly at: number; readonly data: T}
/** The region metadata the brief is built from (name, centre, zone): without it a saved brief cannot be rebuilt before region.json is read. */
export interface SavedRegion {readonly name: string; readonly center: readonly [number, number]; readonly timezone: string}
export interface SavedBrief {
  readonly v: 1;
  readonly region: string;
  /** Absent when the region's own file had not been read when the brief was saved; the brief then waits for it as before. */
  readonly region_info?: SavedRegion;
  readonly daily: SavedPart<RegionalDailyFeed> | null;
  readonly forecast: SavedPart<ConditionsForecast> | null;
}

/** The browser's store, or null when there is none or it is blocked. */
export function browserStore(): SavedStore | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage; } catch { return null; }
}

const finiteTime = (v: unknown, now: number): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0 && v - now <= FUTURE_MS;

/** The forecast as the brief reads it: the chosen point's model runs, not the whole multi-point feed. */
export const displayedForecast = (f: ConditionsForecast): ConditionsForecast => ({region: f.region, retrieved: f.retrieved, point: f.point, models: f.models});

/** Only the region fields the brief reads. */
export const displayedRegion = (r: SavedRegion): SavedRegion => ({name: r.name, center: [r.center[0], r.center[1]], timezone: r.timezone});

const validCenter = (c: unknown): c is [number, number] => Array.isArray(c) && c.length === 2
  && typeof c[0] === 'number' && typeof c[1] === 'number' && Number.isFinite(c[0]) && Number.isFinite(c[1]) && Math.abs(c[0]) <= 90 && Math.abs(c[1]) <= 180;

/** Keep the entry for `region`; a part not given is dropped. Returns false (and keeps nothing new) when the store refuses. */
export function writeSaved(store: SavedStore | null, region: string, daily: SavedPart<RegionalDailyFeed> | null, forecast: SavedPart<ConditionsForecast> | null, info: SavedRegion | null = null): boolean {
  if (!store || !daily) return false;
  try {
    const entry: SavedBrief = {v: 1, region, ...info ? {region_info: displayedRegion(info)} : {}, daily, forecast: forecast ? {at: forecast.at, data: displayedForecast(forecast.data)} : null};
    store.setItem(SAVED_BRIEF_KEY, JSON.stringify(entry));
    return true;
  } catch { return false; }
}

/** The saved entry for `region`, checked as the live feeds are (schema, region identity, a usable fetch time); null otherwise. */
export function readSaved(store: SavedStore | null, region: string, now: number): SavedBrief | null {
  if (!store) return null;
  try {
    const raw = store.getItem(SAVED_BRIEF_KEY);
    if (!raw) return null;
    const e = JSON.parse(raw) as Partial<SavedBrief> | null;
    if (!e || e.v !== 1 || e.region !== region) return null;
    const d = e.daily, f = e.forecast;
    const feed = d?.data as (Partial<RegionalDailyFeed> & {schema_version?: number}) | undefined;
    if (!d || !finiteTime(d.at, now) || feed?.schema_version !== 1 || feed.region_id !== region || !feed.sources || typeof feed.sources !== 'object') return null;
    const fc = f?.data as Partial<ConditionsForecast> | undefined;
    const forecast = f && finiteTime(f.at, now) && fc?.region === region && typeof fc.retrieved === 'number' && Number.isFinite(fc.retrieved) && fc.models && typeof fc.models === 'object' && fc.point
      ? {at: f.at, data: fc as ConditionsForecast} : null;
    const ri = e.region_info as Partial<SavedRegion> | undefined;
    const region_info = ri && typeof ri.name === 'string' && validCenter(ri.center) && validZone(ri.timezone) ? displayedRegion(ri as SavedRegion) : undefined;
    return {v: 1, region, ...region_info ? {region_info} : {}, daily: {at: d.at, data: d.data}, forecast};
  } catch { return null; }
}

export type SavedState = 'updating' | 'failed' | 'offline';

/**
 * The "Last updated" line for a brief that is (partly) still the saved one. `at` is the oldest part's fetch time. It is amber
 * when that is older than the brief's own freshness limit (the forecast run's, verdict.ts RUN_STALE_MS) or when a reading
 * on screen is already stale; a clock that reads ahead of now is never fresh. SC1722-03: `offline` is data the saved offline
 * pack answered, at the time the pack saved it; it is a complete sentence of its own, with no "updating" tail.
 */
export function savedLine(at: number, now: number, state: SavedState, readingsStale: boolean, tz: string, lang: Language = 'en'): {text: string; amber: boolean} {
  const age = now - at;
  const time = new Intl.DateTimeFormat(localeOf(lang), {weekday: 'short', hour: 'numeric', minute: '2-digit', timeZone: tz, timeZoneName: 'short'}).format(new Date(at));
  const text = state === 'offline' ? t('brief.saved.offline', lang, {time}) : `${t('brief.saved.line', lang, {time})} ${t(state === 'failed' ? 'brief.saved.failed' : 'brief.saved.updating', lang)}`;
  return {text, amber: readingsStale || !(age >= 0) || age > RUN_STALE_MS};
}
