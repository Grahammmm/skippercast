"""Runtime checks for the coast coverage report (C1–C3)."""

import json
import shutil
import socket
import subprocess
import sys
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
           'beyond': [{'region': 'outside', 'edge': 'north', 'by_deg': 2}],
           'islands_inside': {}, 'islands_partial': [], 'ok': False}


def test_C1_overlaps_are_clipped_and_nested_spans_do_not_shorten_coverage():
    """C1: Clip only the latitude sweep, not the bounds used for diagnostics."""
    assert coast.coverage({
        'south': 30, 'north': 40,
        'release': {'north': (-124, 37, -114, 42), 'nested': (-123, 28, -115, 32),
                    'south': (-125, 29, -113, 37)},
        'islands': {'equal-edge': (-124, 38, -114, 42), 'two-containers': (-122, 31, -120, 32)},
    }) == {'gaps': [], 'overlaps': [{'regions': ['nested', 'south'], 'latitudes': [30, 32]}],
           'beyond': [{'region': 'nested', 'edge': 'south', 'by_deg': 2},
                      {'region': 'north', 'edge': 'north', 'by_deg': 2},
                      {'region': 'south', 'edge': 'south', 'by_deg': 1}],
           'islands_inside': {'equal-edge': 'north', 'two-containers': 'nested'},
           'islands_partial': [], 'ok': False}


def test_C1_islands_need_one_full_rectangle():
    """C1: Latitude alone, partial longitude coverage, and union containment do not count."""
    assert coast.coverage({
        'south': 30, 'north': 40,
        'release': {'south': (-125, 30, -115, 35), 'north': (-125, 35, -115, 40)},
        'islands': {'offshore': (-126, 32, -124, 33), 'straddles': (-124, 34, -120, 36),
                    'disjoint': (-127, 32, -126, 33), 'touching': (-126, 33, -125, 34)},
    }) == {'gaps': [], 'overlaps': [], 'beyond': [],
           'islands_inside': {'disjoint': None, 'offshore': None, 'straddles': None, 'touching': None},
           'islands_partial': ['offshore', 'straddles', 'touching'], 'ok': False}


def test_C2_partial_island_alone_fails_coverage():
    """C2: A complete coast with no overhang must still fail for a partial island."""
    assert coast.coverage({
        'south': 30, 'north': 40, 'release': {'umbrella': (-125, 30, -115, 40)},
        'islands': {'offshore': (-126, 31, -124, 32)},
    }) == {'gaps': [], 'overlaps': [], 'beyond': [], 'islands_inside': {'offshore': None},
           'islands_partial': ['offshore'], 'ok': False}


@pytest.mark.parametrize('low, high', [
    pytest.param(29.9999995, 40.0000005, id='C1: ignore sub-tolerance overhang'),
    pytest.param(29.999999, 40.000001, id='C1: ignore overhang at the tolerance'),
])
def test_C1_anchor_tolerance(low, high):
    """C1: Detect an inclusive cutoff or floating-point noise at normal latitudes."""
    assert coast.coverage({
        'south': 30, 'north': 40, 'release': {'umbrella': (-125, low, -115, high)},
        'islands': {},
    }) == {'gaps': [], 'overlaps': [], 'beyond': [], 'islands_inside': {},
           'islands_partial': [], 'ok': True}


def test_C1_reversed_anchors_refused():
    """C1: An inverted window must not pass as a gap-free coast."""
    with pytest.raises(ValueError) as error:
        coast.coverage({'south': 40, 'north': 30, 'release': {}, 'islands': {}})
    assert error.type is ValueError


def test_C3_real_release_bounds():
    """C3: Record the actual verdict, including the configured southern overhang."""
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
        'beyond': [{'region': 'southern-california', 'edge': 'south',
                    'by_deg': 0.034300000000001774}],
        'islands_inside': {'channel-islands-north': 'southern-california',
                           'outer-islands-borderland': 'southern-california'},
        'islands_partial': [],
        'ok': False,
    }


@pytest.fixture
def config_files(monkeypatch, tmp_path):
    # A closed, in-memory config tree: undeclared reads under tmp_path fail.
    files: dict[str, dict] = {'dist/regions/index.json': {'regions': [{'id': 'umbrella'}]}}
    for region_id, bounds in {
        'san-diego': [-120, 30, -115, 32],
        'crescent-city': [-125, 38, -120, 40],
        'channel-islands-north': [-124, 36, -122, 38],
        'outer-islands-borderland': [-123, 33, -121, 35],
        'umbrella': [-125, 30, -115, 40],
    }.items():
        files[f'regions/{region_id}/region.json'] = {'bounds': bounds}

    read_text_from_disk = Path.read_text

    def read_text(path, **kwargs):
        if not path.is_relative_to(tmp_path):
            return read_text_from_disk(path, **kwargs)
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


@pytest.fixture
def catalog_files(config_files, tmp_path):
    relief = tmp_path / 'catalog/relief'
    contours = tmp_path / 'catalog/depth-contours'
    relief.mkdir(parents=True)
    contours.mkdir()
    schema = ROOT / 'catalog/relief/pointer.schema.json'
    (relief / schema.name).write_bytes(schema.read_bytes())
    return relief, contours


@pytest.fixture
def pointer():
    return {
        'schema': 'sc-relief-pointer/1', 'status': 'reviewed', 'private': False,
        'generation': '0123456789abcdef' * 4, 'release_sha256': 'a' * 64,
        'envelope_sha256': 'b' * 64, 'sha256': 'c' * 64, 'bytes': 1,
        'digest_root_sha256': 'd' * 64, 'previous': None,
        'region': 'umbrella', 'bounds': [-125, 30, -115, 40],
        'minzoom': 8, 'maxzoom': 8,
        'sources': [{
            'id': 'fixture', 'label': 'Fixture survey', 'attribution': 'Synthetic fixture',
            'vertical_datum': 'fixture datum', 'survey_dates': ['2000'], 'rights_class': 'public',
            'rights': {'public_display': 'allowed', 'license': 'fixture license'},
        }],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [{
            'source_id': 'fixture', 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 5,
        }]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'sources': [
            {'id': 'fixture', 'resolution_m': 5, 'tiles': 1},
        ]}},
    }


@pytest.fixture
def run_standalone(config_files, tmp_path):
    script = Path('scripts/relief/coast_coverage.py')
    (tmp_path / script).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / script, tmp_path / script)
    for name, value in config_files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def run(*flags):
        # Ignore environment paths and site-packages (including editable installs).
        return subprocess.run([sys.executable, '-E', '-S', str(script), *flags],
                              cwd=tmp_path, capture_output=True, text=True, timeout=10)

    return run


@pytest.mark.parametrize(('flags', 'expected'), [
    pytest.param(['--help'], 'usage: coast_coverage.py', id='help'),
    pytest.param([], 'Configured coast coverage: OK', id='no-flags'),
])
def test_C2_direct_script_without_install(run_standalone, flags, expected):
    """An eager package import must not break direct help or the legacy check."""
    result = run_standalone(*flags)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    assert expected in result.stdout


def test_C2_standalone_pointer_validation_without_jsonschema(run_standalone, catalog_files, pointer):
    """Optional extras must not silence valid pointers or bypass nested schema checks."""
    relief, _ = catalog_files
    path = relief / 'umbrella.json'
    path.write_text(json.dumps(pointer), encoding='utf-8')
    markdown = run_standalone('--markdown')
    assert markdown.returncode == 0, markdown.stderr
    assert '| umbrella | 0123456789ab | none |' in markdown.stdout

    # A nested violation still has a plausible generation and matching region.
    pointer['sources'][0]['rights']['public_display'] = 'denied'
    path.write_text(json.dumps(pointer), encoding='utf-8')
    report = run_standalone('--json')
    assert report.returncode == 0, report.stderr
    assert json.loads(report.stdout)['regions'] == [
        {'id': 'umbrella', 'relief': 'invalid', 'contours': 'none'},
    ]


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
    config_files['regions/umbrella/region.json']['bounds'] = [-125, 35.5, -115, 39]
    assert coast.main([]) == 1
    assert capsys.readouterr() == (
        'Check      | Region(s) / island           | Result\n'
        'Gap        | -                            | 30 to 35.5 N\n'
        'Overlap    | umbrella / crescent-city | 38 to 39 N\n'
        'Island     | channel-islands-north | umbrella\n'
        'Island     | outer-islands-borderland | outside\n'
        'Configured coast coverage: NOT OK\n', '',
    )


def test_C2_json_failure(config_files, catalog_files, capsys):
    """C2: A failed check still emits the full JSON report and returns 1."""
    config_files['regions/umbrella/region.json']['bounds'] = [-125, 32, -115, 35]
    assert coast.main(['--json']) == 1
    out, err = capsys.readouterr()
    assert err == ''
    assert json.loads(out) == {
        'gaps': [[30, 32], [35, 40]], 'overlaps': [], 'beyond': [],
        'islands_inside': {'channel-islands-north': None, 'outer-islands-borderland': 'umbrella'},
        'islands_partial': [],
        'ok': False,
        'regions': [{'id': 'umbrella', 'relief': 'none', 'contours': 'none'}],
    }


@pytest.mark.parametrize('flags, expected', [
    pytest.param([], (
        'Check      | Region(s) / island           | Result\n'
        'Island     | outer-islands-borderland | umbrella\n'
        'Beyond     | umbrella | 1° past south anchor\n'
        'Beyond     | umbrella | 1° past north anchor\n'
        'Island     | channel-islands-north | partial\n'
        'Configured coast coverage: NOT OK\n'
    ), id='C2: table shows both diagnostics'),
    pytest.param(['--markdown'], (
        '| Region | Relief | Contours |\n'
        '| --- | --- | --- |\n'
        '| umbrella | none | none |\n'
        '\n| Check | Region / island | Result |\n'
        '| --- | --- | --- |\n'
        '| Beyond | umbrella | 1° past south anchor |\n'
        '| Beyond | umbrella | 1° past north anchor |\n'
        '| Island | channel-islands-north | partial |\n'
    ), id='C2: Markdown shows both diagnostics'),
    pytest.param(['--json'], {
        'gaps': [], 'overlaps': [],
        'beyond': [{'region': 'umbrella', 'edge': 'south', 'by_deg': 1},
                   {'region': 'umbrella', 'edge': 'north', 'by_deg': 1}],
        'islands_inside': {'channel-islands-north': None, 'outer-islands-borderland': 'umbrella'},
        'islands_partial': ['channel-islands-north'], 'ok': False,
        'regions': [{'id': 'umbrella', 'relief': 'none', 'contours': 'none'}],
    }, id='C2: JSON shows both diagnostics'),
])
def test_C2_formats_report_boundary_findings(config_files, catalog_files, capsys, flags, expected):
    """C2: An output branch must not drop findings or return success for gap-free bounds."""
    config_files['regions/umbrella/region.json']['bounds'] = [-123, 29, -115, 41]
    assert coast.main(flags) == 1
    out, err = capsys.readouterr()
    assert (json.loads(out) if flags == ['--json'] else out, err) == (expected, '')


@pytest.mark.parametrize('argv', [
    pytest.param(['--js'], id='C2: refuse abbreviated flags'),
    pytest.param(['--json', '--markdown'], id='C1: refuse competing output formats'),
])
def test_C2_usage_refusal(config_files, argv):
    """C2: Invalid flags fail with usage status before any coverage report."""
    with pytest.raises(SystemExit) as error:
        coast.main(argv)
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
        'release': {'umbrella': (-125, 30, -115, 40)},
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


def test_C1_markdown_covers_every_release_region(config_files, catalog_files, pointer, capsys):
    """C1: Missing assets must not drop a row; unrelated files must not add one."""
    relief, contours = catalog_files
    config_files['dist/regions/index.json']['regions'].append({'id': 'crescent-city'})
    (relief / 'umbrella.json').write_text(json.dumps(pointer), encoding='utf-8')
    (contours / 'umbrella.geojson').write_text('{"type":"FeatureCollection","features":[]}', encoding='utf-8')
    (contours / 'channel-islands-north.geojson').touch()  # not a release ID
    assert coast.main(['--markdown']) == 0
    assert capsys.readouterr() == (
        '| Region | Relief | Contours |\n'
        '| --- | --- | --- |\n'
        '| crescent-city | none | none |\n'
        '| umbrella | 0123456789ab | present |\n', '',
    )


@pytest.mark.parametrize('defect', [
    pytest.param('schema', id='C2: reject a private pointer even with a valid generation'),
    pytest.param('false-as-number', id='C2: numeric zero is not JSON false'),
    pytest.param('extra-field', id='C2: reject unevaluated top-level fields'),
    pytest.param('duplicate-field', id='C2: reject duplicate members even if the final value is public'),
    pytest.param('malformed', id='C2: report malformed JSON as invalid'),
    pytest.param('wrong-region', id='C2: do not credit a pointer for another region'),
    pytest.param('directory', id='C2: report an unreadable pointer as invalid'),
])
def test_C2_invalid_pointer_is_not_live(catalog_files, pointer, capsys, defect):
    """C2: Invalid is distinct from absent, and contours are checked independently."""
    relief, contours = catalog_files
    path = relief / 'umbrella.json'
    if defect == 'schema':
        pointer['private'] = True
    elif defect == 'false-as-number':
        pointer['private'] = 0
    elif defect == 'extra-field':
        pointer['unexpected'] = True
    elif defect == 'wrong-region':
        pointer['region'] = 'crescent-city'
    if defect == 'directory':
        path.mkdir()
    else:
        body = json.dumps(pointer)
        if defect == 'duplicate-field':
            body = '{"private": true, ' + body[1:]
        path.write_text('{' if defect == 'malformed' else body, encoding='utf-8')
    (contours / 'umbrella.geojson').write_text('{"type":"FeatureCollection","features":[]}', encoding='utf-8')

    assert coast.main(['--json']) == 0
    out, err = capsys.readouterr()
    assert err == ''
    assert json.loads(out) == {
        'gaps': [], 'overlaps': [], 'ok': True,
        'beyond': [], 'islands_partial': [],
        'islands_inside': {'channel-islands-north': 'umbrella', 'outer-islands-borderland': 'umbrella'},
        'regions': [{'id': 'umbrella', 'relief': 'invalid', 'contours': 'present'}],
    }


def test_C2_unusable_schema_refuses_report(catalog_files, capsys):
    """C2: A bad schema is a report error, not a conclusion about a pointer."""
    relief, _ = catalog_files
    (relief / 'pointer.schema.json').write_text('[]', encoding='utf-8')
    assert coast.main(['--json']) == 1
    assert capsys.readouterr() == ('', 'Coast coverage could not be checked: expected a JSON object\n')
