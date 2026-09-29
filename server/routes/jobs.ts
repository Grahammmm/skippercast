// POST /api/jobs/check: the scheduler pages through saved trips. Authorised by a
// short-lived GitHub Actions OIDC token (server/job-auth.ts), never a password.
import {Hono} from 'hono';
import {verifyJobToken} from '../job-auth.ts';
import {checkTrips} from '../trips.ts';
import {deployment} from '../config.ts';
import {json, body, budget} from '../http.ts';
import {ClientError} from '../errors.ts';
import type {AppEnv} from '../env.ts';

export const jobs = new Hono<AppEnv>();
jobs.post('/api/jobs/check', async c => {
  const token = c.req.header('Authorization')?.replace(/^Bearer /, '');
  const claims = await verifyJobToken(token, deployment); if (!claims) return json({error: 'Unauthorized'}, 401);
  const input = await body(c.req.raw), cursor = input.cursor || ''; if (typeof cursor !== 'string' || cursor.length > 50) throw new ClientError('invalid cursor');
  await budget(c.env, 'job:' + claims.jti);
  return json(await checkTrips(c.env, cursor));
});
