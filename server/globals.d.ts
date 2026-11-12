// Build-time constants: scripts/build-worker.mjs replaces these identifiers
// (esbuild `define`) with the reviewed region manifests, the deployment policy,
// the fingerprinted page map, the build id and the advisor pages' hashed assets. Tests assign them on globalThis.
import type {Region, Deployment} from './types.ts';

declare global {
  const REGIONS: Record<string, Region>;
  const DEPLOYMENT: Deployment;
  const SHELLS: Record<string, string>;
  const BUILD_ID: string;
  // TA-W1: hashed paths of the advisor pages' stylesheet and script ('advisor/pages.css', 'advisor/chat.js'), from the Vite manifest.
  const ADVISOR_ASSETS: Record<string, string>;
}
