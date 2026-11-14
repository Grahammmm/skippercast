// Published feeds (live conditions, daily evidence, forecast tiles) live in
// Cloudflare R2. Region configs still name each feed by its old GitHub
// location (RAW below is only that logical name); the browser always asks the
// site's /feeds/ route, which serves R2 and never GitHub.
export const RAW = 'https://raw.githubusercontent.com/Grahammmm/skippercast/';
const BRANCHES = ['conditions/', 'data/', 'forecasts/'];

export function feedURL(url) {
  if (typeof url !== 'string' || !url.startsWith(RAW)) return url;
  const rest = url.slice(RAW.length);
  return BRANCHES.some(b => rest.startsWith(b)) ? '/feeds/' + rest : url;
}

const FEED_KEYS = ['daily_feed', 'legacy_daily_feed', 'conditions_feed', 'intelligence_feed', 'habitat_feed',
  'feed_url', 'survey_feed_url', 'survey_product_feed_url'];

/** Copy of a region or catalog object with its feed URLs routed through /feeds/. */
export function withFeeds(object) {
  if (!object || typeof object !== 'object') return object;
  const copy = {...object};
  for (const key of FEED_KEYS) if (key in copy) copy[key] = feedURL(copy[key]);
  return copy;
}
