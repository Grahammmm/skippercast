// Cron watchdog (Cloudflare Cron Trigger, every 15 minutes). GitHub runs the
// heavy Python refresh but throttles its own schedules; if the published live
// feed is more than 45 minutes old and no refresh is running, dispatch one.
// It also logs critical sources (buoys, alerts, tides, models) that have served
// degraded data past the limit scripts/check_feed_freshness.py uses
// (catalog/feed-health.json), naming any kind whose every source is out (the
// check's failure condition); a new run would not fix those, so it only warns.
// Needs GITHUB_TOKEN (fine-grained, Actions: read and write on this repo).
import health from '../catalog/feed-health.json' with {type: 'json'};
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

const CRITICAL_KINDS = new Set<string>(health.critical_kinds);
export const CRITICAL_DEGRADED_HOURS = health.feeds.conditions.critical_degraded_hours;

export interface DegradedSource {id: string; kind: string; status: string; critical: boolean; age_hours: number | null}

const clock = (value: unknown): number => typeof value === 'string' && /(Z|[+-]\d\d:?\d\d)$/.test(value) ? Date.parse(value) : NaN;

/** How old a source's data was when the feed was built (its checked_at, else the feed's), in hours; null without a data time. */
export function dataAgeHours(source: ExternalJSON, feed: ExternalJSON): number | null {
  const data = source?.data && typeof source.data === 'object' ? source.data : {};
  const built = [source?.checked_at, feed?.generated_at, feed?.published_at, feed?.completed_at].map(clock).find(Number.isFinite);
  if (built === undefined) return null;
  for (const stamp of [data.sample_at, data.issued_at, source?.data_retrieved_at, source?.last_success_at]) {
    const at = clock(stamp);
    if (Number.isFinite(at)) return Math.max(0, (built - at) / 3_600_000);
  }
  return null;
}

/** Every source whose status is not ok, critical first: the same rows check_feed_freshness.py reports. */
export function degradedSources(feed: ExternalJSON): DegradedSource[] {
  const sources = feed?.sources && typeof feed.sources === 'object' ? feed.sources : {};
  return Object.entries<ExternalJSON>(sources)
    .filter(([, source]) => source && typeof source === 'object' && source.status !== 'ok')
    .map(([key, source]) => ({id: String(source.id || key), kind: String(source.kind || 'unknown'), status: String(source.status || 'unknown'),
      critical: CRITICAL_KINDS.has(source.kind), age_hours: dataAgeHours(source, feed)}))
    .sort((a, b) => Number(b.critical) - Number(a.critical) || a.id.localeCompare(b.id));
}

/** Critical sources degraded past the limit (or with no data time): every one the freshness check reports. */
export function criticalDegraded(feed: ExternalJSON, limitHours = CRITICAL_DEGRADED_HOURS): DegradedSource[] {
  return degradedSources(feed).filter(row => row.critical && (row.age_hours === null || row.age_hours > limitHours));
}

/**
 * Critical kinds whose every source in the feed is degraded past the limit: the ones that fail
 * the freshness check (failing_kinds in check_feed_freshness.py). One buoy out while another
 * (or its spectrum, also kind observation) reports is a partial outage, not a failing kind.
 */
export function failingKinds(feed: ExternalJSON, limitHours = CRITICAL_DEGRADED_HOURS): string[] {
  const over = new Map<string, number>();
  for (const row of criticalDegraded(feed, limitHours)) over.set(row.kind, (over.get(row.kind) || 0) + 1);
  const totals = new Map<string, number>();
  const sources = feed?.sources && typeof feed.sources === 'object' ? Object.values<ExternalJSON>(feed.sources) : [];
  for (const source of sources) if (source && typeof source === 'object') totals.set(source.kind, (totals.get(source.kind) || 0) + 1);
  return [...over].filter(([kind, count]) => totals.get(kind) === count).map(([kind]) => kind).sort();
}

async function github(env: WatchdogEnv, path: string, init: RequestInit & {headers?: Record<string, string>} = {}): Promise<Response> {
  return fetch(`https://api.github.com/repos/${REPO}${path}`, {...init, signal: AbortSignal.timeout(15000),
    headers: {Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json',
      'User-Agent': 'SkipperCast-watchdog', 'Content-Type': 'application/json', ...init.headers}});
}

const WORKFLOW_FILE = /^[\w.-]{1,100}\.ya?ml$/;

/**
 * Start a workflow_dispatch run of .github/workflows/<file> on `ref` with the
 * watchdog's GITHUB_TOKEN (TA-M1: the advisor dispatches advisor-media.yml
 * through this, so there is one GitHub client). Returns the HTTP status (204
 * when GitHub accepted it), or 0 without a token; a network error throws.
 */
export async function dispatchWorkflow(env: WatchdogEnv, file: string, ref = 'main', inputs?: Record<string, string>): Promise<number> {
  if (!WORKFLOW_FILE.test(file) || !/^[\w./-]{1,100}$/.test(ref)) throw Error('invalid workflow or ref');
  if (!env.GITHUB_TOKEN) return 0;
  const response = await github(env, `/actions/workflows/${file}/dispatches`, {method: 'POST', body: JSON.stringify(inputs ? {ref, inputs} : {ref})});
  await response.body?.cancel().catch(() => {});
  return response.status;
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

export async function watchdog(env: WatchdogEnv, now = Date.now(), feedRead: Promise<ExternalJSON> = liveFeed()): Promise<{age_minutes: number | null; action: string; degraded: string[]; failing_kinds: string[]}> {
  const feed = await feedRead;
  const age = feedAgeMinutes(feed, now);
  const degraded = criticalDegraded(feed);
  const failing = failingKinds(feed);
  if (degraded.length) console.warn(failing.length ? 'Live feed critical kind out' : 'Live feed critical sources degraded (partial)',
    {limit_hours: CRITICAL_DEGRADED_HOURS, failing_kinds: failing,
      sources: degraded.map(row => `${row.id} ${row.status} ${row.age_hours === null ? 'no data time' : `${row.age_hours.toFixed(1)} h`}`)});
  const result = {age_minutes: Number.isFinite(age) ? Math.round(age) : null, action: 'none', degraded: degraded.map(row => row.id), failing_kinds: failing};
  if (age <= STALE_MINUTES) return result;
  if (!env.GITHUB_TOKEN) { console.warn('Live feed stale; GITHUB_TOKEN not set, cannot restart', result); return {...result, action: 'no-token'}; }
  for (const status of ['in_progress', 'queued']) {
    const runs = await github(env, `/actions/workflows/${WORKFLOW}/runs?status=${status}&per_page=1`);
    if (runs.ok && (await runs.json<{total_count: number}>()).total_count > 0) return {...result, action: `already-${status}`};
  }
  const status = await dispatchWorkflow(env, WORKFLOW);
  const outcome = {...result, action: status === 204 ? 'dispatched' : `dispatch-failed-${status}`};
  console.log('Live feed watchdog', outcome);
  return outcome;
}
