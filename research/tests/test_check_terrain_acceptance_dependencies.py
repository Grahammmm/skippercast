"""A missing jsonschema stops terrain acceptance up front (audit S4, NEXT-ITERATION item 57).

The checker needs numpy and rasterio in its own interpreter; ``run`` also needs
jsonschema wherever the ``--python`` renderer imports from. A ``sys.modules``
patch cannot reach the renderer subprocess, so the renderer cases use real
environments that lack jsonschema: a fresh venv sharing the checker's resolved
binary, and the checker's own interpreter with jsonschema shadowed on the
renderer's PYTHONPATH. The ``sys.modules`` patch still proves the checker-side
preflight and terrain_only.verify's ValueError.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import types
import venv

import pytest

from research.scripts import check_terrain_acceptance as module
from skippercast.coastal.render import terrain_only

PREFIX = 'jsonschema required: install skippercast[survey] into '
RENDERER_SUFFIX = ' (renderer --python)\n'


@pytest.fixture
def checker_modules(monkeypatch):
    """numpy and rasterio importable, real or stubbed, so the checker preflight passes in
    both the GIS and the non-GIS CI job."""
    for name in ('numpy', 'rasterio'):
        monkeypatch.setitem(sys.modules, name, sys.modules.get(name) or types.ModuleType(name))


@pytest.fixture
def no_jsonschema(monkeypatch, checker_modules):
    monkeypatch.setitem(sys.modules, 'jsonschema', None)


@pytest.fixture
def prep(tmp_path):
    root = tmp_path / 'prep'
    core = root / 'core-a'
    core.mkdir(parents=True)
    (core / 'acceptance.json').write_text('{}')
    return root


@pytest.fixture
def bare_venv(tmp_path):
    """A fresh venv without pip or jsonschema; its python links to the checker's base binary."""
    env_dir = tmp_path / 'renderer-env'
    venv.create(env_dir, with_pip=False, symlinks=True)
    return env_dir, env_dir / 'bin' / 'python'


@pytest.fixture
def shadow_jsonschema(tmp_path):
    """A PYTHONPATH directory whose jsonschema fails to import, as if it were not installed."""
    path = tmp_path / 'shadow'
    (path / 'jsonschema').mkdir(parents=True)
    (path / 'jsonschema' / '__init__.py').write_text("raise ImportError('shadowed for the test')\n")
    return path


def tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))


def run(prep, *extra):
    return module.main(['run', '--prep-root', str(prep), '--expect-cores', '1', *extra])


def test_renderer_venv_sharing_the_resolved_binary_is_probed_before_any_work(checker_modules, prep, bare_venv,
                                                                             capsys):
    env_dir, python = bare_venv
    # Same underlying executable, separate site-packages: round 1 compared resolved paths and let this through.
    assert python.resolve() == Path(sys.executable).resolve()
    before = tree(prep)
    assert run(prep, '--python', str(python), '--pythonpath', str(Path('src').resolve())) == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err.count('\n') == 1
    assert captured.err.startswith(PREFIX) and captured.err.endswith(RENDERER_SUFFIX)
    assert Path(captured.err[len(PREFIX):-len(RENDERER_SUFFIX)]).resolve() == env_dir.resolve()
    assert tree(prep) == before  # no render directory, no receipt
    assert not (prep / 't13-receipt.json').exists()


def test_renderer_environment_not_checker_imports_decides(checker_modules, prep, shadow_jsonschema, capsys):
    import jsonschema  # noqa: F401  (importable here: survey/test extras)
    before = tree(prep)
    assert run(prep, '--pythonpath', str(shadow_jsonschema)) == 2  # default --python: this interpreter
    assert capsys.readouterr().err == f'{PREFIX}{sys.prefix}{RENDERER_SUFFIX}'
    assert tree(prep) == before


def test_renderer_that_cannot_run_is_rejected_before_any_work(checker_modules, prep, tmp_path, capsys):
    before = tree(prep)
    absent = tmp_path / 'absent' / 'python3'
    assert run(prep, '--python', str(absent)) == 2
    assert capsys.readouterr().err == (
        f'renderer --python {absent} cannot run the dependency probe (FileNotFoundError)\n')

    not_python = tmp_path / 'not-python'
    not_python.write_text('#!/bin/sh\nexit 7\n')
    not_python.chmod(0o755)
    assert run(prep, '--python', str(not_python)) == 2
    assert capsys.readouterr().err == f'renderer --python {not_python} cannot run the dependency probe (exit 7)\n'
    assert tree(prep) == before


def test_default_renderer_with_jsonschema_passes_the_probe():
    import jsonschema  # noqa: F401
    args = types.SimpleNamespace(python=sys.executable, pythonpath=str(Path('src').resolve()))
    assert module.probe_renderer(args) == (sys.prefix, [])
    assert module.probe_renderer(args, ('jsonschema', 'no_such_module_sc8c')) == (sys.prefix, ['no_such_module_sc8c'])


def test_probe_runs_the_renderer_python_with_the_render_environment(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs['env']))
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(dict(prefix='/p', missing=[])) + '\n')

    monkeypatch.setattr(module.subprocess, 'run', fake_run)
    args = types.SimpleNamespace(python='/x/python', pythonpath=str(tmp_path))
    assert module.probe_renderer(args) == ('/p', [])
    (command, env), = calls
    assert command[:3] == ['/x/python', '-B', '-c'] and command[4:] == ['jsonschema']
    assert env == module.renderer_env(args)
    assert env['PYTHONPATH'] == str(tmp_path.resolve()) and env['PYTHONDONTWRITEBYTECODE'] == '1'


def test_checker_modules_are_checked_in_process_on_one_line(monkeypatch, prep, capsys):
    for name in ('numpy', 'rasterio'):
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setattr(module, 'probe_renderer', lambda args: pytest.fail('renderer probed after a checker miss'))
    for mode in ('run', 'verify'):
        assert module.main([mode, '--prep-root', str(prep)]) == 2
        assert capsys.readouterr().err == f'numpy, rasterio required: install skippercast[survey] into {sys.prefix}\n'


def test_preflight_runs_before_argument_checks_touch_the_prep_root(checker_modules, tmp_path, bare_venv, capsys):
    _, python = bare_venv
    missing = tmp_path / 'absent'
    assert module.main(['run', '--prep-root', str(missing), '--python', str(python)]) == 2
    assert capsys.readouterr().err.startswith(PREFIX)
    assert not missing.exists()


def test_verify_mode_proceeds_without_jsonschema(no_jsonschema, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(module, 'probe_renderer', lambda args: pytest.fail('verify mode probed the renderer'))
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
