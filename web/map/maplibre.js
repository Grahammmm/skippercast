// The Chart presentation's library (FE-11, design § 3): web/map/chart.ts imports
// it dynamically on the first Chart view, so MapLibre and PMTiles load after
// the app's first paint and never reach the landing. MapLibre 6 is ESM only;
// Vite's `?worker&url` bundles its module worker (which imports a shared chunk)
// into one hashed same-origin file (worker-src 'self'), never a blob.
//
// Plain JavaScript with its types in maplibre.d.ts: the web program then never
// type-checks the library bundle (as web/map/terrain.js does for the renderer).
import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import './chart.css';

export {PMTiles, Protocol} from 'pmtiles';
export {workerUrl};
export const lib = maplibregl;
