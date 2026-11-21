export const ANALYSIS_LAYERS = ['sst-analysis', 'chlorophyll-observation'] as const;

export type AnalysisAlert = {owner: string; region: string; layer: string; sampleAt: string};

type AnalysisAlertInput = {
  subscriptions: readonly {owner: string; region: string; layers: readonly string[]}[];
  previous: Record<string, Record<string, string>>;
  current: Record<string, Record<string, string>>;
};

// Read data fields only: inherited properties aren't samples, and a malformed
// field must not throw or turn into an absent previous sample.
function ownValue(record: unknown, key: string | number): unknown {
  if (typeof record !== 'object' || record === null) return null;
  try {
    const field = Object.getOwnPropertyDescriptor(record, key);
    return field === undefined ? undefined : Object.hasOwn(field, 'value') ? field.value : null;
  } catch {
    return null;
  }
}

function arrayLength(value: unknown): number {
  try {
    const length = Array.isArray(value) ? ownValue(value, 'length') : null;
    return typeof length === 'number' && Number.isSafeInteger(length) && length >= 0 ? length : 0;
  } catch {
    return 0;
  }
}

function sampleAt(samples: unknown, region: string, layer: string): unknown {
  try {
    const row = Array.isArray(samples) ? null : ownValue(samples, region);
    return row === undefined ? undefined : Array.isArray(row) ? null : ownValue(row, layer);
  } catch {
    return null;
  }
}

const ISO_INSTANT = /^(\d{4}|[+-]\d{6})-(\d{2})-(\d{2})T(\d{2}:\d{2}(?::\d{2})?)(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})$/i;

function parseInstant(value: unknown): {second: number; fraction: string} | undefined {
  if (typeof value !== 'string') return;
  const match = ISO_INSTANT.exec(value);
  if (!match || match[0] !== value) return;
  const [, year, month, day, time = '', digits = '', zone] = match;
  if (digits && (time.length !== 8 || (time.startsWith('24:') && /[1-9]/.test(digits)))) return;
  const date = `${year}-${month}-${day}`;
  const midnight = new Date(`${date}T00:00:00Z`);
  const second = Date.parse(`${date}T${time}${zone}`);
  // Date.parse may roll a nonexistent calendar day into the next month.
  if (!Number.isFinite(second) || midnight.getUTCDate() !== Number(day)) return;
  // Keep precision beyond milliseconds and compare equal spellings (e.g. .10 and .1) equally.
  let end = digits.length;
  while (digits[end - 1] === '0') end--;
  return {second, fraction: digits.slice(0, end)};
}

const compare = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;

/** Identify publication candidates only; delivery policy is evaluated separately. */
export function analysisAlertCandidates(input: AnalysisAlertInput): AnalysisAlert[] {
  const matches = new Map<string, AnalysisAlert>();
  const subscriptions = ownValue(input, 'subscriptions');
  const previous = ownValue(input, 'previous');
  const current = ownValue(input, 'current');
  const count = arrayLength(subscriptions);
  for (let i = 0; i < count; i++) {
    const subscription = ownValue(subscriptions, i);
    const owner = ownValue(subscription, 'owner');
    const region = ownValue(subscription, 'region');
    if (typeof owner !== 'string' || typeof region !== 'string') continue;
    const layers = ownValue(subscription, 'layers');
    const layerCount = arrayLength(layers);
    for (let j = 0; j < layerCount; j++) {
      const layer = ownValue(layers, j);
      if (layer !== ANALYSIS_LAYERS[0] && layer !== ANALYSIS_LAYERS[1]) continue;
      const sample = sampleAt(current, region, layer);
      if (typeof sample !== 'string') continue;
      const published = parseInstant(sample);
      if (!published) continue;
      const priorSample = sampleAt(previous, region, layer);
      if (priorSample !== undefined) {
        const prior = parseInstant(priorSample);
        if (!prior || prior.second > published.second ||
            (prior.second === published.second && prior.fraction >= published.fraction)) continue;
      }
      matches.set(JSON.stringify([owner, region, layer]), {owner, region, layer, sampleAt: sample});
    }
  }
  return [...matches.values()].sort((a, b) =>
    compare(a.owner, b.owner) || compare(a.region, b.region) || compare(a.layer, b.layer));
}
