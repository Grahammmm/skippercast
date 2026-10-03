"""Irregular official sonar tables can qualify leads without creating habitat."""
import gzip
import hashlib
import json

import pytest
from pyproj import Transformer
from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient

from research.scripts.triage_multibeam_beams import COLUMNS, esri_polygon, load_native_gap_query, triage
from research.scripts.discover_noaa_multibeam_footprints import gap_sectors
from tests.gis.test_multibeam_gap_discovery import cell, snapshot

pytestmark = pytest.mark.gis


def fixture(tmp_path, rows, kind='all'):
    folder = tmp_path/'coverage'; folder.mkdir()
    snapshot(folder, [cell(-270, -1420), cell(-269, -1420, 62500)])
    raw = ('\n'.join(rows)+'\n').encode()
    table = tmp_path/'beams.tsv.gz'; table.write_bytes(gzip.compress(raw))
    receipt = tmp_path/'beams.json'
    receipt.write_text(json.dumps({'columns': COLUMNS,
                                  'binary_sha256': 'a'*64,
                                  'command': ['mblist', '-F57', '-Ifixture.mb57', '-MA', '-OXYzFMN#'],
                                  'stdout_sha256': hashlib.sha256(raw).hexdigest(),
                                  'shallow_sha256': hashlib.sha256(raw).hexdigest(),
                                  'rows': len(rows), 'good_nominal_shallow_rows': len(rows)}))
    return table, receipt, folder


def beam(depth=80, flag=0, supported=False):
    project = Transformer.from_crs(3310, 4326, always_xy=True)
    lon, lat = project.transform((-269 if supported else -270)*250+125, -1420*250+125)
    return f'{lon:.12f}\t{lat:.12f}\t{depth}\t{flag}\t890000000\t1\t5'


def test_valid_shallow_points_in_checked_gaps_create_no_area(tmp_path):
    args = fixture(tmp_path, [beam(), beam(91.44), beam(80, supported=True),
                              beam(91.45), beam(0), beam(80, 129)])
    result = triage(*args, table_kind='all')
    assert result['evaluated_beam_rows'] == 6
    assert result['good_nominal_shallow_rows'] == 3
    assert result['good_shallow_rows_in_gaps'] == 2
    assert result['rejected_flag_rows'] == 1
    assert result['rejected_depth_rows'] == 2
    assert result['gap_depth_min_m'] == 80 and result['gap_depth_max_m'] == 91.44
    assert result['new_measured_km2'] == result['new_physical_candidates'] == result['new_public_locations'] == 0
    assert not result['fishing_target'] and not result['exportable']


def test_shallow_subset_rejects_bad_flags_and_deep_records(tmp_path):
    args = fixture(tmp_path, [beam(92)])
    with pytest.raises(ValueError, match='Shallow subset'):
        triage(*args)


def test_corrupt_source_table_never_returns_a_result(tmp_path):
    args = fixture(tmp_path, [beam()])
    args[0].write_bytes(gzip.compress((beam(89)+'\n').encode()))
    with pytest.raises(ValueError, match='hash or row count'):
        triage(*args)


def test_corrupt_coverage_checkpoint_rejected(tmp_path):
    args = fixture(tmp_path, [beam()])
    (args[2]/'coverage-cells.json').write_text('{}')
    with pytest.raises(ValueError, match='checkpoint hash'):
        triage(*args)


@pytest.mark.parametrize('row', [beam('nan'), beam(flag=1.5), '1 2 3',
                                 '180.1 34 80 0 890000000 1 2'])
def test_nonfinite_malformed_coordinates_and_flags_rejected(tmp_path, row):
    args = fixture(tmp_path, [row])
    with pytest.raises(ValueError):
        triage(*args, table_kind='all')


def test_missing_quality_and_unit_schema_rejected(tmp_path):
    args = fixture(tmp_path, [beam()])
    args[1].write_text(json.dumps({'columns': ['X','Y','Z']}))
    with pytest.raises(ValueError, match='columns or depth units'):
        triage(*args)


@pytest.mark.parametrize('option', ['-W', '-P2', '-K10', '-OXYZ', '-Q'])
def test_feet_averaging_decimation_and_wrong_columns_rejected(tmp_path, option):
    args = fixture(tmp_path, [beam()])
    metadata = json.loads(args[1].read_text());metadata['command'].append(option)
    args[1].write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='preserve beam positions'):
        triage(*args)


def test_decompression_and_rows_bounded(tmp_path):
    args = fixture(tmp_path, [beam(), beam()])
    with pytest.raises(ValueError, match='row count'):
        triage(*args, max_rows=1)
    with pytest.raises(ValueError, match='byte/line bound'):
        triage(*args, max_bytes=10)


def test_no_shallow_gap_evidence_is_not_zero_fishing_quality(tmp_path):
    result = triage(*fixture(tmp_path, [beam(95)]), table_kind='all')
    assert result['good_shallow_rows_in_gaps'] == 0
    assert result['gap_depth_min_m'] is None and result['gap_beam_bounds_wgs84'] is None


def ring(square, clockwise):
    return [list(p) for p in orient(Polygon(square), sign=-1 if clockwise else 1).exterior.coords]


def test_esri_holes_nested_islands_and_disconnected_shells():
    geometry = {'rings': [ring([(0,0),(10,0),(10,10),(0,10)], True),
                          ring([(2,2),(8,2),(8,8),(2,8)], False),
                          ring([(4,4),(6,4),(6,6),(4,6)], True),
                          ring([(20,0),(22,0),(22,2),(20,2)], True)]}
    result = esri_polygon(geometry)
    assert result.area == 72
    assert result.covers(Point(5,5)) and result.covers(Point(21,1))
    assert not result.covers(Point(3,3))


def test_invalid_ring_and_unowned_hole_never_repaired():
    with pytest.raises(ValueError):
        esri_polygon({'rings': [[[0,0],[1,0],[1,1]]]})
    with pytest.raises(ValueError, match='outside exteriors'):
        esri_polygon({'rings': [ring([(0,0),(2,0),(2,2),(0,2)], True),
                                ring([(4,4),(5,4),(5,5),(4,5)], False)]})


def test_tiny_sliver_at_large_projected_coordinates_keeps_orientation():
    tiny = ring([(-58000,-385000),(-58000+1e-8,-385000),
                 (-58000+1e-8,-384970),(-58000,-384970)], True)
    result = esri_polygon({'rings': [tiny]})
    assert result.equals(Polygon(tiny))
    assert result.area > 0


def test_deep_filter_requires_verified_native_masks(tmp_path):
    with pytest.raises(ValueError, match='requires checked native masks'):
        triage(*fixture(tmp_path, [beam()]), exclude_measured_deep=True)


def saved_query(folder, target):
    groups, identity = gap_sectors(folder)
    # A fixture represents a previously verified native snapshot. The caller
    # must pin its bytes; this test does not fabricate actual source coverage.
    identity.update(native_support_inputs_sha256='b'*64, native_support_sha256='c'*64,
                    retained_run_sha256='d'*64)
    payload = {'groups': groups, 'coverage_snapshot': identity}
    target.write_text(json.dumps(payload))
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


def test_pinned_query_matches_existing_triage_without_original_cache(tmp_path):
    table, receipt, folder = fixture(tmp_path, [beam(), beam(80, supported=True), beam(92)])
    query, pin = saved_query(folder, tmp_path/'private-query.json')
    original = triage(table, receipt, folder, table_kind='all')
    # No raster/cache or coverage directory is read through this path.
    result = triage(table, receipt, gap_query=query, gap_query_sha256=pin, table_kind='all')
    for key in ('evaluated_beam_rows', 'good_nominal_shallow_rows', 'good_shallow_rows_in_gaps',
                'by_gap_group', 'gap_depth_min_m', 'gap_depth_max_m'):
        assert result[key] == original[key]
    assert result['gap_query_sha256'] == pin
    assert result['new_measured_km2'] == result['new_public_locations'] == 0
    assert any('not proof of current coverage' in v for v in result['limitations'])


@pytest.mark.parametrize('pin', [None, 'a'*63, 'A'*64, 'b'*64])
def test_query_requires_matching_explicit_pin(tmp_path, pin):
    _, _, folder = fixture(tmp_path, [beam()])
    query, _ = saved_query(folder, tmp_path/'private-query.json')
    with pytest.raises(ValueError, match='pin|hash mismatch'):
        load_native_gap_query(query, pin)


@pytest.mark.parametrize('problem', ['native_identity', 'duplicate', 'mixed_reach', 'crs', 'deep_identity'])
def test_pinned_bytes_do_not_replace_native_identity_or_topology_checks(tmp_path, problem):
    _, _, folder = fixture(tmp_path, [beam()])
    query, _ = saved_query(folder, tmp_path/'private-query.json')
    payload = json.loads(query.read_text())
    if problem == 'native_identity':
        del payload['coverage_snapshot']['native_support_sha256']
    elif problem == 'duplicate':
        payload['groups'].append(payload['groups'][0])
    elif problem == 'mixed_reach':
        payload['groups'][0]['id'] = 'different-reach-gap-0001'
    elif problem == 'crs':
        payload['groups'][0]['query_geometry']['spatialReference']['wkid'] = 4326
    else:
        payload['coverage_snapshot']['measured_deep_mask_sha256'] = 'e'*64
        payload['coverage_snapshot']['measured_deep_method'] = 'unverified'
    query.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_native_gap_query(query, hashlib.sha256(query.read_bytes()).hexdigest())


def test_saved_query_keeps_holes_and_inclusive_boundaries(tmp_path):
    _, _, folder = fixture(tmp_path, [beam()])
    query, _ = saved_query(folder, tmp_path/'private-query.json')
    payload = json.loads(query.read_text())
    geometry = payload['groups'][0]['query_geometry']
    geometry['rings'] = [ring([(0,0),(10,0),(10,10),(0,10)], True),
                         ring([(2,2),(8,2),(8,8),(2,8)], False)]
    query.write_text(json.dumps(payload))
    groups, _ = load_native_gap_query(query, hashlib.sha256(query.read_bytes()).hexdigest())
    shape = esri_polygon(groups[0]['query_geometry'])
    assert shape.covers(Point(0,5)) and shape.covers(Point(2,5))
    assert not shape.covers(Point(5,5))


def test_saved_query_cannot_mix_cache_options(tmp_path):
    table, receipt, folder = fixture(tmp_path, [beam()])
    query, pin = saved_query(folder, tmp_path/'private-query.json')
    with pytest.raises(ValueError, match='mixed with cache'):
        triage(table, receipt, folder, gap_query=query, gap_query_sha256=pin)


def test_query_read_is_bounded(tmp_path, monkeypatch):
    _, _, folder = fixture(tmp_path, [beam()])
    query, pin = saved_query(folder, tmp_path/'private-query.json')
    monkeypatch.setattr('research.scripts.triage_multibeam_beams.MAX_GAP_QUERY_BYTES', 10)
    with pytest.raises(ValueError, match='read bound'):
        load_native_gap_query(query, pin)
