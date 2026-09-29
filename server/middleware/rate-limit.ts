// Per-IP limits on anonymous reads, from a Workers Rate Limiting binding.
// Limits apply only where the binding exists (not in local tests); a limiter
// failure fails open (server/edge-cache.ts).
import type {MiddlewareHandler} from 'hono';
import {overLimit, clientIP, tooManyRequests} from '../edge-cache.ts';
import type {AppEnv} from '../env.ts';

export const rateLimit = (binding: 'PUBLIC_LIMITER' | 'FEED_LIMITER', prefix: string): MiddlewareHandler<AppEnv> => async (c, next) => {
  if (await overLimit(c.env?.[binding], prefix + ':' + clientIP(c.req.raw))) return tooManyRequests();
  await next();
};
