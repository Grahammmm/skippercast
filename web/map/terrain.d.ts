// Types of web/map/terrain.js (FE-71). They come from packages/coast's
// renderer-free embed-types.ts, so the web program never loads the renderer.
import type {CoastHandle, CoastMountOptions} from '../../packages/coast/src/embed-types.ts';

/** packages/coast/src/embed.ts `mountCoast`, re-exported. */
export declare function mountCoast(host: HTMLElement, options?: CoastMountOptions): CoastHandle;
/** Stylesheet URLs for the terrain host's shadow root. */
export declare const styles: readonly string[];
