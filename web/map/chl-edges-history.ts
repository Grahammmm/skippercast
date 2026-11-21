import {readChlEdges, type ChlEdgesDoc} from './chl-edges-feed.ts';

type IndexEntry = {date: string; path: string; sha256: string};
type ChlEdgesDay = {state: 'ready'; date: string; doc: ChlEdgesDoc} | {state: 'none'} | {state: 'error'};

function isDay(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000-')) return false;
  const date = new Date(`${value}T00:00:00Z`);
  // ISO round-trip rejects dates the parser silently normalizes, such as February 30.
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function readChlEdgesIndex(data: unknown): IndexEntry[] | null {
  const entries = new Map<string, IndexEntry>();
  try {
    if (!Array.isArray(data)) return null;
    for (let i = 0, length = data.length; i < length; i++) {
      try {
        const entry: unknown = data[i];
        if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) continue;
        const {date, path, sha256} = entry as Record<string, unknown>;
        if (!isDay(date) || path !== `chl-edges/${date}.json` || typeof sha256 !== 'string'
          || !/^[0-9a-f]{64}$/.test(sha256) || entries.has(date)) continue;
        entries.set(date, {date, path, sha256});
      } catch {
        // A malformed non-JSON caller must not hide its readable siblings.
      }
    }
  } catch {
    // An unreadable array (for example a revoked Proxy) yields no pointers.
  }
  return [...entries.values()].sort((a, b) => a.date < b.date ? 1 : -1).slice(0, 7);
}

export async function loadChlEdgesDay(regionId: string, day: string, o: {
  fetchFn: typeof fetch; page: string; signal?: AbortSignal;
}): Promise<ChlEdgesDay> {
  try {
    if (typeof regionId !== 'string' || !/^[a-z0-9-]+$/.test(regionId) || !isDay(day)) return {state: 'error'};
    const {signal} = o;
    const root = `/feeds/conditions/regions/${regionId}`;
    const fetchPath = (path: string) => o.fetchFn(new URL(`${root}/${path}`, o.page).href, signal ? {signal} : {});
    signal?.throwIfAborted();
    const indexResponse = await fetchPath('chl-edges/index.json');
    signal?.throwIfAborted();
    if (indexResponse.status === 404) return {state: 'none'};
    if (!indexResponse.ok) return {state: 'error'};
    const index = readChlEdgesIndex(await indexResponse.json());
    signal?.throwIfAborted();
    if (!index) return {state: 'error'};
    const entry = index.find(item => item.date === day);
    if (!entry) return {state: 'none'};

    const response = await fetchPath(entry.path);
    signal?.throwIfAborted();
    if (!response.ok) return {state: 'error'};
    const bytes = await response.arrayBuffer();
    signal?.throwIfAborted();
    if (bytes.byteLength > 5_000_000) return {state: 'error'};
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    signal?.throwIfAborted();
    const sha256 = Array.from(digest, n => n.toString(16).padStart(2, '0')).join('');
    if (sha256 !== entry.sha256) return {state: 'error'};
    const doc = readChlEdges(JSON.parse(new TextDecoder().decode(bytes)), regionId);
    return doc ? {state: 'ready', date: entry.date, doc} : {state: 'error'};
  } catch (error) {
    if (o.signal?.aborted) throw error;
    return {state: 'error'};
  }
}
