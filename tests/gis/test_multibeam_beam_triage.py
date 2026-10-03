"""Irregular official sonar tables can qualify leads without creating habitat."""
import gzip
import hashlib
import json

import pytest
from pyproj import Transformer
from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient

from research.scripts.triage_multibeam_beams import COLUMNS, esri_polygon, triage
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
