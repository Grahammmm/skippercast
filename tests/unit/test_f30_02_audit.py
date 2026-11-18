"""Synthetic C2 controls for contour interpolation across survey seams (F30-02)."""

import json

import pytest

pytestmark = pytest.mark.gis


@pytest.fixture
def preview(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    from research.scripts.coast_mvp.coast_contours import build

    # A small invented metric grid, not a survey or a recorded location.
    affine = from_origin(100, 500, 10, 10)

    def run(values, codes, **metadata):
        sources = [dict(code=1, id='synthetic-west', resolution_m=10),
                   dict(code=2, id='synthetic-east', resolution_m=20)]
        manifest = tmp_path / 'sources.json'
        manifest.write_text(json.dumps(dict(sources=sources, **metadata)))
        for name, cells, nodata in [('elevation', values, -999999), ('contributor', codes, 0)]:
            with rasterio.open(tmp_path / f'{name}.tif', 'w', driver='GTiff',
                               width=cells.shape[1], height=cells.shape[0], count=1,
                               crs='EPSG:3857', transform=affine, dtype=cells.dtype,
                               nodata=nodata) as raster:
                raster.write(cells, 1)
        out = tmp_path / 'preview'
        build(tmp_path / 'elevation.tif', tmp_path / 'contributor.tif', manifest, out, zoom=15)
        return json.loads((out / 'contours.geojson').read_text())['features']

    return run, affine


@pytest.mark.parametrize('feather_m', [0, 40], ids=['hard-seam', 'display-feather'])
def test_flat_surveys_do_not_create_intermediate_contours(preview, feather_m):
    import numpy as np

    from research.scripts.coast_mvp.coast_mosaic import seam_feather

    run, _ = preview
    _, cols = np.indices((32, 48))
    codes = np.where(cols < 24, 1, 2).astype('uint16')
    values = np.where(codes == 1, -4, -15).astype('float32')
    changed_cells = 0
    if feather_m:
        values, changed = seam_feather(values, codes, feather_m=feather_m)
        changed_cells = int(changed.sum())
        assert changed_cells > 0
    with pytest.raises(ValueError, match='^No supported contour lines generated$'):
        features = run(values, codes, seam_feather=dict(feather_m=feather_m,
                                                        changed_cells=changed_cells))
        pytest.fail(f'Invented contours (source, feet): '
                    f'{sorted((f["properties"]["source_code"], f["properties"]["depth_ft"]) for f in features)}')


@pytest.mark.parametrize('adjacent_feathered_source', [False, True], ids=['one-survey', 'with-display-feather'])
def test_real_gradient_keeps_depths_and_labels_without_filling_hole(preview, adjacent_feathered_source):
    import numpy as np
    from pyproj import Transformer
    import shapely
    from shapely.geometry import box, shape

    from research.scripts.coast_mvp.coast_mosaic import seam_feather

    run, affine = preview
    _, cols = np.indices((32, 48 if adjacent_feathered_source else 32))
    values = (-4 - cols * 0.5).astype('float32')
    codes = np.ones(values.shape, dtype='uint16')
    # The stored gradient still exists inside this hole but has no contributor.
    codes[10:22, 8:14] = 0
    hole = box(*(affine * (8, 22)), *(affine * (14, 10)))
    expected = {20, 30, 40, 50, 60}
    metadata = {}
    if adjacent_feathered_source:
        codes[:, 32:] = 2
        values[:, 32:] = -25
        values, changed = seam_feather(values, codes, feather_m=40)
        metadata['seam_feather'] = dict(feather_m=40, changed_cells=int(changed.sum()))
        expected.remove(60)  # Its interpolation nodes would enter the display blend.
    features = run(values, codes, **metadata)
    assert {f['properties']['depth_ft'] for f in features} == expected
    project = Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True)
    thirty = []
    for feature in features:
        props = feature['properties']
        assert (props['source_code'], props['source_id'], props['source_resolution_m']) == (
            1, 'synthetic-west', 10)
        line = shapely.transform(shape(feature['geometry']), project.transform, interleaved=False)
        assert line.is_valid and line.is_simple
        assert not line.intersects(hole.buffer(-0.001))
        expected_x, _ = affine * (0.5 + (props['depth_ft'] * 0.3048 - 4) / 0.5, 0)
        assert all(abs(x - expected_x) < 0.001 for x, _ in line.coords)
        if props['depth_ft'] == 30:
            thirty.append(line)
    assert len(thirty) == 2  # 30 ft runs through the hole and must stop on both sides.
    assert all(line.distance(hole) < 0.001 for line in thirty)
