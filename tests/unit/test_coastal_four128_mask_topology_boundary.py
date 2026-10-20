"""SC-5b pre-scan: the reviewed source/import boundary, in cold processes.

Each case builds a throwaway git code root holding the exact mask-topology
script, the exact reviewed source guard and an INSTRUMENTED stand-in for the
shared pins (profiles.py writes a marker file when imported). The script is then
run as the live command runs it (python -I -B ... scan/plan). A refusal must
happen before the marker exists, i.e. before any project code executes, and long
before any source path is touched. HOME points into the temporary directory, so
the default project root is never the real data repository; no BAG is involved.
"""
import json
import os
import subprocess
import sys

import pytest

from research.scripts import coastal_four128_mask_topology as topo
from tests._support import ROOT

SCRIPT = 'research/scripts/coastal_four128_mask_topology.py'
GIT = ['git', '-c', 'user.name=boundary-test', '-c', 'user.email=boundary@test.invalid',
       '-c', 'commit.gpgsign=false', '-c', 'init.defaultBranch=main']


def environment(tmp_path):
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    return dict(PATH=os.environ.get('PATH', '/usr/bin:/bin'), HOME=str(home), GIT_CONFIG_NOSYSTEM='1',
                GIT_CONFIG_GLOBAL=os.devnull, LANG='C.UTF-8')


def build(tmp_path):
    root = tmp_path / 'code'
    marker = tmp_path / 'project-code-executed'
    pins = repr([list(w) for w in topo.WINDOWS])
    files = {
        SCRIPT: (ROOT / SCRIPT).read_text(),
        topo.GUARD_RELATIVE: (ROOT / topo.GUARD_RELATIVE).read_text(),
        'research/scripts/coastal_four128_resources.py': '',
        'src/skippercast/__init__.py': '',
        'src/skippercast/coastal/__init__.py': '',
        'src/skippercast/coastal/authenticated_v1/__init__.py': '',
        'src/skippercast/coastal/coordinator/__init__.py': '',
        'src/skippercast/coastal/authenticated_v1/profiles.py':
            'from pathlib import Path\nPath(%r).write_text("executed")\nPARTIAL_WINDOWS = %s\n' % (str(marker), pins),
        'src/skippercast/coastal/coordinator/ordered_trial.py': 'PARTIAL_BOUNDS = %r\n' % (list(topo.BOUNDS),),
        '.gitignore': '__pycache__/\n*.pyc\n',
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    env = environment(tmp_path)
    for argv in (['init', '-q'], ['add', '-A'], ['commit', '-q', '-m', 'fake reviewed head']):
        subprocess.run([*GIT, '-C', str(root), *argv], check=True, env=env, capture_output=True)
    head = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], check=True, env=env,
                          capture_output=True, text=True).stdout.strip()
    return root, marker, head


def commit(tmp_path, root, message):
    env = environment(tmp_path)
    subprocess.run([*GIT, '-C', str(root), 'add', '-A'], check=True, env=env, capture_output=True)
    subprocess.run([*GIT, '-C', str(root), 'commit', '-q', '-m', message], check=True, env=env, capture_output=True)
    return subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], check=True, env=env,
                          capture_output=True, text=True).stdout.strip()


def invoke(tmp_path, root, *args, flags=('-I', '-B')):
    # A missing amendment: the first check AFTER the project imports, so a run that
    # gets that far proves the boundary passed, and nothing beyond it ever runs.
    amendment = tmp_path / 'missing-amendment.json'
    argv = [sys.executable, *flags, str(root / SCRIPT), *args, '--amendment', str(amendment)]
    return subprocess.run(argv, env=environment(tmp_path), capture_output=True, text=True, timeout=60,
                          cwd=str(tmp_path))


def assert_refused_before_import(result, marker, message):
    assert result.returncode != 0, result.stdout
    assert message in result.stderr, result.stderr
    assert not marker.exists(), 'project code executed before the refusal'


def no_outputs(tmp_path):
    return not any((tmp_path / 'home').rglob('outputs'))


def test_control_clean_exact_head_reaches_the_first_post_import_check(tmp_path):
    root, marker, head = build(tmp_path)
    result = invoke(tmp_path, root, 'scan', '--code-head', head)
    assert result.returncode != 0 and 'bounded regular signed amendment file required' in result.stderr, result.stderr
    assert marker.read_text() == 'executed'  # the instrumentation does detect an import
    assert no_outputs(tmp_path)
    marker.unlink()
    result = invoke(tmp_path, root, 'plan')
    assert 'bounded regular signed amendment file required' in result.stderr and marker.exists()


def test_wrong_head_refuses_before_any_project_import(tmp_path):
    root, marker, head = build(tmp_path)
    for wrong in ('0' * 40, head[:12], head.upper()):
        assert_refused_before_import(invoke(tmp_path, root, 'scan', '--code-head', wrong), marker,
                                     'exact clean reviewed head')
    assert no_outputs(tmp_path)


@pytest.mark.parametrize('dirt', ['tracked', 'untracked', 'ignored-src-cache', 'ignored-scripts-pyc',
                                  'untracked-module'])
def test_dirty_tree_refuses_before_any_project_import(tmp_path, dirt):
    root, marker, head = build(tmp_path)
    if dirt == 'tracked':
        profiles = root / 'src/skippercast/coastal/authenticated_v1/profiles.py'
        profiles.write_text(profiles.read_text() + '# unreviewed edit\n')
    elif dirt == 'untracked':
        (root / 'research/scripts/extra.py').write_text('')
    elif dirt == 'ignored-src-cache':
        cache = root / 'src/skippercast/coastal/authenticated_v1/__pycache__'
        cache.mkdir()
        (cache / 'profiles.cpython-312.pyc').write_bytes(b'stale bytecode')
    elif dirt == 'ignored-scripts-pyc':
        (root / 'research/scripts/coastal_four128_resources.pyc').write_bytes(b'stale bytecode')
    else:
        (root / 'src/skippercast/coastal/shadow.py').write_text('')
    assert_refused_before_import(invoke(tmp_path, root, 'scan', '--code-head', head), marker,
                                 'exact clean reviewed head')
    assert no_outputs(tmp_path)


@pytest.mark.parametrize('tree', ['src/skippercast/coastal', 'research/scripts'])
def test_committed_symlink_passes_git_but_the_source_guard_refuses(tmp_path, tree):
    root, marker, _ = build(tmp_path)
    (root / tree / 'linked.py').symlink_to(root / 'src/skippercast/__init__.py')
    head = commit(tmp_path, root, 'reviewed symlink')  # clean per git: only the guard can catch it
    assert_refused_before_import(invoke(tmp_path, root, 'scan', '--code-head', head), marker,
                                 'project source symlink/compiled bytecode forbidden')
    assert_refused_before_import(invoke(tmp_path, root, 'plan'), marker,
                                 'project source symlink/compiled bytecode forbidden')
    assert no_outputs(tmp_path)


def test_plan_guards_ignored_bytecode_before_any_project_import(tmp_path):
    root, marker, _ = build(tmp_path)
    cache = root / 'src/skippercast/__pycache__'
    cache.mkdir()
    assert_refused_before_import(invoke(tmp_path, root, 'plan'), marker, 'project compiled bytecode forbidden')


@pytest.mark.parametrize('flags', [(), ('-B',), ('-I',)])
def test_scan_requires_an_isolated_bytecode_free_interpreter(tmp_path, flags):
    root, marker, head = build(tmp_path)
    assert_refused_before_import(invoke(tmp_path, root, 'scan', '--code-head', head, flags=flags), marker,
                                 'python -I -B')


def test_the_plan_command_is_the_isolated_bytecode_free_form():
    text = (ROOT / SCRIPT).read_text()
    assert 'scan = [python, "-I", "-B", str(Path(__file__).resolve()), "scan"' in text
    assert json.dumps(topo.IMPORTED_TREES) == '["src/skippercast", "research/scripts"]'
