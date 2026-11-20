"""F07-11: comparing raw facts directly to resolved values falsely holds G3 renders."""
import json

import pytest

from skippercast.coastal import vertical
from skippercast.coastal.handoff.common import ref
from skippercast.coastal.render import terrain_only

pytestmark = pytest.mark.gis


@pytest.fixture
def reviewed(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from tests.gis.test_coastal_terrain_dispatch_adoption_guards import approve

    transform = from_origin(10, 20, 2, 2)
    profile = dict(driver='GTiff', width=4, height=4, count=1, crs='EPSG:3310', transform=transform)
    raw = -np.arange(80, 160, 5, dtype='float32').reshape(4, 4)
    with rasterio.open(tmp_path / 'raw.tif', 'w', dtype='float32', **profile) as ds:
        ds.write(raw, 1)
        ds.set_band_unit(1, 'm')
        ds.update_tags(vertical_sign='positive_up')
    source_hash = ref(tmp_path, 'raw.tif', 'native-raster-v1')['sha256']
    with rasterio.open(tmp_path / 'raw.tif') as ds:
        observed = vertical.from_raster(ds, source_sha256=source_hash)
    assert observed['facts']['datum'] is None
    declared = dict(observed['facts'], datum='unstated', depth_lane='M')
    resolved = vertical.require_resolved(declared, observed, [vertical.evidence_from_observation(observed)])
    depth = vertical.to_depth(raw, resolved).astype('float32')
    with rasterio.open(tmp_path / 'mask.tif', 'w', dtype='uint8', **profile) as ds:
        ds.write(np.isfinite(depth).astype('uint8'), 1)

    def build(change=None):
        normalized = vertical.normalized(resolved)
        source = normalized['lineage']['source_vertical']
        tagged_hash = source_hash
        if change == 'source-hash':
            tagged_hash = 'b' * 64
        elif change == 'units':
            source['evidence'][0]['facts']['units'] = 'ft'
        elif change == 'unsupported-datum':
            source['evidence'][0]['facts']['datum'] = 'unsupported-datum'
        elif change == 'shallow':
            source['depth_lane'] = 'S'
        normalized['evidence'] = source['evidence']
        normalized['lineage']['source_vertical_sha256'] = vertical.digest(source)
        with rasterio.open(tmp_path / 'terrain.tif', 'w', dtype='float32', nodata=np.nan, **profile) as ds:
            ds.write(depth, 1)
            ds.set_band_unit(1, 'm')
            ds.set_band_description(1, 'depth_m_positive_down')
            ds.update_tags(vertical_sign='positive_down', vertical_datum='unstated', scale_offset_applied='true',
                           vertical_contract=json.dumps(normalized), source_sha256=tagged_hash)
        return approve(tmp_path, dict(
            schema=terrain_only.INPUT, creator_id='synthetic-builder', segment_id='synthetic-only',
            terrain=ref(tmp_path, 'terrain.tif', 'coastal-normalized-terrain-v1'),
            mask=ref(tmp_path, 'mask.tif', 'coastal-native-support-v2'), vertical=normalized,
            crs=profile['crs'], affine=list(transform), support_kind='derived_valid_sample_support',
            provenance=dict(source_sha256s=[tagged_hash], upstream_receipt_sha256='c' * 64),
            limitations=['Synthetic fixture.'], synthetic=True, source_accessed=False, imagery_used=False,
            internal_diagnostic=True, publication_prohibited=True, website='held', habitat='unassessed'))

    return build


def test_reviewed_unstated_datum_renders_privately(tmp_path, reviewed):
    result = terrain_only.preview(tmp_path, reviewed(), output_dir='preview', now='2026-10-09T00:00:00Z')
    assert result['state'] == 'done' and result['triangles'] > 0
    assert (tmp_path / 'preview' / 'preview.png').is_file()
    assert result['internal_diagnostic'] and result['publication_prohibited'] and result['website'] == 'held'
    assert result['vertical']['evidence'][0]['facts']['datum'] is None
    assert result['vertical']['deep_datum']['navigation'] == 'not-for-navigation'
    assert result['support_cells'] == 13  # The 80, 85 and 90 m cells are below the M floor.


@pytest.mark.parametrize(('change', 'hold'), [
    ('shallow', 'normalized_vertical_lineage_invalid'),
    ('source-hash', 'source_vertical_evidence_lineage_mismatch'),
    ('units', 'source_vertical_evidence_lineage_mismatch'),
    ('unsupported-datum', 'source_vertical_evidence_lineage_mismatch'),
])
def test_review_does_not_override_bad_lineage(tmp_path, reviewed, change, hold):
    with pytest.raises(ValueError, match=f'^{hold}$'):
        terrain_only.preview(tmp_path, reviewed(change), output_dir='preview', now='2026-10-09T00:00:00Z')
    assert not (tmp_path / 'preview').exists()
