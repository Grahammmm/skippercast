import type {TidePoint} from '../packages/coast/src/types.ts';
import {TREND_MATCH_MS, tideTrend, type TideTrend} from '../web/tides.ts';

type CatchTide =
  | {stage: Lowercase<TideTrend> | null; height_ft: number; station: string; at: string}
  | {missing: 'no station' | 'bad time' | 'not archived' | 'no tide curve'};

// Numeric offsets must follow a clock (or a zone name), not be part of the date.
const EXPLICIT_ZONE = /(?:\dZ|\b(?:GMT|UTC|[ECMP][SD]T)|(?:\d:\d{2}(?:\.\d+)?\s*|GMT|UTC)[+-]\d{2}:?\d{2})\s*$/i;

export function catchTide(points: readonly TidePoint[], startedAt: string, station: string | null): CatchTide {
  if (!station) return {missing: 'no station'};
  const time = Date.parse(startedAt);
  if (!EXPLICIT_ZONE.test(startedAt) || !Number.isFinite(time)) return {missing: 'bad time'};

  // Keep the supplied order: the shared trend rule uses the first match and its next point.
  const curve = points.filter(point => Number.isFinite(point.heightFt) && Number.isFinite(Date.parse(point.at)));
  const first = curve[0], last = curve.at(-1);
  if (curve.length < 2 || !first || !last ||
      time < Date.parse(first.at) - TREND_MATCH_MS || time > Date.parse(last.at) + TREND_MATCH_MS) {
    return {missing: 'not archived'};
  }
  const match = curve.find(point => Math.abs(Date.parse(point.at) - time) <= TREND_MATCH_MS);
  if (!match) return {missing: 'no tide curve'};

  const trend = tideTrend(curve, startedAt);
  return {stage: trend === null ? null : trend.toLowerCase() as Lowercase<TideTrend>,
    height_ft: Number(match.heightFt.toFixed(2)), station, at: match.at};
}
