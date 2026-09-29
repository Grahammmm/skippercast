// Worker entry (bundled by scripts/build-worker.mjs into dist/server/index.js).
import {app} from './app.ts';
import {useBucket} from './feeds.ts';
import {watchdog} from './watchdog.ts';
import {scheduledPrune} from './trips.ts';
import type {Env} from './env.ts';

export {ClientError, RateLimited} from './errors.ts';
export {validateSubscription, validateTrip, validateTripBoat, prune, checkTrips} from './trips.ts';
export {canonicalRedirect} from './middleware/canonical.ts';
export {app};

// Cron (every 15 minutes): restart a stalled live refresh, and apply retention.
async function scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
  useBucket(env);
  ctx.waitUntil(Promise.all([watchdog(env), scheduledPrune(env)]));
}

export default {fetch: app.fetch, scheduled} satisfies ExportedHandler<Env>;
