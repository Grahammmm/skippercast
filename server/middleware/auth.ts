// Private routes: a signed-in user, an allowed Origin on every mutation and
// per-caller limits (SC-LAUNCH-4, docs/operations/cost-ceiling.md):
//   - per IP, before the session lookup, so a flood of requests (with or
//     without a cookie) cannot turn into D1 reads: FEED_LIMITER, 300 a minute;
//   - per account on reads: PUBLIC_LIMITER, 60 a minute;
//   - per account on mutations: the D1 request budget, 30 a minute.
// Over a limit answers the documented 429 (Retry-After: 60). The two Rate
// Limiting checks no-op where the bindings are absent (tests, a bare dev runtime).
import type {MiddlewareHandler} from 'hono';
import {json, requireOrigin, budget} from '../http.ts';
import {overLimit, clientIP, tooManyRequests} from '../edge-cache.ts';
import {signInPath} from './context.ts';
import type {AppEnv} from '../env.ts';

export const requireUser: MiddlewareHandler<AppEnv> = async (c, next) => {
  if (await overLimit(c.env?.FEED_LIMITER, 'private-ip:' + clientIP(c.req.raw))) return tooManyRequests();
  const who = await c.var.identify(), owner = who?.id || null, signIn = signInPath(c.var.identityProvider);
  if (!owner) return json({error: signIn ? 'Sign in to save private trips or feedback' : 'Accounts are not available on this site yet', signIn}, 401);
  if (c.req.method !== 'GET') { requireOrigin(c.req.raw, c.var.extraOrigins); await budget(c.env, owner); }
  else if (await overLimit(c.env?.PUBLIC_LIMITER, 'account:' + owner)) return tooManyRequests();
  c.set('owner', owner);
  await next();
};
