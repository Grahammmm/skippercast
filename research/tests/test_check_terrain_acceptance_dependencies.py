"""A missing jsonschema stops terrain acceptance up front (audit S4, NEXT-ITERATION item 57)."""
from datetime import datetime, timezone
import json
import sys
import types

import pytest

from research.scripts import check_terrain_acceptance as module
from skippercast.coastal.render import terrain_only


@pytest.fixture
def no_jsonschema(monkeypatch):
    """jsonschema unimportable; numpy and rasterio importable, real or stubbed, so the
    preflight line names only jsonschema in both the GIS and the non-GIS CI job."""
    monkeypatch.setitem(sys.modules, 'jsonschema', None)
    for name in ('numpy', 'rasterio'):
        monkeypatch.setitem(sys.modules, name, sys.modules.get(name) or types.ModuleType(name))


@pytest.fixture
def prep(tmp_path):
    core = tmp_path / 'core-a'
    core.mkdir()
    (core / 'acceptance.json').write_text('{}')
    return tmp_path


def tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))


def test_run_preflight_names_jsonschema_and_exits_before_any_work(no_jsonschema, prep, capsys):
    before = tree(prep)
    assert module.main(['run', '--prep-root', str(prep), '--expect-cores', '1']) == 2
    captured = capsys.readouterr()
    assert captured.err == f'jsonschema required: install skippercast[survey] into {sys.prefix}\n'
    assert captured.out == ''
    assert tree(prep) == before  # no render directory, no receipt


def test_preflight_runs_before_argument_checks_touch_the_prep_root(no_jsonschema, tmp_path, capsys):
    missing = tmp_path / 'absent'
    assert module.main(['run', '--prep-root', str(missing)]) == 2
    assert capsys.readouterr().err.startswith('jsonschema required: ')
    assert not missing.exists()


def test_preflight_names_every_missing_module_on_one_line(monkeypatch, prep, capsys):
    for name in ('numpy', 'rasterio', 'jsonschema'):
        monkeypatch.setitem(sys.modules, name, None)
    assert module.main(['run', '--prep-root', str(prep)]) == 2
    err = capsys.readouterr().err
    assert err == f'numpy, rasterio, jsonschema required: install skippercast[survey] into {sys.prefix}\n'
    assert err.count('\n') == 1


def test_verify_mode_and_another_renderer_python_do_not_need_jsonschema_here():
    parse = lambda mode, python: types.SimpleNamespace(mode=mode, python=python)  # noqa: E731
    assert module.preflight_modules(parse('run', sys.executable)) == ['numpy', 'rasterio', 'jsonschema']
    assert module.preflight_modules(parse('verify', sys.executable)) == ['numpy', 'rasterio']
    # The renderer on another interpreter reports its own terrain_only_dependency:jsonschema hold.
    assert module.preflight_modules(parse('run', '/nonexistent/python3')) == ['numpy', 'rasterio']


def test_verify_mode_proceeds_without_jsonschema(no_jsonschema, tmp_path, capsys):
    # No cores: the run reaches the verdict (FAIL, wrong core count) instead of the preflight exit.
    assert module.main(['verify', '--prep-root', str(tmp_path), '--expect-cores', '1']) == 1
    assert capsys.readouterr().err == ''


def test_terrain_only_verify_raises_value_error_not_module_not_found(no_jsonschema, tmp_path):
    with pytest.raises(ValueError, match=r'^terrain_only_dependency:jsonschema$') as raised:
        terrain_only.verify(tmp_path, {}, now=datetime.now(timezone.utc))
    assert not isinstance(raised.value, ImportError)
    assert isinstance(raised.value.__cause__, ImportError)


def test_terrain_only_cli_reports_the_dependency_as_a_hold(no_jsonschema, tmp_path, capsys):
    acceptance = tmp_path / 'acceptance.json'
    acceptance.write_text('{}')
    code = terrain_only.main(['--root', str(tmp_path), '--acceptance', str(acceptance), '--output-dir', 'render'])
    assert code == 2
    result = json.loads(capsys.readouterr().out)
    assert (result['state'], result['holds']) == ('held', ['terrain_only_dependency:jsonschema'])
    assert not (tmp_path / 'render').exists()
