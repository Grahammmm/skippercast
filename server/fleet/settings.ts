// Charter fleet settings from Worker vars (docs/plans/charter-fleet/design.md § 16).
// Pure: no I/O, no secrets. Every flag defaults off; anything but "true" or
// "false" (any case, trimmed) keeps the default, like advisorSettings
// (server/advisor/settings.ts), so a typo in a repository variable never
// switches a feature on.
import type {Env} from '../env.ts';

export type FleetVars = Pick<Env, 'FLEET_ENABLED' | 'FLEET_MAP_ENABLED' | 'FLEET_PUBLIC_HEAT_ENABLED'>;

export interface FleetSettings {
  enabled: boolean;     // FLEET_ENABLED: admin fleet views, job routes, registry data on /boats, /go/
  mapEnabled: boolean;  // FLEET_MAP_ENABLED: map routes and layers (admin only); effective only with `enabled`
  publicHeatEnabled: boolean;  // FLEET_PUBLIC_HEAT_ENABLED: the anonymous heat route (fleet/public-heat.ts); effective only with `enabled`
}

export const FLEET_DEFAULTS: Readonly<FleetSettings> = Object.freeze({enabled: false, mapEnabled: false, publicHeatEnabled: false});

function flag(value: unknown, fallback: boolean): boolean {
  const v = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return v === 'true' ? true : v === 'false' ? false : fallback;
}

/** Charter fleet settings from Worker vars, every field defaulted. */
export function fleetSettings(env: FleetVars = {}): FleetSettings {
  return {
    enabled: flag(env.FLEET_ENABLED, FLEET_DEFAULTS.enabled),
    mapEnabled: flag(env.FLEET_MAP_ENABLED, FLEET_DEFAULTS.mapEnabled),
    publicHeatEnabled: flag(env.FLEET_PUBLIC_HEAT_ENABLED, FLEET_DEFAULTS.publicHeatEnabled),
  };
}
