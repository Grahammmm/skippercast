// Deployment configuration the build injects (see globals.d.ts).
import type {Region, Deployment} from './types.ts';

// Injected from reviewed region manifests by the build; never visitor-supplied URLs.
export const regions: Record<string, Region> = REGIONS;
export const deployment: Deployment = DEPLOYMENT;
export const origins = new Set(deployment.allowed_origins);
export const regionById = (id: unknown): Region | null => typeof id === 'string' && Object.hasOwn(regions, id) ? regions[id]! : null;
export const build = (): string => typeof BUILD_ID === 'undefined' ? 'dev' : BUILD_ID;
export const PUBLIC_TTL = 'public, max-age=300, s-maxage=300';
