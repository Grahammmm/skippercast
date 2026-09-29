// Per-request setup from the Worker's bindings: the feed bucket, the identity
// provider, extra allowed origins and a lazy identity resolver.
import type {MiddlewareHandler} from 'hono';
import {useBucket} from '../feeds.ts';
import {sessionUser, SIGN_IN_PATH} from '../auth.ts';
import type {SessionUser} from '../auth.ts';
import {db} from '../http.ts';
import type {AppEnv, Env} from '../env.ts';

// Identity is SkipperCast's own. No request header names a user: a visitor can
// send any header, so none is ever trusted. IDENTITY_PROVIDER (wrangler.jsonc)
// selects how a request is tied to an account: "skippercast" means a passkey
// session cookie (server/auth.ts). An absent, empty or unknown value means no
// identity at all, so every private route answers 401 (fail closed).
const IDENTITY: Record<string, (request: Request, env: Env) => Promise<SessionUser | null>> = {skippercast: (request, env) => sessionUser(request, () => db(env))};
const SIGN_IN: Record<string, string> = {skippercast: SIGN_IN_PATH};
export const signInPath = (provider: string): string | null => Object.hasOwn(SIGN_IN, provider) ? SIGN_IN[provider]! : null;
export const accountsEnabled = (provider: string): boolean => Object.hasOwn(IDENTITY, provider);

export const context: MiddlewareHandler<AppEnv> = async (c, next) => {
  const env = c.env ?? {};
  useBucket(env);
  const provider = String(env.IDENTITY_PROVIDER ?? 'none');
  c.set('path', new URL(c.req.url).pathname);
  c.set('identityProvider', provider);
  // Extra origins (e.g. a workers.dev staging copy, or http://localhost:8787 for
  // wrangler dev) may post and use passkeys; production origins come from the deployment policy.
  c.set('extraOrigins', new Set(String(env.EXTRA_ORIGINS || '').split(',').map(s => s.trim()).filter(s => /^https:\/\/[a-z0-9.-]+$/.test(s) || /^http:\/\/localhost(:\d{1,5})?$/.test(s))));
  // The identity resolver is chosen from IDENTITY_PROVIDER only; storage is
  // touched only when a route asks who is signed in.
  const resolve = accountsEnabled(provider) ? IDENTITY[provider]! : async () => null;
  c.set('identify', async () => { const user = await resolve(c.req.raw, env); c.set('user', user); return user; });
  await next();
};
