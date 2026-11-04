// Trip plan legs (harbor, stops, harbor): a leg takes the water route when `route` computes one (FSC-04), else the
// straight line, labelled `basis: 'straight'` with the route's reason. Planning sums only; no forecast or export changes.
import {distanceNm} from '../dist/spot-ranking.js';
import {screenPlace, type PlaceVerdict} from '../dist/geo-screen.js';
import {runMinutes} from './brief/run.ts';
import type {Route, RouteFailure, RoutePoint} from './route.ts';

type Point = {name: string; lat: number; lon: number};
type Stop = Point & {id: string};
type Leg = {from: string; to: string; nm: number; runMin: number | null; basis: 'water' | 'straight'; why?: RouteFailure;
  /** BF-closures-everywhere: the verdict for the line the leg draws, end to end (a middle that crosses a closure is inside). */
  screen: PlaceVerdict};
const valid = (p: Point): boolean => Number.isFinite(p.lat) && Math.abs(p.lat) <= 90 && Number.isFinite(p.lon) && Math.abs(p.lon) <= 180;

export function tripLegs(origin: Point | null, stops: Stop[], speedKn: number | null, route?: (a: RoutePoint, b: RoutePoint) => Route | null, screen: unknown = null): {
  legs: Leg[]; totalNm: number; totalRunMin: number | null; skipped: string[];
} {
  const seen = new Set<string>(), skipped: string[] = [], points: Point[] = [];
  for (const stop of stops) {
    if (seen.has(stop.id)) continue;
    seen.add(stop.id);
    if (!valid(stop)) skipped.push(stop.name);
    else points.push(stop);
  }
  if (points.length < 2) points.length = 0;
  if (origin && valid(origin) && points.length) {
    points.unshift(origin);
    points.push(origin);
  }
  const legs: Leg[] = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!, b = points[i]!, from = {latitude: a.lat, longitude: a.lon}, to = {latitude: b.lat, longitude: b.lon};
    const r = route ? route(from, to) : null;
    const nm = r?.ok ? r.nm : distanceNm(from, to);
    const path = [from, ...(r?.ok ? r.points : []), to].map(p => [p.longitude, p.latitude]);
    legs.push({from: a.name, to: b.name, nm, runMin: speedKn === null ? null : runMinutes(nm, speedKn),
      basis: r?.ok ? 'water' : 'straight', ...(r && !r.ok ? {why: r.reason} : {}),
      screen: screenPlace(screen, {geometry: {type: 'LineString', coordinates: path}})});
  }
  return {legs, totalNm: legs.reduce((sum, leg) => sum + leg.nm, 0),
    totalRunMin: speedKn !== null && Number.isFinite(speedKn) && speedKn > 0 ? legs.reduce((sum, leg) => sum + leg.runMin!, 0) : null, skipped};
}
