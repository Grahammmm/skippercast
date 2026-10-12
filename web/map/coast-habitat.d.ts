// Types of web/map/coast-habitat.js (FE-18): packages/coast/src/state/habitat-selection.ts's, restated
// because that module imports the renderer's readers, which web/tsconfig.json never loads.
import type {HabitatReceipt} from './habitat.ts';

/** Resolves an exact public habitat id admitted by the reviewed release, or null; metadata only, no graphics. */
export declare function resolveHabitatSelection(
  request: {id: string; species: string; depthLimitFt?: number},
  options?: {signal?: AbortSignal; isCurrent?: () => boolean},
): Promise<(HabitatReceipt & {region?: string}) | null>;
