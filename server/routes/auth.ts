// /api/auth/*: passkey registration, sign-in, sign-out and passkey management
// (server/auth.ts). A per-IP budget on every call; mutations need an allowed Origin.
import {Hono} from 'hono';
import {authRoute, relyingParty} from '../auth.ts';
import {origins} from '../config.ts';
import {json, body, budget, db, requireOrigin} from '../http.ts';
import {clientIP} from '../edge-cache.ts';
import {accountsEnabled} from '../middleware/context.ts';
import type {AppEnv} from '../env.ts';

export const auth = new Hono<AppEnv>();
auth.all('/api/auth/*', async (c, next) => {
  const path = c.var.path, request = c.req.raw;
  if (!path.startsWith('/api/auth/')) return next();   // '/api/auth' itself is a private path
  if (!accountsEnabled(c.var.identityProvider)) return json({error: 'Accounts are not available on this site', signIn: null}, 404);
  await budget(c.env, 'auth:' + clientIP(request), 20);
  if (request.method !== 'GET') requireOrigin(request, c.var.extraOrigins);
  const current = await c.var.identify();
  const rp = relyingParty(new URL(request.url), new Set([...origins, ...c.var.extraOrigins]));
  const answered = await authRoute(request, {path, db: db(c.env), rp, body, json, current});
  return answered ?? json({error: 'Not found'}, 404);
});
