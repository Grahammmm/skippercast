// Charter fleet routes (docs/plans/charter-fleet/design.md § 12, § 16). Mounted
// before the private gate and unconditionally: `app` is a module-level
// singleton and env exists only per request, so the router gates itself. Every
// /api/fleet/* and /api/admin/fleet/* path answers 404 unless FLEET_ENABLED is
// "true" in this request's env; /api/fleet/map/* also needs FLEET_MAP_ENABLED.
// The prefixes are reserved here, ahead of their routes, so later tasks inherit
// the gate.
//
// fleetRouter only gates /api/admin/fleet/* and /api/fleet/map/*: it is mounted
// before the private gate, so it must never register handlers there. Those
// handlers belong in adminRoutes (routes/admin.ts), behind requireUser and
// requireAdmin; only the job routes (/api/fleet/jobs/*, requireFleetJob) live here.
//
//   GET /api/fleet/jobs/ping   job identity check: {ok: true, region}
//   GET /go/<slug>             public outbound link, gated and per-IP limited (fleet/go.ts, CF-34)
//   GET /api/fleet/jobs/snapshot, POST /api/fleet/jobs/registry   CF-11 (server/fleet/jobs.ts)
//   /api/admin/fleet/reviews*, /api/admin/fleet/vessels*            CF-30, registered in routes/admin.ts (fleet/admin/*.ts)
import {Hono} from 'hono';
import type {MiddlewareHandler} from 'hono';
import {fleetSettings} from '../fleet/settings.ts';
import {registry, snapshot} from '../fleet/jobs.ts';
import {verifyJobToken} from '../job-auth.ts';
import type {JobClaims, JobScope} from '../job-auth.ts';
import {deployment} from '../config.ts';
import {json, budget} from '../http.ts';
import type {AppEnv} from '../env.ts';
import {rateLimit} from '../middleware/rate-limit.ts';
import {fleetGo} from '../fleet/go.ts';

const NOT_FOUND = (): Response => json({error: 'Not found'}, 404);

/** The fleet's hard switch as middleware (the shape of server/advisor/gate.ts). */
export const fleetGate: MiddlewareHandler<AppEnv> = async (c, next) => {
  const settings = fleetSettings(c.env);
  if (!settings.enabled) return NOT_FOUND();
  if (c.var.path.startsWith('/api/fleet/map/') && !settings.mapEnabled) return NOT_FOUND();
  await next();
};

// The Hermes workflows (§ 12) call /api/fleet/jobs/* with a GitHub Actions OIDC
// token requested for the audience <public_origin>/api/fleet/jobs; each workflow
// must also be listed in deployments/production.json scheduler.workflows.
export const FLEET_JOB_SCOPE: JobScope = {
  audiencePath: '/api/fleet/jobs',
  workflows: ['fleet-registry.yml', 'fleet-osint.yml', 'fleet-ais.yml', 'fleet-health.yml'],
};
/** Test seam: the token check (default: verifyJobToken with FLEET_JOB_SCOPE). */
export const fleetJobs: {verify: (token: string | undefined) => Promise<JobClaims | false>} = {
  verify: token => verifyJobToken(token, deployment, FLEET_JOB_SCOPE),
};
const JOB_BUDGET = 240;   // requests a minute per run (jti), as the advisor-media job

/** A fleet job identity, else 401; sets `fleetJob` to the verified claims. */
export const requireFleetJob: MiddlewareHandler<AppEnv> = async (c, next) => {
  const token = c.req.header('Authorization')?.replace(/^Bearer /, '');
  const claims = await fleetJobs.verify(token);
  if (!claims) return json({error: 'Unauthorized'}, 401);
  await budget(c.env, 'fleet-job:' + claims.jti, JOB_BUDGET);
  c.set('fleetJob', claims);
  await next();
};

const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;   // a regions/<id> directory name

export const fleetRouter = new Hono<AppEnv>();
fleetRouter.use('/api/fleet/*', fleetGate);
fleetRouter.use('/api/admin/fleet/*', fleetGate);
fleetRouter.use('/api/fleet/jobs/*', requireFleetJob);

fleetRouter.get('/api/fleet/jobs/ping', c => {
  const region = c.req.query('region') ?? null;
  if (region !== null && !REGION.test(region)) return json({error: 'invalid region'}, 400);
  return json({ok: true, region});
});

fleetRouter.get('/go/:slug', fleetGate, rateLimit('PUBLIC_LIMITER', 'fleet-go'), c => fleetGo(c));
const UNAVAILABLE = (): Response => json({error: 'This service is temporarily unavailable.'}, 503);
fleetRouter.get('/api/fleet/jobs/snapshot', async c => {
  if (!c.env.DB) return UNAVAILABLE();
  const result = await snapshot(c.env.DB, c.req.query('region'), c.req.query('cursor'));
  return json(result.body, result.status);
});
fleetRouter.post('/api/fleet/jobs/registry', async c => {
  if (!c.env.DB) return UNAVAILABLE();
  const result = await registry(c.env.DB, c.req.raw);
  return json(result.body, result.status);
});
