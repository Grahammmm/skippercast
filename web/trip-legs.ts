// Straight-line planning sums only; no forecast, routing or export changes.
import {distanceNm} from '../dist/spot-ranking.js';
import {runMinutes} from './brief/run.ts';

type Point = {name: string; lat: number; lon: number};
type Stop = Point & {id: string};
type Leg = {from: string; to: string; nm: number; runMin: number | null};
const valid = (p: Point): boolean => Number.isFinite(p.lat) && Math.abs(p.lat) <= 90 && Number.isFinite(p.lon) && Math.abs(p.lon) <= 180;

export function tripLegs(origin: Point | null, stops: Stop[], speedKn: number | null): {
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
    const a = points[i - 1]!, b = points[i]!;
    const nm = distanceNm({latitude: a.lat, longitude: a.lon}, {latitude: b.lat, longitude: b.lon});
    legs.push({from: a.name, to: b.name, nm, runMin: speedKn === null ? null : runMinutes(nm, speedKn)});
  }
  return {legs, totalNm: legs.reduce((sum, leg) => sum + leg.nm, 0),
    totalRunMin: speedKn !== null && Number.isFinite(speedKn) && speedKn > 0 ? legs.reduce((sum, leg) => sum + leg.runMin!, 0) : null, skipped};
}
