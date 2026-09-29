// Build-time constants: scripts/build-worker.mjs replaces these identifiers
// (esbuild `define`) with the reviewed region manifests, the deployment policy,
// the fingerprinted page map and the build id. Tests assign them on globalThis.
import type {Region, Deployment} from './types.ts';

declare global {
  const REGIONS: Record<string, Region>;
  const DEPLOYMENT: Deployment;
  const SHELLS: Record<string, string>;
  const BUILD_ID: string;
}
