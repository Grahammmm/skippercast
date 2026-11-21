export const PATTERN_MIN_N = 10;
export const PATTERN_MAX_ENTRIES = 2000;

type Band = {bandF: number; tide: string; fish: number; blank: number};
export type Patterns = {n: number; shown: boolean; bands: Band[]};

function read(record: unknown, key: PropertyKey): unknown {
  if (record === null || (typeof record !== 'object' && typeof record !== 'function')) return undefined;
  try {
    return (record as Record<PropertyKey, unknown>)[key];
  } catch {
    // Treat an unreadable field like a missing one without dropping other rows.
    return undefined;
  }
}

export function catchPatterns(entries: readonly {outcome: string; conditions?: unknown}[]): Patterns {
  const groups = new Map<string, Band>();
  const length = read(entries, 'length');
  const limit = typeof length === 'number' ? Math.min(length, PATTERN_MAX_ENTRIES) : 0;
  let n = 0;
  for (let i = 0; i < limit; i++) {
    const entry = read(entries, i);
    const outcome = read(entry, 'outcome');
    if (outcome !== 'fish' && outcome !== 'blank') continue;
    const conditions = read(entry, 'conditions');
    if (read(conditions, 'v') !== 1) continue;
    const layers = read(conditions, 'layers');
    const temp = read(layers, 'water_temp');
    const value = read(temp, 'value');
    if (typeof value !== 'number' || !Number.isFinite(value) || read(temp, 'unit') !== 'F') continue;

    const stage = read(read(layers, 'tide'), 'stage');
    const tide = typeof stage === 'string' && stage !== '' ? stage : 'unknown';
    const bandF = Math.floor(value);
    const key = `${bandF}:${tide}`;
    let band = groups.get(key);
    if (!band) {
      band = {bandF, tide, fish: 0, blank: 0};
      groups.set(key, band);
    }
    band[outcome]++;
    n++;
  }

  const shown = n >= PATTERN_MIN_N;
  const bands = shown ? [...groups.values()].sort((a, b) =>
    a.bandF - b.bandF || (a.tide < b.tide ? -1 : a.tide > b.tide ? 1 : 0)) : [];
  return {n, shown, bands};
}
