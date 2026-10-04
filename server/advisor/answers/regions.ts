// The reviewed region manifests the build injects (REGIONS, server/globals.d.ts),
// read defensively so advisor modules and their tests work when a region is
// absent. The advisor never hard-codes Morro Bay (principle 9): everything a
// data tool needs about a place comes from regions/<id>/region.json through here
// and from catalog/home-ports.json through links.ts.
import type {Region} from '../../types.ts';

const all = (): Record<string, Region> => (typeof REGIONS === 'undefined' ? {} : REGIONS) as Record<string, Region>;

/** The region manifest, or null for an unknown or draft region. */
export const regionConfig = (id: string | null | undefined): Region | null =>
  id && Object.hasOwn(all(), id) ? all()[id]! : null;

/** The rules jurisdiction (a jurisdictions/<id>.json id) of a region, or null. */
export const jurisdictionFor = (region: string | null | undefined): string | null => regionConfig(region)?.jurisdiction_id ?? null;
