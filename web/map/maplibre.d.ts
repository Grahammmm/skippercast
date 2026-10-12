// Types of web/map/maplibre.js (FE-11): the npm packages' own declarations.
import type * as MapLibre from 'maplibre-gl';
import type {PMTiles as PMTilesArchive, Protocol as PMTilesProtocol} from 'pmtiles';

/** maplibre-gl's ESM build (`import * as maplibregl from 'maplibre-gl'`). */
export declare const lib: typeof MapLibre;
/** The hashed URL of maplibre-gl-worker.mjs, bundled with its shared chunk by Vite's `?worker&url`. */
export declare const workerUrl: string;
export declare const Protocol: typeof PMTilesProtocol;
export declare const PMTiles: typeof PMTilesArchive;
