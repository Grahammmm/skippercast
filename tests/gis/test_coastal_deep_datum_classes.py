"""PC-1 / G3: deep-band datum classes through the real raster and mapping path.

A header-silent synthetic GeoTIFF (the Cal DIG I shape: no vertical datum in the
file) is held in a lane S window and admitted in a lane M window. Admission maps
only cells at or below the lane floor and labels the product not for navigation.
"""
import json

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from skippercast.coastal import mapping, vertical
from skippercast.coastal.handoff import mapping_input
from skippercast.coastal.handoff.common import ref, write

pytestmark = pytest.mark.gis
NOW = '2026-10-18T00:00:00Z'


def _raster(path, raw, **tags):
    with rasterio.open(path, 'w', driver='GTiff', width=raw.shape[1], height=raw.shape[0], count=1,
                       dtype='float32', crs='EPSG:3310', transform=from_origin(10, 20, 2, 2),
                       nodata=np.nan) as ds:
        ds.write(raw, 1)
        ds.set_band_unit(1, 'm')
        ds.update_tags(vertical_sign='positive_up', scale_offset_applied='false', **tags)


def _declared(root, source, **extra):
    source_ref = ref(root, source, 'native-raster-v1')
    with rasterio.open(source) as ds:
        observed = vertical.from_raster(ds, source_sha256=source_ref['sha256'])
    block = dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                 evidence=[vertical.evidence_from_observation(observed)])
    block.update(extra)
    return source_ref, observed, block


def _produce(root, source_ref, block, output_dir):
    segment_id = 'seg:3310:0:0:5000'
    write(root / 'segment.json', dict(schema='coastal-segment-v1', segment_id=segment_id, crs='EPSG:3310',
                                      bbox=[0, 0, 5000, 5000], region='synthetic'))
    write(root / 'fixture-evidence.json', dict(synthetic=True))
    return mapping_input.produce(root, source_ref, segment_id=segment_id,
        segment=ref(root, root / 'segment.json', 'coastal-segment-v1'),
        window=[0, 0, 4, 4], vertical=block, output_dir=output_dir, synthetic=True,
        rights=dict(private_use=True, evidence=[ref(root, root / 'fixture-evidence.json',
                                                    'synthetic-fixture-evidence-v1')]))


@pytest.fixture
def silent(tmp_path):
    # Elevations -50 ... -200 m (depth 50-200 m), one hole; no vertical datum stated.
    raw = -np.linspace(50, 200, 16, dtype='float32').reshape(4, 4)
    raw[3, 3] = np.nan
    source = tmp_path / 'caldig_synthetic.tif'
    _raster(source, raw)
    return tmp_path, source, raw


def test_header_silent_raster_observes_no_datum(silent):
    root, source, _ = silent
    _, observed, _ = _declared(root, source)
    assert observed['facts']['datum'] is None and observed['conflicts'] == []


@pytest.mark.parametrize('lane', [None, 'S'])
def test_unstated_class_held_in_lane_s_window(silent, lane):
    root, source, _ = silent
    extra = dict(datum='unstated') | ({} if lane is None else dict(depth_lane=lane))
    source_ref, _, block = _declared(root, source, **extra)
    document = _produce(root, source_ref, block, 'input-s')
    assert 'vertical_datum_deep_lane_only' in document['machine_holds']
    assert document['native_facts']['vertical'] is None
    assert document['native_facts']['depth_values_sha256'] is None
    assert 'deep_lane_support' not in document['native_facts']


def test_unstated_class_admitted_and_mapped_in_lane_m_window(silent):
    root, source, raw = silent
    source_ref, _, block = _declared(root, source, datum='unstated', depth_lane='M')
    document = _produce(root, source_ref, block, 'input-m')
    assert document['machine_holds'] == []
    facts = document['native_facts']
    record = facts['vertical']['deep_datum']
    assert record == vertical.deep_datum_record('unstated', 'M')
    assert record['uncertainty_bound_required'] is False and record['navigation'] == 'not-for-navigation'
    depth = -raw.astype('float64')
    native = np.isfinite(depth)
    kept = native & (depth >= 91.44)
    assert facts['deep_lane_support'] == dict(depth_lane='M', lane_floor_m=91.44,
                                              cells_dropped_shallower_than_floor=int((native & ~kept).sum()))
    assert facts['valid_count'] == int(kept.sum()) and facts['support']['valid_cells'] == int(kept.sum())

    review = dict(schema='coastal-private-input-review-v2', independent=True,
                  reviewer_id='synthetic-test-reviewer', facts_digest=document['facts_digest'],
                  checked_at='2026-10-17T00:00:00Z', valid_until='2026-10-19T00:00:00Z',
                  decision='accept', holds_added=[])
    write(root / 'review.json', review)
    document['review'] = ref(root, root / 'review.json', review['schema'])
    result = mapping.run(root, document, output_dir='mapped', now=NOW)
    assert result['state'] == 'done', result
    assert result['vertical']['deep_datum'] == record and result['vertical']['depth_lane'] == 'M'
    terrain = root / result['outputs']['terrain']['path']
    with rasterio.open(terrain) as ds:
        actual = ds.read(1, masked=True)
        np.testing.assert_array_equal(~np.ma.getmaskarray(actual), kept)
        np.testing.assert_allclose(actual.data[kept], depth[kept].astype('float32'))
        assert float(actual.min()) >= 91.44
        tags = ds.tags()
        assert tags['vertical_datum'] == 'unstated'
        contract = json.loads(tags['vertical_contract'])
        assert contract['deep_datum']['navigation'] == 'not-for-navigation'
        # Downstream readers re-authenticate the stored label from the file
        # (evidence is replaced by the storage header's own evidence).
        reread = vertical.normalized_from_raster(ds, source_sha256=result['outputs']['terrain']['sha256'])
        assert reread['deep_datum'] == record
        assert {k: v for k, v in reread.items() if k != 'evidence'} == {
            k: v for k, v in contract.items() if k != 'evidence'}
    with rasterio.open(root / result['outputs']['mask']['path']) as ds:
        np.testing.assert_array_equal(ds.read(1), kept.astype('uint8'))
    assert mapping.verify(root, result, now=NOW)['ready']


def test_named_class_without_statement_held_in_lane_m(silent):
    root, source, _ = silent
    source_ref, _, block = _declared(root, source, datum='EGM2008', depth_lane='D')
    assert 'vertical_datum_statement_required' in _produce(root, source_ref, block, 'input-d')['machine_holds']


def test_lane_floor_can_empty_a_window(tmp_path):
    raw = -np.full((4, 4), 30.0, dtype='float32')
    source = tmp_path / 'shallow.tif'
    _raster(source, raw, vertical_datum='instantaneous sea level')
    source_ref, observed, block = _declared(tmp_path, source, depth_lane='M')
    assert observed['facts']['datum'] == 'instantaneous-sea-level'
    document = _produce(tmp_path, source_ref, block, 'input-shallow')
    assert 'native_support_empty' in document['machine_holds']
    assert document['native_facts']['deep_lane_support']['cells_dropped_shallower_than_floor'] == 16


def test_egm2008_vertical_crs_is_recognised(tmp_path):
    source = tmp_path / 'crm_synthetic.tif'
    with rasterio.open(source, 'w', driver='GTiff', width=2, height=2, count=1, dtype='float32',
                       crs=CRS.from_user_input('EPSG:3310+3855'), transform=from_origin(10, 20, 2, 2)) as ds:
        ds.write(-np.full((2, 2), 250.0, dtype='float32'), 1)
    with rasterio.open(source) as ds:
        observed = vertical.from_raster(ds, source_sha256='c' * 64)
    assert observed['facts']['datum'] == 'EGM2008'
    assert observed['facts']['sign'] == 'positive_up' and observed['facts']['units'] == 'm'


def test_to_depth_drops_cells_shallower_than_the_lane_floor():
    observed = dict(header={}, facts=dict(sign='positive_down', units='m', datum=None, scale=1.0, offset=0.0,
                                          scale_offset_applied=True, datum_realization='unknown'))
    observed.update(header_sha256=vertical.digest(observed['header']), source_sha256='d' * 64, conflicts=[])
    base = dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                evidence=[vertical.evidence_from_observation(observed)])
    values = np.array([[10.0, 91.43, 91.44], [182.87, 182.88, 900.0]])
    lane_m = vertical.require_resolved(dict(base, datum='unstated', depth_lane='M'), observed)
    lane_d = vertical.require_resolved(dict(base, datum='unstated', depth_lane='D'), observed)
    np.testing.assert_array_equal(np.isfinite(vertical.to_depth(values, lane_m)),
                                  [[False, False, True], [True, True, True]])
    np.testing.assert_array_equal(np.isfinite(vertical.to_depth(values, lane_d)),
                                  [[False, False, False], [False, True, True]])
    survey = dict(base, datum='MSL', evidence=base['evidence'])
    # A survey-grade datum in a deep lane keeps every cell (the bridge lane has no depth gate).
    assert np.isfinite(vertical.to_depth(values, dict(survey, depth_lane='M'))).all()
