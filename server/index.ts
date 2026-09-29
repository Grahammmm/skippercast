// Worker entry (bundled by scripts/build-worker.mjs into dist/server/index.js).
import {app} from './app.ts';
import {useBucket} from './feeds.ts';
import {watchdog, liveFeed} from './watchdog.ts';
import {scheduleTripChecks, consumeTripChecks, consumeDeadLetters, TRIP_DLQ} from './trip-queue.ts';
import type {TripCheckMessage} from './trip-queue.ts';
import {scheduledPrune} from './trips.ts';
import type {Env} from './env.ts';

export {ClientError, RateLimited} from './errors.ts';
export {validateSubscription, validateTrip, validateTripBoat, prune, checkTrips, checkOwnerTrips} from './trips.ts';
export {scheduleTripChecks, consumeTripChecks, consumeDeadLetters} from './trip-queue.ts';
export {canonicalRedirect} from './middleware/canonical.ts';
export {app};

// Cron (every 15 minutes): restart a stalled live refresh, apply retention and,
// when the trip queue is bound, queue trip checks for a new live publication.
async function scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
  useBucket(env);
  const feed = liveFeed();
  ctx.waitUntil(Promise.all([watchdog(env, Date.now(), feed), scheduledPrune(env),
    scheduleTripChecks(env, Date.now(), feed).then(result => { if (result.action !== 'no-queue') console.log(JSON.stringify({event: 'trip_check_schedule', ...result})); })]));
}

// Queue consumer (only when ENABLE_QUEUES added the bindings): trip checks and their dead letters.
async function queue(batch: MessageBatch<TripCheckMessage>, env: Env): Promise<void> {
  useBucket(env);
  if (batch.queue === TRIP_DLQ) consumeDeadLetters(batch);
  else await consumeTripChecks(batch, env);
}

export default {fetch: app.fetch, scheduled, queue} satisfies ExportedHandler<Env, TripCheckMessage>;
