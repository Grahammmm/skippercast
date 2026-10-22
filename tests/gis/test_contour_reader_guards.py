"""Single-fault controls for the contour reader; invented grids only."""
import numpy as np
import pytest
import rasterio

from skippercast.platform import depth_contours as dc
from .coast_adversarial_synth import load_script, write_tif

bdc = load_script('build_depth_contours')


def grid(tmp_path, **kwargs):
    return write_tif(tmp_path / 'grid.tif', np.full((16, 16), -20, 'float32'), **kwargs)


@pytest.mark.parametrize('metadata', [
    {'units': 'ft'}, {'units': 'furlong'}, {'tags': {'z_units': 'feet'}},
    {'tags': {'z_units': 'unknown'}}, {'tags': {'positive': 'down'}},
    {'tags': {'vertical_sign': 'unknown'}}, {'tags': {'z_positive': 'positive_down'}},
])
def test_explicit_incompatible_units_or_sign_refused(tmp_path, metadata):
    path = grid(tmp_path, **metadata)
    with pytest.raises(ValueError, match='vertical units|positive-up'):
        bdc.merged_blocks([path], bdc.lattice_for([path]))


@pytest.mark.parametrize('key,value', [('z_units', 'ft'), ('vertical_sign', 'down'),
                                      ('z_positive', 'unknown'), ('positive', 'positive_down')])
def test_band_level_metadata_is_not_ignored(tmp_path, key, value):
    path = grid(tmp_path)
    with rasterio.open(path, 'r+') as dst:
        dst.update_tags(1, **{key: value})
    with pytest.raises(ValueError, match='vertical units|positive-up'):
        bdc.merged_blocks([path], bdc.lattice_for([path]))


@pytest.mark.parametrize('metadata', [
    {}, {'units': 'm'}, {'units': 'metre', 'tags': {'z_units': 'meters', 'positive': 'up'}},
    {'tags': {'vertical_sign': 'positive_up', 'z_positive': 'up'}},
])
def test_legacy_or_explicit_metre_elevation_positive_control(tmp_path, metadata):
    path = grid(tmp_path, **metadata)
    depth, owner, _ = bdc.merged_blocks([path], bdc.lattice_for([path]))
    assert np.allclose(depth, 20 * dc.FEET_PER_M)
    assert (owner == 0).all()


@pytest.mark.parametrize('metadata', [
    {'units': 'm', 'tags': {'z_units': 'ft'}},
    {'tags': {'positive': 'up', 'vertical_sign': 'down'}},
])
def test_contradictory_metadata_is_refused(tmp_path, metadata):
    path = grid(tmp_path, **metadata)
    with pytest.raises(ValueError, match='conflicting vertical metadata'):
        bdc.merged_blocks([path], bdc.lattice_for([path]))


def test_dataset_and_band_conflict_is_refused(tmp_path):
    path = grid(tmp_path, tags={'positive': 'up'})
    with rasterio.open(path, 'r+') as dst:
        dst.update_tags(1, positive='down')
    with pytest.raises(ValueError, match='conflicting vertical metadata'):
        bdc.merged_blocks([path], bdc.lattice_for([path]))


@pytest.mark.parametrize('vertical_crs,reason', [
    ('EPSG:6360', 'vertical_crs_unit_unsupported'), ('EPSG:5715', 'positive-up')])
def test_vertical_crs_units_or_down_axis_refused(tmp_path, vertical_crs, reason):
    from pyproj import CRS
    from pyproj.crs import CompoundCRS
    crs = CompoundCRS('synthetic compound', [CRS.from_epsg(32610), CRS(vertical_crs)])
    path = grid(tmp_path, crs=crs)
    with rasterio.open(path) as dataset:
        # Test the vertical guard independently of the horizontal CRS guard.
        with pytest.raises(ValueError, match=reason):
            bdc.require_contour_vertical(dataset)


def test_guard_runs_before_any_pixel_read(tmp_path, monkeypatch):
    path = grid(tmp_path, units='ft')
    class HeaderOnly:
        def __init__(self, wrapped):
            self.wrapped = wrapped
        def __getattr__(self, name):
            return getattr(self.wrapped, name)
        def read(self, *args, **kwargs):
            pytest.fail('incompatible metadata must fail before reading pixels')
    actual_open = rasterio.open
    monkeypatch.setattr(bdc.rasterio, 'open', lambda p: HeaderOnly(actual_open(p)))
    with pytest.raises(ValueError, match='vertical units'):
        bdc.merged_blocks([path], (500000, 4000000, 2, 2))


@pytest.mark.parametrize('metadata', [
    {'scale': .01}, {'scale': -1}, {'scale': 0}, {'offset': 10},
    {'scale': float('nan')}, {'scale': float('inf')}, {'offset': float('nan')},
    {'offset': float('inf')},
    {'scale': .01, 'tags': {'scale_offset_applied': 'true'}},
])
def test_packing_is_refused_instead_of_guessed(tmp_path, metadata):
    path = grid(tmp_path, **metadata)
    with pytest.raises(ValueError, match='unpacked samples'):
        bdc.merged_blocks([path], bdc.lattice_for([path]))


def test_malformed_packing_tag_refused(tmp_path):
    path = grid(tmp_path, tags={'scale_offset_applied': 'maybe'})
    with pytest.raises(ValueError, match='unsupported scale_offset_applied'):
        bdc.merged_blocks([path], bdc.lattice_for([path]))


@pytest.mark.parametrize('applied', ['true', 'false'])
def test_identity_packing_is_unambiguous(tmp_path, applied):
    path = grid(tmp_path, scale=1, offset=0, tags={'scale_offset_applied': applied})
    depth, _, _ = bdc.merged_blocks([path], bdc.lattice_for([path]))
    assert np.allclose(depth, 20 * dc.FEET_PER_M)


def test_int16_nodata_only_invalidates_its_own_block(tmp_path):
    values = np.full((16, 16), -20, 'int16')
    values[2, 3] = -32768
    path = write_tif(tmp_path / 'masked.tif', values, nodata=-32768)
    depth, owner, _ = bdc.merged_blocks([path], bdc.lattice_for([path]))
    assert np.isnan(depth[0, 0]) and owner[0, 0] == -1
    assert np.allclose(depth[[0, 1, 1], [1, 0, 1]], 20 * dc.FEET_PER_M)
    assert (owner[[0, 1, 1], [1, 0, 1]] == 0).all()
