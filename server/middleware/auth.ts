// Private routes: a signed-in user, an allowed Origin on every mutation and a
// per-owner request budget (30 a minute).
import type {MiddlewareHandler} from 'hono';
import {json, requireOrigin, budget} from '../http.ts';
import {signInPath} from './context.ts';
import type {AppEnv} from '../env.ts';

export const requireUser: MiddlewareHandler<AppEnv> = async (c, next) => {
  const who = await c.var.identify(), owner = who?.id || null, signIn = signInPath(c.var.identityProvider);
  if (!owner) return json({error: signIn ? 'Sign in to save private trips or feedback' : 'Accounts are not available on this site yet', signIn}, 401);
  if (c.req.method !== 'GET') { requireOrigin(c.req.raw, c.var.extraOrigins); await budget(c.env, owner); }
  c.set('owner', owner);
  await next();
};
