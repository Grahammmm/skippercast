"""Audit repro (2026-10-22): terrain-only depth bands lose one band.

`render.terrain_only.render_terrain` quantizes the colour ramp with
``floor(t*(N-1))/(N-1)``. For every t < 1 that yields only N-1 distinct
levels, so ``depth_bands=2`` paints all in-range depths one colour and N bands
put every band edge at k/(N-1) of the range instead of k/N. The test asserts
the correct behaviour (two bands show two colours) and fails on current main.
"""
import json

import numpy as np
import pytest

pytestmark = pytest.mark.gis

rasterio = pytest.importorskip('rasterio')
from rasterio.transform import from_origin  # noqa: E402

from skippercast.coastal import vertical  # noqa: E402
from skippercast.coastal.handoff.common import ref  # noqa: E402
from skippercast.coastal.render import terrain_only  # noqa: E402

SRC = 'a' * 64
BACKGROUND = (238, 243, 246)


def normalized_terrain(root, depth, valid, transform=None, crs='EPSG:26911'):
    """Write a derived terrain/mask pair exactly as derived_batch stores them."""
    transform = transform or from_origin(1000, 2000, 2, 2)
    raw = dict(sign='positive_up', units='m', datum='MLLW', datum_realization='unknown',
               scale=1., offset=0., scale_offset_applied=False)
    block = dict(schema='vertical-v1', **raw, conflicts=[], evidence=[dict(
        kind='raster_header', source_sha256=SRC, header_sha256='b' * 64, facts=raw)])
    norm = vertical.normalized(block)
    h, w = depth.shape
    common = dict(driver='GTiff', width=w, height=h, count=1, crs=crs, transform=transform)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        with rasterio.open(root / 'terrain.tif', 'w', dtype='float32', nodata=np.nan, **common) as ds:
            ds.write(np.where(valid, depth, np.nan).astype('float32'), 1)
            ds.write_mask(valid.astype('uint8') * 255)
            ds.set_band_unit(1, 'm')
            ds.set_band_description(1, 'depth_m_positive_down')
            ds.update_tags(vertical_contract=json.dumps(norm, sort_keys=True), vertical_sign='positive_down',
                           vertical_datum='MLLW', datum_realization='unknown', scale_offset_applied='true',
                           publication_prohibited='true', source_sha256=SRC)
        with rasterio.open(root / 'mask.tif', 'w', dtype='uint8', nodata=None, **common) as ds:
            ds.write(valid.astype('uint8'), 1)
    return dict(schema=terrain_only.INPUT, creator_id='synthetic', segment_id='synthetic',
                terrain=ref(root, root / 'terrain.tif', 'coastal-normalized-terrain-v1'),
                mask=ref(root, root / 'mask.tif', 'coastal-native-support-v2'),
                vertical=norm, crs=crs, affine=list(transform),
                provenance=dict(source_sha256s=[SRC], upstream_receipt_sha256='c' * 64),
                uncertainty_kind='unavailable', limitations=['Synthetic.'], synthetic=True)


def terrain_colours(pixels):
    # Terrain occupies rows 60..340; legend rows sit outside that band.
    band = pixels[60:341].reshape(-1, 3)
    return {tuple(int(v) for v in p) for p in band} - {BACKGROUND}


def test_two_depth_bands_show_two_colours(tmp_path):
    # A single plane (constant shading) from 10 m to 30 m deep, locked range 9-31 m.
    _, xx = np.indices((12, 40))
    depth = 10 + 20 * xx / 39.0
    document = normalized_terrain(tmp_path, depth, np.ones(depth.shape, bool))
    mesh = terrain_only.build_terrain(tmp_path, document)
    style = terrain_only.style_controls(dict(depth_bands=2, color_range='locked',
        locked_depth_range_m=[9.0, 31.0], contour_interval_m=1000.0, no_data_overlay=False))
    rendered, pixels = terrain_only.render_terrain(mesh, None, style)
    assert rendered['outlier_pixels'] == dict(below=0, above=0)
    colours = terrain_colours(pixels)
    assert len(colours) == 2, (
        f'depth_bands=2 over 10-30 m painted {len(colours)} terrain colour(s); '
        'shallow and deep halves are indistinguishable')


import os as _audit_os  # noqa: E402

import pytest as _audit_pytest  # noqa: E402

pytestmark = [pytest.mark.gis, _audit_pytest.mark.skipif(
    _audit_os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1",
    reason="audit repro (fails on purpose): set SKIPPERCAST_AUDIT_CLOUD=1",
)]
