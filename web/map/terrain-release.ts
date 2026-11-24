import {projectionFor, type ProjectionOrigin} from '../../packages/coast/src/coast3d/grid.ts';

type Asset = {url: string; sha256: string; bytes: number; encoding?: 'gzip'; decodedBytes?: number};

type UnavailableReason = 'no-release' | 'schema' | 'origin-mismatch' | 'asset-contract' | 'region-mismatch';
export type TerrainReleaseSelection =
  | {available: true; regionId: string; origin: Readonly<ProjectionOrigin>; assets: readonly Asset[]; nodataSourceId: 0}
  | {available: false; reason: UnavailableReason};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const MAX_ASSET_BYTES = 20 * 1024 * 1024;
function boundedSize(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1 && value <= MAX_ASSET_BYTES;
}

const ASSET_BASE = 'https://terrain.invalid'; // Parse without depending on the browser or issuing a request.
function isAssetURL(raw: string): boolean {
  if (/[?#\\\s\u0000-\u001f\u007f]|%25|%2f|%5c/i.test(raw)) return false;
  try {
    const {origin, pathname} = new URL(raw, ASSET_BASE);
    // Refuse normalization rather than validating one spelling and returning another.
    return origin === ASSET_BASE && pathname === raw && pathname.startsWith('/data/') &&
      !pathname.endsWith('/') && !pathname.includes('//') &&
      !/[\u0000-\u001f\u007f]/.test(decodeURIComponent(pathname));
  } catch {
    return false;
  }
}

function isAsset(value: unknown): value is Asset {
  // Preflight the path and metadata. The loader still verifies the actual response's length and digest.
  return isRecord(value) && typeof value.url === 'string' && isAssetURL(value.url) &&
    typeof value.sha256 === 'string' && value.sha256.length === 64 && /^[a-f0-9]{64}$/.test(value.sha256) &&
    boundedSize(value.bytes) && (value.encoding === undefined ||
      (value.encoding === 'gzip' && boundedSize(value.decodedBytes)));
}

/** A terrain grid must decode to exactly the length decodeTerrain accepts. Mirrors the check in
 * packages/coast/src/coast3d/regional.ts decodeTerrain (line 25, no exported constant): integer size in 2..1025 and
 * byteLength === size * size * 5 (a float32 height plus one source byte per cell). Run on an isAsset-validated
 * value; the decoded length is decodedBytes for gzip and the asset's own length for an unencoded grid. */
function isGridAsset(value: unknown): boolean {
  const {size, encoding, decodedBytes, bytes} = value as Asset & {size?: unknown};
  return typeof size === 'number' && Number.isInteger(size) && size >= 2 && size <= 1025 &&
    (encoding === 'gzip' ? decodedBytes : bytes) === size * size * 5;
}

/** Select a parsed terrain.py v1 manifest supplied with its enclosing release's
 * regionId. The caller must supply that identity from the release, not from the
 * request. The producer writes [lon, lat]; return FE16's named scene origin. */
export function selectTerrainRelease(regionId: string, release?: unknown): TerrainReleaseSelection {
  if (release == null) return {available: false, reason: 'no-release'};
  if (!isRecord(release) || release.schemaVersion !== 1 || release.nodataSourceId !== 0) {
    return {available: false, reason: 'schema'};
  }
  if (typeof release.regionId !== 'string' || !release.regionId || release.regionId !== regionId) {
    return {available: false, reason: 'region-mismatch'};
  }

  const coordinates = release.origin;
  if (!Array.isArray(coordinates) || coordinates.length !== 2) return {available: false, reason: 'origin-mismatch'};
  const [lon, lat] = coordinates;
  let origin: Readonly<ProjectionOrigin>;
  try {
    ({origin} = projectionFor({lon, lat}));
  } catch {
    return {available: false, reason: 'origin-mismatch'};
  }

  const {overview, tiles, harborTiles, imagery} = release;
  if (!Array.isArray(tiles) || !Array.isArray(harborTiles) || !Array.isArray(imagery)) {
    return {available: false, reason: 'asset-contract'};
  }
  const assets: unknown[] = [overview];
  const grids: unknown[] = [overview]; // Overview and tile levels are decoded as grids; imagery is not.
  for (const tile of [...tiles, ...harborTiles]) {
    if (!isRecord(tile) || !Array.isArray(tile.lods) || tile.lods.length === 0) {
      return {available: false, reason: 'asset-contract'};
    }
    for (const lod of tile.lods) { assets.push(lod); grids.push(lod); }
  }
  for (const image of imagery) assets.push(image);
  if (!assets.every(isAsset)) return {available: false, reason: 'asset-contract'};
  if (!grids.every(isGridAsset)) return {available: false, reason: 'asset-contract'};
  return {available: true, regionId, origin, assets, nodataSourceId: 0};
}
