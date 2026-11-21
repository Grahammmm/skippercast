import type {FeedHour} from '../web/score.ts';
import type {ConditionsV1} from './conditions-v1.ts';

type Missing = {missing: string};
type SnapshotLayers = Extract<ConditionsV1, {layers: object}>['layers'];
type WindItem = Exclude<SnapshotLayers['wind'], Missing | undefined>;
type SwellItem = Exclude<SnapshotLayers['swell'], Missing | undefined>;
type ForecastLayers = {wind: WindItem | Missing; swell: SwellItem | Missing};

const UTC_INSTANT = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?Z$/;

function isFrameTime(value: unknown): value is string {
  if (typeof value !== 'string' || !value.endsWith('Z') || !UTC_INSTANT.test(value)) return false;
  const instant = Date.parse(value);
  // Reject normalized dates and clock times without rewriting accepted fractions.
  return Number.isFinite(instant) && new Date(instant).toISOString().slice(0, 19) === value.slice(0, 19);
}

function nonnegative(value: number | null): value is number {
  return value !== null && Number.isFinite(value) && value >= 0;
}

function fromDegrees(value: number | null): number | null {
  return nonnegative(value) && value <= 360 ? (value === 360 ? 0 : value) : null;
}

export function catchForecastLayers(hour: FeedHour | null, run: string, validAt: string): ForecastLayers {
  if (hour === null) return {wind: {missing: 'not archived'}, swell: {missing: 'not archived'}};
  if (typeof run !== 'string' || run.length === 0 || run.length > 400 || [...run].length > 200
    || !isFrameTime(validAt)) {
    return {wind: {missing: 'bad frame'}, swell: {missing: 'bad frame'}};
  }

  const {wind, wind_from, swell, swell_period, swell_from} = hour;
  const windFrom = fromDegrees(wind_from);
  const swellFrom = fromDegrees(swell_from);
  return {
    wind: nonnegative(wind) && windFrom !== null
      ? {kn: wind, from_deg: windFrom, run, valid_at: validAt}
      : {missing: 'no value'},
    swell: nonnegative(swell) && nonnegative(swell_period) && swell_period > 0 && swellFrom !== null
      ? {ft: swell, period_s: swell_period, from_deg: swellFrom, run, valid_at: validAt}
      : {missing: 'no value'},
  };
}
