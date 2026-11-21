export const CONDITIONS_MAX_BYTES = 4096;

type Check<T> = (value: unknown) => value is T;
type Fields = Record<string, Check<unknown>>;
type FieldValues<T extends Fields> = { [K in keyof T]: T[K] extends Check<infer V> ? V : never };

const MAX_TEXT_CHARS = 200;
const isText = (value: unknown): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= 2 * MAX_TEXT_CHARS && [...value].length <= MAX_TEXT_CHARS;
const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const isNonnegative = (value: unknown): value is number => isNumber(value) && value >= 0;
const isDegrees = (value: unknown): value is number => isNonnegative(value) && value < 360;
const literal = <const T>(expected: T): Check<T> => (value): value is T => value === expected;

function isUtc(value: unknown): value is string {
  if (typeof value !== 'string' || !value.endsWith('Z') || !Number.isFinite(Date.parse(value))) return false;
  const day = /^((?:\d{4}|[+-]\d{6})-\d{2}-\d{2})T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z$/.exec(value)?.[1];
  if (!day) return false;
  // Date.parse can roll dates like February 30 into the next month.
  const midnight = Date.parse(`${day}T00:00:00Z`);
  return Number.isFinite(midnight) && new Date(midnight).toISOString().startsWith(`${day}T`);
}

const observed = { product: isText, sample_at: isUtc };
const forecast = { run: isText, valid_at: isUtc };
const layerFields = {
  water_temp: { value: isNumber, unit: literal('F'), ...observed },
  contrast: { value: isNumber, unit: literal('F/nm'), ...observed },
  chlorophyll: { value: isNonnegative, unit: literal('mg/m3'), ...observed },
  front_nm: { value: isNonnegative, ...observed },
  current: { kn: isNumber, toward_deg: isDegrees, ...forecast },
  swell: { ft: isNumber, period_s: isNumber, from_deg: isDegrees, ...forecast },
  wind: { kn: isNumber, from_deg: isDegrees, ...forecast },
  tide: { stage: isText, height_ft: isNumber, station: isText },
};

type LayerKey = keyof typeof layerFields;
type Layers = { [K in LayerKey]?: FieldValues<(typeof layerFields)[K]> | { missing: string } };

export type ConditionsV1 =
  | { v: 1; pending: true }
  | { v: 1; missing: string }
  | { v: 1; at: string; layers: Layers };
export type ConditionsParse = { ok: true; value: ConditionsV1 } | { ok: false; error: string };

class InvalidConditions extends Error {}
function fail(path: string): never {
  throw new InvalidConditions(path);
}

type Descriptors = Record<PropertyKey, PropertyDescriptor>;
function record(raw: unknown, path: string): Descriptors {
  try {
    if (raw !== null && typeof raw === 'object' && !Array.isArray(raw)) {
      const proto = Object.getPrototypeOf(raw);
      if (proto === Object.prototype || proto === null) {
        // Inspect only own fields, without running getters or copying input prototypes.
        return Object.getOwnPropertyDescriptors(raw);
      }
    }
  } catch {
    // An unknown input can also be a proxy whose reflection throws.
  }
  return fail(path);
}

const fieldPath = (parent: string, key: PropertyKey) => `${parent === '$' ? '' : `${parent}.`}${String(key)}`;
function onlyKeys(input: Descriptors, allowed: object, path: string): void {
  for (const key of Reflect.ownKeys(input)) {
    if (!Object.hasOwn(allowed, key)) fail(fieldPath(path, key));
  }
}

function ownValue(input: Descriptors, key: string): unknown {
  const desc = Object.hasOwn(input, key) ? input[key] : undefined;
  return desc && Object.hasOwn(desc, 'value') ? desc.value : undefined;
}

function read<T>(input: Descriptors, key: string, check: Check<T>, path: string): T {
  const value = ownValue(input, key);
  if (!check(value)) fail(fieldPath(path, key));
  return value;
}

function readFields<T extends Fields>(input: Descriptors, fields: T, path: string): FieldValues<T> {
  onlyKeys(input, fields, path);
  const copy: Record<string, unknown> = {};
  for (const [key, check] of Object.entries(fields)) copy[key] = read(input, key, check, path);
  return copy as FieldValues<T>;
}

const isVersion = literal(1);
const pendingFields = { v: isVersion, pending: literal(true) };
const missingFields = { missing: isText };
const unavailableFields = { v: isVersion, ...missingFields };
const snapshotKeys = { v: true, at: true, layers: true };

function readLayers(raw: unknown): Layers {
  const path = 'layers';
  const input = record(raw, path);
  onlyKeys(input, layerFields, path);
  const layers: Record<string, unknown> = {};
  for (const key of Object.keys(input) as LayerKey[]) {
    const layerPath = fieldPath(path, key);
    const layer = record(ownValue(input, key), layerPath);
    layers[key] = Object.hasOwn(layer, 'missing')
      ? readFields(layer, missingFields, layerPath)
      : readFields(layer, layerFields[key], layerPath);
  }
  return layers as Layers;
}

function readSnapshot(raw: unknown): ConditionsV1 {
  const path = '$';
  const input = record(raw, path);
  const v = read(input, 'v', isVersion, path);
  if (Object.hasOwn(input, 'pending')) return readFields(input, pendingFields, path);
  if (Object.hasOwn(input, 'missing')) return readFields(input, unavailableFields, path);
  onlyKeys(input, snapshotKeys, path);
  const at = read(input, 'at', isUtc, path);
  return { v, at, layers: readLayers(ownValue(input, 'layers')) };
}

export function parseConditionsV1(raw: unknown): ConditionsParse {
  try {
    const snapshot = readSnapshot(raw);
    if (new TextEncoder().encode(JSON.stringify(snapshot)).byteLength > CONDITIONS_MAX_BYTES) fail('$');
    return { ok: true, value: snapshot };
  } catch (error) {
    return { ok: false, error: error instanceof InvalidConditions ? error.message : '$' };
  }
}
