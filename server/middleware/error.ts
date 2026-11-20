// Typed error mapping for /api/, in one place. Errors caused by the request
// itself answer 400 with their fixed, safe message; rate limits 429; anything
// else is a dependency failure and answers a generic 503. Outside /api/ an
// error is not mapped: the Worker fails as it always has.
import type {ErrorHandler} from 'hono';
import {ClientError, RateLimited} from '../errors.ts';
import {AuthError} from '../auth.ts';
import {json} from '../http.ts';
import {routeOf} from '../analytics.ts';
import type {AppEnv} from '../env.ts';

export const onError: ErrorHandler<AppEnv> = (error, c) => {
  const path = c.get('path') ?? new URL(c.req.url).pathname;
  if (!path.startsWith('/api/')) throw error;
  const client = error instanceof ClientError || error instanceof AuthError, limited = error instanceof RateLimited, message = error.message || '';
  const status = limited ? 429 : client ? 400 : 503;
  // Use only the registered API pattern, never the URL. The API catch-all
  // and failures outside a specific API route have no route class.
  const pattern = routeOf(c);
  const route = pattern.startsWith('/api/') && pattern !== '/api/*' ? pattern : 'unmatched';
  console.error('SkipperCast request failed', {route, status, type: client ? 'validation' : limited ? 'rate' : 'dependency', request_id: c.get('requestId')});
  return json({error: limited ? 'Please try again shortly' : client ? message : 'This service is temporarily unavailable. Your existing records are preserved.'}, status);
};
