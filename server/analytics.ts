// Workers Analytics Engine: one data point per request, LLM call, queue batch
// and cron run, in the dataset `skippercast_events` (binding ANALYTICS, added
// to the deploy config only with ENABLE_ANALYTICS=true). Without the binding
// every write is a no-op. A failed write never affects the request.
//
// Never written: owner or user ids, IP addresses, emails, raw paths or query
// strings, boat names or lookup queries. Routes are Hono route patterns
// ('/api/trips', '/feeds/*'), so the set of values is bounded.
//
// Columns, per kind (index1 and blob1 are the kind; scripts/ops_report.py and
// docs/cloudflare.md#observability query these positions):
//
//   request      blob2 route, blob3 method, blob4 cache (hit|miss|none), blob5 colo,
//                blob6 request-id hash (16 hex of sha256)
//                double1 status, double2 ms, double3 weight (rows written per request, see FEED_SAMPLE)
//   llm          blob2 feature, blob3 outcome, blob4 model
//                double1 input tokens, double2 output tokens, double3 web searches, double4 turns
//   queue_batch  blob2 queue, blob3 outcome (ok|retried|dead)
//                double1 messages, double2 owners, double3 retried, double4 invalid, double5 checked,
//                double6 changes, double7 delivered, double8 held, double9 in_app, double10 ms
//                (advisor queues: double5 = messages done, double7 = texts sent, double8 = held;
//                owners, changes and in_app are 0)
//   cron         blob2 cron, blob3 watchdog action, blob4 trip-check action, blob5 prune outcome,
//                blob6 advisor outcome (ok|disabled|no-db|partial|error; server/advisor/cron.ts)
//                double1 ms, double2 owners queued, double3 live feed age minutes (-1 unknown)
//   advisor_turn blob2 intent, blob3 outcome (done|held|dropped|retried|timeout|failed)
//                double1 ms, double2 actions, double3 sends, double4 retries (message attempts - 1)
//                (server/advisor/analytics.ts: one per processed inbound text)
//   publish      blob2 post kind, blob3 outcome; double1 ms (one per social publish attempt)
//   client_event, client_error  funnel events and browser errors posted to
//                /api/telemetry; columns in server/telemetry.ts
import type {MiddlewareHandler} from 'hono';
import {matchedRoutes} from 'hono/route';
import {hash} from './http.ts';
import type {AppEnv, Env} from './env.ts';

export const DATASET = 'skippercast_events';
// Successful /feeds/ reads (map tiles by byte range, many per visit) are written
// 1 in FEED_SAMPLE, with double3 = FEED_SAMPLE so sums stay unbiased. Errors
// and every other route are written every time. Keeps the free plan's
// 100,000 data points a day for the requests that matter.
export const FEED_SAMPLE = 10;

type Point = {blobs: string[]; doubles: number[]};
const clip = (value: unknown, max = 96): string => String(value ?? '').slice(0, max);
const num = (value: unknown): number => typeof value === 'number' && Number.isFinite(value) ? value : 0;

/** Write one data point of `kind`; never throws. */
export function writePoint(env: Pick<Env, 'ANALYTICS'> | undefined, kind: string, {blobs, doubles}: Point): void {
  const dataset = env?.ANALYTICS;
  if (!dataset) return;
  try { dataset.writeDataPoint({indexes: [kind], blobs: [kind, ...blobs.map(b => clip(b))], doubles: doubles.map(num)}); }
  catch { /* analytics must never fail a request */ }
}

export interface LlmUsage {model?: string; turns?: number; input_tokens?: number; output_tokens?: number; web_search_requests?: number}
export function recordLlm(env: Pick<Env, 'ANALYTICS'>, feature: string, outcome: string, usage: LlmUsage): void {
  writePoint(env, 'llm', {blobs: [feature, outcome, usage.model || ''],
    doubles: [num(usage.input_tokens), num(usage.output_tokens), num(usage.web_search_requests), num(usage.turns)]});
}

export interface BatchCounts {messages: number; owners?: number; retried?: number; invalid?: number; checked?: number; changes?: number; delivered?: number; held?: number; in_app?: number}
export function recordQueueBatch(env: Pick<Env, 'ANALYTICS'>, queue: string, outcome: string, counts: BatchCounts, ms: number): void {
  writePoint(env, 'queue_batch', {blobs: [queue, outcome], doubles: [counts.messages, num(counts.owners), num(counts.retried), num(counts.invalid),
    num(counts.checked), num(counts.changes), num(counts.delivered), num(counts.held), num(counts.in_app), ms]});
}

export interface CronRun {cron: string; watchdog: string; trips: string; prune: string; advisor?: string; ms: number; owners?: number; feed_age_minutes?: number | null}
export function recordCron(env: Pick<Env, 'ANALYTICS'>, run: CronRun): void {
  writePoint(env, 'cron', {blobs: [run.cron, run.watchdog, run.trips, run.prune, run.advisor ?? ''],
    doubles: [run.ms, num(run.owners), typeof run.feed_age_minutes === 'number' ? run.feed_age_minutes : -1]});
}

/** The route pattern that answered, never the raw path. */
export function routeOf(c: Parameters<MiddlewareHandler<AppEnv>>[0]): string {
  try { return matchedRoutes(c)[c.req.routeIndex]?.path || 'unmatched'; } catch { return 'unmatched'; }
}

/**
 * Request metrics middleware (first in the chain, so it sees the final status,
 * including errors mapped under /api/). An exception that escapes the app is
 * recorded as status 500 and re-thrown unchanged.
 */
export const metrics: MiddlewareHandler<AppEnv> = async (c, next) => {
  const started = Date.now();
  let status = 500;
  try { await next(); status = c.res.status; }
  finally {
    const env = c.env;
    if (env?.ANALYTICS) {
      const route = routeOf(c), sampled = route.startsWith('/feeds') && status < 400;
      if (!sampled || Math.random() < 1 / FEED_SAMPLE) {
        const cache = status < 500 ? c.res.headers.get('X-SC-Cache') : null;
        const colo = (c.req.raw as {cf?: {colo?: unknown}}).cf?.colo;
        const id = c.get('requestId');
        writePoint(env, 'request', {blobs: [route, c.req.method, cache === 'hit' || cache === 'miss' ? cache : 'none', typeof colo === 'string' ? colo : '', id ? (await hash(id)).slice(0, 16) : ''],
          doubles: [status, Date.now() - started, sampled ? FEED_SAMPLE : 1]});
      }
    }
  }
};
