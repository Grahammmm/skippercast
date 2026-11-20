"""Validate producer-side mosaic attribution on synthetic DL-5 inputs."""
import re
from types import SimpleNamespace

import pytest
import rasterio

from skippercast.relief import receipts, terrain
from tests.gis.test_relief_terrain import fixture, write_json


@pytest.fixture
def mosaic(tmp_path):
    region = fixture(tmp_path / 'out', native=False)
    upstream = receipts.read_receipt(region.receipt_path('mosaic', 'public'))
    return SimpleNamespace(region=region, upstream={'mosaic.public': upstream})


@pytest.mark.parametrize(('code', 'reason'), [
    (1, 'duplicate mosaic contributor code 1'),
    (0, 'reserved for nodata'),
    (-1, 'expected an integer in 1..65534'),
    (65535, 'expected an integer in 1..65534'),
    (65536, 'expected an integer in 1..65534'),
    (True, 'expected an integer in 1..65534'),
    (2.0, 'expected an integer in 1..65534'),
])
def test_invalid_contributor_code_refused_before_grid_write(tmp_path, mosaic, code, reason):
    # The producer must reject malformed rows even when no raster cell uses
    # that row: duplicates overwrite attribution and NumPy accepts negative indices.
    manifest_path = mosaic.region.dir / 'receipted-mosaic/manifest.json'
    manifest = terrain.read_json(manifest_path)
    manifest['sources'].append(dict(manifest['sources'][-1], code=code))
    write_json(manifest_path, manifest)
    out = tmp_path / 'terrain'
    out.mkdir()

    # Invoke the producer directly so receipt hash checking does not preempt the
    # bad-code diagnostic, and stage cleanup cannot hide premature writes.
    with pytest.raises(receipts.ReceiptError, match=re.escape(reason)):
        terrain.build(mosaic, out)
    assert list(out.iterdir()) == []


def test_maximum_mosaic_code_preserves_terrain_output_bytes(tmp_path, mosaic):
    # The mosaic code is not the output source byte. Changing only that code to
    # the writer's upper bound must not lose attribution or turn nodata into a source.
    folder = mosaic.region.dir / 'receipted-mosaic'
    before, after = tmp_path / 'ordinary', tmp_path / 'maximum'
    before.mkdir()
    after.mkdir()
    with rasterio.open(folder / 'contributor.tif', 'r+') as raster:
        raster.nodata = 0
        codes = raster.read(1)
        codes[5, 5] = 0
        raster.write(codes, 1)
    terrain.build(mosaic, before)

    with rasterio.open(folder / 'contributor.tif', 'r+') as raster:
        codes[codes == 300] = 65534
        raster.write(codes, 1)
    manifest_path = folder / 'manifest.json'
    manifest = terrain.read_json(manifest_path)
    manifest['sources'][-1]['code'] = 65534
    write_json(manifest_path, manifest)
    terrain.build(mosaic, after)

    assert {p.name: p.read_bytes() for p in after.iterdir()} == {
        p.name: p.read_bytes() for p in before.iterdir()
    }
