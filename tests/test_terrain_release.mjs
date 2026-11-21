import assert from 'node:assert/strict';
import test from 'node:test';

const MAX_ASSET_BYTES = 20 * 1024 * 1024;
function releaseFor(regionId, origin) {
  const grid = name => ({url: `/data/relief/${regionId}/terrain/${name}.bin.gz`,
    sha256: 'a'.repeat(64), bytes: 12, encoding: 'gzip', decodedBytes: 20, size: 2});
  return {
    regionId, schemaVersion: 1, origin, nodataSourceId: 0,
    bounds: [0, 0, 512, 512], sources: [], waterReferenceM: 0,
    overview: {...grid('overview'), x: 0, z: 0, dx: 512, dz: 512},
    tiles: [{x: 0, z: 0, width: 512, lods: [{...grid('tile-0-0-32'), spacing: 32}]}],
    harborTiles: [], imagery: [],
  };
}

test('terrain-release-selector', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', () => { throw new Error('unexpected terrain request'); });
  // Guard module initialization as well as valid and refused selections.
  const {selectTerrainRelease} = await import('../web/map/terrain-release.ts');
  const north = releaseFor('north', [-124.3, 42]);
  const south = releaseFor('south', [-117.25, 32.72]);
  const island = releaseFor('island', [-118.4, 33.38]);
  // Catch a legacy central origin, swapped coordinates, or dropped tile assets.
  for (const [record, origin] of [[north, {lon: -124.3, lat: 42}],
    [south, {lon: -117.25, lat: 32.72}], [island, {lon: -118.4, lat: 33.38}]]) {
    assert.deepEqual(selectTerrainRelease(record.regionId, record), {available: true, regionId: record.regionId,
      origin, assets: [record.overview, ...record.tiles[0].lods], nodataSourceId: 0});
  }

  // Catch central fallback, a name-only eligibility check, or permissive metadata validation.
  for (const [label, record, reason] of [
    ['absent', undefined, 'no-release'],
    ['null', null, 'no-release'],
    ['different region', south, 'region-mismatch'],
    ['missing release identity', {...north, regionId: undefined}, 'region-mismatch'],
    ['unknown version', {...north, schemaVersion: 2}, 'schema'],
    ['changed nodata convention', {...north, nodataSourceId: 1}, 'schema'],
    ['malformed origin', {...north, origin: [-124.3]}, 'origin-mismatch'],
    ['non-finite origin', {...north, origin: [Infinity, 42]}, 'origin-mismatch'],
    ['outside projection', {...north, origin: [-124.3, 86]}, 'origin-mismatch'],
    ['missing overview', {...north, overview: undefined}, 'asset-contract'],
    ['external overview', {...north, overview: {...north.overview, url: 'https://example.test/terrain'}}, 'asset-contract'],
    ['bad digest in a harbor LOD', {...north, harborTiles: [{...north.tiles[0],
      lods: [{...north.tiles[0].lods[0], sha256: 'z'.repeat(64)}]}]}, 'asset-contract'],
    ['oversized imagery', {...north, imagery: [{...north.overview, bytes: MAX_ASSET_BYTES + 1}]}, 'asset-contract'],
    ['empty asset', {...north, overview: {...north.overview, bytes: 0}}, 'asset-contract'],
    ['fractional byte count', {...north, overview: {...north.overview, bytes: 1.5}}, 'asset-contract'],
    ['oversized decoded asset', {...north, overview: {...north.overview, decodedBytes: MAX_ASSET_BYTES + 1}}, 'asset-contract'],
  ]) {
    assert.deepEqual(selectTerrainRelease('north', record), {available: false, reason}, label);
  }
  assert.equal(fetch.mock.callCount(), 0);
});

// Catch raw-prefix validation accepting noncanonical asset paths instead of rejecting them before fetch.
test('terrain release admits only canonical same-origin data asset URLs', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', () => { throw new Error('unexpected terrain request'); });
  const {selectTerrainRelease} = await import('../web/map/terrain-release.ts');
  const north = releaseFor('north', [-124.3, 42]);
  const select = url => selectTerrainRelease('north', {...north, overview: {...north.overview, url}});
  for (const url of [north.overview.url, '/data/relief/north/terrain/Coast%20caf%C3%A9.bin.gz']) {
    const selected = select(url);
    assert.equal(selected.available, true, url);
    assert.equal(selected.assets[0].url, url, 'retain the original encoded asset name');
  }
  for (const [label, url] of [
    ['parent segment outside data', '/data/../overview.bin.gz'],
    ['encoded parent segment outside data', '/data/%2e%2E/overview.bin.gz'],
    ['dot segment within data', '/data/relief/./overview.bin.gz'],
    ['backslash', '/data/relief\\overview.bin.gz'],
    ['protocol-relative', '//example.test/data/overview.bin.gz'],
    ['absolute', 'https://example.test/data/overview.bin.gz'],
    ['query', '/data/overview.bin.gz?kind=terrain'],
    ['fragment', '/data/overview.bin.gz#terrain'],
    ['empty query', '/data/overview.bin.gz?'],
    ['empty fragment', '/data/overview.bin.gz#'],
    ['encoded separator', '/data/relief%2Foverview.bin.gz'],
    ['encoded backslash', '/data/relief%5Coverview.bin.gz'],
    ['double encoding', '/data/relief/caf%25C3%25A9.bin.gz'],
    ['invalid escape', '/data/overview%xy.bin.gz'],
    ['control character', '/data/over\nview.bin.gz'],
    ['encoded control character', '/data/over%0Aview.bin.gz'],
    ['trailing space', '/data/overview.bin.gz '],
    ['empty path segment', '/data/relief//overview.bin.gz'],
    ['directory only', '/data/relief/'],
  ]) {
    assert.deepEqual(select(url), {available: false, reason: 'asset-contract'}, label);
  }
  assert.equal(fetch.mock.callCount(), 0);
});
