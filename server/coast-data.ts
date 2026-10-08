// Read-only bridge to the owner's reviewed Fish public service during the
// product merge. Original bytes/clocks and publication gates remain upstream;
// this is not an arbitrary proxy or a new source/rights approval. Asset groups
// copied to R2 by scripts/coast/publish_assets.py are served from there instead,
// each object hashed against its manifest entry before any byte leaves.
import {json} from './http.ts';

const ORIGIN = 'https://fish-report.g4651.workers.dev';
const MB = 1024 * 1024;
const SLO_REGIONS = new Set(['morro-bay', 'cambria-san-simeon']);
const HABITAT_REGIONS = new Set([...SLO_REGIONS, 'monterey-point-sur', 'point-arguello-conception']);
const SNAPSHOTS = new Set(['report', 'ocean', 'history']);
const DATA_FILES = new Set([
  '/data/skippercast-manifest.json', '/data/skippercast-habitat.geojson', '/data/skippercast-species.json',
  '/data/slo-shore-habitat.geojson', '/data/slo-shoreline.geojson', '/data/coast3d/chart-model.json',
]);
const RESPONSE_HEADERS = ['Content-Type', 'ETag', 'Last-Modified', 'Content-Range', 'Accept-Ranges',
  'X-Fish-Habitat-Release', 'X-Fish-Habitat-Source', 'X-Fish-Bathymetry-Source'];

/** Strict raw paths: percent escapes, traversal, private prefixes and URLs are never forwarded. */
export function coastTarget(input: URL): {url: URL; max: number; snapshot: string | null; asset: string | null; release: string | null} | null {
  const path = input.pathname;
  if (/%|\\|\/\/|(?:^|\/)\.{1,2}(?:\/|$)/.test(path)) return null;
  let upstream: string, max = 8 * MB, snapshot: string | null = null, asset: string | null = null;
  const params = new URLSearchParams();
  if (path.startsWith('/api/coast/')) {
    const name = path.slice('/api/coast/'.length);
    if (SNAPSHOTS.has(name)) {
      if ((input.searchParams.has('county') && input.searchParams.get('county') !== 'slo') ||
          (input.searchParams.has('region') && !SLO_REGIONS.has(input.searchParams.get('region')!))) return null;
      if ([...input.searchParams.keys()].some(k => !['county', 'region'].includes(k))) return null;
      upstream = '/api/' + name; snapshot = name; max = name === 'history' ? 16 * MB : 8 * MB;
    } else if (name === 'habitat/release') {
      if (input.search) return null;
      upstream = asset = '/api/habitat/release'; max = 512 * 1024;
    } else if (name === 'habitat/tiles') {
      const region = input.searchParams.get('region'), release = input.searchParams.get('release');
      if (!region || !HABITAT_REGIONS.has(region) || (release !== null && !/^[a-f0-9]{64}$/.test(release))) return null;
      if ([...input.searchParams.keys()].some(k => !['region', 'release'].includes(k))) return null;
      params.set('region', region); if (release) params.set('release', release);
      upstream = '/api/habitat/tiles'; asset = upstream + '?region=' + region; max = 2 * MB;
    } else return null;
  } else if (path.startsWith('/coast-data/')) {
    upstream = path.slice('/coast-data'.length);
    const terrain = /^\/data\/(?:coast-wide|coast3d)\/[a-zA-Z0-9_.-]+\.(?:json|bin|png|jpg)$/.test(upstream);
    if (!terrain && !DATA_FILES.has(upstream)) return null;
    asset = upstream;
    const release = input.searchParams.get('release');
    if (release !== null && !/^[a-f0-9]{64}$/.test(release)) return null;
    if ([...input.searchParams.keys()].some(k => k !== 'release')) return null;
    if (release) params.set('release', release);
  } else return null;
  for (const key of new Set(input.searchParams.keys())) if (input.searchParams.getAll(key).length !== 1) return null;
  const url = new URL(upstream, ORIGIN); url.search = params.toString();
  return {url, max, snapshot, asset, release: params.get('release')};
}

// R2 layout written by scripts/coast/publish_assets.py: content-addressed objects, a
// manifest whose SHA-256 is its release id, and a pointer written last.
type Entry = {sha256: string; bytes: number; contentType: string; habitatRelease?: string; expiresAt?: string};
type Release = {groups: string[]; objects: Record<string, Entry>};
export type CoastStore = Pick<R2Bucket, 'get' | 'head'>;
const SHA = /^[a-f0-9]{64}$/, VERIFY_MAX = 32 * MB;
const releases = new Map<string, Release>(); // immutable: keyed by the manifest digest
const verified = new Map<string, string>();  // object key -> R2 etag whose full bytes matched
const hashing = new Map<string, Promise<Uint8Array<ArrayBuffer>>>(); // one whole-object read per key at a time
const hex = async (bytes: Uint8Array<ArrayBuffer>) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
/** Same grouping as publish_assets.py group_of: a group is served from R2 only once it is published; null stays on the bridge. */
export const assetGroup = (asset: string) => /^\/(?:api\/habitat\/|data\/skippercast-|data\/coast-wide\/reef-context\.)/.test(asset) ? 'habitat'
  : /^\/data\/(?:coast-wide|coast3d)\//.test(asset) ? 'terrain' : null;
const validEntry = (e: Entry | undefined): e is Entry => !!e && typeof e === 'object' && SHA.test(e.sha256) && Number.isSafeInteger(e.bytes) && e.bytes > 0 &&
  e.bytes <= VERIFY_MAX && /^[a-z]+\/[a-z0-9.+-]+$/.test(e.contentType) && (e.habitatRelease === undefined || SHA.test(e.habitatRelease)) &&
  (e.expiresAt === undefined || Number.isFinite(Date.parse(e.expiresAt)));

async function small(store: CoastStore, key: string, max: number): Promise<Uint8Array<ArrayBuffer> | null> {
  const object = await store.get(key); if (!object) return null;
  if (object.size > max) { await object.body.cancel(); throw Error('Byte limit'); }
  return new Uint8Array(await object.arrayBuffer());
}

/** The verified current release, or null when nothing is published (the bridge stays the source). */
async function currentRelease(store: CoastStore): Promise<Release | null> {
  const raw = await small(store, 'coast/current.json', 4096); if (!raw) return null;
  const pointer = JSON.parse(new TextDecoder().decode(raw)) as {schemaVersion?: number; status?: string; releaseId?: string};
  if (pointer.schemaVersion !== 1 || pointer.status !== 'ready' || !SHA.test(pointer.releaseId ?? '')) throw Error('Coast release held');
  let release = releases.get(pointer.releaseId!);
  if (!release) {
    const bytes = await small(store, `coast/releases/${pointer.releaseId}.json`, 4 * MB);
    if (!bytes || await hex(bytes) !== pointer.releaseId) throw Error('Coast manifest identity');
    const data = JSON.parse(new TextDecoder().decode(bytes)) as Release & {schemaVersion: number; kind: string};
    if (data.schemaVersion !== 1 || data.kind !== 'skippercast-coast-assets' || !Array.isArray(data.groups) || !data.objects || typeof data.objects !== 'object') throw Error('Coast manifest shape');
    release = {groups: data.groups, objects: data.objects}; releases.clear(); releases.set(pointer.releaseId!, release);
  }
  return release;
}

/** Whole-object digest once per R2 object version; later reads pin that version's etag. */
async function verifiedRead(store: CoastStore, entry: Entry, method: string, range: {start: number; end: number} | null): Promise<Uint8Array<ArrayBuffer> | null> {
  const key = 'coast/objects/' + entry.sha256, etag = verified.get(key);
  if (etag !== undefined) {
    if (method === 'HEAD') { const head = await store.head(key); if (head?.etag === etag && head.size === entry.bytes) return null; }
    else {
      const object = await store.get(key, {onlyIf: {etagMatches: etag}, ...(range ? {range: {offset: range.start, length: range.end - range.start + 1}} : {})});
      if (object && 'body' in object && object.etag === etag && object.size === entry.bytes) return new Uint8Array(await object.arrayBuffer());
      if (object && 'body' in object) await object.body.cancel();
    }
    verified.delete(key);
  }
  let pending = hashing.get(key);
  if (!pending) {
    pending = (async () => {
      const object = await store.get(key);
      if (!object || object.size !== entry.bytes) { await object?.body.cancel(); throw Error('Coast object identity'); }
      const bytes = new Uint8Array(await object.arrayBuffer());
      if (bytes.byteLength !== entry.bytes || await hex(bytes) !== entry.sha256) throw Error('Coast object digest');
      if (verified.size > 20000) verified.clear();
      verified.set(key, object.etag);
      return bytes;
    })().finally(() => hashing.delete(key));
    hashing.set(key, pending);
  }
  const bytes = await pending;
  return method === 'HEAD' ? null : range ? bytes.slice(range.start, range.end + 1) : bytes.slice();
}

async function fromStore(store: CoastStore, target: {asset: string; release: string | null; max: number}, method: string, range: {start: number; end: number} | null): Promise<Response | undefined> {
  const group = assetGroup(target.asset); if (!group) return undefined;
  const release = await currentRelease(store);
  if (!release || !release.groups.includes(group)) return undefined;
  const entry = Object.hasOwn(release.objects, target.asset) ? release.objects[target.asset] : undefined;
  if (!validEntry(entry)) return json({error: 'Unknown coast dataset'}, 404);
  if (target.release !== null && target.release !== entry.habitatRelease) return json({error: 'Unknown coast release'}, 404);
  if (entry.expiresAt !== undefined && !(Date.parse(entry.expiresAt) > Date.now())) return json({error: 'Coast release expired'}, 503);
  if (range && range.end >= entry.bytes) return new Response(null, {status: 416, headers: {'Content-Range': `bytes */${entry.bytes}`, 'Cache-Control': 'no-store'}});
  if (!range && method === 'GET' && entry.bytes > target.max) return json({error: 'Coast source unavailable'}, 503);
  const bytes = await verifiedRead(store, entry, method, range);
  const out = new Headers({'Cache-Control': 'no-store', 'Content-Type': entry.contentType, ETag: `"sha256-${entry.sha256}"`, 'Accept-Ranges': 'bytes',
    'Content-Length': String(range ? range.end - range.start + 1 : entry.bytes), 'X-Content-Type-Options': 'nosniff'});
  if (entry.habitatRelease) out.set('X-Fish-Habitat-Release', entry.habitatRelease);
  if (range) out.set('Content-Range', `bytes ${range.start}-${range.end}/${entry.bytes}`);
  if (bytes && bytes.byteLength !== (range ? range.end - range.start + 1 : entry.bytes)) throw Error('Invalid returned range');
  return new Response(bytes, {status: range ? 206 : 200, headers: out});
}

// FE-84: snapshot sources from SkipperCast's own published feeds, switched one by one with the
// COAST_FEEDS var. A switched feed is used only while it is present, valid and inside its age
// limit; otherwise that source comes from the Fish Worker exactly as before. That fallback is dated:
// it goes when FE-62 retires the bridge. Values keep their original clocks and outcomes.
export type CoastFeed = 'nearshore' | 'water-quality' | 'ocean' | 'history';
type Json = Record<string, any>;
const HOUR = 3_600_000, SKEW = 300_000;
const clock = (v: unknown) => typeof v === 'string' ? Date.parse(v) : NaN;
const isClock = (v: unknown) => Number.isFinite(clock(v));
const rows = (v: unknown): v is Json[] => Array.isArray(v) && v.every(x => !!x && typeof x === 'object' && !Array.isArray(x));
const reported = (s: Json) => typeof s.id === 'string' && ['ok', 'error', 'pending'].includes(s.outcome) && isClock(s.fetchedAt);
// SLO's feeds are published under the Morro Bay region: FE-40, FE-41, coast_snapshots.py (live cycle) and FE-42 (weekly).
const FEEDS: Record<CoastFeed, {key: string; max: number; maxAge: number; generated: string; valid: (d: Json) => boolean}> = {
  nearshore: {key: 'conditions/regions/morro-bay/nearshore.json', max: MB, maxAge: 3 * HOUR, generated: 'generated_at',
    valid: d => d.schema_version === 1 && d.region_id === 'morro-bay' && rows(d.nearshore) && rows(d.sources) &&
      d.nearshore.every(s => typeof s.id === 'string' && typeof s.areaId === 'string' && ['available', 'error'].includes(s.availability) &&
        ['current', 'stale', 'unknown'].includes(s.freshness) && Array.isArray(s.hours) && isClock(s.fetchedAt) && (s.issuedAt === null || isClock(s.issuedAt))) &&
      d.sources.every(s => reported(s) && s.id.startsWith('cdip-'))},
  'water-quality': {key: 'conditions/regions/morro-bay/beach-health.json', max: MB, maxAge: 3 * HOUR, generated: 'generatedAt',
    valid: d => d.schemaVersion === 1 && d.countyId === 'slo' && d.regionId === 'morro-bay' && rows(d.waterQuality) && rows(d.sources) && d.sources.length > 0 &&
      d.waterQuality.every(s => typeof s.id === 'string' && typeof s.status === 'string' && isClock(s.fetchedAt)) &&
      d.sources.every(s => reported(s) && s.id === 'slo-beach-water-quality')},
  ocean: {key: 'conditions/regions/morro-bay/coast-ocean.json', max: 8 * MB, maxAge: 3 * HOUR, generated: 'generatedAt',
    valid: d => d.schemaVersion === 1 && d.countyId === 'slo' && rows(d.currents) && (d.cloud === null || (!!d.cloud && typeof d.cloud === 'object')) &&
      rows(d.sources) && d.sources.every(s => typeof s.id === 'string' && ['ok', 'error'].includes(s.status) && isClock(s.fetchedAt))},
  history: {key: 'data/regions/morro-bay/history.json', max: 16 * MB, maxAge: 8 * 24 * HOUR, generated: 'generatedAt',
    valid: d => d.schemaVersion === 1 && d.countyId === 'slo' && rows(d.stations) &&
      d.stations.every(s => typeof s.stationId === 'string' && !!s.recent && typeof s.recent === 'object' && !!s.baseline && Array.isArray(s.sources))},
};
const SNAPSHOT_FEEDS: Record<string, CoastFeed[]> = {report: ['nearshore', 'water-quality'], ocean: ['ocean'], history: ['history']};

/** The sources COAST_FEEDS moves to SkipperCast feeds. Unset or unknown names: none, so every snapshot is Fish's. */
export function coastFeeds(value: string | undefined): Set<CoastFeed> {
  return new Set((value ?? '').split(',').map(s => s.trim().toLowerCase()).filter((s): s is CoastFeed => Object.hasOwn(FEEDS, s)));
}

/** A published feed, or why it is not used: missing, unreadable, invalid or stale (its own clock against this request's). */
async function ownFeed(store: CoastStore | null, name: CoastFeed, now: number): Promise<Json | string> {
  if (!store) return 'unbound';
  const feed = FEEDS[name];
  try {
    const bytes = await small(store, feed.key, feed.max); if (!bytes) return 'missing';
    const data = JSON.parse(new TextDecoder().decode(bytes)) as Json;
    if (!data || typeof data !== 'object' || !feed.valid(data) || !isClock(data[feed.generated])) return 'invalid';
    const age = now - clock(data[feed.generated]);
    return age >= -SKEW && age < feed.maxAge ? data : 'stale';
  } catch { return 'unreadable'; }
}

/** Freshness against this request's clock: a model issue 48 h old or more is never current, whatever the collector said. */
const nearshoreNow = (s: Json, now: number) => s.freshness === 'current' && !(now - clock(s.issuedAt) < 48 * HOUR) ? {...s, freshness: 'stale'} : s;
/** A recorded series whose last observation is over 3 h old is stale now, though it was current when published (weekly). */
const historyNow = (d: Json, now: number) => ({...d, stations: d.stations.map((s: Json) =>
  ({...s, recent: {...s.recent, stale: s.recent.stale === true || !(now - clock(s.recent.lastObservedAt) <= 3 * HOUR)}}))});
/** Fish's report with the switched enrichment rows and their source statuses replaced by SkipperCast's. */
function overlay(report: Json, own: Partial<Record<CoastFeed, Json>>, now: number): Json {
  let out: Json = {...report, sources: Array.isArray(report.sources) ? report.sources : []};
  const nearshore = own.nearshore, water = own['water-quality'];
  if (nearshore) out = {...out, nearshore: nearshore.nearshore.map((s: Json) => nearshoreNow(s, now)),
    sources: [...out.sources.filter((s: Json) => !String(s?.id).startsWith('cdip-')), ...nearshore.sources]};
  if (water) out = {...out, waterQuality: water.waterQuality,
    sources: [...out.sources.filter((s: Json) => s?.id !== 'slo-beach-water-quality'), ...water.sources]};
  return out;
}
function ownResponse(data: Json, method: string, upstream: string): Response {
  const bytes = new TextEncoder().encode(JSON.stringify(data));
  return new Response(method === 'HEAD' ? null : bytes, {status: 200, headers: {'Cache-Control': 'no-store', 'Content-Type': 'application/json',
    'Content-Length': String(bytes.byteLength), 'X-Content-Type-Options': 'nosniff', 'X-Coast-Upstream': upstream}});
}

async function bounded(response: Response, max: number): Promise<Uint8Array<ArrayBuffer>> {
  const length = response.headers.get('Content-Length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > max)) { await response.body?.cancel(); throw Error('Byte limit'); }
  const reader = response.body?.getReader(); if (!reader) throw Error('Missing data');
  const parts: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const {done, value} = await reader.read(); if (done) break;
      size += value.byteLength; if (size > max) throw Error('Byte limit');
      parts.push(value);
    }
  } catch (error) { await reader.cancel(); throw error; }
  finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
  return bytes;
}

/** Cookie/identity/auth headers never leave SkipperCast. Only bounded public GET/HEAD requests.
 * `feeds` (COAST_FEEDS) moves snapshot sources to SkipperCast's feeds; empty keeps every path as before FE-84. */
export async function serveCoastData(request: Request, fetcher: typeof fetch = fetch, store: CoastStore | null = null,
  feeds: ReadonlySet<CoastFeed> = new Set()): Promise<Response> {
  if (!['GET', 'HEAD'].includes(request.method)) return new Response('Method not allowed', {status: 405, headers: {Allow: 'GET, HEAD'}});
  const target = coastTarget(new URL(request.url)); if (!target) return json({error: 'Unknown coast dataset'}, 404);
  const headers = new Headers();
  const range = request.headers.get('Range');
  if (range) {
    const match = /^bytes=(\d+)-(\d+)$/.exec(range);
    if (!match || !Number.isSafeInteger(Number(match[1])) || !Number.isSafeInteger(Number(match[2])) ||
        Number(match[2]) < Number(match[1]) || Number(match[2]) - Number(match[1]) + 1 > target.max || target.snapshot) return json({error: 'Invalid coast range'}, 416);
    headers.set('Range', range);
  }
  if (store && target.asset) {
    try {
      const wanted = range ? /^bytes=(\d+)-(\d+)$/.exec(range)! : null;
      const local = await fromStore(store, {asset: target.asset, release: target.release, max: target.max}, request.method,
        wanted ? {start: Number(wanted[1]), end: Number(wanted[2])} : null);
      if (local) return local;
    } catch { return json({error: 'Coast source unavailable'}, 503); }
  }
  // FE-84: switched snapshot sources from SkipperCast's feeds; the rest of a report stays on the bridge.
  const own: Partial<Record<CoastFeed, Json>> = {}, notes: string[] = [], now = Date.now();
  if (target.snapshot) {
    for (const name of SNAPSHOT_FEEDS[target.snapshot]!.filter(n => feeds.has(n))) {
      const result = await ownFeed(store, name, now);
      if (typeof result === 'string') notes.push(`${name}=fish (${result})`);
      else { own[name] = result; notes.push(`${name}=skippercast`); }
    }
    if (own.ocean) return ownResponse(own.ocean, request.method, notes.join(', '));
    if (own.history) return ownResponse(historyNow(own.history, now), request.method, notes.join(', '));
  }
  const overlaid = Object.keys(own).length > 0;
  // Do not forward client cookies, Origin, Referer, Authorization or arbitrary headers.
  try {
    const upstream = await fetcher(new Request(target.url, {method: request.method, headers,
      redirect: 'manual', signal: AbortSignal.timeout(20000)}));
    if (![200, 206].includes(upstream.status)) {
      await upstream.body?.cancel();
      return json({error: 'Coast source unavailable'}, upstream.status === 404 ? 404 : 503);
    }
    if (upstream.status !== (range ? 206 : 200)) { await upstream.body?.cancel(); return json({error: 'Coast range unavailable'}, 503); }
    let rangeLength: number | null = null;
    if (range) {
      const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(upstream.headers.get('Content-Range') ?? '');
      const wanted = /^bytes=(\d+)-(\d+)$/.exec(range)!;
      if (!match || match[1] !== wanted[1] || match[2] !== wanted[2] || !Number.isSafeInteger(Number(match[3])) || Number(match[3]) <= Number(match[2])) {
        await upstream.body?.cancel(); return json({error: 'Coast range unavailable'}, 503);
      }
      rangeLength = Number(match[2]) - Number(match[1]) + 1;
    }
    const out = new Headers({'Cache-Control': 'no-store'});
    for (const key of RESPONSE_HEADERS) { const value = upstream.headers.get(key); if (value !== null) out.set(key, value); }
    if (notes.length) out.set('X-Coast-Upstream', notes.join(', '));
    if (request.method === 'HEAD') {
      const size = upstream.headers.get('Content-Length');
      if (size !== null) {
        if (!/^\d+$/.test(size) || !Number.isSafeInteger(Number(size)) || (rangeLength !== null && Number(size) !== rangeLength)) {
          await upstream.body?.cancel(); return json({error: 'Coast range unavailable'}, 503);
        }
        if (!overlaid) out.set('Content-Length', size);  // an overlaid report's length differs from Fish's
      }
      await upstream.body?.cancel();
      return new Response(null, {status: upstream.status, headers: out});
    }
    let bytes: Uint8Array = await bounded(upstream, target.max);
    if (target.snapshot) {
      if (!/^application\/json\b/i.test(upstream.headers.get('Content-Type') ?? '')) throw Error('Unexpected format');
      const data = JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>;
      if (!data || data.schemaVersion !== 1 || data.countyId !== 'slo' || typeof data.generatedAt !== 'string' || !Number.isFinite(Date.parse(data.generatedAt))) throw Error('Wrong snapshot identity');
      if (overlaid) bytes = new TextEncoder().encode(JSON.stringify(overlay(data, own, now)));
    }
    if (rangeLength !== null && bytes.byteLength !== rangeLength) throw Error('Invalid returned range');
    out.set('Content-Length', String(bytes.byteLength));
    return new Response(bytes, {status: upstream.status, headers: out});
  } catch { return json({error: 'Coast source unavailable'}, 503); }
}
