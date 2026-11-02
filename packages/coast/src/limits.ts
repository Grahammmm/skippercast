// Your own comfort limits (issue #542): the wind, gust and seas limits a
// lower-exposure window uses, and for spear the highest surge band, set per
// profile by the user and kept on the device (web/limits.ts).
//
// Defaults are the thresholds the brief already uses: web/score.ts
// WINDOW_LIMITS (boat 10 kt, 15 kt gusts, 4 ft seas; shore, spear and kayak
// 8 kt, 12 kt, 3 ft) and spear.ts SPEAR.windowMaxSurge. A user may set a
// comfort limit lower or higher within LIMIT_BOUNDS. Hazard rules never read
// these numbers, so no limit can relax them: marine alerts, and the per-hour
// check in daily.ts windowHourHazards (the long-period swell rule, the shore
// sneaker-wave caution, a hazardous bar hour, offshore wind and launch surf for
// a kayak, daylight, Heavy surge, and any hour the profile grades Rough).
// Kayak seas can only be tightened: the kayak verdict (kayak.ts) sets the
// window above 3 ft whatever the limit says.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {BriefMode} from './types.ts';
import {WINDOW_LIMITS} from '../../../web/score.ts';
import {SPEAR, SURGE_RANK} from './spear.ts';

/** The surge bands a spear limit may name; Heavy is never allowed. */
export const LIMIT_SURGE_BANDS = ['Low', 'Moderate', 'Strong'] as const;
export type LimitSurge = typeof LIMIT_SURGE_BANDS[number];

/** Comfort limits. Units: knots and feet. `surge` is read for spear only. */
export type ComfortLimits = {wind: number; gust: number; seas: number; surge?: LimitSurge};
export type LimitField = 'wind' | 'gust' | 'seas';
export const LIMIT_FIELDS: readonly LimitField[] = ['wind', 'gust', 'seas'];

/** The defaults: the brief's own window limits for the profile. */
export function defaultLimits(mode: BriefMode): ComfortLimits {
  const base = WINDOW_LIMITS[mode === 'boat' ? 'boat' : 'other'];
  const limits: ComfortLimits = {wind: base.wind, gust: base.gust, seas: base.wave};
  if (mode === 'spear') limits.surge = SPEAR.windowMaxSurge;
  return limits;
}

/**
 * The range each limit may take, and the step it rounds to. Sane bounds, not
 * safety limits: the upper bounds stay well under gale force and the seas
 * where the profile's own scale reads Large or Heavy.
 */
export const LIMIT_BOUNDS: Readonly<Record<BriefMode, Readonly<Record<LimitField, {min: number; max: number; step: number}>>>> = {
  boat: {wind: {min: 4, max: 20, step: 1}, gust: {min: 6, max: 25, step: 1}, seas: {min: 1, max: 8, step: 0.5}},
  shore: {wind: {min: 4, max: 15, step: 1}, gust: {min: 6, max: 20, step: 1}, seas: {min: 1, max: 6, step: 0.5}},
  spear: {wind: {min: 4, max: 12, step: 1}, gust: {min: 6, max: 18, step: 1}, seas: {min: 1, max: 5, step: 0.5}},
  kayak: {wind: {min: 4, max: 12, step: 1}, gust: {min: 6, max: 18, step: 1}, seas: {min: 1, max: 3, step: 0.5}},
};

const isSurge = (value: unknown): value is LimitSurge => typeof value === 'string' && (LIMIT_SURGE_BANDS as readonly string[]).includes(value);

const limitNumber = (value: unknown): number => typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN;

/** Whether the gust limit is below the wind limit (both readable), so gusts decide every window. Equal is fine. */
export function gustBelowWind(limits: {wind: unknown; gust: unknown}): boolean {
  const wind = limitNumber(limits.wind), gust = limitNumber(limits.gust);
  return Number.isFinite(wind) && Number.isFinite(gust) && gust < wind;
}

/** Limits inside the bounds: a missing or unreadable value takes the default; numbers round to the step and clamp. */
export function clampLimits(mode: BriefMode, raw: Partial<Record<string, unknown>> | null | undefined): ComfortLimits {
  const base = defaultLimits(mode), bounds = LIMIT_BOUNDS[mode];
  const out: ComfortLimits = {...base};
  for (const field of LIMIT_FIELDS) {
    const value = raw?.[field];
    const n = limitNumber(value);
    if (!Number.isFinite(n)) continue;
    const {min, max, step} = bounds[field];
    out[field] = Math.min(max, Math.max(min, Math.round(n / step) * step));
  }
  if (mode === 'spear') out.surge = isSurge(raw?.surge) ? raw.surge : base.surge;
  else delete out.surge;
  return out;
}

/** Whether two limits are the same for the profile. */
export function sameLimits(mode: BriefMode, a: ComfortLimits, b: ComfortLimits): boolean {
  return LIMIT_FIELDS.every(field => a[field] === b[field]) && (mode !== 'spear' || a.surge === b.surge);
}

/** The fields the user set below the default (stricter). */
export function stricterFields(mode: BriefMode, limits: ComfortLimits): {fields: LimitField[]; surge: boolean} {
  const base = defaultLimits(mode);
  return {fields: LIMIT_FIELDS.filter(field => limits[field] < base[field]),
    surge: mode === 'spear' && !!limits.surge && !!base.surge && SURGE_RANK[limits.surge] < SURGE_RANK[base.surge]};
}

/** The fields the user set above the default (looser). */
export function looserFields(mode: BriefMode, limits: ComfortLimits): {fields: LimitField[]; surge: boolean} {
  const base = defaultLimits(mode);
  return {fields: LIMIT_FIELDS.filter(field => limits[field] > base[field]),
    surge: mode === 'spear' && !!limits.surge && !!base.surge && SURGE_RANK[limits.surge] > SURGE_RANK[base.surge]};
}

const fmt = (n: number) => Number(n.toFixed(1)).toString();

/** "wind 12 kt, gusts 18 kt, seas 5 ft, surge strong": the limits as one phrase. */
export function limitsText(mode: BriefMode, limits: ComfortLimits): string {
  const parts = [`wind ${fmt(limits.wind)} kt`, `gusts ${fmt(limits.gust)} kt`, `${mode === 'shore' ? 'surf' : 'seas'} ${fmt(limits.seas)} ft`];
  if (mode === 'spear' && limits.surge) parts.push(`surge ${limits.surge.toLowerCase()}`);
  return parts.join(', ');
}
