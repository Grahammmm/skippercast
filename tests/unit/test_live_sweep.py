import json
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts.relief import live_sweep
from tests._support import ROOT


@pytest.fixture
def sweep(tmp_path, monkeypatch):
    repo = tmp_path / 'input clone'
    catalog = repo / 'catalog' / 'relief'
    catalog.mkdir(parents=True)
    (catalog / 'pointer.schema.json').write_text('{}')
    (catalog / 'README.md').write_text('catalog')
    out = tmp_path / 'output'
    replies = {}
    calls = []

    def live_check(argv, *, check):
        run_out = Path(argv[9])
        region = argv[5]
        base = replies[region][2]
        assert argv == [sys.executable, '-B', str(ROOT / 'scripts/relief/region.py'),
                        'live-check', '--region', region, '--repo', str(repo), '--out',
                        str(run_out), *([] if base is None else [f'--base={base}'])]
        assert check is False
        assert run_out.parent == out
        calls.append(region)
        code, body, _ = replies[region]
        if isinstance(code, OSError):
            raise code
        if body is not None:
            receipt = run_out / region / 'live' / ('a' * 64) / 'live.json'
            receipt.parent.mkdir(parents=True)
            receipt.write_text(body)
        return subprocess.CompletedProcess(argv, code)

    monkeypatch.setattr(live_sweep, 'subprocess', SimpleNamespace(run=live_check))

    def add(region, code=0, requests=4, *, base=None, receipt=True):
        (catalog / f'{region}.json').write_text('{"status":"reviewed"}')
        body = json.dumps(dict(region=region, verdict='PASS' if code == 0 else 'FAIL',
                               requests=requests))
        replies[region] = (code, body if receipt else None, base)

    return SimpleNamespace(repo=repo, catalog=catalog, out=out, add=add, calls=calls,
                           replies=replies, argv=['--repo', str(repo), '--out', str(out)])


def test_c1_all_pass(sweep, capsys):
    """C1: Use pointer filenames in sorted order and print each receipt's count."""
    sweep.add('zeta', requests=20)
    sweep.add('alpha', requests=3)
    assert live_sweep.main(sweep.argv) == 0
    assert sweep.calls == ['alpha', 'zeta']
    assert capsys.readouterr() == ('region verdict requests\nalpha PASS 3\nzeta PASS 20\nALL PASS\n', '')


def test_c1_empty_catalog(sweep, capsys):
    """C1: A schema-only catalog does not launch a live check or create OUT."""
    assert (live_sweep.main(sweep.argv), sweep.calls, sweep.out.exists()) == (0, [], False)
    assert capsys.readouterr() == ('region verdict requests\nALL PASS\n', '')


def test_c2_continues_and_only_prints_rollback(sweep, capsys):
    """C2: A failed verdict and a refused check cannot stop later regions or execute rollback."""
    base = 'https://example.test'
    sweep.add('broken', 1, 8, base=base)
    sweep.add('refused', 2, base=base, receipt=False)
    sweep.add('working', 0, 5, base=base)
    stale = sweep.out / 'broken' / 'live' / ('a' * 64) / 'live.json'
    stale.parent.mkdir(parents=True)
    stale.write_text('{"region":"broken","verdict":"FAIL","requests":1}')
    before = {p: p.read_bytes() for p in sweep.catalog.iterdir()}
    assert live_sweep.main([*sweep.argv, '--base', base]) == 1
    assert sweep.calls == ['broken', 'refused', 'working']
    clone = shlex.quote(str(sweep.repo))
    python = shlex.quote(sys.executable)
    cli = shlex.quote(str(ROOT / 'scripts/relief/region.py'))
    assert capsys.readouterr() == (
        'region verdict requests\nbroken FAIL 8\nrefused FAIL -\nworking PASS 5\n'
        f'{python} {cli} rollback --region broken --repo {clone}\n'
        f'{python} {cli} rollback --region refused --repo {clone}\n'
        'FAIL regions: broken, refused\n',
        'refused: live-check exited 2\n',
    )
    assert stale.read_text() == '{"region":"broken","verdict":"FAIL","requests":1}'
    assert {p: p.read_bytes() for p in sweep.catalog.iterdir()} == before


def test_c2_printed_rollback_runs_outside_checkout(sweep, capsys, tmp_path, monkeypatch):
    """The copied command finds its CLI even from another directory and with spaces."""
    cli = tmp_path / 'cli with spaces' / 'region.py'
    cli.parent.mkdir()
    cli.symlink_to(ROOT / 'scripts/relief/region.py')
    monkeypatch.setattr(live_sweep, '_REGION_CLI', cli)
    sweep.add('broken', 1)
    # The live-check stub normally expects the original CLI path.
    monkeypatch.setattr(live_sweep, '_check_region', lambda *args: ('FAIL', 1))
    assert live_sweep.main(sweep.argv) == 1
    command = capsys.readouterr().out.splitlines()[2]
    result = subprocess.run([*shlex.split(command), '--help'], cwd=tmp_path,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert 'rollback' in result.stdout


@pytest.mark.parametrize(('code', 'body', 'error'), [
    pytest.param(FileNotFoundError('cannot launch'), None, 'cannot launch', id='C2: launcher error'),
    pytest.param(0, None, 'expected exactly one fresh live-check receipt', id='C2: missing receipt'),
    pytest.param(0, '{"region":"alpha","verdict":"PASS","requests":true}',
                 'invalid live-check receipt', id='C2: invalid receipt'),
])
def test_c2_unusable_outcome(sweep, capsys, code, body, error):
    """C2: Neither launch failure nor absent/unusable evidence is reported as PASS."""
    sweep.add('alpha')
    sweep.replies['alpha'] = (code, body, None)
    assert live_sweep.main(sweep.argv) == 1
    assert capsys.readouterr() == (
        'region verdict requests\nalpha FAIL -\n'
        f'{shlex.quote(sys.executable)} {shlex.quote(str(ROOT / "scripts/relief/region.py"))} '
        f'rollback --region alpha --repo {shlex.quote(str(sweep.repo))}\n'
        'FAIL regions: alpha\n', f'alpha: {error}\n',
    )


def test_c2_refuses_output_alias_into_clone(sweep, capsys, tmp_path):
    """C2: A symlink cannot route sweep writes into the clone."""
    sweep.add('alpha')
    alias = tmp_path / 'alias'
    alias.symlink_to(sweep.repo, target_is_directory=True)
    assert live_sweep.main(['--repo', str(sweep.repo), '--out', str(alias / 'output')]) == 2
    assert sweep.calls == []
    assert not (sweep.repo / 'output').exists()
    assert capsys.readouterr() == ('', 'live_sweep.py: OUT must stay outside --repo\n')


def test_c1_refuses_missing_catalog(sweep, capsys, tmp_path):
    """C1: An invalid clone path cannot produce an empty all-pass report."""
    missing = tmp_path / 'missing'
    assert live_sweep.main(['--repo', str(missing), '--out', str(sweep.out)]) == 2
    assert (sweep.calls, sweep.out.exists()) == ([], False)
    assert capsys.readouterr() == (
        '', "live_sweep.py: [Errno 2] No such file or directory: "
            f"'{missing / 'catalog' / 'relief'}'\n",
    )


@pytest.mark.parametrize('flag', [
    pytest.param('--repo', id='C1: repo required'),
    pytest.param('--out', id='C1: out required'),
])
def test_c1_required_arguments(sweep, flag):
    """C1: Missing required paths are refused without launching anything."""
    index = sweep.argv.index(flag)
    with pytest.raises(SystemExit) as exc:
        live_sweep.main(sweep.argv[:index] + sweep.argv[index + 2:])
    assert (type(exc.value), exc.value.code, sweep.calls, sweep.out.exists()) == (SystemExit, 2, [], False)
