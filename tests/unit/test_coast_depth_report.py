import json
import subprocess
import sys

import pytest

from scripts.relief import coast_depth_report as coast
from tests._support import ROOT


def _write_report(out, region, shallow, deep, *, reaches=False, claimed_region=None):
    def areas(values):
        return dict(zip(('measured_m2', 'estimated_m2', 'unsurveyed_m2'), values))

    path = out / region / 'coverage' / 'depth-coverage.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        'region': region if claimed_region is None else claimed_region,
        'bands': {
            '0-66ft': areas(shallow), '66-300ft': areas(deep), 'unknown-band': areas((0, 0, 900)),
        },
        'reaches_300ft': reaches,
        'deepest_m': 100 if reaches else 60,
        'mosaic_generation': 'synthetic',
        'coarse_sha256': None,
    }), encoding='utf-8')
    return path


def _summary(shallow, deep, reaches):
    keys = ('measured_m2', 'estimated_m2', 'unsurveyed_m2', 'measured_pct', 'estimated_pct', 'unsurveyed_pct')
    return {'bands': {'0-66ft': dict(zip(keys, shallow)), '66-300ft': dict(zip(keys, deep))},
            'reaches_300ft': reaches}


EMPTY_BAND = (0, 0, 0, None, None, None)


def test_c1_default_json_sums_areas_before_calculating_percentages(tmp_path, capsys):
    """C1: Unequal region sizes expose averaging percentages or counting unknown-band area."""
    _write_report(tmp_path, 'b', (0, 7, 1), (19, 8, 9))
    _write_report(tmp_path, 'a', (1, 1, 1), (1, 2, 1), reaches=True)
    (tmp_path / 'not-reported').mkdir()

    assert coast.main(['--out', str(tmp_path), '--json']) == 0
    captured = capsys.readouterr()
    assert captured.err == ''
    assert json.loads(captured.out) == {
        'regions': [
            {'region': 'a', **_summary((1, 1, 1, 33.3, 33.3, 33.3), (1, 2, 1, 25.0, 50.0, 25.0), True)},
            {'region': 'b', **_summary((0, 7, 1, 0.0, 87.5, 12.5), (19, 8, 9, 52.8, 22.2, 25.0), False)},
        ],
        'total': _summary((1, 8, 2, 9.1, 72.7, 18.2), (20, 10, 10, 50.0, 25.0, 25.0), True),
    }


def test_c1_explicit_cli_table_lists_missing_and_excludes_unselected(tmp_path):
    """C1: Explicit selection must not count other reports or silently drop missing regions."""
    _write_report(tmp_path, 'a', (0.5, 0, 2), (0, 0, 0))
    _write_report(tmp_path, 'b', (200, 0, 0), (1, 0, 0), reaches=True)
    result = subprocess.run([
        sys.executable, str(ROOT / 'scripts/relief/coast_depth_report.py'),
        '--out', str(tmp_path), 'missing', 'a', 'a',
    ], capture_output=True, text=True, check=True)
    assert (result.returncode, result.stderr, result.stdout) == (0, '',
        'Region | Reaches 300 ft | 0-66ft measured m² (%) | 0-66ft estimated m² (%) | '
        '0-66ft unsurveyed m² (%) | 66-300ft measured m² (%) | 66-300ft estimated m² (%) | '
        '66-300ft unsurveyed m² (%)\n'
        'missing | no report\n'
        'a | no | 0.5 (20.0%) | 0 (0.0%) | 2 (80.0%) | 0 (n/a) | 0 (n/a) | 0 (n/a)\n'
        'TOTAL | no | 0.5 (20.0%) | 0 (0.0%) | 2 (80.0%) | 0 (n/a) | 0 (n/a) | 0 (n/a)\n'
    )


@pytest.mark.parametrize(('regions', 'rows'), [
    pytest.param([], [], id='C1: no reports discovered'),
    pytest.param(['missing'], [{'region': 'missing', 'status': 'no report'}], id='C1: all requested reports missing'),
])
def test_c1_no_reports_do_not_claim_measured_zero_percent(tmp_path, capsys, regions, rows):
    """C1: No input must not divide by zero or claim a negative reach verdict."""
    assert coast.main(['--out', str(tmp_path), '--json', *regions]) == 0
    captured = capsys.readouterr()
    assert captured.err == ''
    assert json.loads(captured.out) == {'regions': rows, 'total': _summary(EMPTY_BAND, EMPTY_BAND, None)}


def _snapshot(root):
    return {path.relative_to(root): (path.stat().st_mtime_ns, None if path.is_dir() else path.read_bytes())
            for path in [root, *root.rglob('*')]}


def test_c2_read_only_even_with_a_missing_report(tmp_path, capsys):
    """C2: Aggregating must neither refresh an input file nor create a report or directory."""
    _write_report(tmp_path, 'a', (2, 0, 0), (0, 0, 3), reaches=True)
    before = _snapshot(tmp_path)
    assert coast.main(['--out', str(tmp_path), '--json', 'a', 'missing']) == 0
    captured = capsys.readouterr()
    assert captured.err == ''
    expected = _summary((2, 0, 0, 100.0, 0.0, 0.0), (0, 0, 3, 0.0, 0.0, 100.0), True)
    assert json.loads(captured.out) == {
        'regions': [{'region': 'a', **expected}, {'region': 'missing', 'status': 'no report'}],
        'total': expected,
    }
    assert _snapshot(tmp_path) == before


def test_c2_directory_mismatch_refuses_without_partial_output(tmp_path, capsys):
    """C2: A valid-looking report copied to another region must never enter the total."""
    _write_report(tmp_path, 'a', (1, 0, 0), (0, 0, 1))
    path = _write_report(tmp_path, 'b', (8, 0, 0), (0, 0, 9), claimed_region='a')
    message = f"{path}: region 'a' does not match directory 'b'"
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError) as exc:
        coast.summarize(tmp_path)
    assert type(exc.value) is ValueError
    assert str(exc.value) == message
    assert coast.main(['--out', str(tmp_path), '--json']) == 1
    assert capsys.readouterr() == ('', f'coast_depth_report: {message}\n')
    assert _snapshot(tmp_path) == before


def test_c2_rejects_region_path_in_place_of_directory_id(tmp_path, capsys):
    """C2: A selector must not escape the report root."""
    with pytest.raises(SystemExit) as exc:
        coast.main(['--out', str(tmp_path), '../a'])
    assert (type(exc.value), exc.value.code) == (SystemExit, 2)
    output = capsys.readouterr()
    assert output.out == ''
    assert output.err.splitlines()[-1].endswith("expected a region directory name, got '../a'")
