// Types for server/model-api.js. The model API stays plain, dependency-free
// JavaScript so the Python pipeline can run it with any Node through
// scripts/model_api.mjs (no TypeScript step); the Worker imports it with these types.

export type ModelKind = 'forecast' | 'marine';
export const MODELS: Record<string, {kind: ModelKind; precipitation?: 'rate' | 'backward'}>;

/** A query the caller got wrong: answered 400 with its message. */
export class QueryError extends Error {}

/** Where manifests and tiles come from; either may resolve to null when absent. */
export interface TileStore {
  manifest(model: string): Promise<unknown> | null;
  tile(model: string, key: string): Promise<unknown> | null;
}

export function cellWeights(tile: unknown, latitude: number, longitude: number, seaOnly: boolean):
  {cells: [number, number, number][]; grid: {latitude: number | null; longitude: number | null}} | null;
export function hermite(times: number[], values: (number | null)[], targets: number[]): (number | null)[];
export function weatherCode(precipitation: number | null, cloud: number | null, visibility: number | null, temperature: number | null): number | null;
/** An Open-Meteo-style response object (one point) or array (several points). */
export function answer(kind: string, params: URLSearchParams, store: TileStore, now?: number): Promise<unknown>;
export function meta(model: string | undefined, store: TileStore): Promise<Record<string, unknown>>;
