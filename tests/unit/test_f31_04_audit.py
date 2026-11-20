"""F31-04: generalized context must not report native substrate area."""

import hashlib
import json
import zipfile

import pytest

from research.scripts.import_usgs_seafloor_character import compile_context


@pytest.mark.gis
def test_mode_resampled_polygon_reports_only_display_area(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    # Three 10 m hard cells (300 m²) win a single 20 m display cell (400 m²).
    # The old writer labeled the whole display footprint as source area.
    tif = tmp_path / 'synthetic.tif'
    with rasterio.open(tif, 'w', driver='GTiff', width=2, height=2, count=1,
                       dtype='uint8', crs='EPSG:32631',
                       transform=from_origin(500000, 100, 10, 10)) as raster:
        raster.write(np.array([[3, 3], [3, 1]], dtype='uint8'), 1)
    archive = tmp_path / 'synthetic.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.write(tif, tif.name)
    output = tmp_path / 'context.geojson'
    source = {
        'id': 'synthetic', 'sector_id': 'synthetic', 'class': 3, 'class_name': 'Hard',
        'data_release_url': 'https://example.invalid/synthetic', 'source_year': 2000,
        'character_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'native_class_resolution_m': 10, 'display_resolution_m': 20,
        'minimum_display_area_m2': 1, 'rights': 'Synthetic', 'limitations': 'Context only',
    }
    assert compile_context(source, archive, output) == 1
    layer = json.loads(output.read_text())
    feature, = layer['features']
    props = feature['properties']
    assert feature['geometry']['type'] == 'Polygon'
    assert 'source_area_m2' not in props
    assert props['display_area_m2'] == 400
    assert 'native_area_m2' not in props
    assert layer['schema_version'] == 2
