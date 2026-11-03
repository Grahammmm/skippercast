// How old the regional forecast's model runs are, for the advisor's comfort word
// (BF-stale-never-calmer). The limits are the brief's (web/score.ts FORECAST_AGE):
// past holdHours a calm word is held at unknown, past dropHours (or with a run time
// that cannot be read, or more than an hour ahead) the forecast is not used. The
// feed's completed_at is never read: a cache that rewrites it must not make old runs
// look new. Pure; nothing is kept between calls.
import {FORECAST_AGE} from '../../../web/score.ts';

export type ForecastClockState = 'fresh' | 'held' | 'unusable';
export interface ForecastClock {state: ForecastClockState; ageHours: number | null}

const HOUR = 3_600_000;
const MODELS = ['gfs_global', 'ecmwf_ifs025', 'ncep_gfswave016', 'ecmwf_wam'] as const;
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** The oldest run among the models that carry data and no error decides; a missing clock is never fresh. */
export function forecastClock(feed: unknown, now: number): ForecastClock {
  const models = (feed as {forecast?: {models?: Record<string, {data?: unknown; error?: unknown; meta?: {last_run_initialisation_time?: unknown}} | null>}} | null)?.forecast?.models ?? {};
  const ages: number[] = [];
  for (const id of MODELS) {
    const m = models[id];
    if (!m || m.error || m.data === undefined || m.data === null) continue;
    const issued = m.meta?.last_run_initialisation_time;
    if (!finite(issued)) return {state: 'unusable', ageHours: null};
    ages.push(now - issued * 1000);
  }
  if (!ages.length) return {state: 'unusable', ageHours: null};
  const oldest = Math.max(...ages), newest = Math.min(...ages);
  const ageHours = Math.floor(oldest / HOUR);
  if (oldest > FORECAST_AGE.dropHours * HOUR || newest < -HOUR) return {state: 'unusable', ageHours};
  return {state: oldest > FORECAST_AGE.holdHours * HOUR ? 'held' : 'fresh', ageHours};
}
