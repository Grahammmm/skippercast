// Types of web/map/maplibre.js (FE-11): the npm packages' own declarations.
import type * as MapLibre from 'maplibre-gl';
import type {Protocol as PMTilesProtocol} from 'pmtiles';

/** maplibre-gl's CSP build (the same API as the package's main build). */
export declare const lib: typeof MapLibre;
/** The hashed URL of maplibre-gl-csp-worker.js. */
export declare const workerUrl: string;
export declare const Protocol: typeof PMTilesProtocol;
