"""Audit repro (2026-10-22): terrain-only preview drops the deep-datum not-for-navigation label.

`coastal.vertical` admits EGM2008, instantaneous-sea-level and unstated datums
only in lanes M/D, and every such block carries a fixed ``deep_datum`` record
with ``navigation: not-for-navigation`` and a note such as "tides are not
removed". `render.terrain_only.build_terrain` accepts that normalized terrain,
but `render_terrain` draws only "NOMINAL DATUM <name>" and
`preview` adds no deep-datum limitation, so the PNG legend and receipt
limitations drop the navigation warning. (`render.mesh.build_mesh` refuses
these datums.) Fails on current main.
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
DATUM = 'instantaneous-sea-level'


def deep_terrain(root, depth):
    transform = from_origin(1000, 2000, 2, 2)
    raw = dict(sign='positive_up', units='m', datum=DATUM, datum_realization='unknown',
               scale=1., offset=0., scale_offset_applied=False)
    block = dict(schema='vertical-v1', **raw, depth_lane='M',
                 deep_datum=vertical.deep_datum_record(DATUM, 'M'), conflicts=[],
                 evidence=[dict(kind='raster_header', source_sha256=SRC, header_sha256='b' * 64, facts=raw)])
    assert vertical.validate(block) == []
    norm = vertical.normalized(block)
    assert norm['deep_datum']['navigation'] == 'not-for-navigation'
    h, w = depth.shape
    common = dict(driver='GTiff', width=w, height=h, count=1, crs='EPSG:26911', transform=transform)
    valid = np.ones(depth.shape, bool)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        with rasterio.open(root / 'terrain.tif', 'w', dtype='float32', nodata=np.nan, **common) as ds:
            ds.write(depth.astype('float32'), 1)
            ds.write_mask(valid.astype('uint8') * 255)
            ds.set_band_unit(1, 'm')
            ds.set_band_description(1, 'depth_m_positive_down')
            ds.update_tags(vertical_contract=json.dumps(norm, sort_keys=True), vertical_sign='positive_down',
                           vertical_datum=DATUM, datum_realization='unknown', scale_offset_applied='true',
                           publication_prohibited='true', source_sha256=SRC)
        with rasterio.open(root / 'mask.tif', 'w', dtype='uint8', nodata=None, **common) as ds:
            ds.write(valid.astype('uint8'), 1)
    return dict(schema=terrain_only.INPUT, creator_id='synthetic', segment_id='synthetic',
                terrain=ref(root, root / 'terrain.tif', 'coastal-normalized-terrain-v1'),
                mask=ref(root, root / 'mask.tif', 'coastal-native-support-v2'),
                vertical=norm, crs='EPSG:26911', affine=list(transform),
                provenance=dict(source_sha256s=[SRC], upstream_receipt_sha256='c' * 64),
                uncertainty_kind='unavailable', limitations=['Synthetic.'], synthetic=True)


def test_deep_datum_preview_legend_says_not_for_navigation(tmp_path):
    _, xx = np.indices((8, 8))
    depth = 120.0 + xx                      # lane M depths (> 91.44 m)
    mesh = terrain_only.build_terrain(tmp_path, deep_terrain(tmp_path, depth))
    assert mesh['vertical']['deep_datum']['navigation'] == 'not-for-navigation'
    rendered, _ = terrain_only.render_terrain(mesh, None, terrain_only.style_controls())
    legend = ' | '.join(item['text'].upper() for item in rendered['image_legends'])
    assert 'NOT FOR NAVIGATION' in legend, (
        'deep-datum (instantaneous sea level, tides not removed) preview legend omits '
        'NOT FOR NAVIGATION: ' + legend)


import os as _audit_os  # noqa: E402

import pytest as _audit_pytest  # noqa: E402

pytestmark = [pytest.mark.gis, _audit_pytest.mark.skipif(
    _audit_os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1",
    reason="audit repro (fails on purpose): set SKIPPERCAST_AUDIT_CLOUD=1",
)]
