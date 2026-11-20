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

function isAsset(value: unknown): value is Asset {
  // Mirror regional.ts's verifiedAsset metadata checks at its default budget.
  // The loader still verifies the length and digest of the actual response.
  return isRecord(value) && typeof value.url === 'string' && value.url.startsWith('/data/') &&
    typeof value.sha256 === 'string' && value.sha256.length === 64 && /^[a-f0-9]{64}$/.test(value.sha256) &&
    boundedSize(value.bytes) && (value.encoding === undefined ||
      (value.encoding === 'gzip' && boundedSize(value.decodedBytes)));
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
  for (const tile of [...tiles, ...harborTiles]) {
    if (!isRecord(tile) || !Array.isArray(tile.lods) || tile.lods.length === 0) {
      return {available: false, reason: 'asset-contract'};
    }
    for (const lod of tile.lods) assets.push(lod);
  }
  for (const image of imagery) assets.push(image);
  if (!assets.every(isAsset)) return {available: false, reason: 'asset-contract'};
  return {available: true, regionId, origin, assets, nodataSourceId: 0};
}
