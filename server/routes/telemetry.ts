// POST /api/telemetry: cookie-less funnel events and client errors from
// web/telemetry.ts (navigator.sendBeacon), validated by server/telemetry.ts.
// Anonymous like the other public routes, but only from an allowed Origin,
// rate-limited per IP (PUBLIC_LIMITER) and capped at 4 KiB. Answers 204 whether
// or not Analytics Engine is bound: without the binding nothing is written.
import {Hono} from 'hono';
import {body, requireOrigin} from '../http.ts';
import {rateLimit} from '../middleware/rate-limit.ts';
import {MAX_BODY, parseBatch, recordBatch} from '../telemetry.ts';
import type {AppEnv} from '../env.ts';

export const telemetry = new Hono<AppEnv>();
telemetry.post('/api/telemetry', rateLimit('PUBLIC_LIMITER', 'telemetry'), async c => {
  requireOrigin(c.req.raw, c.var.extraOrigins);
  await recordBatch(c.env, parseBatch(await body(c.req.raw, MAX_BODY)));
  return new Response(null, {status: 204, headers: {'Cache-Control': 'no-store'}});
});
