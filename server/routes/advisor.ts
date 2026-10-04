// Text Advisor public routes (docs/plans/text-advisor/). Mounted before the
// private gate; every path the advisor owns passes through `gate` first, so it
// all answers 404 until TEXT_ADVISOR_ENABLED=true is deployed. The prefixes are
// reserved here, ahead of their routes, so later tasks inherit the gate and a
// path such as /ports/x never falls through to the static site while dark.
import {Hono} from 'hono';
import {gate} from '../advisor/gate.ts';
import {advisorSettings} from '../advisor/settings.ts';
import {json} from '../http.ts';
import type {AppEnv} from '../env.ts';

export const advisorPublic = new Hono<AppEnv>();

// Webhooks, web chat and APIs; public pages; media; upload links; contact card; the text deep link.
export const ADVISOR_PATHS = ['/api/advisor/*', '/ports/*', '/species/*', '/boats/*', '/media/*', '/u/*', '/contact.vcf', '/text'] as const;
for (const path of ADVISOR_PATHS) advisorPublic.use(path, gate);

// Liveness and configuration shape only: never a secret, never the number.
advisorPublic.get('/api/advisor/health', c => {
  const settings = advisorSettings(c.env);
  return json({enabled: true, channel: settings.channel, providers: settings.visionProviders});
});
