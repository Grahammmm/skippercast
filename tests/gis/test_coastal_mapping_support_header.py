"""A native-support artifact cannot hide its cells behind nodata or an internal mask."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.enums import MaskFlags
from rasterio.transform import from_origin

from skippercast.coastal import mapping, vertical
from skippercast.coastal.handoff import mapping_input
from skippercast.coastal.handoff.common import ref, write

pytestmark = pytest.mark.gis
NOW = '2026-10-18T00:00:00Z'
REFUSAL = 'native support artifact differs from source cells'


@pytest.fixture
def qualified(tmp_path):
    source = tmp_path / 'native.tif'
    raw = -np.arange(1, 17, dtype='float32').reshape(4, 4)
    raw[1, 2] = np.nan
    with rasterio.open(source, 'w', driver='GTiff', width=4, height=4, count=1, dtype='float32',
                       crs='EPSG:3310', transform=from_origin(10, 20, 2, 2), nodata=np.nan) as ds:
        ds.write(raw, 1)
        ds.set_band_unit(1, 'm')
        ds.update_tags(vertical_sign='positive_up', vertical_datum='MLLW', scale_offset_applied='false')
    source_ref = ref(tmp_path, source, 'native-raster-v1')
    with rasterio.open(source) as ds:
        observed = vertical.from_raster(ds, source_sha256=source_ref['sha256'])
    block = dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                 evidence=[vertical.evidence_from_observation(observed)])
    segment_id = 'seg:3310:0:0:5000'
    write(tmp_path / 'segment.json', dict(schema='coastal-segment-v1', segment_id=segment_id,
          crs='EPSG:3310', bbox=[0, 0, 5000, 5000], region='synthetic'))
    write(tmp_path / 'fixture-evidence.json', dict(synthetic=True))
    document = mapping_input.produce(tmp_path, source_ref, segment_id=segment_id,
        segment=ref(tmp_path, tmp_path / 'segment.json', 'coastal-segment-v1'),
        window=[0, 0, 4, 4], vertical=block, output_dir='input', synthetic=True,
        rights=dict(private_use=True, evidence=[ref(tmp_path,
            tmp_path / 'fixture-evidence.json', 'synthetic-fixture-evidence-v1')]))
    review = dict(schema='coastal-private-input-review-v2', independent=True,
        reviewer_id='synthetic-test-reviewer', facts_digest=document['facts_digest'],
        checked_at='2026-10-17T00:00:00Z', valid_until='2026-10-19T00:00:00Z',
        decision='accept', holds_added=[])
    write(tmp_path / 'review.json', review)
    document['review'] = ref(tmp_path, tmp_path / 'review.json', review['schema'])
    return tmp_path, document, raw


def _mutate(root, document, how):
    path = root / document['valid_support']['path']
    if how in ('nodata_one', 'nodata_zero'):
        with rasterio.open(path, 'r+') as ds:
            ds.nodata = 1 if how == 'nodata_one' else 0
    else:
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(path, 'r+') as ds:
            ds.write_mask(np.full(ds.shape, 0 if how == 'mask_zero' else 255, dtype='uint8'))
    document = deepcopy(document)
    document['valid_support'] = ref(root, path, 'coastal-native-support-v2')
    return document, path


def _snapshot(root):
    return {str(p): p.read_bytes() for p in sorted(Path(root).rglob('*')) if p.is_file()}


def test_support_nodata_one_cannot_hide_qualified_cells(qualified):
    root, document, _ = qualified
    document, path = _mutate(root, document, 'nodata_one')
    with rasterio.open(path) as ds:
        raw = ds.read(1)
        effective = ds.read(1, masked=True)
    assert int((raw == 1).sum()) == 15
    assert int(((~np.ma.getmaskarray(effective)) & (raw == 1)).sum()) == 0
    with pytest.raises(ValueError, match=REFUSAL):
        mapping_input.verify(root, document, now=NOW)


@pytest.mark.parametrize('how', ['nodata_zero', 'mask_zero', 'mask_all_valid'])
def test_noncanonical_validity_encodings_refuse(qualified, how):
    root, document, raw = qualified
    document, path = _mutate(root, document, how)
    if how != 'nodata_zero':
        assert not Path(str(path) + '.msk').exists()
        with rasterio.open(path) as ds:
            np.testing.assert_array_equal(ds.read(1), np.isfinite(raw).astype('uint8'))
    before = _snapshot(root)
    with pytest.raises(ValueError, match=REFUSAL):
        mapping_input.verify(root, document, now=NOW)
    assert _snapshot(root) == before


@pytest.mark.parametrize('how', ['nodata_one', 'nodata_zero', 'mask_zero', 'mask_all_valid'])
def test_public_mapper_refuses_before_output(qualified, how):
    root, document, _ = qualified
    document, _ = _mutate(root, document, how)
    with pytest.raises(ValueError, match=REFUSAL):
        mapping.run(root, document, output_dir='mapped', now=NOW)
    assert not (root / 'mapped').exists()


def test_ordinary_binary_mask_remains_ready(qualified):
    root, document, raw = qualified
    with rasterio.open(root / document['valid_support']['path']) as ds:
        assert ds.nodatavals == (None,)
        assert ds.mask_flag_enums == ([MaskFlags.all_valid],)
    before = _snapshot(root)
    checked = mapping_input.verify(root, document, now=NOW)
    assert checked['ready'] and checked['holds'] == []
    assert set(checked) == {'ready', 'holds', 'facts_digest', 'facts', 'synthetic'}
    assert _snapshot(root) == before
    result = mapping.run(root, document, output_dir='mapped', now=NOW)
    assert result['state'] == 'done'
    with rasterio.open(root / result['outputs']['mask']['path']) as ds:
        np.testing.assert_array_equal(ds.read(1), np.isfinite(raw).astype('uint8'))
