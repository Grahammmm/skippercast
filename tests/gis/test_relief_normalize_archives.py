"""R2 archive and lidar admission through the unchanged mosaic reader."""
import base64
from io import BytesIO
import json
from pathlib import Path
import tarfile
from zipfile import ZipFile

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from research.scripts.coast_mvp.coast_mosaic import load_sources
from scripts.relief.region import main as region_main
from skippercast.relief import receipts
from skippercast.relief.normalize_archives import normalize_archive
from tests._support import FIXTURES

pytestmark = pytest.mark.gis


def tif(path, values, *, cell=2, x=685000, nodata=None, hole=None, description=None, crs='EPSG:26910', **tags):
    bands = values if values.ndim == 3 else values[None]
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        with rasterio.open(path, 'w', driver='GTiff', count=len(bands), dtype=values.dtype, crs=crs,
                           width=bands.shape[2], height=bands.shape[1], nodata=nodata,
                           transform=from_origin(x, 3930000, cell, cell)) as dst:
            dst.write(bands)
            dst.update_tags(**tags)
            if hole is not None:
                mask = np.full(bands.shape[1:], 255, dtype='uint8')
                mask[hole] = 0
                dst.write_mask(mask)
            if description is not None:
                dst.set_band_description(1, description)
    return path


def package(path, members):
    with ZipFile(path, 'w') as output:
        for name, src in members.items():
            output.write(src, name)
    return path


def mosaic_row(tmp_path, result, original):
    assert result.state in {'ok', 'done'}, result.line()
    receipt = receipts.read_receipt(result.receipt)
    assert receipt is not None
    output = Path(receipt['target'])
    assert {p.name for p in output.iterdir()} == {'grid.tif', 'support.tif', 'sidecar.json'}
    sidecar = json.loads((output / 'sidecar.json').read_text())
    assert sidecar['original_sha256'] == receipts.sha256_file(original)
    assert sidecar['value_convention'] == 'elevation_positive_up'
    row = dict(id='fixture', path=str(output / 'grid.tif'), sha256=sidecar['outputs']['grid.tif'],
               resolution_m=sidecar['resolution_m'], vertical_datum=sidecar['vertical_datum'],
               units=sidecar['units'], value_convention=sidecar['value_convention'], vertical_offset_m=0,
               citation='fixture', rights='synthetic', attribution='fixture', offset_note='no datum conversion')
    manifest = tmp_path / 'sources.json'
    manifest.write_text(json.dumps(dict(schema_version=1, sources=[row])))
    assert load_sources(manifest)[0]['sha256'] == row['sha256']
    with rasterio.open(output / 'grid.tif') as elevation, rasterio.open(output / 'support.tif') as support:
        assert elevation.dtypes == ('float32',) and support.dtypes == ('uint8',)
        assert (elevation.transform, elevation.crs, elevation.shape) == (support.transform, support.crs, support.shape)
        assert list(elevation.transform)[:6] == sidecar['transform']
        assert elevation.tags(ns='IMAGE_STRUCTURE')['LAYOUT'] == 'COG'
        assert support.tags(ns='IMAGE_STRUCTURE')['LAYOUT'] == 'COG'
        grid = elevation.read(1, masked=True)
        classes = support.read(1)
        np.testing.assert_array_equal(np.ma.getmaskarray(grid), classes == 0)
    return grid, classes, sidecar


def test_csmp_zip_honors_mask_and_sign_without_staging_by_original(tmp_path, capsys):
    # An adjacent extraction would mutate the held directory; ignoring a TIFF mask
    # or the explicit positive-down input would turn holes or depths into elevations.
    raw = tif(tmp_path / 'raw.tif', np.array([[13, 26], [8, -9999]], dtype='float32'),
              nodata=-9999, hole=(0, 1))
    held = tmp_path / 'held'
    held.mkdir()
    archive = package(held / 'Bathymetry_Synthetic.zip', {'data/Bathymetry_Synthetic.tif': raw})
    kwargs = dict(family='csmp', convention='depth_positive_down', datum='MLLW')
    first = normalize_archive(archive, tmp_path / 'norm', **kwargs)
    grid, support, info = mosaic_row(tmp_path, first, archive)
    np.testing.assert_array_equal(grid.compressed(), [-13, -8])
    np.testing.assert_array_equal(support, [[2, 0], [2, 0]])
    assert info['resolution_m'] == 2 and info['vertical_datum'] == 'MLLW'
    assert set(held.iterdir()) == {archive}
    # Running via the real dispatcher must resolve the archive entry point and
    # hit the same validated cache, not the generic regional stage builder.
    assert first.state == 'ok' and first.generation is not None
    assert region_main(['normalize-archives', '--source', str(archive), '--cache', str(tmp_path / 'norm'),
                        '--family', 'csmp', '--convention', 'depth_positive_down', '--datum', 'MLLW']) == 0
    assert f'DONE generation {first.generation[:12]}' in capsys.readouterr().out


@pytest.mark.parametrize('nested', [False, True])
def test_arcinfo_bathymetry_with_real_adf(tmp_path, nested):
    # Treating a gzip archive as a TIFF or choosing the first nested product would
    # lose the original AIG depths. Use the repository's tiny upstream GDAL fixture.
    raw = json.loads((FIXTURES / 'seafloor-arcgrid/abc3x1.json').read_text())['files']
    member = 'ArcViewGrids/fixture_2mbath10' if nested else 'ArcViewGrids/fixture_2mbathy'
    members = {f'{member}/{name}': base64.b64decode(row['base64'])
               for name, row in raw.items()}
    if nested:
        stream = BytesIO()
        bundle = 'fixture_2mbathy_hill_slope.zip'
        with ZipFile(stream, 'w') as zipped:
            for name, data in members.items():
                zipped.writestr(name, data)
                zipped.writestr(name.replace('2mbath10', '2mhill10'), data)
        members = {bundle: stream.getvalue()}
        member = bundle + '/' + member
    archive = tmp_path / 'products.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            output.addfile(info, BytesIO(data))
    if nested:
        # The ZIP's bathymetry label must not admit its sibling hillshade grid.
        hillshade = member.replace('2mbath10', '2mhill10')
        with pytest.raises(ValueError, match='bathymetry'):
            normalize_archive(archive, tmp_path / 'norm', family='csmp', member=hillshade)
    result = normalize_archive(archive, tmp_path / 'norm', family='csmp', member=member)
    grid, support, info = mosaic_row(tmp_path, result, archive)
    assert grid.shape == (1, 3) and info['resolution_m'] == 1
    np.testing.assert_array_equal(np.sort(grid.compressed()), [0, 1, 2])
    np.testing.assert_array_equal(support, [[2, 2, 2]])


def test_cinms_zip_allows_explicit_island_tiers_without_collapsing_cache(tmp_path):
    # Native spacing and identity come from the selected member; an archive-wide
    # cache key would replay 2 m pixels for the 8 m tier.
    northern = 'CINMS_bathy_merge_2024/CINMS_Northern_2mXY_0_40mWD.tif'
    sbi = 'CINMS_bathy_merge_2024/CINMS_SBI_8mXY_72_160mWD.tif'
    archive = package(tmp_path / 'CINMS_bathy_merge_2024.zip', {
        northern: tif(tmp_path / 'two.tif', np.full((2, 2), -11, dtype='float32'), cell=2),
        sbi: tif(tmp_path / 'eight.tif', np.full((2, 2), -81, dtype='float32'), cell=8),
    })
    norm = tmp_path / 'norm'
    with pytest.raises(ValueError, match='exact'):
        normalize_archive(archive, norm, family='cinms')
    for member, depth, spacing in [(northern, -11, 2), (sbi, -81, 8)]:
        result = normalize_archive(archive, norm, family='cinms', member=member)
        grid, support, info = mosaic_row(tmp_path, result, archive)
        assert info['resolution_m'] == spacing and info['params']['archive_member'] == member
        assert info['vertical_datum'] == 'unstated'
        np.testing.assert_array_equal(grid.compressed(), [depth] * 4)
        np.testing.assert_array_equal(support, np.ones((2, 2), dtype='uint8'))


@pytest.mark.parametrize('name,description', [
    ('Backscatter.tif', None), ('Hillshade.tif', None), ('Bathymetry.tif', 'Shaded relief intensity'),
])
def test_refuse_ancillary_csmp_products_even_if_one_band(tmp_path, name, description):
    # A perfectly valid one-band GeoTIFF does not make image intensity bathymetry.
    raw = tif(tmp_path / 'raw.tif', np.zeros((3, 3), dtype='uint8'), description=description)
    archive = package(tmp_path / 'Bathymetry_bundle.zip', {name: raw})
    if description is None:
        with pytest.raises(ValueError, match='only bathymetry'):
            normalize_archive(archive, tmp_path / 'norm', family='csmp', member=name)
    else:
        result = normalize_archive(archive, tmp_path / 'norm', family='csmp', member=name)
        assert result.state == 'failed' and 'ancillary' in result.reason


def index_pair(path, elevation, count):
    path.write_text(json.dumps(dict(schema_version=1, files=[dict(
        id='fixture', status='gridded', path=str(elevation), count_path=count.name,
        sha256=receipts.sha256_file(elevation), count_sha256=receipts.sha256_file(count),
        classes=[2, 40], vertical_datum='NAVD88', source_qualified=False,
    )])))
    return path


def test_indexed_lidar_count_is_a_mask_not_certification(tmp_path):
    # Valid elevation with zero count must disappear; positive counts (even lots
    # of returns) cannot certify a cell. Rebound evidence must not hit stale cache.
    # Real index elevation TIFFs contain mean/min/max in a compound CRS.
    values = np.array([[-11, -22], [2, -44]], dtype='float64')
    crs = 'EPSG:6339+5703'
    elevation = tif(tmp_path / 'fixture.elevation.tif', np.stack((values, values-1, values+1)),
                    hole=(1, 0), crs=crs, raster_role='elevation', value_convention='elevation-m-positive-up')
    count = tmp_path / 'fixture.elevation.count.tif'
    index = tmp_path / 'lidar-grid-index.json'
    cache = tmp_path / 'norm'
    opts = dict(family='lidar-grid', lidar_id='fixture')
    tif(count, np.array([[1, 0], [7, 144]], dtype='uint32'), crs=crs, raster_role='count', nodata=0)
    index_pair(index, elevation, count)
    first = normalize_archive(index, cache, **opts)
    grid, support, info = mosaic_row(tmp_path, first, elevation)
    np.testing.assert_array_equal(grid.compressed(), [-11, -44])
    np.testing.assert_array_equal(support, [[2, 0], [0, 2]])
    assert info['params']['lidar']['classes'] == [2, 40]
    assert info['vertical_datum'] == 'NAVD88'
    assert [row['role'] for row in info['ignored_bands']] == ['contributor_min', 'contributor_max']
    assert info['params']['count_sha256'] == receipts.sha256_file(count)
    tif(count, np.array([[0, 1], [7, 144]], dtype='uint32'), crs=crs, raster_role='count', nodata=0)
    with pytest.raises(ValueError, match='checksum'):
        normalize_archive(index, cache, **opts)
    index_pair(index, elevation, count)
    second = normalize_archive(index, cache, **opts)
    assert second.generation != first.generation
    grid, support, _ = mosaic_row(tmp_path, second, elevation)
    np.testing.assert_array_equal(grid.compressed(), [-22, -44])
    np.testing.assert_array_equal(support, [[0, 2], [0, 2]])


def test_lidar_refuses_count_only_and_unaligned_pairs(tmp_path):
    # Valid TIFF dimensions are not registration; a one-pixel shift must not
    # erase neighboring terrain. A standalone TIFF has no also-pinned elevation.
    count = tif(tmp_path / 'fixture.count.tif', np.ones((2, 2), dtype='uint32'), x=685002)
    cache = tmp_path / 'norm'
    opts = dict(family='lidar-grid', lidar_id='fixture')
    with pytest.raises(ValueError, match='standalone/count'):
        normalize_archive(count, cache, **opts)
    elevation = tif(tmp_path / 'fixture.elevation.tif', -np.ones((2, 2), dtype='float32'))
    index = index_pair(tmp_path / 'lidar-grid-index.json', elevation, count)
    result = normalize_archive(index, cache, **opts)
    assert result.state == 'failed' and 'aligned' in result.reason
