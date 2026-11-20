"""The terrain readback verifies uncertainty, not just the edited artifact hashes."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from research.scripts import check_terrain_acceptance as checker
from skippercast.coastal import vertical
from skippercast.coastal.handoff.common import ref, write
from skippercast.coastal.render import terrain_only

pytestmark = pytest.mark.gis
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CHECK = 'mesh_uncertainty_matches_reviewed_input'


@pytest.fixture
def rendered(tmp_path, measured):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    root = tmp_path
    y, x = np.indices((8, 8))
    support = (y != 3) | (x != 3)
    depth = np.where(support, 20 + x / 8 + y / 4, np.nan).astype('float32')
    transform = from_origin(1000, 2000, 2, 2)  # invented grid, not a surveyed location
    profile = dict(driver='GTiff', height=8, width=8, count=1, crs='EPSG:3857', transform=transform)
    source_sha = 'a' * 64
    with rasterio.open(root / 'terrain.tif', 'w', dtype='float32', nodata=np.nan, **profile) as ds:
        ds.write(depth, 1)
        ds.set_band_unit(1, 'm')
        ds.set_band_description(1, 'depth_m_positive_down')
        ds.update_tags(vertical_sign='positive_down', vertical_datum='MLLW', scale_offset_applied='false')
    with rasterio.open(root / 'terrain.tif') as ds:
        source = vertical.from_raster(ds, source_sha256=source_sha)
    normalized = vertical.normalized(dict(schema='vertical-v1', **source['facts'], conflicts=[],
                                          evidence=[vertical.evidence_from_observation(source)]))
    with rasterio.open(root / 'terrain.tif', 'r+') as ds:
        ds.update_tags(vertical_contract=json.dumps(normalized), source_sha256=source_sha,
                       scale_offset_applied='true')
    with rasterio.open(root / 'support.tif', 'w', dtype='uint8', **profile) as ds:
        ds.write(support.astype('uint8'), 1)
    doc = dict(schema=terrain_only.INPUT, creator_id='synthetic-builder', segment_id='synthetic-only',
               terrain=ref(root, 'terrain.tif', 'coastal-normalized-terrain-v1'),
               mask=ref(root, 'support.tif', 'coastal-native-support-v2'), vertical=normalized,
               crs='EPSG:3857', affine=list(transform), support_kind='derived_valid_sample_support',
               provenance=dict(source_sha256s=[source_sha], upstream_receipt_sha256='b' * 64),
               limitations=['Synthetic control only.'], synthetic=True, source_accessed=False,
               imagery_used=False, internal_diagnostic=True, publication_prohibited=True,
               website='held', habitat='unassessed')
    if measured:
        # A true zero on support and finite nodata off support are distinct.
        with rasterio.open(root / 'uncertainty.tif', 'w', dtype='float32', nodata=-9999, **profile) as ds:
            ds.write(np.where(support, (x + y) / 8, -9999).astype('float32'), 1)
            ds.set_band_unit(1, 'm')
        doc.update(uncertainty=ref(root, 'uncertainty.tif', 'coastal-derived-uncertainty-m-v1'),
                   uncertainty_kind='producer_uncertainty_m')
    write(root / 'science.json', dict(
        schema=terrain_only.REVIEW, scope='internal-terrain-only-scientific-review',
        facts_digest=terrain_only.context(doc), independent=True, reviewer_id='synthetic-science',
        decision='accept', checked_at=NOW.isoformat(), valid_until=(NOW + timedelta(hours=1)).isoformat(),
        holds_added=[], synthetic=True))
    doc['scientific_review'] = ref(root, 'science.json', terrain_only.REVIEW)
    write(root / 'acceptance.json', doc)
    terrain_only.preview(root, doc, output_dir='render', now=NOW)
    return root, np


@pytest.mark.parametrize(('measured', 'edit'), [
    (True, 'matching'), (True, 'zeroed'), (True, 'value'), (True, 'hole'),
    (True, 'missing_sample'), (True, 'shape'),
    (False, 'matching'), (False, 'value'), (False, 'kind'),
])
def test_readback_binds_mesh_uncertainty_to_review(rendered, edit):
    root, np = rendered
    if edit != 'matching':
        mesh = root / 'render/terrain-mesh.npz'
        with np.load(mesh, allow_pickle=False) as data:
            arrays = dict(data)
        values = arrays['uncertainty_m']
        if edit == 'zeroed':
            values.fill(0.0)
        elif edit == 'value':
            values[0, 1] = 0.0
        elif edit == 'hole':
            values[3, 3] = 0.0
        elif edit == 'missing_sample':
            values[0, 1] = np.nan
        elif edit == 'shape':
            arrays['uncertainty_m'] = values.ravel()
        elif edit == 'kind':
            arrays['uncertainty_kind'] = np.asarray('producer_uncertainty_m')
        np.savez(mesh, **arrays)

        # Refresh both refs: identity checks alone must not decide the result.
        receipt_path = root / 'render/render-receipt.json'
        receipt = checker.read_json(receipt_path)
        mesh_ref = checker.file_ref(root, 'render/terrain-mesh.npz')
        next(a for a in receipt['artifacts'] if a['path'] == mesh_ref['path']).update(mesh_ref)
        write(receipt_path, receipt)
        complete_path = root / 'render/complete.json'
        complete = checker.read_json(complete_path)
        complete['receipt'].update(checker.file_ref(root, 'render/render-receipt.json'))
        write(complete_path, complete)

    checks, _ = checker.verify_core(root, output_dir='render', max_png_bytes=checker.DEFAULT_MAX_PNG_BYTES,
                                    require_holes=True)
    assert checks.failed == ([] if edit == 'matching' else [CHECK]), checks.items
