// Typed error mapping for /api/, in one place. Errors caused by the request
// itself answer 400 with their fixed, safe message; rate limits 429; anything
// else is a dependency failure and answers a generic 503. Outside /api/ an
// error is not mapped: the Worker fails as it always has.
import type {ErrorHandler} from 'hono';
import {ClientError, RateLimited} from '../errors.ts';
import {AuthError} from '../auth.ts';
import {json} from '../http.ts';
import type {AppEnv} from '../env.ts';

/**
 * Hardening (docs/legal/threat-model.md § 9.1, § 9.3): a path segment that is a
 * secret (the webhook token, an old-form upload or export token) never reaches
 * our logs. The advisor's routes answer their own errors, so this is the net
 * under them.
 */
const SECRET_PATHS = /^(\/api\/advisor\/(?:inbound\/(?:bluebubbles|twilio|twilio-status)|upload|export)\/)[^/]+/;
export const redactPath = (path: string): string => path.replace(SECRET_PATHS, '$1[redacted]');

export const onError: ErrorHandler<AppEnv> = (error, c) => {
  const path = c.get('path') ?? new URL(c.req.url).pathname;
  if (!path.startsWith('/api/')) throw error;
  const client = error instanceof ClientError || error instanceof AuthError, limited = error instanceof RateLimited, message = error.message || '';
  console.error('SkipperCast request failed', {path: redactPath(path), type: client ? 'validation' : limited ? 'rate' : 'dependency', request_id: c.get('requestId')});
  return json({error: limited ? 'Please try again shortly' : client ? message : 'This service is temporarily unavailable. Your existing records are preserved.'}, limited ? 429 : client ? 400 : 503);
};
