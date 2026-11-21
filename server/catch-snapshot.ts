import { parseConditionsV1, type ConditionsV1 } from './conditions-v1.ts';

export const SNAPSHOT_LAYERS = ['water_temp', 'contrast', 'front_nm', 'chlorophyll', 'current', 'swell', 'wind', 'tide'] as const;

type Layer = (typeof SNAPSHOT_LAYERS)[number];
type LayerResults = Readonly<Partial<Record<Layer, unknown>>>;

function snapshotLayer(key: Layer, results: LayerResults, at: string): unknown {
  try {
    const value = results[key];
    if (value === undefined) return { missing: 'not computed' };
    const parsed = parseConditionsV1({ v: 1, at, layers: { [key]: value } });
    if (parsed.ok && 'layers' in parsed.value) return parsed.value.layers[key];
  } catch {
    // An unreadable layer need not discard the other layers.
  }
  return { missing: 'invalid value' };
}

function snapshotTime(value: string): number {
  // Require an explicit zone and check the original calendar day before applying it:
  // Date.parse otherwise normalizes impossible dates such as February 30.
  const day = /^((?:\d{4}|[+-]\d{6})-\d{2}-\d{2})T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.exec(value)?.[1];
  if (!day) return NaN;
  const midnight = Date.parse(`${day}T00:00:00Z`);
  if (!Number.isFinite(midnight) || !new Date(midnight).toISOString().startsWith(`${day}T`)) return NaN;
  return Date.parse(value);
}

export function composeSnapshot(input: {
  startedAt: string;
  now: Date;
  region: string | null;
  coverage: 'inside' | 'outside';
  layers: LayerResults;
}): ConditionsV1 {
  try {
    const time = snapshotTime(input.startedAt);
    if (Number.isNaN(time)) return { v: 1, missing: 'invalid time' };
    if (time > Date.prototype.getTime.call(input.now)) return { v: 1, missing: 'future time' };
    const region = input.region;
    if (region === null || region === '') return { v: 1, missing: 'no region' };
    if (input.coverage === 'outside') return { v: 1, missing: 'outside coverage' };

    const at = new Date(time).toISOString();
    const results = input.layers;
    const layers = Object.fromEntries(SNAPSHOT_LAYERS.map(key => [key, snapshotLayer(key, results, at)]));
    const parsed = parseConditionsV1({ v: 1, at, layers });
    if (parsed.ok) return parsed.value;
  } catch {
    // Unreadable input cannot produce a validated snapshot.
  }
  return { v: 1, missing: 'too large' };
}
