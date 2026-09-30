// One section of the region's daily feed (P4-05). The whole feed is ~1.4 MB;
// the map needs only its regulation checks at startup (and its protected-area
// records when the live MPA query fails). The Worker's /api/daily reads the
// same published feed, applies the same checks the full-feed readers apply,
// and returns just the named part. Callers fall back to the full feed, so a
// missing or changed endpoint never removes a check.
import {getRegion, acceptsFeed} from './region.js';
import {DAILY_PARTS, dailyPartPath} from './offline-core.js';

export {DAILY_PARTS};
export const dailyPartURL = (part, region = getRegion()) => dailyPartPath(region.id, part);

/** Whether `data` is the `part` of this region's daily feed as /api/daily returns it. */
export function validDailyPart(data, part, region = getRegion()) {
  if (data?.schema_version !== 1 || data.part !== part || !acceptsFeed(data, region)) return false;
  if (!Number.isFinite(Date.parse(data.generated_at)) || data.catch_probability !== null || data.bite_score !== null) return false;
  return part === 'regulations' ? !!data.regulations && typeof data.regulations === 'object'
    : !!data.sources && typeof data.sources === 'object' && !Array.isArray(data.sources);
}

/** The `part` of the region's live daily feed; throws when unavailable or invalid. */
export async function loadDailyPart(part, {fetch: get = fetch, region = getRegion()} = {}) {
  if (!DAILY_PARTS.includes(part)) throw Error('Unknown daily feed part');
  const response = await get(dailyPartURL(part, region), {cache: 'no-cache', signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw Error(`Daily feed part HTTP ${response.status}`);
  const data = await response.json();
  if (!validDailyPart(data, part, region)) throw Error('Daily feed part changed');
  return data;
}
