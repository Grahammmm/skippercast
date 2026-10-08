// The Chart presentation's library (FE-11, design § 3): web/map/chart.ts imports
// it dynamically on the first Chart view, so MapLibre and PMTiles load after
// the app's first paint and never reach the landing. MapLibre's CSP build runs
// its worker from a hashed same-origin file (worker-src 'self'), never a blob.
//
// Plain JavaScript with its types in maplibre.d.ts: the web program then never
// type-checks the UMD bundle (as web/map/terrain.js does for the renderer).
import maplibregl from 'maplibre-gl/dist/maplibre-gl-csp.js';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-csp-worker.js?url';
import 'maplibre-gl/dist/maplibre-gl.css';
import './chart.css';

export {Protocol} from 'pmtiles';
export {workerUrl};
export const lib = maplibregl;
