// The terrain presentation's module (FE-71, design § 3A.2): web/map/stage.ts
// imports it dynamically on the first terrain choice, so three and the coast
// renderer load after the app's first paint (scripts/check_client.mjs keeps
// them out of the app entry's static imports).
//
// Plain JavaScript with its types in terrain.d.ts: web/tsconfig.json then never
// loads the renderer's sources (packages/coast/src/coast3d/*), which are
// checked by packages/coast/tsconfig.json under that package's own options.
import coastStyles from '../../packages/coast/coast.css?url';
import bridgeStyles from '../../packages/coast/tokens-bridge.css?url';
import placement from './terrain.css?url';

export {mountCoast} from '../../packages/coast/src/embed.ts';
/**
 * Linked in the terrain host's shadow root, in order: the renderer's chrome, the
 * token bridge (the host carries data-coast-theme="tokens", so the chrome reads
 * web/tokens.css, § 3A.4), then the panels' placement around the v2 stage chrome.
 */
export const styles = Object.freeze([coastStyles, bridgeStyles, placement]);
