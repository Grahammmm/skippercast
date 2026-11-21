import { parseConditionsV1, type ConditionsV1 } from '../server/conditions-v1.ts';

type Layers = Extract<ConditionsV1, { layers: unknown }>['layers'];
type LayerKey = keyof Layers;
type Layer = NonNullable<Layers[LayerKey]>;

const layerOrder = [
  'water_temp', 'contrast', 'front_nm', 'chlorophyll', 'current', 'swell', 'wind', 'tide',
] as const satisfies readonly LayerKey[];

function hoursFromEntry(time: string, entryMs: number): number {
  return Math.round((Date.parse(time) - entryMs) / 3_600_000);
}

function lineItem(key: LayerKey, layer: Layer, entryMs: number) {
  if ('missing' in layer) return { key, kind: 'missing' as const, reason: layer.missing };
  const item = { key, kind: 'value' as const };
  if ('product' in layer) {
    const { product, sample_at: time, ...values } = layer;
    return { ...item, values, source: { product }, time, offsetHours: hoursFromEntry(time, entryMs) };
  }
  if ('run' in layer) {
    const { run, valid_at: time, ...values } = layer;
    return { ...item, values, source: { run }, time, offsetHours: hoursFromEntry(time, entryMs) };
  }
  const { station, ...values } = layer;
  return { ...item, values, source: { station }, time: null, offsetHours: null };
}

export type LineItem = ReturnType<typeof lineItem>;
export type ConditionsLine =
  | { state: 'none' }
  | { state: 'invalid' }
  | { state: 'pending' }
  | { state: 'missing'; reason: string }
  | { state: 'ready'; at: string; items: LineItem[] };

export function conditionsLine(raw: unknown): ConditionsLine {
  if (raw === null || raw === undefined) return { state: 'none' };
  const parsed = parseConditionsV1(raw);
  if (!parsed.ok) return { state: 'invalid' };
  const snapshot = parsed.value;
  if ('pending' in snapshot) return { state: 'pending' };
  if ('missing' in snapshot) return { state: 'missing', reason: snapshot.missing };

  const { at, layers } = snapshot;
  const entryMs = Date.parse(at);
  const items: LineItem[] = [];
  for (const key of layerOrder) {
    const layer = layers[key];
    if (layer !== undefined) items.push(lineItem(key, layer, entryMs));
  }
  return { state: 'ready', at, items };
}
