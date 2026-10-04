// Worker entry (bundled by scripts/build-worker.mjs into dist/server/index.js).
import {app} from './app.ts';
import {useBucket} from './feeds.ts';
import {watchdog, liveFeed} from './watchdog.ts';
import {scheduleTripChecks, consumeTripChecks, consumeDeadLetters, TRIP_DLQ} from './trip-queue.ts';
import type {TripCheckMessage} from './trip-queue.ts';
import {scheduledPrune} from './trips.ts';
import {recordCron, recordQueueBatch} from './analytics.ts';
import {consumeAdvisor, consumeAdvisorDeadLetters, ADVISOR_QUEUE_NAME, ADVISOR_DLQ_NAME} from './advisor/consumer.ts';
import {advisorCron} from './advisor/cron.ts';
import {channelFor} from './advisor/channels/index.ts';
import type {AdvisorMessage} from './advisor/types.ts';
import type {Env} from './env.ts';

export {ClientError, RateLimited} from './errors.ts';
export {validateSubscription, validateTrip, validateTripBoat, validateTripPlan, PLAN_LIMITS, prune, checkTrips, checkOwnerTrips} from './trips.ts';
export {scheduleTripChecks, consumeTripChecks, consumeDeadLetters} from './trip-queue.ts';
export {canonicalRedirect} from './middleware/canonical.ts';
export {app};

// Cron (every 15 minutes): restart a stalled live refresh, apply retention and,
// when the trip queue is bound, queue trip checks for a new live publication,
// and run the Text Advisor's hooks (a no-op unless TEXT_ADVISOR_ENABLED).
// One `cron` analytics point per run records what each part did.
async function scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
  useBucket(env);
  const started = Date.now(), feed = liveFeed();
  const failed = (part: string) => (error: unknown) => { console.error(`Cron ${part} failed`, {reason: String((error as Error)?.message).slice(0, 200)}); return null; };
  const run = Promise.all([
    watchdog(env, started, feed).catch(failed('watchdog')),
    scheduledPrune(env),
    scheduleTripChecks(env, started, feed).then(result => { if (result.action !== 'no-queue') console.log(JSON.stringify({event: 'trip_check_schedule', ...result})); return result; }).catch(failed('trip checks')),
    advisorCron(env, started).catch(() => 'error' as const),
  ]).then(([dog, prune, trips, advisor]) => {
    recordCron(env, {cron: controller?.cron || '', watchdog: dog?.action ?? 'error', trips: trips?.action ?? 'error', prune, advisor, ms: Date.now() - started,
      owners: trips?.owners, feed_age_minutes: dog?.age_minutes});
    if (!dog || !trips) throw Error('cron run failed');
  });
  ctx.waitUntil(run.catch(() => {}));
  await run;   // a failed part fails the invocation, so Cloudflare's cron-failure alerts see it
}

// Queue consumer (only when ENABLE_QUEUES / ENABLE_ADVISOR added the bindings):
// Text Advisor messages and their dead letters, then trip checks and theirs.
async function queue(batch: MessageBatch<TripCheckMessage | AdvisorMessage>, env: Env): Promise<void> {
  useBucket(env);
  const started = Date.now();
  if (batch.queue === ADVISOR_DLQ_NAME) {
    const dead = await consumeAdvisorDeadLetters(batch as MessageBatch<AdvisorMessage>, env, {channelFor});
    recordQueueBatch(env, batch.queue, 'dead', {messages: batch.messages.length, checked: dead.failed, delivered: dead.apologies}, Date.now() - started);
    return;
  }
  if (batch.queue === ADVISOR_QUEUE_NAME) {
    const r = await consumeAdvisor(batch as MessageBatch<AdvisorMessage>, env, {channelFor});
    recordQueueBatch(env, batch.queue, r.retried ? 'retried' : 'ok', {messages: r.messages, retried: r.retried, invalid: r.invalid, checked: r.done, delivered: r.sends, held: r.held}, Date.now() - started);
    return;
  }
  const trips = batch as MessageBatch<TripCheckMessage>;
  if (batch.queue === TRIP_DLQ) { consumeDeadLetters(trips); recordQueueBatch(env, batch.queue, 'dead', {messages: batch.messages.length}, Date.now() - started); return; }
  const result = await consumeTripChecks(trips, env);
  recordQueueBatch(env, batch.queue, result.retried ? 'retried' : 'ok', {messages: batch.messages.length, ...result}, Date.now() - started);
}

export default {fetch: app.fetch, scheduled, queue} satisfies ExportedHandler<Env, TripCheckMessage | AdvisorMessage>;
