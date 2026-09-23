// Public discussion links are research leads, never catch or location evidence.
const FEED = 'https://raw.githubusercontent.com/Grahammmm/skippercast/data/recent-intel.json';
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const formatDate = value => new Date(value).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'America/Los_Angeles'});
const hoursSince = (value, now) => (now - Date.parse(value)) / 3600000;
const validURL = value => {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; }
  catch { return null; }
};

export function recentDiscussionState(feed, regionId, now = Date.now()) {
  if (feed?.schema_version !== 1 || !Array.isArray(feed.candidates) || !feed.health || !Number.isFinite(Date.parse(feed.generated_at)))
    return {status:'unavailable', candidates:[], checkedQueries:0, totalQueries:0};
  const age = hoursSince(feed.generated_at, now);
  if (!Number.isFinite(age) || age < -1 || age > 48)
    return {status:'stale', candidates:[], checkedQueries:Object.keys(feed.checks || {}).length, totalQueries:feed.health.watchlist_queries || 0, generatedAt:feed.generated_at};
  const candidates = feed.candidates.filter(item => item.region_id === regionId && item.review_status === 'candidate'
    && validURL(item.url) && Number.isFinite(Date.parse(item.published_at))
    && hoursSince(item.published_at, now) >= -1 && hoursSince(item.published_at, now) <= 30 * 24)
    .sort((a,b) => Date.parse(b.published_at) - Date.parse(a.published_at)).slice(0,4);
  return {status:feed.health.status === 'ok' ? 'current' : 'degraded', candidates,
    checkedQueries:Object.keys(feed.checks || {}).length, totalQueries:feed.health.watchlist_queries || 0,
    generatedAt:feed.generated_at};
}

export function recentDiscussionMarkup(state) {
  if (state.status === 'unavailable') return '<p>Recent discussion search is unavailable. Check the public data job for its source status.</p>';
  if (state.status === 'stale') return `<p>The last research snapshot is dated ${escapeHTML(formatDate(state.generatedAt))}. Current local discussion coverage is unverified.</p>`;
  const coverage = `${state.checkedQueries}/${state.totalQueries} rotating searches checked in this update`;
  const notice = state.status === 'degraded' ? ' · some sources failed or returned partial results' : '';
  const links = state.candidates.map(item => `<li><a href="${escapeHTML(validURL(item.url))}" target="_blank" rel="noopener noreferrer">${escapeHTML(item.title)}</a><small>Published ${escapeHTML(formatDate(item.published_at))} · ${escapeHTML(item.source)} · ${escapeHTML(item.location_basis || 'regional search')}</small></li>`).join('');
  return `<p class="small">Updated ${escapeHTML(formatDate(state.generatedAt))} · ${coverage}${notice}. Search coverage rotates across regions; an empty result does not mean fish are absent.</p>${links ? `<ul class="recent-discussion-links">${links}</ul>` : '<p>No dated local discussion links passed the search filter for this region yet.</p>'}<p class="small">These are unreviewed links. Posting date is not fishing date; the search does not verify a catch, species, boat position, or hotspot. <a href="https://github.com/Grahammmm/skippercast/blob/main/docs/recent-intel.md" target="_blank" rel="noopener noreferrer">How this search works ↗</a></p>`;
}

export async function initRecentDiscussions(regionId) {
  const panel = document.getElementById('recent-discussions');
  if (!panel) return;
  const body = panel.querySelector('.recent-discussions-body');
  if (!body) return;
  try {
    const response = await fetch(FEED,{cache:'no-cache',signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('Feed request failed');
    body.innerHTML = recentDiscussionMarkup(recentDiscussionState(await response.json(),regionId));
  } catch {
    body.innerHTML = '<p>Recent discussion search is unavailable. <a href="https://github.com/Grahammmm/skippercast/actions/workflows/daily-data.yml" target="_blank" rel="noopener noreferrer">Check the daily data job ↗</a></p>';
  }
}
