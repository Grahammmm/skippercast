// Types of web/map/terrain.js (FE-71). They come from packages/coast's
// renderer-free embed-types.ts, so the web program never loads the renderer.
import type {CoastHandle, CoastMountOptions} from '../../packages/coast/src/embed-types.ts';

/** packages/coast/src/embed.ts `mountCoast`, re-exported. */
export declare function mountCoast(host: HTMLElement, options?: CoastMountOptions): CoastHandle;
/** Stylesheet URLs for the terrain host's shadow root. */
export declare const styles: readonly string[];
/** A mounted C2 release view (web/map/c2.js, M9). */
export type C2View = {destroy(): void; setVisible(visible: boolean): void};
/** web/map/c2.js, imported only when web/map/c2-releases.ts lists the region. */
export declare function loadC2(): Promise<{mountRelease(host: HTMLElement, url: string): Promise<C2View | {refused: string}>}>;
