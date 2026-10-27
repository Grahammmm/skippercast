import pytest
pytest.importorskip('numpy')
pytest.importorskip('rasterio')
from copy import deepcopy
import json
import struct
from datetime import datetime, timezone
from tests.unit.child_release_fixture import observed_clocks

def _fresh_iso(offset):
    return datetime.fromtimestamp(observed_clocks()[0] + offset, timezone.utc).isoformat()
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from skippercast.coastal import vertical
from skippercast.coastal.handoff.common import digest, ref, write
from skippercast.coastal.render import terrain_only as module
NOW = '2026-10-09T00:00:00Z'

def approve(root, document, **changes):
    review = dict(schema=module.REVIEW, scope='internal-terrain-only-scientific-review', facts_digest=module.context(document), independent=True, reviewer_id='synthetic-independent-science', decision='accept', checked_at='2026-10-08T00:00:00Z', valid_until='2026-10-11T00:00:00Z', holds_added=[], synthetic=True)
    review.update(changes)
    write(root / 'science.json', review)
    document['scientific_review'] = ref(root, 'science.json', module.REVIEW)
    return document

@pytest.fixture
def accepted(tmp_path):
    size = 16
    rows, cols = np.indices((size, size))
    data = (10 + cols * 0.7 + rows * 0.3).astype('float32')
    data[0, 0] = 0
    data[-1, -1] = 200
    support = np.ones(data.shape, dtype='uint8')
    support[6:9, 6:9] = 0
    data[support == 0] = np.nan
    transform = from_origin(500000, 4000000, 2, 2)
    profile = dict(driver='GTiff', height=size, width=size, count=1, crs='EPSG:26911', transform=transform)
    terrain = tmp_path / 'terrain.tif'
    with rasterio.open(terrain, 'w', dtype='float32', nodata=np.nan, **profile) as ds:
        ds.write(data, 1)
        ds.set_band_unit(1, 'm')
        ds.set_band_description(1, 'depth_m_positive_down')
        ds.update_tags(vertical_sign='positive_down', vertical_datum='MLLW', scale_offset_applied='false')
    with rasterio.open(terrain) as ds:
        observation = vertical.from_raster(ds, source_sha256='a' * 64)
    block = dict(schema='vertical-v1', **observation['facts'], conflicts=[], evidence=[vertical.evidence_from_observation(observation)])
    normalized = vertical.normalized(block)
    with rasterio.open(terrain, 'r+') as ds:
        ds.update_tags(vertical_contract=json.dumps(normalized), source_sha256='a' * 64, scale_offset_applied='true')
    with rasterio.open(tmp_path / 'mask.tif', 'w', dtype='uint8', **profile) as ds:
        ds.write(support, 1)
    uncertainty = np.where(support, cols * 0.02 + 0.1, np.nan).astype('float32')
    with rasterio.open(tmp_path / 'uncertainty.tif', 'w', dtype='float32', nodata=np.nan, **profile) as ds:
        ds.write(uncertainty, 1)
        ds.set_band_unit(1, 'm')
    document = dict(schema=module.INPUT, creator_id='synthetic-builder', segment_id='synthetic-only', terrain=ref(tmp_path, 'terrain.tif', 'coastal-normalized-terrain-v1'), mask=ref(tmp_path, 'mask.tif', 'coastal-native-support-v2'), uncertainty=ref(tmp_path, 'uncertainty.tif', 'coastal-derived-uncertainty-m-v1'), uncertainty_kind='producer_uncertainty_m', vertical=normalized, crs='EPSG:26911', affine=list(transform), provenance=dict(source_sha256s=['a' * 64], upstream_receipt_sha256='b' * 64), support_kind='derived_valid_sample_support', limitations=['Synthetic fixture; no real terrain claim.'], synthetic=True, source_accessed=False, imagery_used=False, internal_diagnostic=True, publication_prohibited=True, website='held', habitat='unassessed')
    return (tmp_path, approve(tmp_path, document), data, support, uncertainty)

@pytest.mark.parametrize('change', [dict(valid_until='2026-10-09T00:00:00Z'), dict(checked_at='2026-10-10T00:00:00Z'), dict(facts_digest='c' * 64), dict(reviewer_id='synthetic-builder'), dict(independent=False), dict(synthetic=False), dict(scope='website-display'), dict(holds_added=['science_hold'])])
def test_invalid_independent_review_is_rejected(accepted, change):
    root, document, *_ = accepted
    approve(root, document, **change)
    with pytest.raises(ValueError):
        module.preview(root, document, output_dir='must-not-exist', now=NOW)
    assert not (root / 'must-not-exist').exists()

@pytest.mark.parametrize('field,value', [('sign', 'positive_up'), ('units', 'ft'), ('datum', 'unknown'), ('scale', 2), ('offset', 1), ('scale_offset_applied', False)])
def test_vertical_declaration_errors_never_pass_review(accepted, field, value):
    root, document, *_ = accepted
    document['vertical'][field] = value
    approve(root, document)
    with pytest.raises(ValueError):
        module.preview(root, document, output_dir='invalid', now=NOW)

def test_hash_and_actual_header_errors(accepted):
    root, document, *_ = accepted
    with rasterio.open(root / 'terrain.tif', 'r+') as ds:
        ds.update_tags(vertical_sign='positive_up')
    with pytest.raises(ValueError, match='hash'):
        module.build_terrain(root, document)
    document['terrain'] = ref(root, 'terrain.tif', 'coastal-normalized-terrain-v1')
    approve(root, document)
    with pytest.raises(ValueError, match='vertical'):
        module.preview(root, document, output_dir='invalid', now=NOW)

def test_derived_vrt_sidecar_and_confinement_before_gdal(accepted, monkeypatch):
    root, document, *_ = accepted
    with pytest.raises(ValueError, match='relative'):
        module.preview(root, document, output_dir='../escape', now=NOW)
    (root / 'terrain.tfw').write_text('unbound')
    monkeypatch.setattr(rasterio, 'open', lambda *args, **kwargs: pytest.fail('GDAL opened before sidecar check'))
    with pytest.raises(ValueError, match='sidecar'):
        module.build_terrain(root, document)


def test_geographic_segment_mismatch_refuses_without_enqueue(accepted):
    root, document, *_ = accepted
    from skippercast.coastal.coordinator.store import Store
    from skippercast.coastal.handoff.common import ref, write
    write(root/'accepted-input.json',document)
    st=Store.__new__(Store);st.root=root;st.clock=lambda:__import__('time').time()
    job={'stage':'render','segment_id':'seg:3310:0:0:5000','input_manifest':ref(root,root/'accepted-input.json','coastal-terrain-only-input-v1'),'params':{'terrain_root':str(root)}}
    from unittest.mock import MagicMock
    from skippercast.coastal.coordinator.segments import segment
    st.db=MagicMock();st.db.execute.return_value.fetchone.return_value=[__import__('json').dumps(segment(0,0,region='synthetic'))]
    ok,holds=st._evidence_gate(job)
    assert not ok and 'segment_mismatch' in holds

pytestmark=pytest.mark.gis
