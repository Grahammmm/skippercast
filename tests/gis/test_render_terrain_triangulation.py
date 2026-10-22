"""Audit repro (2026-10-22): fixed-diagonal triangulation hides supported soundings.

`render.terrain_only.build_terrain` (and `render.mesh.build_mesh`, whose faces
`terrain_demo.payload` re-derives) splits every 2x2 quad along one fixed
diagonal and keeps a triangle only if all three of its corners are supported.
When exactly three corners are supported and the missing one is the
lower-left corner, both fixed triangles are dropped even though the other
diagonal's triangle is fully supported. The top-left sample then belongs to no
face and never reaches the preview, so a supported shoal sounding vanishes
while receipts still count it as supported. Fails on current main.
"""
import numpy as np
import pytest

pytestmark = pytest.mark.gis

import json  # noqa: E402,I001

rasterio = pytest.importorskip('rasterio')
from rasterio.transform import from_origin  # noqa: E402

from skippercast.coastal import vertical  # noqa: E402
from skippercast.coastal.handoff.common import ref  # noqa: E402
from skippercast.coastal.render import terrain_only  # noqa: E402

SRC = 'a' * 64


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


def shoal_fixture(tmp_path):
    depth = np.full((4, 4), 20.0)
    depth[0, 0] = 2.0                      # supported 2 m shoal sounding
    valid = np.ones(depth.shape, bool)
    valid[1, 0] = False                    # one missing neighbour (lower-left of the quad)
    mesh = terrain_only.build_terrain(tmp_path, normalized_terrain(tmp_path, depth, valid))
    return mesh


def test_three_supported_corners_keep_their_triangle(tmp_path):
    mesh = shoal_fixture(tmp_path)
    shoal = int(np.flatnonzero((mesh['grid_pixels'] == [0, 0]).all(axis=1))[0])
    assert mesh['support'][0, 0] and mesh['support'][0, 1] and mesh['support'][1, 1]
    assert (mesh['faces'] == shoal).any(), (
        'supported sample (0,0) with supported neighbours (0,1),(1,1) is in no triangle; '
        'the 2 m shoal is dropped from the mesh')


def test_supported_shoal_is_visible_in_preview(tmp_path):
    mesh = shoal_fixture(tmp_path)
    style = terrain_only.style_controls(dict(color_range='locked', locked_depth_range_m=[5.0, 25.0]))
    rendered, _ = terrain_only.render_terrain(mesh, None, style)
    assert rendered['outlier_pixels']['below'] > 0, (
        'preview shows no depth shallower than 5 m although a supported 2 m sounding exists')
