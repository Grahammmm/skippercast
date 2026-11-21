"""Synthetic raster orientation checks at the nearshore render boundary."""
import pytest

from skippercast.relief import tiles

pytestmark = pytest.mark.gis


class _ReachedShading(Exception):
    """Stop the test exactly where shading would start."""


@pytest.mark.parametrize(
    ('column_step', 'row_step', 'expected_error'),
    [
        pytest.param(10, 10, ValueError, id='south-up'),
        pytest.param(-10, -10, ValueError, id='west-up'),
        pytest.param(10, -10, _ReachedShading, id='north-up'),
    ],
)
def test_nearshore_grid_orientation(tmp_path, monkeypatch, column_step, row_step, expected_error):
    # Both flips have the same unsigned cell size as the north-up control;
    # checking resolution alone lets them reach directional shading.
    np = pytest.importorskip('numpy')
    rio = pytest.importorskip('rasterio')
    source = tmp_path / 'mosaic.tif'
    transform = rio.Affine(column_step, 0, 100, 0, row_step, 200)
    with rio.open(source, 'w', driver='GTiff', width=3, height=3, count=1,
                  dtype='float32', crs='EPSG:3310', transform=transform) as ds:
        ds.write(np.full((3, 3), -10, dtype='float32'), 1)

    def stop_at_shading(*args, **kwargs):
        raise _ReachedShading

    monkeypatch.setattr(tiles, '_bake', stop_at_shading)
    out = tmp_path / 'tiles'
    out.mkdir()
    match = 'north-up square cells' if expected_error is ValueError else None
    with pytest.raises(expected_error, match=match):
        tiles._render(source, None, [], (-121, 37, -119, 39), out, 'synthetic', None)
    assert not list(out.iterdir())  # In particular, no PMTiles archive or coverage sidecar.
