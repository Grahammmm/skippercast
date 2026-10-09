// packages/coast's habitat restore without graphics (FE-18), imported dynamically by
// web/map/marks.ts. Plain JavaScript typed by coast-habitat.d.ts, as terrain.js: its
// readers sit beside the renderer (coast3d/regional.ts), which web/tsconfig.json never
// loads. It reaches only the bridge (`coastFetch`), never three.
export {resolveHabitatSelection} from '../../packages/coast/src/state/habitat-selection.ts';
