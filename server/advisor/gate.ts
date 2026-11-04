// The Text Advisor's hard switch as middleware: every advisor path answers 404
// unless TEXT_ADVISOR_ENABLED is "true" in this request's env. `app` is a
// module-level singleton and env exists only per request, so the router is
// mounted unconditionally and gates itself here (01 § request flow).
import type {MiddlewareHandler} from 'hono';
import {json} from '../http.ts';
import {advisorSettings} from './settings.ts';
import type {BetaScope} from './settings.ts';
import {fleetSettings} from '../fleet/settings.ts';
import {publicPagesSettings} from '../pages-settings.ts';
import type {AppEnv} from '../env.ts';

export const gate: MiddlewareHandler<AppEnv> = async (c, next) => {
  if (!advisorSettings(c.env).enabled) return json({error: 'Not found'}, 404);
  await next();
};

/**
 * BF-advisor-beta: whether an inbound whose resolved region and reply language are given is inside the pilot's scope
 * (betaScope in settings.ts). No list means no restriction. With a region list, a region that could not be resolved
 * (null) is outside it: the scope fails closed. The engine answers an outside inbound with nothing at all, which is
 * what the sender gets while TEXT_ADVISOR_ENABLED is off (the gate's 404 sends no text).
 */
export function inBetaScope(scope: BetaScope, region: string | null, language: string): boolean {
  return (!scope.regions || (region !== null && scope.regions.includes(region))) && (!scope.langs || scope.langs.includes(language));
}

/**
 * /boats/* (charter-fleet design § 13, CF-33): the one boat page serves advisor boats and
 * charter fleet registry vessels, so it passes when either TEXT_ADVISOR_ENABLED or
 * FLEET_ENABLED is on; the page itself reads each source only while its flag is on.
 */
export const boatsGate: MiddlewareHandler<AppEnv> = async (c, next) => {
  if (!advisorSettings(c.env).enabled && !fleetSettings(c.env).enabled) return json({error: 'Not found'}, 404);
  await next();
};

/** Port and species pages can be enabled independently of the text advisor. */
export const pagesGate: MiddlewareHandler<AppEnv> = async (c, next) => {
  if (!advisorSettings(c.env).enabled && !publicPagesSettings(c.env).enabled) return json({error: 'Not found'}, 404);
  await next();
};
