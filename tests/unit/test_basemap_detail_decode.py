"""Excessively nested saved basemap JSON gets a filename-qualified FAIL, not a traceback."""
import json
import subprocess
import sys
from unittest import mock

import pytest

from scripts.basemap import check_detail
from tests._support import ROOT
from tests.unit.test_basemap_detail import settings

NAMES = ('plan.json', 'detail.geojson')
DEEP = {'array': '[' * 100000 + '0' + ']' * 100000,
        'object': '{"x":' * 100000 + '0' + '}' * 100000}
CLI = [sys.executable, '-B', str(ROOT / 'scripts/basemap/check_detail.py')]


def _write(tmp_path, bad_name=None, bad_text=None):
    planned, detail = settings()
    files = {'plan.json': json.dumps(planned), 'detail.geojson': json.dumps(detail)}
    if bad_name:
        files[bad_name] = bad_text
    for name, text in files.items():
        (tmp_path / name).write_text(text)


@pytest.mark.parametrize('name', NAMES)
def test_load_translates_decoder_exhaustion(tmp_path, name):
    (tmp_path / name).write_text('{}')
    original = RecursionError('synthetic decoder exhaustion')
    with mock.patch.object(check_detail.json, 'loads', side_effect=original):
        with pytest.raises(ValueError) as caught:
            check_detail._load(tmp_path / name)
    assert str(caught.value) == f'{name}: JSON nesting exceeds parser limit'
    assert caught.value.__cause__ is original


@pytest.mark.parametrize('name', NAMES)
def test_main_reports_exhaustion_for_target_only(tmp_path, name, capsys):
    _write(tmp_path)
    real = json.loads
    loaded = []

    def fake(text):
        loaded.append(len(text))
        if len(loaded) == NAMES.index(name) + 1:
            raise RecursionError('synthetic')
        return real(text)

    with mock.patch.object(check_detail.json, 'loads', side_effect=fake), \
            mock.patch.object(check_detail, 'check_detail') as checked:
        with pytest.raises(SystemExit) as exit_info:
            check_detail.main(['--dir', str(tmp_path)])
    out = capsys.readouterr()
    assert exit_info.value.code == 1
    assert out.err.endswith(f'FAIL: {name}: JSON nesting exceeds parser limit\n')
    assert out.out == ''
    checked.assert_not_called()
    assert len(loaded) == NAMES.index(name) + 1


@pytest.mark.parametrize('shape', DEEP)
@pytest.mark.parametrize('name', NAMES)
def test_cli_names_deeply_nested_file(tmp_path, name, shape):
    _write(tmp_path, name, DEEP[shape])
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = subprocess.run([*CLI, '--dir', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stdout == ''
    assert 'Traceback' not in result.stderr
    assert result.stderr == f'FAIL: {name}: JSON nesting exceeds parser limit\n'
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_controls_keep_other_refusals_and_pass_output(tmp_path):
    _write(tmp_path, 'plan.json', '[')
    syntax = subprocess.run([*CLI, '--dir', str(tmp_path)], capture_output=True, text=True)
    assert syntax.returncode == 1 and syntax.stdout == ''
    assert syntax.stderr.startswith('FAIL: plan.json: not valid JSON (line 1 column 2)')
    (tmp_path / 'plan.json').unlink()
    missing = subprocess.run([*CLI, '--dir', str(tmp_path)], capture_output=True, text=True)
    assert missing.returncode == 1 and missing.stderr.startswith('FAIL: plan.json: cannot read')
    _write(tmp_path)
    saved = subprocess.run([*CLI, '--dir', str(tmp_path)], capture_output=True, text=True)
    default = subprocess.run(CLI, capture_output=True, text=True)
    assert saved.returncode == 0 and saved.stdout == default.stdout
    assert '22 of 22 regions inside a detail box' in default.stdout
