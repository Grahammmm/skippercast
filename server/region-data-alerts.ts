import {ANALYSIS_LAYERS} from './analysis-alerts.ts';

export type AnalysisLayer = (typeof ANALYSIS_LAYERS)[number];

type ValidationResult =
  | {ok: true; region: string; layers: AnalysisLayer[]}
  | {ok: false; field: 'region'; error: 'unknown-region'}
  | {ok: false; field: 'body'; error: 'not-object' | 'unexpected-key'}
  | {ok: false; field: 'layers'; error: 'not-list' | 'unknown-layer' | 'too-many'};

export function validateDataAlerts(
  region: unknown,
  body: unknown,
  knownRegion: (id: string) => boolean,
): ValidationResult {
  const unknownRegion = {ok: false, field: 'region', error: 'unknown-region'} as const;
  if (typeof region !== 'string' || !/^[a-z0-9-]{1,64}$/.test(region)) return unknownRegion;
  try {
    if (knownRegion(region) !== true) return unknownRegion;
  } catch {
    return unknownRegion;
  }

  const notObject = {ok: false, field: 'body', error: 'not-object'} as const;
  if (body === null || typeof body !== 'object') return notObject;
  try {
    const prototype = Object.getPrototypeOf(body);
    if (Array.isArray(body) || (prototype !== Object.prototype && prototype !== null)) return notObject;
    const keys = Reflect.ownKeys(body);
    if (keys.length !== 1 || keys[0] !== 'layers') {
      return {ok: false, field: 'body', error: 'unexpected-key'};
    }
    const layers: unknown = (body as {layers: unknown}).layers;
    if (!Array.isArray(layers)) return {ok: false, field: 'layers', error: 'not-list'};
    const length = layers.length;
    if (length > 8) return {ok: false, field: 'layers', error: 'too-many'};
    const chosen = new Set<string>();
    for (let i = 0; i < length; i++) {
      const layer: unknown = layers[i];
      if (typeof layer !== 'string' || !ANALYSIS_LAYERS.some(allowed => allowed === layer)) {
        return {ok: false, field: 'layers', error: 'unknown-layer'};
      }
      chosen.add(layer);
    }
    return {ok: true, region, layers: ANALYSIS_LAYERS.filter(layer => chosen.has(layer))};
  } catch {
    return notObject;
  }
}

export function dataAlertRows(
  owner: string,
  region: string,
  layers: readonly AnalysisLayer[],
  existing: readonly {layer: string; lastSentDay: string | null}[],
): {owner: string; region: string; layer: AnalysisLayer; lastSentDay: string | null}[] {
  return ANALYSIS_LAYERS.filter(layer => layers.includes(layer)).map(layer => ({
    owner,
    region,
    layer,
    lastSentDay: existing.find(row => row.layer === layer)?.lastSentDay ?? null,
  }));
}
