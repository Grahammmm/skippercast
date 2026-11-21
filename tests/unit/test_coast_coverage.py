"""Runtime checks for the coast coverage report (C1–C3)."""

import json
import socket
from pathlib import Path

import pytest

from scripts.relief import coast_coverage as coast
from tests._support import ROOT


def test_C1_gap_at_each_edge_and_between_regions():
    """C1: A gap sweep must start and stop at the configured anchors."""
    assert coast.coverage({
        'south': 30, 'north': 40,
        'release': {'north': (-125, 36, -115, 39), 'south': (-125, 31, -115, 34),
                    'outside': (-125, 41, -115, 42)},
        'islands': {},
    }) == {'gaps': [[30, 31], [34, 36], [39, 40]], 'overlaps': [],
           'islands_inside': {}, 'ok': False}


def test_C1_overlaps_are_clipped_and_nested_spans_do_not_shorten_coverage():
    """C1: Nested spans must not reset the frontier; touching is not overlap."""
    assert coast.coverage({
        'south': 30, 'north': 40,
        'release': {'north': (-124, 37, -114, 42), 'nested': (-123, 28, -115, 32),
                    'south': (-125, 29, -113, 37)},
        'islands': {'equal-edge': (-124, 38, -114, 42), 'two-containers': (-122, 31, -120, 32)},
    }) == {'gaps': [], 'overlaps': [{'regions': ['nested', 'south'], 'latitudes': [30, 32]}],
           'islands_inside': {'equal-edge': 'north', 'two-containers': 'nested'}, 'ok': True}


def test_C1_islands_need_one_full_rectangle():
    """C1: Latitude alone, partial longitude coverage, and union containment do not count."""
    assert coast.coverage({
        'south': 30, 'north': 40,
        'release': {'south': (-125, 30, -115, 35), 'north': (-125, 35, -115, 40)},
        'islands': {'offshore': (-126, 32, -124, 33), 'straddles': (-124, 34, -120, 36)},
    }) == {'gaps': [], 'overlaps': [], 'islands_inside': {'offshore': None, 'straddles': None},
           'ok': False}


def test_C1_reversed_anchors_refused():
    """C1: An inverted window must not pass as a gap-free coast."""
    with pytest.raises(ValueError) as error:
        coast.coverage({'south': 40, 'north': 30, 'release': {}, 'islands': {}})
    assert error.type is ValueError


def test_C1_real_release_bounds():
    """C1: Record the actual coverage and both island parents on the checked-in tree."""
    assert coast.coverage(coast.load_regions(ROOT)) == {
        'gaps': [],
        'overlaps': [
            {'regions': ['point-arguello-conception', 'morro-bay'], 'latitudes': [34.95, 35.07]},
            {'regions': ['morro-bay', 'cambria-san-simeon'], 'latitudes': [35.45, 35.66]},
            {'regions': ['morro-bay', 'south-big-sur-san-simeon'], 'latitudes': [35.66, 35.85]},
            {'regions': ['monterey-point-sur', 'santa-cruz-monterey-bay'], 'latitudes': [36.6, 36.625]},
            {'regions': ['bodega-point-reyes', 'point-arena-bodega'], 'latitudes': [38.4, 38.5]},
            {'regions': ['point-arena-bodega', 'fort-bragg-point-arena'], 'latitudes': [38.958333333333336, 39.0]},
        ],
        'islands_inside': {'channel-islands-north': 'southern-california',
                           'outer-islands-borderland': 'southern-california'},
        'ok': True,
    }


@pytest.fixture
def config_files(monkeypatch, tmp_path):
    # A closed, in-memory tree: any attempt to read an undeclared data file fails.
    files: dict[str, dict] = {'dist/regions/index.json': {'regions': [{'id': 'umbrella'}]}}
    for region_id, bounds in {
        'san-diego': [-120, 30, -115, 32],
        'crescent-city': [-125, 38, -120, 40],
        'channel-islands-north': [-124, 36, -122, 38],
        'outer-islands-borderland': [-123, 33, -121, 35],
        'umbrella': [-125, 29, -115, 41],
    }.items():
        files[f'regions/{region_id}/region.json'] = {'bounds': bounds}

    def read_text(path, **kwargs):
        name = path.relative_to(tmp_path).as_posix()
        if name not in files:
            raise AssertionError(f'unexpected config read: {name}')
        return json.dumps(files[name])

    def no_network(*args, **kwargs):
        raise AssertionError('coverage must not open a socket')

    monkeypatch.setattr(coast, 'ROOT', tmp_path)
    monkeypatch.setattr(Path, 'read_text', read_text)
    monkeypatch.setattr(socket, 'socket', no_network)
    return files


def test_C2_table_success(config_files, capsys):
    """C2: No flag prints the table with both island rows and success status."""
    assert coast.main([]) == 0
    assert capsys.readouterr() == (
        'Check      | Region(s) / island           | Result\n'
        'Island     | channel-islands-north | umbrella\n'
        'Island     | outer-islands-borderland | umbrella\n'
        'Configured coast coverage: OK\n', '',
    )


def test_C2_table_shows_gaps_overlaps_and_outside_islands(config_files, capsys):
    """C2: A text report must not hide a gap or mistake an overlap for failure."""
    config_files['dist/regions/index.json']['regions'].append({'id': 'crescent-city'})
    config_files['regions/umbrella/region.json']['bounds'] = [-125, 35, -115, 39]
    assert coast.main([]) == 1
    assert capsys.readouterr() == (
        'Check      | Region(s) / island           | Result\n'
        'Gap        | -                            | 30 to 35 N\n'
        'Overlap    | umbrella / crescent-city | 38 to 39 N\n'
        'Island     | channel-islands-north | umbrella\n'
        'Island     | outer-islands-borderland | outside\n'
        'Configured coast coverage: NOT OK\n', '',
    )


def test_C2_json_failure(config_files, capsys):
    """C2: A failed check still emits the full JSON report and returns 1."""
    config_files['regions/umbrella/region.json']['bounds'] = [-125, 32, -115, 36]
    assert coast.main(['--json']) == 1
    out, err = capsys.readouterr()
    assert err == ''
    assert json.loads(out) == {
        'gaps': [[30, 32], [36, 40]], 'overlaps': [],
        'islands_inside': {'channel-islands-north': None, 'outer-islands-borderland': 'umbrella'},
        'ok': False,
    }


def test_C2_usage_refusal(config_files):
    """C2: Invalid flags fail with usage status before any coverage report."""
    with pytest.raises(SystemExit) as error:
        coast.main(['--js'])
    assert error.type is SystemExit
    assert error.value.code == 2


def test_C2_invalid_config_reports_failure(config_files, capsys):
    """C2: Bad input cannot be presented as a successful coverage table."""
    config_files['regions/umbrella/region.json']['bounds'] = [-115, 30, -125, 40]
    assert coast.main(['--json']) == 1
    assert capsys.readouterr() == ('', 'Coast coverage could not be checked: invalid bounds for umbrella\n')


def test_C3_load_only_index_and_region_configs(config_files):
    """C3: Derive anchors and rectangles from configs, selecting release IDs only from the index."""
    assert coast.load_regions(coast.ROOT) == {
        'south': 30, 'north': 40,
        'release': {'umbrella': (-125, 29, -115, 41)},
        'islands': {'channel-islands-north': (-124, 36, -122, 38),
                    'outer-islands-borderland': (-123, 33, -121, 35)},
    }


@pytest.mark.parametrize('region_id, config_bounds', [
    pytest.param('../other', [-125, 29, -115, 41], id='C3: reject a non-region path'),
    pytest.param('umbrella', [-125, 41, -115, 29], id='C3: reject reversed bounds'),
])
def test_C3_loader_refusals(config_files, region_id, config_bounds):
    """C3: Reject an out-of-tree lookup or non-geographic rectangle."""
    config_files['dist/regions/index.json']['regions'] = [{'id': region_id}]
    config_files['regions/umbrella/region.json']['bounds'] = config_bounds
    with pytest.raises(ValueError) as error:
        coast.load_regions(coast.ROOT)
    assert error.type is ValueError
