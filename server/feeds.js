// Feed storage for the Worker. Published feeds (conditions, data, forecasts)
// are read from the R2 bucket bound as FEEDS when present; otherwise from their
// GitHub branch. Keys mirror the branch layout: '<branch>/<path>'.
export const RAW = 'https://raw.githubusercontent.com/Grahammmm/skippercast/';
const BRANCHES = new Set(['conditions', 'data', 'forecasts', 'tiles']);
const SAFE = /^(conditions|data|forecasts|tiles)\/(?!.*\.\.)[A-Za-z0-9._\/-]{1,300}$/;

let bucket = null;
export function useBucket(env) { bucket = env?.FEEDS || null; }

/** R2 key for a published-feed URL or /feeds/ path, or null when it is not one. */
export function feedKey(value) {
  let key = null;
  if (typeof value !== 'string') return null;
  if (value.startsWith(RAW)) key = value.slice(RAW.length);
  else if (value.startsWith('/feeds/')) key = value.slice('/feeds/'.length);
  return key && SAFE.test(key) && BRANCHES.has(key.split('/')[0]) ? key : null;
}

/** Parsed JSON from R2, or undefined when R2 is not bound or lacks the key. */
export async function readBucketJSON(url) {
  const key = feedKey(url);
  if (!bucket || !key) return undefined;
  const object = await bucket.get(key);
  return object ? object.json() : undefined;
}

const contentType = key => key.endsWith('.json') || key.endsWith('.geojson') ? 'application/json'
  : key.endsWith('.pmtiles') ? 'application/octet-stream' : key.endsWith('.md') ? 'text/markdown; charset=utf-8' : 'application/octet-stream';
// Feeds named latest/index/manifest change in place; tiles are replaced per model cycle.
const cacheFor = key => /(^|\/)(latest|index|manifest|status|health|intelligence|habitat-dynamics)[^/]*\.json$/.test(key) ? 60 : 300;

function parseRange(header, size) {
  const match = /^bytes=(\d*)-(\d*)$/.exec(header || '');
  if (!match || (match[1] === '' && match[2] === '')) return null;
  let start, end;
  if (match[1] === '') { const suffix = Number(match[2]); start = Math.max(0, size - suffix); end = size - 1; }
  else { start = Number(match[1]); end = match[2] === '' ? size - 1 : Math.min(Number(match[2]), size - 1); }
  return start <= end && start < size ? {start, end} : 'invalid';
}

/** Serve bytes with HTTP Range support (PMTiles reads by range). */
export function rangeResponse(bytes, request, headers) {
  const size = bytes.byteLength, range = parseRange(request.headers.get('Range'), size);
  headers.set('Accept-Ranges', 'bytes');
  if (range === 'invalid') { headers.set('Content-Range', `bytes */${size}`); return new Response(null, {status: 416, headers}); }
  if (!range) { headers.set('Content-Length', String(size)); return new Response(bytes, {status: 200, headers}); }
  headers.set('Content-Range', `bytes ${range.start}-${range.end}/${size}`);
  headers.set('Content-Length', String(range.end - range.start + 1));
  return new Response(bytes.slice(range.start, range.end + 1), {status: 206, headers});
}

/**
 * GET /feeds/<branch>/<path>: R2 first (with Range and ETag), then the GitHub
 * branch through the edge cache. Returns null when the path is not a feed.
 */
export async function serveFeed(request, path, assets) {
  const key = feedKey(path);
  if (!key) return null;
  // Seafloor source/cache/review prefixes are never feeds. Public archives
  // require a current publication receipt, even when old R2 bytes still exist.
  const seafloor = key.startsWith('tiles/seafloor/');
  let publication = null;
  if (seafloor && key.endsWith('.pmtiles')) {
    const match = /^tiles\/seafloor\/seafloor-([a-z0-9-]+)\.pmtiles$/.exec(key);
    if (!match || !bucket) return new Response('Not found', {status: 404});
    let manifest;
    try { manifest = await (await bucket.get(`tiles/seafloor/manifest-${match[1]}.json`))?.json(); }
    catch { manifest = null; }
    publication = manifest;
    const expires = Date.parse(manifest?.expires_at);
    if (manifest?.status !== 'ready' || manifest?.region !== match[1] || !Number.isFinite(expires) || expires <= Date.now() || !/^[a-f0-9]{64}$/.test(manifest?.archive_sha256 || '')) {
      return new Response('Seafloor screening unavailable or expired', {status: 503, headers: {'Cache-Control': 'no-store'}});
    }
  }
  const headers = new Headers({'Content-Type': contentType(key), 'Cache-Control': seafloor ? 'no-store' : `public, max-age=${cacheFor(key)}`,
    'X-Content-Type-Options': 'nosniff', 'Access-Control-Allow-Origin': '*'});
  if (bucket) {
    const object = await bucket.get(key, {range: request.headers, onlyIf: request.headers});
    if (object) {
      if (publication && object.customMetadata?.sha256 !== publication.archive_sha256) {
        return new Response('Seafloor archive revision unavailable', {status: 503, headers});
      }
      headers.set('ETag', object.httpEtag);
      headers.set('X-Feed-Source', 'r2');
      headers.set('Accept-Ranges', 'bytes');
      if (!('body' in object)) return new Response(null, {status: 304, headers});
      if (object.range && request.headers.has('Range')) {
        const {offset = 0, length = object.size - offset} = object.range;
        headers.set('Content-Range', `bytes ${offset}-${offset + length - 1}/${object.size}`);
        headers.set('Content-Length', String(length));
        return new Response(object.body, {status: 206, headers});
      }
      headers.set('Content-Length', String(object.size));
      return new Response(object.body, {status: 200, headers});
    }
  }
  if (seafloor) return new Response('Not found', {status: 404, headers});
  if (key.startsWith('tiles/')) {  // map tiles ship with the site until R2 is connected
    const response = assets ? await assets.fetch(new Request(new URL('/' + key, request.url))) : null;
    if (!response?.ok) return new Response('Not found', {status: 404, headers});
    headers.set('X-Feed-Source', 'assets');
    return rangeResponse(new Uint8Array(await response.arrayBuffer()), request, headers);
  }
  const upstream = await fetch(RAW + key, {signal: AbortSignal.timeout(18000), redirect: 'manual',
    cf: {cacheTtl: cacheFor(key), cacheEverything: true}});
  if (!upstream.ok) return new Response(JSON.stringify({error: 'Feed unavailable'}), {status: upstream.status === 404 ? 404 : 502, headers});
  headers.set('X-Feed-Source', 'github');
  return new Response(upstream.body, {status: 200, headers});
}
