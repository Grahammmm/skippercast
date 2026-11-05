// SC1822-09: one selected mark's planning distance from the home port or launch, for the mark card. The same rule and words as
// Where to look (web/brief/WhereToLook.tsx): by water where a route is computed, else the straight line, labelled; the one-way
// run at the saved cruise speed beside it. One origin and one destination, never the ranking, and no bearing or course:
// a planning aid, not a navigation chart (docs/legal/disclaimers.md). Display text only: nothing here is stored or sent.
//
// Erasable syntax only: Node tests import this file.
import {distanceNm} from '../dist/spot-ranking.js';
import {ROUTE_BUDGET, type RouteFn} from './ranking.ts';
import type {LandWaterLines, LandWaterModel} from './land-water.ts';
import type {RouteFailure, RoutePoint} from './route.ts';
import {durationText, runMinutes} from './brief/run.ts';
import {t, type Language} from './i18n.ts';

/** Most route searches one stable selection runs: one before the lines file is known, one after it loads. */
export const MARK_ROUTE_ATTEMPTS = 2;
if (MARK_ROUTE_ATTEMPTS > ROUTE_BUDGET) throw new Error('mark routes exceed ROUTE_BUDGET');

export interface MarkDistance {readonly nm: number; readonly basis: 'water' | 'straight'; readonly why?: RouteFailure}

/** A position with finite latitude in [-90, 90] and longitude in [-180, 180]. */
export function usablePoint(p: unknown): p is RoutePoint {
  const q = p as Partial<RoutePoint> | null | undefined;
  return !!q && typeof q.latitude === 'number' && Number.isFinite(q.latitude) && Math.abs(q.latitude) <= 90
    && typeof q.longitude === 'number' && Number.isFinite(q.longitude) && Math.abs(q.longitude) <= 180;
}

/** The straight line between two usable points, in nautical miles; null when either is not usable. */
export function straightDistance(from: unknown, to: unknown): MarkDistance | null {
  if (!usablePoint(from) || !usablePoint(to)) return null;
  const nm = distanceNm(from, to);
  return Number.isFinite(nm) && nm >= 0 ? {nm, basis: 'straight'} : null;
}

/**
 * The distance for one pair: the water route when `route` (called at most once, and only with a product) returns a finite,
 * nonnegative distance, else the labelled straight line with the route's own reason.
 */
export function markDistance(from: unknown, to: unknown, model: LandWaterModel | null, lines: LandWaterLines | null | false, route: RouteFn): MarkDistance | null {
  const line = straightDistance(from, to);
  if (!line || !model) return line;
  const got = route(model, lines, from as RoutePoint, to as RoutePoint);
  if (got?.ok && Number.isFinite(got.nm) && got.nm >= 0) return {nm: got.nm, basis: 'water'};
  return got && !got.ok ? {...line, why: got.reason} : line;
}

/** "Port · 4.2 nm by water · run 20 min": the origin's name, the distance, then the run when the speed is usable. Run keeps the unrounded distance. */
export function markDistanceLine(originName: string, d: MarkDistance, speedKn: number | null, lang: Language = 'en'): string {
  const nm = d.nm.toFixed(1), shown = lang === 'es' ? nm.replace('.', ',') : nm;
  const min = speedKn === null ? null : runMinutes(d.nm, speedKn);
  const run = min === null ? '' : t('where.run', lang, {bound: d.basis === 'water' ? '' : '≥ ', duration: durationText(min)});
  return `${originName} · ${t(d.basis === 'water' ? 'where.distance.water' : 'where.distance.straight', lang, {nm: shown})}${run}`;
}
