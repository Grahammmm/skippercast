// Offline ocean save (docs/plans/offline-ocean-coverage.md D1, D2, D4, D5, D5a, D7): puts a regional feed's two drawn layers,
// `sst-analysis` and `wcofs-surface-forecast`, into a pack, a layer whole or not at all. Nothing calls it yet (the pack wires it later).
//
// - Every tile of a layer is fetched into memory (concurrency 4, `cache: 'no-cache'`, no `X-SC-Offline` copy) and passes the readers' own
//   `tileRows` (length, SHA-256, region, layer, fields, grid, bounds, frames) before any of the layer is written. A layer that fails
//   leaves no key and no counted byte. A layer past a cap is skipped whole, never trimmed.
// - The manifest is read as a stream cut at 1 MiB and written last, from the exact bytes checked, whenever it passed.
// - A rejected `put` is never caught as a miss: it is rethrown as the storage message, so the caller drops the whole candidate pack.
//
// Erasable syntax only: tests/test_ocean_pack.mjs imports it by type stripping.
import {SST_LAYER_ID, WCOFS_LAYER_ID, habitatManifestURL, habitatTileURL, layerOf, tileRows} from './habitat-feed.ts';

export const OCEAN_BYTE_CAP = 12_000_000;
export const MANIFEST_CAP = 1_048_576;
export const OCEAN_LAYERS = [SST_LAYER_ID, WCOFS_LAYER_ID] as const;
const MAX_TILES = 64, MAX_TILE_BYTES = 5_000_000, CONCURRENCY = 4, TIMEOUT_MS = 15_000;
const STORAGE_FULL = 'storage on this device is full or unavailable. Saved regions are unchanged.';
const READS: Record<string, {kind: string; needs: readonly string[]}> = {
  [SST_LAYER_ID]: {kind: 'analysis', needs: ['temperature_c', 'analysis_error_c']},
  [WCOFS_LAYER_ID]: {kind: 'forecast', needs: ['u_mps', 'v_mps']},
};

export type OceanReason = 'network' | 'http' | 'offline-copy' | 'length' | 'integrity' | 'identity' | 'byte-limit';
export interface OceanLayerRecord {
  readonly state: 'saved' | 'failed' | 'over-cap' | 'not-current' | 'absent';
  readonly reason?: OceanReason | 'manifest';
  /** `eligible`'s answer, for `not-current`. */
  readonly why?: string;
  readonly tiles: {readonly saved: number; readonly listed: number};
  readonly bytes: number;
}
export type OceanManifestRecord =
  | {readonly stored: true; readonly url: string; readonly sha256: string; readonly bytes: number; readonly generated_at: string | null}
  | {readonly stored: false; readonly reason: OceanReason};
export interface OceanSave {
  readonly manifest: OceanManifestRecord;
  /** The manifest's bytes plus the bytes of the saved layers: every byte written. */
  readonly bytes: number;
  readonly cap_bytes: number;
  readonly layers: Record<string, OceanLayerRecord>;
}
export interface OceanOptions {
  readonly regionId: string;
  readonly origin: string;
  readonly put: (key: string, body: ArrayBuffer, headers: Headers) => Promise<void>;
  readonly signal: AbortSignal;
  readonly fetchFn?: typeof fetch;
  /** Save-time rule for a layer (the drawable window): null to go on, else the `why` it is not current. Asked before any tile is fetched. */
  readonly eligible?: (layerId: string, manifest: unknown) => string | null;
  readonly progress?: (phase: string, done: number, total: number) => void;
}

class Refused extends Error {
  reason: OceanReason;
  constructor(reason: OceanReason) { super(reason); this.reason = reason; }
}
const cancelled = () => new DOMException('Cancelled', 'AbortError');
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const hex = (b: ArrayBuffer) => Array.from(new Uint8Array(b), n => n.toString(16).padStart(2, '0')).join('');
/** The reason a read or check was refused; anything else (an abort, a bug) is not a layer's failure. */
const refusal = (error: unknown): OceanReason => {
  if (error instanceof Refused) return error.reason;
  if (error instanceof SyntaxError) return 'identity';
  throw error;
};

/** A body read as a stream and cut at `limit` bytes. */
async function readBody(response: Response, limit: number): Promise<ArrayBuffer | null> {
  const reader = response.body?.getReader();
  if (!reader) { const whole = await response.arrayBuffer(); return whole.byteLength > limit ? null : whole; }
  const parts: Uint8Array[] = [];
  let n = 0;
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    n += value.byteLength;
    if (n > limit) { await reader.cancel(); return null; }
    parts.push(value);
  }
  const out = new Uint8Array(n);
  let at = 0;
  for (const part of parts) { out.set(part, at); at += part.byteLength; }
  return out.buffer as ArrayBuffer;
}

/** One read: ok, a fresh answer (not a saved copy), at most `limit` bytes. */
async function get(o: Required<Pick<OceanOptions, 'signal' | 'fetchFn'>>, url: string, limit: number): Promise<ArrayBuffer> {
  try {
    const response = await o.fetchFn(url, {cache: 'no-cache', signal: AbortSignal.any([o.signal, AbortSignal.timeout(TIMEOUT_MS)])});
    if (!response.ok) throw new Refused('http');
    if (response.headers.has('X-SC-Offline')) throw new Refused('offline-copy');
    const body = await readBody(response, limit);
    if (!body) throw new Refused('byte-limit');
    return body;
  } catch (error) {
    if (o.signal.aborted) throw cancelled();
    throw error instanceof Refused ? error : new Refused('network');
  }
}

/** Saves the region's SST and WCOFS layers into the pack, each whole or not at all. Rejects only for a cancel or a failed write. */
export async function saveOcean(o: OceanOptions): Promise<OceanSave> {
  const {regionId, origin, put, signal, fetchFn = fetch, eligible = () => null, progress = () => {}} = o, io = {signal, fetchFn};
  const manifestURL = habitatManifestURL(regionId, origin), layers: Record<string, OceanLayerRecord> = {};
  const write = async (url: string, body: ArrayBuffer): Promise<void> => {
    if (signal.aborted) throw cancelled();
    try { await put(url, body, new Headers({'Content-Type': 'application/json'})); } catch (cause) {
      if (signal.aborted) throw cancelled();
      throw new Error(STORAGE_FULL, {cause});
    }
  };
  let bytes: ArrayBuffer, data: unknown;
  try {
    bytes = await get(io, manifestURL, MANIFEST_CAP);
    data = JSON.parse(new TextDecoder().decode(bytes));
  } catch (error) {
    const reason = refusal(error);
    for (const id of OCEAN_LAYERS) layers[id] = {state: 'failed', reason: 'manifest', tiles: {saved: 0, listed: 0}, bytes: 0};
    return {manifest: {stored: false, reason}, bytes: 0, cap_bytes: OCEAN_BYTE_CAP, layers};
  }
  let used = bytes.byteLength;

  async function saveLayer(id: string): Promise<OceanLayerRecord> {
    const raw = object(data) && object(data.layers) && object(data.layers[id]) ? data.layers[id].tiles : undefined;
    const listed = Array.isArray(raw) ? raw.length : 0;
    const none = (state: OceanLayerRecord['state'], extra: {reason?: OceanLayerRecord['reason']; why?: string} = {}): OceanLayerRecord => ({state, ...extra, tiles: {saved: 0, listed}, bytes: 0});
    let layer: ReturnType<typeof layerOf>;
    try { layer = layerOf(data, regionId, id, READS[id]!.kind, READS[id]!.needs); } catch {
      return listed > MAX_TILES ? none('over-cap') : none('failed', {reason: 'identity'});
    }
    if (!layer) return none('absent');
    const why = eligible(id, data);
    if (why !== null) return none('not-current', {why});
    if (!layer.tiles.length) return none('failed', {reason: 'identity'});
    const declared = layer.tiles.map(t => object(t) && typeof t.bytes === 'number' ? t.bytes : 0);
    if (declared.some(n => n > MAX_TILE_BYTES)) return none('over-cap');
    let urls: string[];
    try { urls = layer.tiles.map(t => habitatTileURL(manifestURL, t, regionId)); } catch { return none('failed', {reason: 'identity'}); }
    if (declared.reduce((a, b) => a + b, 0) > OCEAN_BYTE_CAP - used) return none('over-cap');

    const bodies: ArrayBuffer[] = [];
    let next = 0, done = 0, failure: unknown;
    await Promise.all(Array.from({length: Math.min(CONCURRENCY, urls.length)}, async () => {
      while (failure === undefined && next < urls.length) {
        const i = next++;
        try {
          const body = await get(io, urls[i]!, declared[i]!);
          try { await tileRows(body, layer.tiles[i]!, regionId, layer); } catch (error) {
            const m = error instanceof Error ? error.message : '';
            throw new Refused(/length mismatch/.test(m) ? 'length' : /integrity/.test(m) ? 'integrity' : 'identity');
          }
          bodies[i] = body;
          progress(id, ++done, urls.length);
        } catch (error) { failure ??= error; }
      }
    }));
    if (signal.aborted) throw cancelled();
    if (failure !== undefined) return none('failed', {reason: refusal(failure)});
    for (let i = 0; i < urls.length; i++) await write(urls[i]!, bodies[i]!);
    const size = bodies.reduce((a, b) => a + b.byteLength, 0);
    return {state: 'saved', tiles: {saved: urls.length, listed}, bytes: size};
  }

  for (const id of OCEAN_LAYERS) {
    if (signal.aborted) throw cancelled();
    layers[id] = await saveLayer(id);
    used += layers[id].bytes;
  }
  await write(manifestURL, bytes);
  const generated = object(data) && typeof data.generated_at === 'string' ? data.generated_at : null;
  return {manifest: {url: new URL(manifestURL).pathname, sha256: hex(await crypto.subtle.digest('SHA-256', bytes)), bytes: bytes.byteLength, generated_at: generated, stored: true},
    bytes: used, cap_bytes: OCEAN_BYTE_CAP, layers};
}
