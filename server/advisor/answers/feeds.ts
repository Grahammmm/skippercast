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

/** The region's intelligence feed (forecast models), or null when missing, unreadable or for another region. */
export async function intelligenceFeed(region: Region, read: FeedReader): Promise<ExternalJSON | null> {
  try {
    const feed = await read(region.intelligence_feed);
    return feed?.region_id === region.id ? feed : null;
  } catch { return null; }
}
