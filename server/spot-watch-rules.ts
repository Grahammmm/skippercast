export const WATCH_LAYERS = ['water-temp', 'chlorophyll', 'sst-contrast'] as const;
export const WATCH_OPS = ['>=', '<=', 'between'] as const;
export const WATCH_RANGES = {
  'water-temp': [28, 95],
  chlorophyll: [0.01, 100],
  'sst-contrast': [0, 10],
} as const;

export type WatchLayer = typeof WATCH_LAYERS[number];
export type WatchOp = typeof WATCH_OPS[number];

type WatchField = 'body' | 'layer' | 'op' | 'a' | 'b';
export type WatchInput =
  | {ok: true; watch: {layer: WatchLayer; op: WatchOp; a: number; b: number | null}}
  | {ok: false; field: WatchField; error: string};

function inRange(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max;
}

export function validateWatchInput(body: unknown): WatchInput {
  let field: WatchField = 'body';
  try {
    if (body === null || typeof body !== 'object' || Array.isArray(body)) {
      return {ok: false, field, error: 'Expected a watch object.'};
    }
    if (Reflect.ownKeys(body).some(key => key !== 'layer' && key !== 'op' && key !== 'a' && key !== 'b')) {
      return {ok: false, field, error: 'Unexpected watch key.'};
    }

    // Read own data properties only; inherited values and getters are not input data.
    field = 'layer';
    const rawLayer: unknown = Object.getOwnPropertyDescriptor(body, 'layer')?.value;
    const layer = WATCH_LAYERS.find(option => option === rawLayer);
    if (layer === undefined) return {ok: false, field, error: 'Invalid watch layer.'};

    field = 'op';
    const rawOp: unknown = Object.getOwnPropertyDescriptor(body, 'op')?.value;
    const op = WATCH_OPS.find(option => option === rawOp);
    if (op === undefined) return {ok: false, field, error: 'Invalid watch comparison.'};

    field = 'a';
    const [min, max] = WATCH_RANGES[layer];
    const a: unknown = Object.getOwnPropertyDescriptor(body, 'a')?.value;
    if (!inRange(a, min, max)) return {ok: false, field, error: 'Expected a finite number in the layer range.'};

    field = 'b';
    const descriptor = Object.getOwnPropertyDescriptor(body, 'b');
    const b: unknown = descriptor?.value;
    if (op !== 'between') {
      if (descriptor !== undefined && b !== null) return {ok: false, field, error: 'Expected b to be absent or null.'};
      return {ok: true, watch: {layer, op, a, b: null}};
    }
    if (!inRange(b, min, max)) return {ok: false, field, error: 'Expected a finite number in the layer range.'};
    if (a >= b) return {ok: false, field, error: 'Expected b to be greater than a.'};
    return {ok: true, watch: {layer, op, a, b}};
  } catch {
    // Reflection on a proxy can throw even without reading any getters.
    return {ok: false, field, error: 'Could not inspect watch input.'};
  }
}
