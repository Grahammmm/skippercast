"""The mapper consumes exactly the observation that passed every input check."""
from copy import deepcopy
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from skippercast.coastal import mapping, vertical
from skippercast.coastal.handoff import mapping_input
from skippercast.coastal.handoff.common import ref, write

pytestmark = pytest.mark.gis
NOW = '2026-10-18T00:00:00Z'


@pytest.fixture
def qualified(tmp_path):
    source = tmp_path / 'native.tif'
    raw = -np.arange(1, 17, dtype='float32').reshape(4, 4)
    raw[1, 2] = np.nan
    transform = from_origin(10, 20, 2, 2)
    with rasterio.open(source, 'w', driver='GTiff', width=4, height=4,
                       count=1, dtype='float32', crs='EPSG:3310',
                       transform=transform, nodata=np.nan) as ds:
        ds.write(raw, 1)
        ds.set_band_unit(1, 'm')
        ds.update_tags(vertical_sign='positive_up', vertical_datum='MLLW',
                       scale_offset_applied='false')
    source_ref = ref(tmp_path, source, 'native-raster-v1')
    with rasterio.open(source) as ds:
        observed = vertical.from_raster(ds, source_sha256=source_ref['sha256'])
    block = dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                 evidence=[vertical.evidence_from_observation(observed)])
    segment_id = 'seg:3310:0:0:5000'
    write(tmp_path / 'segment.json', dict(schema='coastal-segment-v1',
          segment_id=segment_id, crs='EPSG:3310', bbox=[0, 0, 5000, 5000], region='synthetic'))
    write(tmp_path / 'fixture-evidence.json', dict(synthetic=True))
    document = mapping_input.produce(tmp_path, source_ref, segment_id=segment_id,
        segment=ref(tmp_path, tmp_path / 'segment.json', 'coastal-segment-v1'),
        window=[0, 0, 4, 4], vertical=block, output_dir='input', synthetic=True,
        rights=dict(private_use=True, evidence=[ref(tmp_path,
            tmp_path / 'fixture-evidence.json', 'synthetic-fixture-evidence-v1')]))
    assert document['machine_holds'] == []
    review = dict(schema='coastal-private-input-review-v2', independent=True,
        reviewer_id='synthetic-test-reviewer', facts_digest=document['facts_digest'],
        checked_at='2026-10-17T00:00:00Z', valid_until='2026-10-19T00:00:00Z',
        decision='accept', holds_added=[])
    write(tmp_path / 'review.json', review)
    document['review'] = ref(tmp_path, tmp_path / 'review.json', review['schema'])
    return tmp_path, document, raw


def test_mapping_consumes_one_verified_observation_and_preserves_cells(qualified):
    root, document, raw = qualified
    with patch.object(mapping_input, 'observe', wraps=mapping_input.observe) as observed:
        result = mapping.run(root, document, output_dir='mapped', now=NOW)
    assert observed.call_count == 1
    assert result['state'] == 'done'
    assert result['facts_digest'] == document['facts_digest']
    valid = np.isfinite(raw)
    with rasterio.open(root / result['outputs']['terrain']['path']) as ds:
        actual = ds.read(1, masked=True)
        np.testing.assert_array_equal(~np.ma.getmaskarray(actual), valid)
        np.testing.assert_array_equal(actual.data[valid], -raw[valid])
        assert ds.tags()['vertical_sign'] == 'positive_down'
    with rasterio.open(root / result['outputs']['mask']['path']) as ds:
        np.testing.assert_array_equal(ds.read(1), valid.astype('uint8'))


def test_public_verifier_keeps_result_contract(qualified):
    root, document, _ = qualified
    checked = mapping_input.verify(root, document, now=NOW)
    assert set(checked) == {'ready', 'holds', 'facts_digest', 'facts', 'synthetic'}
    assert checked['ready'] and checked['synthetic'] and checked['holds'] == []
    assert checked['facts'] == document['native_facts']
    assert mapping_input.validate_handoff is mapping_input.verify


@pytest.mark.parametrize('expired', [False, True])
def test_review_holds_prevent_mapping_outputs(qualified, expired):
    root, document, _ = qualified
    if not expired:
        document['review'] = None
    result = mapping.run(root, document, output_dir='held',
                         now='2026-10-20T00:00:00Z' if expired else NOW)
    assert result['state'] == 'held'
    assert ('review_expired_or_future' if expired else 'independent_review_missing') in result['holds']
    assert not (root / 'held').exists()


@pytest.mark.parametrize('tamper', ['source', 'mask', 'facts'])
def test_source_mask_and_facts_tamper_remain_rejected(qualified, tamper):
    root, document, _ = qualified
    document = deepcopy(document)
    if tamper == 'source':
        with rasterio.open(root / document['source']['path'], 'r+') as ds:
            values = ds.read(1)
            values[0, 0] -= 1
            ds.write(values, 1)
        expected = 'artifact bytes/hash changed'
    elif tamper == 'mask':
        path = root / document['valid_support']['path']
        with rasterio.open(path, 'r+') as ds:
            values = ds.read(1)
            values[1, 2] = 1
            ds.write(values, 1)
        document['valid_support'] = ref(root, path, 'coastal-native-support-v2')
        expected = 'native support artifact differs'
    else:
        document['native_facts']['valid_count'] += 1
        expected = 'native facts changed or forged'
    with pytest.raises(ValueError, match=expected):
        mapping.run(root, document, output_dir='rejected', now=NOW)
    assert not (root / 'rejected').exists()


@pytest.fixture
def original_bag(tmp_path):
    import hashlib
    import h5py
    from skippercast.coastal import bag_v2
    from tests.gis.test_regular_bag_native_window import OriginalBagWindowTests
    source = tmp_path / 'H11879_MB_2m_MLLW_1of5.bag'
    xml = OriginalBagWindowTests._make_original_bag(source)
    # The older reader fixture omits an axis. This vertical-contract test must
    # explicitly agree with GDAL's MLLW depth coordinate (BAG samples stay up).
    old_vertical = ('VERT_CS["MLLW depth", VERT_DATUM["Mean Lower Low Water",2005, '
                    'AUTHORITY["EPSG","1089"]], UNIT["metre",1,AUTHORITY["EPSG","9001"]]]')
    new_vertical = old_vertical[:-1] + ', AXIS["Depth",DOWN], AUTHORITY["EPSG","5866"]]'
    assert old_vertical in xml
    xml = xml.replace(old_vertical, new_vertical)
    with h5py.File(source, 'r+') as bag:
        del bag['BAG_root']['metadata']
        bag['BAG_root'].create_dataset('metadata', data=np.frombuffer(xml.encode(), dtype='S1'),
                                      dtype='S1', maxshape=(None,), chunks=True)
    artifact = ref(tmp_path, source, 'native-raster-v1')
    row = dict(id='synthetic-bag', title=source.name, kind='bathymetry', format='bag',
        url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/' + source.name,
        sha256=artifact['sha256'], horizontal_crs='EPSG:26911', vertical_datum='MLLW', resolution_m=2)
    metadata = bag_v2.inspect_metadata(source, 'H11879')
    assert metadata == bag_v2.parse_metadata(xml, 'H11879')
    with rasterio.open(source) as ds:
        observed = vertical.from_raster(ds, source_sha256=artifact['sha256'], bag_metadata=metadata)
    block = dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                 evidence=[vertical.evidence_from_observation(observed)])
    assert vertical.resolve(block, observed)['holds'] == []
    return tmp_path, source, artifact, row, block, hashlib.sha256(xml.encode()).hexdigest()


def test_bag_observation_authenticates_twice_without_duplicate_metadata_hashing(original_bag):
    from skippercast.coastal.handoff import common
    from skippercast.seafloor.adapters import regular_bag_window
    root, source, artifact, row, block, metadata_hash = original_bag
    with patch.object(common, 'sha', wraps=common.sha) as container_sha, \
         patch.object(regular_bag_window, 'sha256', wraps=regular_bag_window.sha256) as native_sha:
        facts, holds, raw, valid, _, _, depth = mapping_input.observe(root, artifact,
            window=[2, 0, 4, 4], vertical=block, source_row=row, metadata_sha256=metadata_hash)
    assert container_sha.call_count == native_sha.call_count == 1
    assert holds == [] and facts['valid_count'] == 15
    assert not valid[0, 3]
    np.testing.assert_array_equal(depth[valid], -raw[valid])


@pytest.mark.parametrize('defect', ['variable_resolution', 'oversized_metadata', 'external_link'])
def test_guarded_bag_metadata_entry_point_retains_rejections(original_bag, defect):
    import h5py
    from skippercast.coastal import bag_v2
    _, source, _, _, _, _ = original_bag
    with h5py.File(source, 'r+') as bag:
        root = bag['BAG_root']
        if defect == 'variable_resolution':
            root.create_dataset('varres_refinements', data=np.ones((1, 2)))
            expected = 'Variable-resolution'
        elif defect == 'oversized_metadata':
            del root['metadata']
            root.create_dataset('metadata', shape=(1_000_001,), dtype='S1')
            expected = 'BAG metadata byte bound exceeded'
        else:
            root['untrusted'] = h5py.ExternalLink('/unavailable', '/dataset')
            expected = 'external/soft links refused'
    with pytest.raises(ValueError, match=expected):
        bag_v2.inspect_metadata(source, 'H11879')
