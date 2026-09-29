// Queue-based trip checks (Cloudflare Queues). Optional: the bindings exist only
// when the deploy sets ENABLE_QUEUES=true (scripts/wrangler_config.mjs). Without
// TRIP_QUEUE the cron does nothing here and trip checks keep running from the
// GitHub `notify` job through POST /api/jobs/check, as before.
//
//   cron (every 15 min) -> new live publication? -> one message per owner with
//   due trips, sent 100 at a time -> consumer (batches of 25) checks each owner's
//   trips -> a message that keeps failing goes to the dead-letter queue.
//
// Every step is safe to repeat: alert events and push deliveries are claimed with
// stable ids (server/trips.ts), so a re-delivered message, the manual job and the
// queue can overlap without a second notification.
import {checkOwnerTrips, ownersWithDueTrips} from './trips.ts';
import type {FeedCache} from './trips.ts';
import {liveFeed} from './watchdog.ts';
import {db} from './http.ts';
import type {Env} from './env.ts';
import type {ExternalJSON} from './types.ts';

export const TRIP_QUEUE = 'skippercast-trip-checks';
export const TRIP_DLQ = 'skippercast-trip-checks-dlq';
export interface TripCheckMessage {owner: string; publication: string}

export const SEND_BATCH = 100;      // Queues accepts at most 100 messages per sendBatch
export const OWNER_PAGE = 500;      // owners read from D1 per query
// The live publication uploads many files to R2; wait this long after it so the
// regional feeds the checks read belong to the same cycle.
export const SETTLE_MS = 2 * 60000;
export const STATE_KEY = 'trip_checks.publication';

/** A stable id for one live-conditions publication, or null when the feed is unreadable. */
export function publicationMarker(feed: ExternalJSON): string | null {
  const done = feed?.completed_at || feed?.generated_at;
  if (typeof done !== 'string' || !Number.isFinite(Date.parse(done))) return null;
  const run = typeof feed?.run_id === 'string' ? feed.run_id : '';
  return `${run}@${done}`.slice(0, 200);
}

/** Send one message per owner with due trips, in bounded pages and batches. */
export async function enqueueDueOwners(env: Env, queue: Queue<TripCheckMessage>, publication: string): Promise<{owners: number; batches: number}> {
  let after = '', owners = 0, batches = 0;
  for (;;) {
    const page = await ownersWithDueTrips(env, after, OWNER_PAGE);
    for (let i = 0; i < page.length; i += SEND_BATCH) {
      await queue.sendBatch(page.slice(i, i + SEND_BATCH).map(owner => ({body: {owner, publication}, contentType: 'json' as const})));
      batches++;
    }
    owners += page.length;
    if (page.length < OWNER_PAGE) return {owners, batches};
    after = page.at(-1)!;
  }
}

export interface ScheduleResult {action: string; publication?: string; owners?: number; batches?: number}

/**
 * Cron producer: when the live feed shows a publication not yet queued, claim it
 * in D1 (job_state) and enqueue the owners. A failed send releases the claim so
 * the next cron run tries the same publication again.
 */
export async function scheduleTripChecks(env: Env, now = Date.now(), feedRead: Promise<ExternalJSON> = liveFeed()): Promise<ScheduleResult> {
  if (!env.TRIP_QUEUE) return {action: 'no-queue'};
  if (!env.DB) return {action: 'no-db'};
  const feed = await feedRead, publication = publicationMarker(feed);
  if (!publication) return {action: 'no-feed'};
  const published = Date.parse(feed.published_at || feed.completed_at);
  if (Number.isFinite(published) && now - published < SETTLE_MS) return {action: 'settling', publication};
  const previous = (await db(env).prepare('SELECT value FROM job_state WHERE key=?').bind(STATE_KEY).first<{value: string}>())?.value ?? null;
  if (previous === publication) return {action: 'unchanged', publication};
  const claim = await db(env).prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at WHERE job_state.value IS NOT excluded.value')
    .bind(STATE_KEY, publication, new Date(now).toISOString()).run();
  if (!claim.meta.changes) return {action: 'unchanged', publication};
  try {
    return {action: 'enqueued', publication, ...await enqueueDueOwners(env, env.TRIP_QUEUE, publication)};
  } catch (error) {
    const release = previous === null
      ? db(env).prepare('DELETE FROM job_state WHERE key=? AND value=?').bind(STATE_KEY, publication)
      : db(env).prepare('UPDATE job_state SET value=? WHERE key=? AND value=?').bind(previous, STATE_KEY, publication);
    await release.run().catch(() => {});
    console.error('Trip check enqueue failed; the next cron run retries', {reason: String((error as Error).message).slice(0, 200)});
    return {action: 'enqueue-failed', publication};
  }
}

export interface ConsumeResult {owners: number; retried: number; invalid: number; checked: number; changes: number; delivered: number; held: number; in_app: number}

/**
 * Consumer: check every due trip of each owner in the batch. A message is
 * acknowledged when its owner was checked (a held delivery is recorded in its
 * receipt and never resent blindly), retried when the check threw, and dropped
 * when its body is malformed. After max_retries Cloudflare moves it to the DLQ.
 */
export async function consumeTripChecks(batch: MessageBatch<TripCheckMessage>, env: Env, now = Date.now()): Promise<ConsumeResult> {
  const feeds: FeedCache = new Map();
  const out: ConsumeResult = {owners: 0, retried: 0, invalid: 0, checked: 0, changes: 0, delivered: 0, held: 0, in_app: 0};
  for (const message of batch.messages) {
    const owner = message.body?.owner;
    if (typeof owner !== 'string' || !owner || owner.length > 200) { out.invalid++; message.ack(); continue; }
    try {
      const result = await checkOwnerTrips(env, owner, now, feeds);
      for (const key of ['checked', 'changes', 'delivered', 'held', 'in_app'] as const) out[key] += result[key];
      out.owners++;
      message.ack();
    } catch (error) {
      out.retried++;
      console.error('Trip check failed; message will be retried', {attempt: message.attempts, reason: String((error as Error).message).slice(0, 200)});
      message.retry({delaySeconds: Math.min(300, 30 * message.attempts)});
    }
  }
  console.log(JSON.stringify({event: 'trip_check_batch', queue: batch.queue, messages: batch.messages.length, ...out}));
  return out;
}

/**
 * Dead-letter consumer: a message lands here after max_retries failed checks.
 * It is logged (counts only, never the owner) and acknowledged: the owner's trips
 * are queued again with the next publication, so nothing waits on this message.
 */
export function consumeDeadLetters(batch: MessageBatch<TripCheckMessage>): {dead: number} {
  console.error(JSON.stringify({event: 'trip_check_dead_letter', queue: batch.queue, messages: batch.messages.length}));
  batch.ackAll();
  return {dead: batch.messages.length};
}
