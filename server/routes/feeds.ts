// GET /feeds/<branch>/<path>: published feeds from R2 (edge-cached, Range and
// ETag aware) or their GitHub branch; per-IP limited (server/feeds.ts).
import {Hono} from 'hono';
import {serveFeed} from '../feeds.ts';
import {build} from '../config.ts';
import {rateLimit} from '../middleware/rate-limit.ts';
import {waitUntil} from './util.ts';
import type {AppEnv} from '../env.ts';

export const feeds = new Hono<AppEnv>();
feeds.get('/feeds/*', rateLimit('FEED_LIMITER', 'feeds'), async c => {
  const served = await serveFeed(c.req.raw, c.var.path, c.env.ASSETS, {ctx: waitUntil(c), build: build()});
  return served ?? new Response('Not found', {status: 404});
});
