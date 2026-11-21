"""Numbered offline CLI acceptance for the R8 depth supplement."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.relief import review_supplement
from skippercast.relief import receipts
from tests._support import ROOT
from tests.unit import test_relief_package as fixture
from tests.unit.test_r8_packet import _snapshot, build  # noqa: F401 (pytest fixture)
from tests.unit.test_relief_package import assembly  # noqa: F401 (pytest fixture)

_REGION = 'fixture-west'
_HEADING = 'Depth coverage fixture-west (supplement only)\n'
_ROWS = (
    '  depth: reaches_300ft=true deepest_ft=320\n'
    '  depth 0-66ft: measured=66.7% estimated=0.0% unsurveyed=33.3%\n'
    '  depth 66-300ft: measured=5.0% estimated=30.0% unsurveyed=65.0%\n'
    '  depth unknown-band: measured=n/a estimated=n/a unsurveyed=n/a\n'
)


def _report(**changes):
    return {
        'deepest_m': 97.536,
        'reaches_300ft': True,
        'bands': {
            'unknown-band': dict(measured_m2=0, estimated_m2=0, unsurveyed_m2=0),
            '66-300ft': dict(measured_m2=1, estimated_m2=6, unsurveyed_m2=13),
            '0-66ft': dict(measured_m2=2, estimated_m2=0, unsurveyed_m2=1),
        },
        **changes,
    }


def _write_report(out, region=_REGION, **changes):
    path = out / region / 'coverage' / 'depth-coverage.json'
    fixture.write_json(path, _report(region=region, coarse_sha256=None, **changes))
    return path


def _observe(out, capsys, *args):
    capsys.readouterr()
    code = review_supplement.main(['--out', str(out), *(args or (_REGION,))])
    return code, *capsys.readouterr()


def test_C1_two_regions_use_each_band_total_and_keep_argument_order(tmp_path, capsys):
    """C1: Catch a global denominator, wrong feet conversion, or mixed region rows."""
    east = _report()['bands']
    east['unknown-band']['unsurveyed_m2'] = 25
    _write_report(tmp_path, 'fixture-east', bands=east, deepest_m=None, reaches_300ft=False)
    _write_report(tmp_path)
    assert _observe(tmp_path, capsys, 'fixture-east', _REGION) == (0, (
        'Depth coverage fixture-east (supplement only)\n'
        '  depth: reaches_300ft=false deepest_ft=unknown\n'
        '  depth 0-66ft: measured=66.7% estimated=0.0% unsurveyed=33.3%\n'
        '  depth 66-300ft: measured=5.0% estimated=30.0% unsurveyed=65.0%\n'
        '  depth unknown-band: measured=0.0% estimated=0.0% unsurveyed=100.0%\n'
        + _HEADING + _ROWS
    ), '')


def test_C2_missing_does_not_stop_next_region(tmp_path, capsys):
    """C2: Catch aborting or granting a verdict when a report is missing."""
    _write_report(tmp_path)
    assert _observe(tmp_path, capsys, 'fixture-missing', _REGION) == (0, (
        'Depth coverage fixture-missing (supplement only)\n'
        '  depth: not computed (run region.py depth-coverage)\n'
        + _HEADING + _ROWS
    ), '')
    assert not (tmp_path / 'fixture-missing').exists()


@pytest.mark.parametrize(('change', 'reason'), [
    pytest.param(b'{', 'Expecting property name enclosed in double quotes: line 1 column 2 (char 1)',
                 id='C2: malformed JSON'),
    pytest.param(b'[]', 'expected a JSON object', id='C2: wrong JSON shape'),
    pytest.param({'region': 'other'}, 'report region does not match', id='C2: wrong region'),
    pytest.param({'reaches_300ft': 'false'}, 'reaches_300ft must be a boolean', id='C2: string flag'),
    pytest.param(b'{"reaches_300ft":false}', 'missing deepest_m', id='C2: missing depth'),
    pytest.param({'deepest_m': -2}, 'deepest_m must be a finite nonnegative depth or null', id='C2: bad depth'),
    pytest.param({'deepest_m': 1e308}, 'deepest_m must be a finite nonnegative depth or null', id='C2: depth overflow'),
    pytest.param({'bands': {}}, 'expected 0-66ft, 66-300ft and unknown-band in bands', id='C2: missing bands'),
    pytest.param({'bands': _report()['bands'] | {'0-66ft': []}},
                 '0-66ft areas must be finite nonnegative numbers', id='C2: wrong band shape'),
    pytest.param({'bands': _report()['bands'] | {'0-66ft': {'measured_m2': True}}},
                 '0-66ft areas must be finite nonnegative numbers', id='C2: malformed area'),
    pytest.param({'bands': _report()['bands'] | {'0-66ft': dict(measured_m2=1e308, estimated_m2=1e308, unsurveyed_m2=0)}},
                 '0-66ft total must be finite', id='C2: nonfinite total'),
    pytest.param({'mosaic_generation': 'latest'}, 'invalid mosaic_generation', id='C2: malformed mosaic hash'),
])
def test_C2_malformed_report_has_no_partial_rows(tmp_path, capsys, change, reason):
    """C2: Catch accepting malformed data or printing partial depth rows before refusing."""
    path = _write_report(tmp_path)
    if isinstance(change, bytes):
        path.write_bytes(change)
    else:
        fixture.write_json(path, json.loads(path.read_bytes()) | change)
    assert _observe(tmp_path, capsys) == (0, _HEADING + f'  depth: invalid report ({reason})\n', '')


def test_C2_unreadable_report_is_not_missing(tmp_path, capsys, monkeypatch):
    """C2: Catch classifying a read failure as not computed or returning nonzero."""
    path = _write_report(tmp_path)
    read_bytes = Path.read_bytes

    def deny_report(self):
        if self == path:
            raise PermissionError('permission denied')
        return read_bytes(self)

    monkeypatch.setattr(Path, 'read_bytes', deny_report)
    assert _observe(tmp_path, capsys) == (0, _HEADING + '  depth: invalid report (permission denied)\n', '')


def test_C2_directory_is_not_a_report(tmp_path, capsys):
    """C2: Catch treating a non-file at the report path as missing."""
    (tmp_path / _REGION / 'coverage' / 'depth-coverage.json').mkdir(parents=True)
    assert _observe(tmp_path, capsys) == (0, _HEADING + '  depth: invalid report (expected a file)\n', '')


def _mosaic(region, code_digest):
    def write_elevation(output):
        (output / 'elevation.tif').write_bytes(b'stub')

    run = receipts.StageRun(region, 'mosaic', write_elevation, code_digest, scope='public', target='mosaic/public')
    result = receipts.run_stage(run)
    assert result.state == 'ok'
    return result.generation


def test_C2_compares_against_packaged_mosaic_not_live_generation(build, capsys, monkeypatch):  # noqa: F811
    """C2: Catch comparing to package SHA, using the live mosaic, or following a moved tile receipt."""
    out, make = build
    original_inputs = fixture.inputs
    packaged = None

    def write_tiles(output):
        for layer, content in fixture.LAYERS.items():
            path = output / layer.removeprefix('layers/public/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def rebuild_tiles(region):
        assert receipts.run_stage(receipts.StageRun(
            region, 'tiles', write_tiles, 'e' * 64, scope='public', target='layers/public',
            upstream=[receipts.Ref('mosaic', 'public')],
        )).state == 'ok'

    def inputs(root):
        nonlocal packaged
        region, manifest = original_inputs(root)
        packaged = _mosaic(region, 'a' * 64)
        rebuild_tiles(region)
        return region, manifest

    monkeypatch.setattr(fixture, 'inputs', inputs)
    region, *_ = make(_REGION)
    assert packaged
    live = _mosaic(region, 'b' * 64)
    assert live and live != packaged

    _write_report(out, mosaic_generation=packaged)
    assert _observe(out, capsys) == (0, _HEADING + _ROWS, '')
    _write_report(out, mosaic_generation=live)
    assert _observe(out, capsys) == (0, _HEADING + f'  depth: stale (mosaic {live[:12]})\n', '')
    rebuild_tiles(region)
    _write_report(out, mosaic_generation=packaged)
    assert _observe(out, capsys) == (0, _HEADING + _ROWS, '')


@pytest.mark.parametrize(('args', 'error'), [
    (['fixture-west'], 'the following arguments are required: --out'),
    (['--out', 'out'], 'the following arguments are required: REGION'),
    (['--out', 'out', '../escape'], "invalid region id '../escape'"),
    (['--out', 'out', 'one', 'two', 'three', 'four'], 'expected at most 3 regions'),
], ids=['C2: no output path', 'C2: no region', 'C2: invalid region', 'C2: too many regions'])
def test_C2_usage_refuses_before_printing(args, error, capsys):
    """C2: Catch relaxing the packet's CLI constraints or returning success on bad usage."""
    with pytest.raises(SystemExit) as exc:
        review_supplement.main(args)
    assert type(exc.value) is SystemExit and exc.value.code == 2
    assert capsys.readouterr() == ('', (
        'usage: review_supplement.py [-h] --out OUT [--markdown] REGION [REGION ...]\n'
        f'review_supplement.py: error: {error}\n'
    ))


def test_C3_direct_script_markdown_is_read_only(tmp_path):
    """C3: Catch broken sibling imports, non-packet Markdown, or writes during review."""
    _write_report(tmp_path, mosaic_generation='a' * 64)
    before = _snapshot(tmp_path)
    result = subprocess.run([
        sys.executable, str(ROOT / 'scripts/relief/review_supplement.py'), '--out', str(tmp_path),
        '--markdown', _REGION, 'fixture-missing',
    ], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert (result.returncode, result.stdout, result.stderr) == (0, (
        '| Field | Value |\n'
        '| --- | --- |\n'
        '| Depth coverage fixture-west (supplement only) |  |\n'
        '| depth | reaches_300ft=true deepest_ft=320 |\n'
        '| depth 0-66ft | measured=66.7% estimated=0.0% unsurveyed=33.3% |\n'
        '| depth 66-300ft | measured=5.0% estimated=30.0% unsurveyed=65.0% |\n'
        '| depth unknown-band | measured=n/a estimated=n/a unsurveyed=n/a |\n\n'
        '| Field | Value |\n'
        '| --- | --- |\n'
        '| Depth coverage fixture-missing (supplement only) |  |\n'
        '| depth | not computed (run region.py depth-coverage) |\n\n'
    ), '')
    assert _snapshot(tmp_path) == before
