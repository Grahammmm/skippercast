// Read-only bridge to the owner's reviewed Fish public service during the
// product merge. Original bytes/clocks and publication gates remain upstream;
// this is not an arbitrary proxy or a new source/rights approval.
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
export function coastTarget(input: URL): {url: URL; max: number; snapshot: string | null} | null {
  const path = input.pathname;
  if (/%|\\|\/\/|(?:^|\/)\.{1,2}(?:\/|$)/.test(path)) return null;
  let upstream: string, max = 8 * MB, snapshot: string | null = null;
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
      upstream = '/api/habitat/release'; max = 512 * 1024;
    } else if (name === 'habitat/tiles') {
      const region = input.searchParams.get('region'), release = input.searchParams.get('release');
      if (!region || !HABITAT_REGIONS.has(region) || (release !== null && !/^[a-f0-9]{64}$/.test(release))) return null;
      if ([...input.searchParams.keys()].some(k => !['region', 'release'].includes(k))) return null;
      params.set('region', region); if (release) params.set('release', release);
      upstream = '/api/habitat/tiles'; max = 2 * MB;
    } else return null;
  } else if (path.startsWith('/coast-data/')) {
    upstream = path.slice('/coast-data'.length);
    const terrain = /^\/data\/(?:coast-wide|coast3d)\/[a-zA-Z0-9_.-]+\.(?:json|bin|png|jpg)$/.test(upstream);
    if (!terrain && !DATA_FILES.has(upstream)) return null;
    const release = input.searchParams.get('release');
    if (release !== null && !/^[a-f0-9]{64}$/.test(release)) return null;
    if ([...input.searchParams.keys()].some(k => k !== 'release')) return null;
    if (release) params.set('release', release);
  } else return null;
  for (const key of new Set(input.searchParams.keys())) if (input.searchParams.getAll(key).length !== 1) return null;
  const url = new URL(upstream, ORIGIN); url.search = params.toString();
  return {url, max, snapshot};
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

/** Cookie/identity/auth headers never leave SkipperCast. Only bounded public GET/HEAD requests. */
export async function serveCoastData(request: Request, fetcher: typeof fetch = fetch): Promise<Response> {
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
    if (request.method === 'HEAD') {
      const size = upstream.headers.get('Content-Length');
      if (size !== null) {
        if (!/^\d+$/.test(size) || !Number.isSafeInteger(Number(size)) || (rangeLength !== null && Number(size) !== rangeLength)) {
          await upstream.body?.cancel(); return json({error: 'Coast range unavailable'}, 503);
        }
        out.set('Content-Length', size);
      }
      await upstream.body?.cancel();
      return new Response(null, {status: upstream.status, headers: out});
    }
    const bytes = await bounded(upstream, target.max);
    if (target.snapshot) {
      if (!/^application\/json\b/i.test(upstream.headers.get('Content-Type') ?? '')) throw Error('Unexpected format');
      const data = JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>;
      if (!data || data.schemaVersion !== 1 || data.countyId !== 'slo' || typeof data.generatedAt !== 'string' || !Number.isFinite(Date.parse(data.generatedAt))) throw Error('Wrong snapshot identity');
    }
    if (rangeLength !== null && bytes.byteLength !== rangeLength) throw Error('Invalid returned range');
    out.set('Content-Length', String(bytes.byteLength));
    return new Response(bytes, {status: upstream.status, headers: out});
  } catch { return json({error: 'Coast source unavailable'}, 503); }
}
