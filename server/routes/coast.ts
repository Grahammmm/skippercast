import {Hono} from 'hono';
import {coastFeeds, serveCoastData} from '../coast-data.ts';
import {rateLimit} from '../middleware/rate-limit.ts';
import type {WaitUntil} from '../edge-cache.ts';
import type {AppEnv} from '../env.ts';

export const coastData = new Hono<AppEnv>();
coastData.all('/api/coast/*', rateLimit('FEED_LIMITER', 'coast'), c => serveCoastData(c.req.raw, fetch, c.var.feeds ?? null, coastFeeds(c.env.COAST_FEEDS)));
coastData.all('/coast-data/*', rateLimit('FEED_LIMITER', 'coast'), c => {
  const store = c.var.feeds ?? null, binding = c.env?.FEEDS;
  let ctx: WaitUntil;
  try { ctx = c.executionCtx; } catch { /* Local requests may have no execution context. */ }
  // The unwrapped binding is a key only. All reads use the metered store.
  return serveCoastData(c.req.raw, fetch, store, undefined, {verification: store && binding ? {binding, ctx} : undefined});
});
