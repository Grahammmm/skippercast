import {signal} from '@preact/signals';
import {loadTideReading, readSavedTideStations, saveSavedTideStations, MAX_SAVED_TIDE_STATIONS, stationsInRegion, TIDE_DIRECTORY_URL, tidePackURLs, type TideReading, type TideRegion, type TideStation} from './tide-stations.ts';

export function createTideSelection(fetcher: typeof fetch = (...args) => fetch(...args), storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>) {
  const region = signal<TideRegion | null>(null), stations = signal<readonly TideStation[]>([]);
  const choice = signal<string | null>(null), reading = signal<TideReading | null>(null);
  const saved = signal<readonly string[]>([]);
  const loading = signal(false), error = signal('');
  let generation = 0, directory: Promise<unknown> | null = null;
  function catalog(): Promise<unknown> {
    return directory ??= fetcher(TIDE_DIRECTORY_URL, {credentials: 'omit', signal: AbortSignal.timeout(20000)}).then(async r => {
      if (!r.ok) throw new Error('Station directory unavailable');
      const body = await r.json() as {stations?: unknown};
      if (!Array.isArray(body?.stations)) throw new Error('Station directory unavailable');
      return body;
    }).catch(e => { directory = null; throw e; });
  }
  async function list(): Promise<readonly TideStation[]> {
    const selected = region.peek();
    if (!selected) return [];
    try {
      const rows = stationsInRegion(await catalog(), selected.bounds);
      if (region.peek() === selected) stations.value = rows;
      return rows;
    } catch {
      if (region.peek() === selected) error.value = 'NOAA station directory unavailable. Retry when connected.';
      return [];
    }
  }
  async function load(): Promise<void> {
    const token = ++generation, selected = region.peek(), id = choice.peek();
    reading.value = null; error.value = ''; loading.value = false;
    if (!selected || !id || id === selected.station) return;
    loading.value = true;
    const rows = await list();
    if (token !== generation) return;
    const station = rows.find(s => s.id === id);
    if (!station) { error.value ||= 'Chosen station unavailable in this region. Choose another station or the region default.'; loading.value = false; return; }
    const result = await loadTideReading(station, fetcher);
    if (token !== generation) return;
    reading.value = result;
    loading.value = false;
    if (result.failed) error.value = 'Some chosen-station predictions are unavailable. Missing readings stay blank rather than using the default station.';
  }
  function configure(next: TideRegion | null): void {
    generation++;
    region.value = next; stations.value = []; reading.value = null; loading.value = false; error.value = '';
    const restored = next ? readSavedTideStations(next.id, storage) : {saved: [], active: null};
    saved.value = restored.saved;
    choice.value = restored.active;
    if (restored.saved.length && !restored.active) void list();
    void load();
  }
  function persist(): void {
    const selected = region.peek();
    if (selected) saveSavedTideStations(selected.id, {saved: [...saved.peek()], active: choice.peek()}, storage);
  }
  function choose(id: string | null): boolean {
    const selected = region.peek();
    if (!selected || (id !== null && id !== selected.station && !stations.peek().some(s => s.id === id) && !saved.peek().includes(id))) return false;
    const active = id === selected.station ? null : id;
    if (active && !saved.peek().includes(active)) {
      if (saved.peek().length >= MAX_SAVED_TIDE_STATIONS) {
        error.value = 'Up to three tide stations can be saved per region. Remove one before adding another.';
        return false;
      }
      saved.value = [...saved.peek(), active];
    }
    choice.value = active;
    persist();
    void load();
    return true;
  }
  function remove(id: string): void {
    if (!saved.peek().includes(id)) return;
    saved.value = saved.peek().filter(s => s !== id);
    if (choice.peek() === id) {
      choice.value = null;
      void load();
    } else error.value = '';
    persist();
  }
  /** Snapshot the choice before saving; changing it during the save cannot mix stations. */
  async function packURLs(id: string, now = Date.now()): Promise<string[]> {
    const selected = region.peek(), chosen = choice.peek();
    if (!selected || selected.id !== id || !chosen || chosen === selected.station) return [];
    const rows = await list(), station = rows.find(s => s.id === chosen);
    if (!station) throw new Error('The chosen tide station could not be resolved. Retry or select the region default before saving.');
    return tidePackURLs(station, now);
  }
  return {region, stations, saved, choice, reading, loading, error, configure, list, choose, remove, refresh: load, packURLs};
}
export const tideSelection = createTideSelection();
