"""An explicit raster sign convention takes precedence over its vertical CRS."""
from unittest.mock import Mock

import numpy as np
import pytest
import rasterio
from pyproj import CRS
from rasterio.transform import from_origin

from skippercast.relief import normalize as norm
from tests.gis.test_relief_normalize import result_files, tif, values

pytestmark = pytest.mark.gis

# UTM zone 10N + mean sea level depth (positive-down, metres).
DEPTH_CRS = 'EPSG:26910+5715'


@pytest.mark.parametrize('tags,override,expected_convention,expected_cell', [
    pytest.param({'positive': 'UP'}, None, norm.VALUE_UP, -3, id='positive-up-beats-axis'),
    pytest.param({}, None, norm.VALUE_DOWN, 3, id='untagged-uses-axis'),
    pytest.param({'positive': 'up', 'value_convention': norm.VALUE_DOWN}, None,
                 norm.VALUE_DOWN, 3, id='value-convention-tag-beats-positive'),
    pytest.param({'positive': 'up', 'value_convention': norm.VALUE_UP}, norm.VALUE_DOWN,
                 norm.VALUE_DOWN, 3, id='caller-beats-tags'),
])
def test_normalize_declared_positive(tmp_path, tags, override, expected_convention, expected_cell):
    src = tif(tmp_path / 'depth-axis.tif', np.full((2, 2), -3, dtype='float32'),
              from_origin(680000, 3930000, 2, 2), DEPTH_CRS, **tags)
    # Check the CRS survived the GeoTIFF round trip; otherwise the old default
    # could preserve the sign for the wrong reason (no vertical axis).
    with rasterio.open(src) as ds:
        crs = CRS.from_user_input(ds.crs)
        assert crs.is_compound and crs.sub_crs_list[1].axis_info[0].direction == 'down'
    target, sidecar = result_files(norm.normalize(src, tmp_path / 'cache', convention=override))
    assert values(target / 'grid.tif')[0, 0] == expected_cell
    assert sidecar['source_value_convention'] == expected_convention


def test_bag_ignores_positive_tag_and_depth_axis():
    # BAG elevation is positive-up by format. An inference shared with TIFFs
    # would incorrectly flip it when either the tag or the vertical CRS is down.
    bag = Mock(driver='BAG', units=(None,))
    bag.tags.side_effect = [{'positive': 'down'}, {}]
    meta = norm.semantics(bag, CRS.from_user_input(DEPTH_CRS), convention=None)
    assert meta['source_value_convention'] == norm.VALUE_UP
