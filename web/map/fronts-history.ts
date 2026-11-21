import {readFronts, type FrontsDoc} from './fronts.ts';

type FrontsIndexEntry = {date: string; path: string; sha256: string};
type FrontsDay = {state: 'ready'; date: string; doc: FrontsDoc} | {state: 'none'} | {state: 'error'};
const MAX_DAY_BYTES = 5_000_000;

function isDay(value: unknown): value is string {
  if (typeof value !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith('0000-')) return false;
  const day = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === value;
}

/** Read the dated pointers, keeping the first valid entry for each date. */
export function readFrontsIndex(data: unknown): FrontsIndexEntry[] | null {
  const entries = new Map<string, FrontsIndexEntry>();
  try {
    if (!Array.isArray(data)) return null;
    for (const entry of data) {
      try {
        if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue;
        const {date, path, sha256} = entry;
        if (!isDay(date) || path !== `sst-fronts/${date}.json` || typeof sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(sha256)
          || entries.has(date)) continue;
        entries.set(date, {date, path, sha256});
      } catch { /* Ignore an unreadable entry as well as malformed JSON entries. */ }
    }
  } catch { /* An unreadable index is not usable. */ return null; }
  return [...entries.values()].sort((a, b) => a.date < b.date ? 1 : -1).slice(0, 7);
}

/** Load only the selected day, verifying the published bytes before parsing. */
export async function loadFrontsDay(regionId: string, day: string, o: {fetchFn: typeof fetch; page: string; signal?: AbortSignal}): Promise<FrontsDay> {
  try {
    if (!/^[a-z0-9-]+$/.test(regionId) || !isDay(day)) return {state: 'error'};
    const base = new URL(`/feeds/conditions/regions/${regionId}/`, o.page);
    const init = o.signal ? {signal: o.signal} : {};
    o.signal?.throwIfAborted();
    const index = await o.fetchFn(new URL('sst-fronts/index.json', base).href, init);
    if (index.status === 404) return {state: 'none'};
    if (!index.ok) return {state: 'error'};
    const entries = readFrontsIndex(await index.json());
    if (!entries) return {state: 'error'};
    const entry = entries.find(e => e.date === day);
    if (!entry) return {state: 'none'};

    const file = await o.fetchFn(new URL(entry.path, base).href, init);
    if (!file.ok) return {state: 'error'};
    const bytes = await file.arrayBuffer();
    if (bytes.byteLength > MAX_DAY_BYTES) return {state: 'error'};
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    o.signal?.throwIfAborted();
    const digest = Array.from(new Uint8Array(hash), n => n.toString(16).padStart(2, '0')).join('');
    if (digest !== entry.sha256) return {state: 'error'};
    const doc = readFronts(JSON.parse(new TextDecoder().decode(bytes)), regionId);
    return doc ? {state: 'ready', date: entry.date, doc} : {state: 'error'};
  } catch (error) {
    if (o.signal?.aborted) throw error;
    return {state: 'error'};
  }
}
