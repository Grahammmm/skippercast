// Cron watchdog (Cloudflare Cron Trigger, every 15 minutes). GitHub runs the
// heavy Python refresh but throttles its own schedules; if the published live
// feed is more than 45 minutes old and no refresh is running, dispatch one.
// Needs GITHUB_TOKEN (fine-grained, Actions: read and write on this repo).
import {readBucketJSON, RAW} from './feeds.ts';
import type {ExternalJSON} from './types.ts';

export interface WatchdogEnv {GITHUB_TOKEN?: string}

const REPO = 'Grahammmm/skippercast';
const WORKFLOW = 'live-conditions.yml';
export const STALE_MINUTES = 45;

export function feedAgeMinutes(feed: ExternalJSON, now = Date.now()): number {
  const stamp = Date.parse(feed?.completed_at || feed?.generated_at || '');
  return Number.isFinite(stamp) ? (now - stamp) / 60000 : Infinity;
}

async function github(env: WatchdogEnv, path: string, init: RequestInit & {headers?: Record<string, string>} = {}): Promise<Response> {
  return fetch(`https://api.github.com/repos/${REPO}${path}`, {...init, signal: AbortSignal.timeout(15000),
    headers: {Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json',
      'User-Agent': 'SkipperCast-watchdog', 'Content-Type': 'application/json', ...init.headers}});
}

/** The published live feed (conditions/latest.json): R2 first, then the branch; null when unreadable. */
export async function liveFeed(): Promise<ExternalJSON> {
  const url = RAW + 'conditions/latest.json';
  let feed: ExternalJSON = await readBucketJSON(url).catch(() => undefined);
  if (feed === undefined) {
    const response = await fetch(url, {signal: AbortSignal.timeout(15000), cf: {cacheTtl: 60}}).catch(() => null);
    feed = response?.ok ? await response.json().catch(() => null) : null;
  }
  return feed;
}

export async function watchdog(env: WatchdogEnv, now = Date.now(), feedRead: Promise<ExternalJSON> = liveFeed()): Promise<{age_minutes: number | null; action: string}> {
  const feed = await feedRead;
  const age = feedAgeMinutes(feed, now);
  const result = {age_minutes: Number.isFinite(age) ? Math.round(age) : null, action: 'none'};
  if (age <= STALE_MINUTES) return result;
  if (!env.GITHUB_TOKEN) { console.warn('Live feed stale; GITHUB_TOKEN not set, cannot restart', result); return {...result, action: 'no-token'}; }
  for (const status of ['in_progress', 'queued']) {
    const runs = await github(env, `/actions/workflows/${WORKFLOW}/runs?status=${status}&per_page=1`);
    if (runs.ok && (await runs.json<{total_count: number}>()).total_count > 0) return {...result, action: `already-${status}`};
  }
  const dispatch = await github(env, `/actions/workflows/${WORKFLOW}/dispatches`, {method: 'POST', body: JSON.stringify({ref: 'main'})});
  const outcome = {...result, action: dispatch.status === 204 ? 'dispatched' : `dispatch-failed-${dispatch.status}`};
  console.log('Live feed watchdog', outcome);
  return outcome;
}
