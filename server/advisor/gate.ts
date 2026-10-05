// The Text Advisor's hard switch as middleware: every advisor path answers 404
// unless TEXT_ADVISOR_ENABLED is "true" in this request's env. `app` is a
// module-level singleton and env exists only per request, so the router is
// mounted unconditionally and gates itself here (01 § request flow).
import type {MiddlewareHandler} from 'hono';
import {json} from '../http.ts';
import {advisorSettings} from './settings.ts';
import {fleetSettings} from '../fleet/settings.ts';
import type {AppEnv} from '../env.ts';

export const gate: MiddlewareHandler<AppEnv> = async (c, next) => {
  if (!advisorSettings(c.env).enabled) return json({error: 'Not found'}, 404);
  await next();
};

/**
 * /boats/* (charter-fleet design § 13, CF-33): the one boat page serves advisor boats and
 * charter fleet registry vessels, so it passes when either TEXT_ADVISOR_ENABLED or
 * FLEET_ENABLED is on; the page itself reads each source only while its flag is on.
 */
export const boatsGate: MiddlewareHandler<AppEnv> = async (c, next) => {
  if (!advisorSettings(c.env).enabled && !fleetSettings(c.env).enabled) return json({error: 'Not found'}, 404);
  await next();
};
