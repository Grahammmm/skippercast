"""Synthetic DL-5 → terrain stage integration; no held or live inputs."""
import gzip
import json
from math import cos, radians
from pathlib import Path
import runpy

import numpy as np
from pyproj import Transformer
import pytest
import rasterio
from affine import Affine

from skippercast.relief import receipts, terrain
from tests._support import ROOT

ORIGIN = (-124.2, 41.7)
BOUNDS = [-124.20035, 41.69975, -124.19965, 41.70025]
TO_MERCATOR = Transformer.from_crs(4326, 3857, always_xy=True)
FROM_MERCATOR = Transformer.from_crs(3857, 4326, always_xy=True)


def write_json(path, doc):
    path.write_bytes(receipts.canonical(doc) + b'\n')


def source(identity, resolution):
    return dict(id=identity, resolution_m=resolution, rights_class='public', units='m',
                vertical_datum='unstated', value_convention='elevation_positive_up',
                label='estimated', citation='Synthetic terrain')


def fixture(root, *, native, epsg=3857, mosaic_crs=None):
    region = receipts.Region(root, 'north-fixture')
    mx, my = Transformer.from_crs(4326, epsg, always_xy=True).transform(*ORIGIN)
    step = 4 / cos(radians(ORIGIN[1])) if epsg == 3857 else 4
    transform = Affine(step, 0, mx - 12 * step, 0, -step, my + 12 * step)
    crs = f'EPSG:{epsg}'

    def raster(path, data, projection=crs):
        with rasterio.open(path, 'w', driver='GTiff', crs=projection, dtype=data.dtype,
                           width=24, height=24, count=1, transform=transform) as ds:
            ds.write(data, 1)

    if native:
        def select(out):
            grid, support = out / 'native.tif', out / 'native-support.tif'
            raster(grid, np.full((24, 24), 24, dtype='float32'))
            mask = np.full((24, 24), 2, dtype='uint8')
            mask[6:10, 7:11] = 0  # Native-only gap with valid mosaic beneath.
            raster(support, mask)
            row = dict(source('native-detail', 4), value_convention='depth_positive_down', vertical_offset_m=1,
                       path=grid.name, sha256=receipts.sha256_file(grid), max_zoom=15,
                       support_path=support.name, support_sha256=receipts.sha256_file(support))
            write_json(out / 'native.json', [row])

        assert receipts.run_stage(receipts.StageRun(region, 'select', select, '1' * 64)).state == 'ok'

    def mosaic(out):
        heights = np.full((24, 24), -11, dtype='float32')
        heights[:, 16:] = 9.25  # Preserve land exactly, even when a native source overlaps it.
        contributors = np.ones((24, 24), dtype='uint16')
        contributors[:, 16:] = 300  # DL-5 contributors are UInt16, not viewer bytes.
        heights[13, 14] = np.nan  # Off-centre sub-overview-pixel hole, even with a contributor.
        elevation_crs, contributor_crs = (crs, crs) if mosaic_crs is None else mosaic_crs
        raster(out / 'elevation.tif', heights, elevation_crs)
        raster(out / 'contributor.tif', contributors, contributor_crs)
        write_json(out / 'manifest.json', dict(segment=region.id, units='m', bounds_wgs84=BOUNDS,
                   value_convention='elevation_positive_up', sources=[dict(source('base', 10), code=1),
                                                                      dict(source('land', 10), code=300)]))

    upstream = (receipts.Ref('select'),) if native else ()
    # Deliberately not the default mosaic/public path: the receipt is authoritative.
    result = receipts.run_stage(receipts.StageRun(region, 'mosaic', mosaic, '2' * 64, scope='public',
                                                 target='receipted-mosaic', upstream=upstream))
    assert result.state == 'ok'
    public = region.dir / 'layers/public'
    public.mkdir(parents=True)
    (public / 'keep').write_text('sibling\n')
    return region


def run(region):
    main = runpy.run_path(str(ROOT / 'scripts/relief/region.py'))['main']
    return main(['terrain', '--region', region.id, '--out', str(region.out_root)])


def read_asset(folder, asset):
    path = folder / Path(asset['url']).name
    payload = gzip.decompress(path.read_bytes())
    size = asset['size']
    assert 2 <= size <= 1025
    assert asset['sha256'] == receipts.sha256_file(path)
    assert asset['bytes'] == path.stat().st_size
    assert len(payload) == asset['decodedBytes'] == 5 * size**2
    return (np.frombuffer(payload, '<f4', count=size**2).reshape(size, size),
            np.frombuffer(payload, 'u1', offset=4 * size**2).reshape(size, size))


def test_companion_nodata_is_not_support_even_when_internal_mask_says_valid(tmp_path):
    profile = dict(driver='GTiff', crs='EPSG:3857', width=4, height=4, count=1,
                   transform=Affine(1, 0, 100, 0, -1, 100))
    grid, support = tmp_path / 'depth.tif', tmp_path / 'support.tif'
    with rasterio.open(grid, 'w', **profile, dtype='float32') as ds:
        ds.write(np.full((4, 4), -12, dtype='float32'), 1)
    cells = np.full((4, 4), 7, dtype='uint16')
    cells[0] = [99, 7, 0, 7]  # Nodata, valid neighbour, zero, explicit mask hole.
    mask = np.full((4, 4), 255, dtype='uint8')
    mask[0, 3] = 0
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        with rasterio.open(support, 'w', **profile, dtype=cells.dtype, nodata=99) as ds:
            ds.write(cells, 1)
            ds.write_mask(mask)

    frame = terrain.Frame([-1, -1, 1, 1])  # x = Mercator easting, z = -northing.
    with rasterio.open(grid) as depth, rasterio.open(support) as companion:
        terrain.aligned(depth, companion)
        assert companion.files == [str(support)]  # No external mask sidecar.
        # GDAL's explicit mask exposes the positive sentinel as unmasked.
        assert companion.nodata == 99
        assert companion.read(1, masked=True)[0].tolist() == [99, 7, 0, None]
        mosaic, native = [terrain.samples(frame, 100.5, -99.5, 1, 1, 4, depth, companion,
                                          contributor=contributor)
                          for contributor in (True, False)]
        for (values, codes), expected_codes in [(mosaic, [0, 7, 0, 0]), (native, [0, 0, 0, 0])]:
            np.testing.assert_array_equal(values[0], [np.nan, -12, np.nan, np.nan])
            np.testing.assert_array_equal(codes[0], expected_codes)

        # A positive centre is not enough if its wider footprint covers the sentinel.
        values, codes = terrain.samples(frame, 101.25, -98.75, 1.5, 1.5, 1, depth, companion,
                                        contributor=True)
        np.testing.assert_array_equal(values, [[np.nan]])
        np.testing.assert_array_equal(codes, [[0]])


def test_receipted_overview_round_trip_and_real_noop(tmp_path, capsys):
    # Wrong origin/axis, nearest-only coarsening and nondeterministic gzip all
    # break this producer test. The binary consumer itself is covered in Node.
    region = fixture(tmp_path / 'out', native=False)
    assert run(region) == 0
    folder = region.dir / 'layers/terrain'
    manifest = json.loads((folder / 'manifest.json').read_text())
    assert manifest['origin'] == pytest.approx(ORIGIN)
    asset = manifest['overview']
    values, ids = read_asset(folder, asset)
    assert values.tolist() == [[-11, -11, 9.25], [-11, 0, 9.25], [-11, -11, 9.25]]
    assert ids.tolist() == [[1, 1, 2], [1, 0, 2], [1, 1, 2]]
    west, south, east, north = BOUNDS
    mx, my = TO_MERCATOR.transform(*manifest['origin'])
    scale = cos(radians(manifest['origin'][1]))
    for col, row, expected in [(0, 0, (west, north)), (2, 2, (east, south))]:
        x = asset['x'] + col * asset['dx']
        z = asset['z'] + row * asset['dz']
        assert FROM_MERCATOR.transform(mx + x / scale, my - z / scale) == pytest.approx(expected, abs=1e-9)

    receipt = region.receipt_path('terrain')
    records = [receipt, *folder.iterdir()]
    contents = [p.read_bytes() for p in records]
    stamps = [p.stat().st_mtime_ns for p in records]
    assert run(region) == 0
    assert '[terrain] DONE' in capsys.readouterr().out
    assert [p.read_bytes() for p in records] == contents
    assert [p.stat().st_mtime_ns for p in records] == stamps
    assert receipts.check(region, 'terrain').done
    assert (region.dir / 'layers/public/keep').read_text() == 'sibling\n'

    # A forced rebuild must also reproduce bytes (a cache hit alone cannot prove this).
    (folder / 'overview.bin.gz').write_bytes(b'corrupt')
    assert run(region) == 0
    assert [p.read_bytes() for p in records[1:]] == contents[1:]

    # A stale/tampered parent is blocked even while good terrain files remain on disk.
    (region.dir / 'receipted-mosaic/manifest.json').write_text('{}')
    assert run(region) == 3
    assert '[terrain] BLOCKED' in capsys.readouterr().out


@pytest.mark.parametrize(('crs_pair', 'message'), [
    pytest.param((None, None), 'must both declare a CRS', id='neither-crs'),
    pytest.param((None, 'EPSG:3857'), 'must both declare a CRS', id='missing-elevation-crs'),
    pytest.param(('EPSG:3857', None), 'must both declare a CRS', id='missing-contributor-crs'),
    pytest.param(('EPSG:3857', 'EPSG:3310'), 'must share one grid', id='mismatched-crs'),
])
def test_mosaic_crs_refused_before_sampling(tmp_path, monkeypatch, crs_pair, message):
    # Equality alone lets two missing CRSs through when affine and shape match.
    region = fixture(tmp_path / 'out', native=False, mosaic_crs=crs_pair)

    def unexpected_sample(*args, **kwargs):
        pytest.fail('terrain reached sampling before refusing the mosaic CRS')

    monkeypatch.setattr(terrain, 'samples', unexpected_sample)
    assert run(region) == 1
    receipt = receipts.read_receipt(region.receipt_path('terrain'))
    assert receipt is not None
    assert receipt['status'] == 'failed'
    assert receipt['error'].startswith('ReceiptError:')
    assert message in receipt['error']
    assert receipt['outputs'] == []
    assert not (region.dir / 'layers/terrain').exists()
    assert not list(region.resolve(receipt['failed_dir']).glob('*.bin.gz'))


@pytest.mark.parametrize('epsg', [3857, 3310])
def test_native_lod_refines_only_supported_water(tmp_path, epsg):
    # A grid that ignores the native support mask, fills a mosaic hole, or
    # replaces +3m land with native soundings must fail at the finest LOD.
    region = fixture(tmp_path / 'out', native=True, epsg=epsg)
    assert run(region) == 0
    folder = region.dir / 'layers/terrain'
    manifest = json.loads((folder / 'manifest.json').read_text())
    assert manifest['nodataSourceId'] == 0
    assert {s['id']: s['sourceId'] for s in manifest['sources']} == {1: 'base', 2: 'land', 3: 'native-detail'}
    (tile,) = manifest['tiles']
    assert [lod['spacing'] for lod in tile['lods']] == [32, 16, 4]
    for lod in tile['lods']:
        assert (lod['size'] - 1) * lod['spacing'] == tile['width']
        values, ids = read_asset(folder, lod)
        assert np.all(values[ids == 2] == 9.25)
        assert np.all(values[ids == 0] == 0)
    assert tile['lods'][-1]['size'] == 1025
    values, ids = read_asset(folder, tile['lods'][-1])
    assert np.any(ids == 3)
    assert np.all(values[ids == 3] == -23)
    # Datum/sign and source id agree, native mask falls back to the mosaic, and
    # the overlapping native raster cannot fill the authoritative mosaic pixel hole.
    for x, z, expected in [(-10, -10, 1), (0, -10, 3), (10, 6, 0), (24, 0, 2)]:
        col = round((x - tile['x']) / 4)
        row = round((z - tile['z']) / 4)
        assert ids[row, col] == expected
