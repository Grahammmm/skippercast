// Pure logic for the offline trip pack, the offline banner and the install
// prompt. No DOM, no network: tests/test_offline.mjs imports this file in node.

export const PACK_PREFIX = 'sc-pack-';
export const PACK_META = '/__skippercast-pack.json';
export const SAVED_HEADER = 'X-SC-Saved-At';
export const TILE_CAP = 1500;
export const TILE_ZOOMS = [8, 12];
// NOAA ENC chart display (chart-map.js): a U.S. government map service. OSM
// street tiles are never bulk-saved; the OSM tile usage policy forbids
// prefetching tiles for offline use.
export const ENC_ORIGIN = 'https://gis.charttools.noaa.gov';
export const ENC_WMS = ENC_ORIGIN + '/arcgis/rest/services/MCS/NOAAChartDisplay/MapServer/exts/MaritimeChartService/WMSServer';
export const ENC_TILE_SIZE = 512;
const HALF = 20037508.342789244;

/**
 * Cache key of one chart tile. dist/sw.js derives the same key from the URL
 * Leaflet requests (encTileKey), so a saved tile answers the map offline.
 */
export function tileKey(layers, z, x, y, size = ENC_TILE_SIZE) {
  return `${ENC_ORIGIN}/__skippercast-tile/${layers}/${size}/${z}/${x}/${y}`;
}

/** Web Mercator tile column/row of a lon/lat on a grid of `n` tiles per axis. */
function tileXY(lon, lat, n) {
  const clamped = Math.max(-85.0511, Math.min(85.0511, lat)) * Math.PI / 180;
  const x = Math.floor((lon + 180) / 360 * n);
  const y = Math.floor((1 - Math.log(Math.tan(clamped) + 1 / Math.cos(clamped)) / Math.PI) / 2 * n);
  return [Math.min(n - 1, Math.max(0, x)), Math.min(n - 1, Math.max(0, y))];
}

/**
 * The chart tiles covering bounds [west, south, east, north] from zoom min to
 * max, as Leaflet requests them: a 512 px tile at map zoom z is one cell of a
 * 2^(z-1) grid. Whole zoom levels only: when the next level would pass `cap`,
 * it and every deeper level are left out, and maxZoom says where it stopped.
 */
export function planTiles(bounds, {minZoom = TILE_ZOOMS[0], maxZoom = TILE_ZOOMS[1], cap = TILE_CAP, size = ENC_TILE_SIZE} = {}) {
  const [west, south, east, north] = bounds || [];
  if (![west, south, east, north].every(Number.isFinite) || west >= east || south >= north) throw new Error('Region bounds unavailable');
  const tiles = [];
  let reached = null;
  for (let z = minZoom; z <= maxZoom; z++) {
    const n = 2 ** z * 256 / size;
    const [x0, y0] = tileXY(west, north, n), [x1, y1] = tileXY(east, south, n);
    const level = [];
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) level.push({z, x, y});
    if (tiles.length + level.length > cap) break;
    tiles.push(...level);
    reached = z;
  }
  return {tiles, minZoom, maxZoom: reached, requestedMaxZoom: maxZoom, cap};
}

/** A WMS 1.3.0 GetMap URL for one tile, the same image chart-map.js shows. */
export function tileURL({z, x, y}, layers, size = ENC_TILE_SIZE) {
  const span = 2 * HALF / (2 ** z * 256 / size);
  const minX = -HALF + x * span, maxY = HALF - y * span;
  const q = new URLSearchParams({service: 'WMS', request: 'GetMap', layers, styles: '', format: 'image/png', transparent: 'false',
    version: '1.3.0', width: String(size), height: String(size), crs: 'EPSG:3857'});
  return `${ENC_WMS}?${q}&bbox=${[minX, maxY - span, minX + span, maxY].join(',')}`;
}

/** The v2 Chart's basemap archive path (FE-10's manifest names it, web/map/chart.ts). */
export const BASEMAP_ARCHIVE = /^\/feeds\/tiles\/basemap\/[A-Za-z0-9._-]{1,120}\.pmtiles$/;

/**
 * The basemap tiles of a v2 pack (FE-51): the chart plan's cells at zoom 8–12
 * as archive tiles. MapLibre draws a 512 px vector tile at zoom z where a
 * 256 px map shows z + 1, so archive zoom z - 1 covers map zoom z (same cap).
 */
export function planBasemap(bounds, options) {
  const plan = planTiles(bounds, options);
  return {...plan, tiles: plan.tiles.map(({z, x, y}) => ({z: z - 1, x, y}))};
}

/**
 * Cache key of one byte range of the basemap archive: web/trip.ts stores each
 * range the PMTiles reader asks for under it, and dist/sw.js derives the same
 * key from the Range header MapLibre's reader sends. Null for anything else.
 */
export function basemapRangeKey(archive, range) {
  const m = /^bytes=(\d+)-(\d+)$/.exec(range || ''), url = new URL(archive);
  return m && !url.search && BASEMAP_ARCHIVE.test(url.pathname) ? `${url.origin}${url.pathname}?sc-range=${m[1]}-${m[2]}` : null;
}

/** Parts of the daily feed the map reads through the Worker (/api/daily; dist/daily-feed.js). */
export const DAILY_PARTS = ['regulations', 'mpa-boundaries', 'additional-closures'];
/** The /api/daily URL for one part: the same string the page requests, so a saved copy matches. */
export const dailyPartPath = (regionId, part) => `/api/daily?region=${encodeURIComponent(regionId)}&part=${encodeURIComponent(part)}`;

/**
 * Everything a region's pages load, as absolute URLs: the region directory,
 * config, manifest, coverage, every asset the config names (atlas, habitats,
 * regulations, protected areas, ...), its feeds, the shared forecast and
 * intelligence bundles, the daily-feed parts, and the forecast/tide/alert requests the Conditions
 * view makes. Order is stable and duplicates are dropped.
 */
export function packRequests({origin, region, config, shared = [], extra = []}) {
  if (!region?.id) throw new Error('Region unavailable');
  const id = region.id, same = path => new URL(path, origin + '/').href;
  const files = [
    'regions/index.json', config || `regions/${id}/region.json`, `regions/${id}/manifest.json`, `regions/${id}/coverage.json`,
    `regions/${id}/strategies.json`, `regions/${id}/intelligence.json`,
    ...Object.values(region.assets || {}).filter(v => typeof v === 'string' && v),
    ...shared,
    ...['daily_feed', 'conditions_feed', 'intelligence_feed', 'habitat_feed'].map(k => region[k]).filter(v => typeof v === 'string' && v),
    `/api/forecast?region=${encodeURIComponent(id)}`, `/api/intelligence?region=${encodeURIComponent(id)}`,
    ...DAILY_PARTS.map(part => dailyPartPath(id, part)),
  ].map(same);
  const out = [];
  for (const url of [...files, ...extra]) {
    const u = new URL(url, origin + '/');
    if (u.origin !== origin && u.protocol !== 'https:') continue;
    if (!out.includes(u.href)) out.push(u.href);
  }
  return out;
}

/** Files every region page loads regardless of region (coasts, ports, evidence). */
export const SHARED_FILES = ['data/coasts.json', 'data/home-ports.json', 'data/species-evidence.json', 'data/central-coverage-ledger-v1.json'];

/** Headers of a response to store, stamped with when it was saved. */
export function stampedHeaders(headers, now = new Date()) {
  const out = new Headers(headers);
  out.set(SAVED_HEADER, now.toISOString());
  return out;
}

/** "just now", "4 min ago", "3 h ago", "2 days ago"; null for an invalid time. */
export function relativeTime(iso, now = Date.now()) {
  const at = Date.parse(iso);
  if (!Number.isFinite(at) || at <= 0) return null;
  const minutes = Math.max(0, Math.round((now - at) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

/** 1.2 MB, 340 KB. */
export function formatBytes(bytes) {
  if (!(bytes >= 0)) return '—';
  if (bytes < 1e6) return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

/** The offline banner text, or null when there is nothing to warn about. */
export function bannerText({online, savedAt, now = Date.now()}) {
  const when = savedAt ? relativeTime(savedAt, now) : null;
  if (!online) return when ? `Offline — showing data saved ${when}` : 'Offline — only saved data is available';
  return when ? `Connection problem — showing data saved ${when}` : null;
}

/** iPhone/iPad Safari (including iPadOS, which reports a Mac user agent). */
export function isIOS(userAgent = '', maxTouchPoints = 0) {
  return /iPad|iPhone|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1);
}

/**
 * Which install help to show: 'prompt' (the browser offered installation),
 * 'ios' (Safari has no prompt, so explain Share → Add to Home Screen), or
 * null. Nothing once installed (standalone) or dismissed.
 */
export function installHint({standalone, promptAvailable, userAgent, maxTouchPoints, dismissed = {}}) {
  if (standalone) return null;
  if (promptAvailable) return dismissed.prompt ? null : 'prompt';
  if (isIOS(userAgent, maxTouchPoints) && !dismissed.ios) return 'ios';
  return null;
}
