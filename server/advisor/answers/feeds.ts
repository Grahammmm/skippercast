// The regional feeds the data tools read (06 § what's biting and § planning):
// the daily feed (landing reports, NWS alerts) and the intelligence feed (the
// model forecast), through readFeed exactly as routes/public.ts does, with the
// same checks. A tool test injects `deps.feeds` (the EngineDeps field the
// engine passes through) so it runs offline on tests/fixtures/feeds/.
import {readFeed} from '../../feeds.ts';
import {validFeed} from './confidence.ts';
import type {Region, ExternalJSON} from '../../types.ts';

export type FeedReader = (url: string) => Promise<ExternalJSON>;   // EngineDeps.feeds

/** The reader from deps when given (tests), else readFeed (R2, then the GitHub branch). */
export const feedReader = (deps: {feeds?: (url: string) => Promise<unknown>} | null | undefined): FeedReader => (deps?.feeds as FeedReader | undefined) ?? readFeed;

/** The region's daily feed, or null when it is missing, unreadable or fails the app's checks (validDailyFeed in routes/public.ts). */
export async function dailyFeed(region: Region, read: FeedReader): Promise<ExternalJSON | null> {
  try {
    const feed = await read(region.daily_feed);
    const ok = (feed?.region_id === region.id || (!feed?.region_id && region.id === 'morro-bay')) && validFeed(feed);
    return ok ? feed : null;
  } catch { return null; }
}

/** The region's intelligence feed (forecast models), or null when missing, unreadable, for another region or with a malformed forecast container. */
export async function intelligenceFeed(region: Region, read: FeedReader): Promise<ExternalJSON | null> {
  try {
    const feed = await read(region.intelligence_feed);
    return feed?.region_id === region.id && forecastContainersOk(feed) ? feed : null;
  } catch { return null; }
}

// The forecast models conditions.ts reads (readHour, windowConditions). Their sample
// values, units and freshness stay that module's policy; this only checks the containers.
const FORECAST_MODELS = ['gfs_global', 'ecmwf_ifs025', 'ncep_gfswave016', 'ecmwf_wam'] as const;
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

/**
 * Read-only shape gate for the containers the conditions readers index into: the feed,
 * forecast and forecast.models are plain objects; each recognized model present is an
 * object; a model's data (required to be an array unless the model is an explicit
 * provider-error record) holds only null or object points; a point's hourly, when
 * present, is an object whose time, when present, is an array. Absent forecast, models,
 * data, hourly or time keep the ordinary unavailable outcome. An error record's array
 * points are checked too, because windowConditions reads gfs_global times either way.
 */
function forecastContainersOk(feed: unknown): boolean {
  if (!isRecord(feed)) return false;
  if (feed.forecast === undefined) return true;
  if (!isRecord(feed.forecast)) return false;
  const models = feed.forecast.models;
  if (models === undefined) return true;
  if (!isRecord(models)) return false;
  for (const id of FORECAST_MODELS) {
    const model = models[id];
    if (model === undefined) continue;
    if (!isRecord(model)) return false;
    if (!Array.isArray(model.data)) {
      if (model.data === undefined || model.error) continue;
      return false;
    }
    for (const point of model.data) {
      if (point === null) continue;
      if (!isRecord(point)) return false;
      if (point.hourly === undefined) continue;
      if (!isRecord(point.hourly)) return false;
      if (point.hourly.time !== undefined && !Array.isArray(point.hourly.time)) return false;
    }
  }
  return true;
}
