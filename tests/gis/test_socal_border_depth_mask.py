"""Synthetic proof at the border clip → raster mask → depth coverage seam."""

import numpy as np
import pytest
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from shapely.geometry import Polygon, box, mapping

from skippercast.relief.border import clip_to_us
from skippercast.relief.depth_coverage import depth_coverage


@pytest.mark.parametrize(
    'clip, deep_area_m2, deepest_m',
    [
        # Ignoring the clip would add the outside cell; masking everything
        # would incorrectly discard the two shallow cells on the retained side.
        pytest.param(True, 0, 10, id='clipped-retains-shallows-excludes-deep-cell'),
        # Deliberately bypass the clip: a misplaced or nodata deep cell would
        # make the exclusion above vacuous. Here it must count and set the max.
        pytest.param(False, 10_000, 60, id='unclipped-recovers-deep-cell'),
    ],
)
def test_border_mask_limits_depth_denominator(clip, deep_area_m2, deepest_m):
    # Invented EPSG:3310 geometry, not a model of the actual border. The
    # sloping edge crosses the row at x=190–210 m, between centres 150 and 250.
    water = box(-50, -50, 350, 150)
    boundary = Polygon([(-100, -100), (170, -100), (230, 200), (-100, 200)])
    water_wgs84, boundary_wgs84 = (
        Polygon(transform_geom('EPSG:3310', 'EPSG:4326', mapping(geom))['coordinates'][0])
        for geom in (water, boundary)
    )
    if clip:
        water_wgs84, _ = clip_to_us(water_wgs84, boundary_wgs84)

    elevation = np.array([[-5, -10, -60]], dtype='float32')
    support = np.full(elevation.shape, 3, dtype='uint8')
    # Same projected, centre-based rasterization as _read_report.
    mask = geometry_mask(
        [transform_geom('EPSG:4326', 'EPSG:3310', mapping(water_wgs84))],
        out_shape=elevation.shape, transform=from_origin(0, 100, 100, 100), invert=True,
    )
    result = depth_coverage(elevation, support, mask, cell_area_m2=10_000)

    assert sum(result['bands']['0-66ft'].values()) == 20_000
    assert sum(result['bands']['66-300ft'].values()) == deep_area_m2
    assert result['deepest_m'] == deepest_m
