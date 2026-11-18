"""Stage receipts, the generation chain and the region CLI (E2E-PIPELINE §3, card E2E-01)."""
from datetime import timedelta
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types

import pytest

from skippercast.relief import receipts
from tests._support import FIXTURES, NOW, ROOT, FakeClock


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TINY = _load('relief_tiny_region', FIXTURES / 'relief' / 'tiny' / 'tiny_region.py')
CLI_PATH = ROOT / 'scripts' / 'relief' / 'region.py'
CLI = _load('relief_region_cli', CLI_PATH)


def host(_path):
    return {'load5': 1.0, 'free_root_gb': 500.0, 'free_out_gb': 500.0}


def sha():
    return 'a' * 40


def run(stage_run, clock=None):
    return receipts.run_stage(stage_run, clock=clock or FakeClock(), host=host, repo_sha=sha)


def states(region):
    return {key: verdict.state for key, verdict in receipts.chain(region)}


def generations(region):
    return {key: verdict.receipt['generation'] for key, verdict in receipts.chain(region)}


def receipt(region, stage, scope=None):
    return json.loads(region.receipt_path(stage, scope).read_text())


@pytest.fixture
def tiny(tmp_path):
    return TINY.build_chain(tmp_path / 'out', clock=FakeClock(), host=host, repo_sha=sha)


def simple(region, build, *, stage='solo', params=None, digest='c' * 64, upstream=()):
    return receipts.StageRun(region, stage, build, digest, upstream=list(upstream),
                             plan=receipts.Plan(params=params or {}))


# --- the chain and the done rule ---------------------------------------------------------------

def test_fixture_chain_is_done_in_upstream_first_order(tiny):
    rows = receipts.chain(tiny)
    assert [key for key, _ in rows] == list(TINY.ORDER)
    assert all(verdict.done for _, verdict in rows), rows
    doc = receipt(tiny, 'inventory')
    assert doc['schema'] == 'sc-stage-receipt/1' and doc['status'] == 'ok' and doc['rc'] == 0
    assert doc['code'] == {'repo_sha': 'a' * 40, 'stage_digest': doc['code']['stage_digest']}
    assert sorted(i['path'] for i in doc['inputs']) == [
        'raw/bluetopo_like_3band.tif', 'raw/geographic_1m.tif', 'raw/projected_1m.tif']
    assert [o['path'] for o in doc['outputs']] == ['inventory/inventory.json']
    mosaic = receipt(tiny, 'mosaic', 'public')
    assert mosaic['scope'] == 'public' and mosaic['target'] == 'mosaic/public'
    assert mosaic['upstream'] == [{'stage': 'select', 'generation': receipt(tiny, 'select')['generation']}]
    assert tiny.receipt_path('mosaic', 'public').name == 'mosaic.public.json'


def test_two_runs_give_identical_generations(tmp_path, tiny):
    other = TINY.build_chain(tmp_path / 'elsewhere', clock=FakeClock(NOW + timedelta(days=3)), host=host,
                             repo_sha=lambda: None)
    assert generations(other) == generations(tiny)
    before = tiny.receipt_path('select').read_bytes()
    result = run(TINY.stage_runs(tiny)['select'])
    assert (result.state, result.exit_code) == ('done', 0)
    assert tiny.receipt_path('select').read_bytes() == before
    assert not list(tiny.dir.glob('select.old-*'))


def test_generation_is_content_only_and_canonical():
    a = receipts.generation([{'role': 'grid', 'sha256': '1' * 64, 'path': '/x/a.tif'},
                             {'role': 'grid', 'sha256': '2' * 64, 'path': '/x/b.tif'}],
                            [{'stage': 'select', 'generation': '3' * 64}], 'd' * 64, {'b': 1, 'a': [1, 2]})
    b = receipts.generation([{'role': 'grid', 'sha256': '2' * 64, 'path': '/elsewhere/b.tif'},
                             {'role': 'grid', 'sha256': '1' * 64, 'path': '/elsewhere/a.tif'}],
                            [{'stage': 'select', 'generation': '3' * 64}], 'd' * 64, {'a': [1, 2], 'b': 1})
    assert a == b
    assert a != receipts.generation([{'role': 'grid', 'sha256': '1' * 64}], [{'stage': 'select', 'generation': '3' * 64}],
                                    'd' * 64, {'b': 1, 'a': [1, 2]})
    with pytest.raises(receipts.ReceiptError):
        receipts.generation([], [], 'd' * 64, {'x': float('nan')})


def test_upstream_change_makes_downstream_stale(tiny):
    before = generations(tiny)
    grid = tiny.dir / 'raw' / 'projected_1m.tif'
    data = bytearray(grid.read_bytes())
    data[-1] ^= 0xFF  # one elevation value changes
    grid.write_bytes(bytes(data))
    runs = TINY.stage_runs(tiny)
    assert run(runs['inventory']).state == 'ok'
    now = dict(receipts.chain(tiny))
    assert now['inventory'].done and now['inventory'].receipt['generation'] != before['inventory']
    assert now['normalize'].state == 'stale' and 'upstream inventory changed' in now['normalize'].reason
    assert now['select'].state == 'stale' and 'upstream normalize not done (stale)' in now['select'].reason
    assert now['mosaic.public'].state == 'stale'
    assert list(tiny.dir.glob('inventory.old-*')), 'the previous generation is kept, not overwritten'
    for key in TINY.ORDER[1:]:
        assert run(runs[key]).state == 'ok'
    after = generations(tiny)
    assert set(states(tiny).values()) == {'done'}
    assert all(after[key] != before[key] for key in TINY.ORDER)


def test_params_and_code_changes_make_new_generations(tiny):
    gen = receipt(tiny, 'mosaic', 'public')['generation']
    changed = TINY.stage_runs(tiny, params={'mosaic': {'cell_m': 5}})['mosaic.public']
    assert run(changed).state == 'ok'
    assert receipt(tiny, 'mosaic', 'public')['generation'] != gen
    recoded = TINY.stage_runs(tiny, code_digest='e' * 64)['inventory']
    assert run(recoded).state == 'ok'
    assert states(tiny)['normalize'] == 'stale'


def test_output_edit_unproves_a_stage(tiny):
    gen = receipt(tiny, 'normalize')['generation']
    out = tiny.dir / 'normalize' / 'projected_1m.tif.json'
    out.write_text(out.read_text().replace('true', 'false'))
    now = dict(receipts.chain(tiny))
    assert now['inventory'].done
    assert now['normalize'].state == 'unproved' and 'output changed: normalize/projected_1m.tif.json' in now['normalize'].reason
    assert now['select'].state == 'stale' and now['mosaic.public'].state == 'stale'
    runs = TINY.stage_runs(tiny)
    blocked = run(runs['select'])
    assert (blocked.state, blocked.exit_code) == ('blocked', 3)
    rebuilt = run(runs['normalize'])
    assert rebuilt.state == 'ok' and rebuilt.generation == gen
    assert receipt(tiny, 'normalize')['attempt'] == 2
    assert set(states(tiny).values()) == {'done'}, 'same generation: downstream is current again without a rerun'
    (tiny.dir / 'select' / 'selection.json').unlink()
    assert dict(receipts.chain(tiny))['select'].reason == 'output missing: select/selection.json'


def test_receipts_are_portable_with_the_region_directory(tmp_path, tiny):
    shutil.copytree(tiny.out_root, tmp_path / 'moved')
    moved = receipts.Region(tmp_path / 'moved', 'tiny')
    assert set(states(moved).values()) == {'done'}


# --- write then rename, failures, crashes, attempts ---------------------------------------------

def test_failed_build_leaves_no_output_and_is_kept_as_failed(tmp_path):
    region = receipts.Region(tmp_path / 'out', 'tiny')
    calls = []

    def bad(out):
        calls.append(1)
        (out / 'half.bin').write_bytes(b'x' * 100)
        raise RuntimeError('disk on fire')

    first = run(simple(region, bad))
    assert (first.state, first.exit_code) == ('failed', 1)
    assert not (region.dir / 'solo').exists()
    failed = sorted(region.dir.glob('solo.failed-*'))
    assert len(failed) == 1 and (failed[0] / 'half.bin').read_bytes() == b'x' * 100
    doc = receipt(region, 'solo')
    assert (doc['status'], doc['attempt'], doc['rc'], doc['outputs']) == ('failed', 1, 1, [])
    assert doc['error'] == 'RuntimeError: disk on fire'
    second = run(simple(region, bad), clock=FakeClock(NOW + timedelta(minutes=10)))
    assert (second.state, second.exit_code) == ('held', 4)
    doc = receipt(region, 'solo')
    assert (doc['status'], doc['attempt']) == ('held', 2)
    assert doc['held_reason'].startswith('2 attempts failed for generation ')
    third = run(simple(region, bad))
    assert third.state == 'held' and len(calls) == 2, 'a held generation is never rerun'
    assert len(list(region.dir.glob('solo.failed-*'))) == 2
    assert not list(region.dir.glob('solo.tmp-*'))
    # A new generation (for example a fixed parameter) starts at attempt 1 again.
    fixed = run(simple(region, lambda out: (out / 'ok.txt').write_text('ok'), params={'fixed': True}))
    assert fixed.state == 'ok' and receipt(region, 'solo')['attempt'] == 1


def test_attempts_survive_switching_generations(tmp_path):
    region = receipts.Region(tmp_path / 'out', 'tiny')
    calls = []

    def bad(out):
        calls.append('A')
        raise RuntimeError('failed')

    def good(out):
        calls.append('B')
        (out / 'ok').write_text('ok')

    a = simple(region, bad)
    b = simple(region, good, params={'generation': 'B'})
    assert run(a).state == 'failed'
    assert run(b).state == 'ok'
    assert run(a).state == 'held'
    assert receipt(region, 'solo')['attempt'] == 2
    assert run(b).state == 'done'
    assert run(a).state == 'held'
    assert calls == ['A', 'B', 'A']
    assert receipts.check(region, 'solo').state == 'held'


def test_a_switch_back_restores_the_intact_success_without_an_attempt(tmp_path):
    region = receipts.Region(tmp_path / 'out', 'tiny')
    calls = []

    def bad(out):
        calls.append('A')
        raise receipts.Held('needs a person')

    def good(out):
        calls.append('B')
        (out / 'ok').write_text('ok')

    a = simple(region, bad)
    b = simple(region, good, params={'generation': 'B'})
    assert run(a).state == 'held'
    assert run(b).state == 'ok'
    ok = {k: v for k, v in receipt(region, 'solo').items() if k != 'generation_history'}
    for _ in range(2):  # A -> B twice: B's outputs still match, so B is restored, never rebuilt or held
        assert run(a).state == 'held' and receipts.check(region, 'solo').state == 'held'
        restored = run(b)
        assert (restored.state, restored.exit_code) == ('done', 0) and 'restored' in restored.reason
        doc = receipt(region, 'solo')
        assert {k: v for k, v in doc.items() if k != 'generation_history'} == ok
        assert (doc['status'], doc['attempt']) == ('ok', 1)
        assert receipts.check(region, 'solo').done
    assert calls == ['A', 'B']
    # Changed outputs are not restored: the switch back rebuilds, as attempt 2.
    assert run(a).state == 'held'
    (region.dir / 'solo' / 'ok').write_text('edited')
    rebuilt = run(b)
    assert rebuilt.state == 'ok' and receipt(region, 'solo')['attempt'] == 2
    assert calls == ['A', 'B', 'B']


def test_failure_over_an_existing_output_keeps_the_old_output(tiny):
    before = (tiny.dir / 'select' / 'selection.json').read_bytes()

    def bad(out):
        (out / 'selection.json').write_text('half')
        raise ValueError('boom')

    runs = TINY.stage_runs(tiny)
    broken = receipts.StageRun(tiny, 'select', bad, 'f' * 64, upstream=[receipts.Ref('normalize')])
    assert run(broken).state == 'failed'
    assert (tiny.dir / 'select' / 'selection.json').read_bytes() == before
    assert states(tiny)['select'] == 'failed' and states(tiny)['mosaic.public'] == 'stale'
    assert run(runs['select']).state == 'done', 'the intact earlier success is restored without a rebuild'
    assert receipt(tiny, 'select')['attempt'] == 1
    assert set(states(tiny).values()) == {'done'}


def test_interrupt_is_recorded_and_reraised(tmp_path):
    region = receipts.Region(tmp_path / 'out', 'tiny')

    def interrupted(out):
        (out / 'half.bin').write_bytes(b'x')
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(simple(region, interrupted))
    assert not (region.dir / 'solo').exists() and list(region.dir.glob('solo.failed-*'))
    assert receipt(region, 'solo')['status'] == 'failed'


CRASH = '''
import os
import sys
from skippercast.relief import receipts

region = receipts.Region(sys.argv[1], 'tiny')


def build(out):
    (out / 'half.bin').write_bytes(b'x' * 1000)
    os._exit(9)


receipts.run_stage(receipts.StageRun(region, 'solo', build, 'c' * 64),
                   host=lambda path: {}, repo_sha=lambda: None)
'''


def test_crash_mid_stage_leaves_no_half_output(tmp_path):
    script = tmp_path / 'crash.py'
    script.write_text(CRASH)
    out = tmp_path / 'out'
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
    proc = subprocess.run([sys.executable, str(script), str(out)],
                          env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 9, proc.stderr
    region = receipts.Region(out, 'tiny')
    assert not (region.dir / 'solo').exists(), 'no half output under the target name'
    assert len(list(region.dir.glob('solo.tmp-*'))) == 1
    doc = receipt(region, 'solo')
    assert (doc['status'], doc['attempt'], doc['rc'], doc['error']) == ('failed', 1, None, receipts.INTERRUPTED)
    assert dict(receipts.chain(region))['solo'].state == 'failed'
    resumed = run(simple(region, lambda out: (out / 'whole.bin').write_bytes(b'y' * 10)))
    assert resumed.state == 'ok'
    assert receipt(region, 'solo')['attempt'] == 2, 'the crashed attempt counts'
    assert not list(region.dir.glob('solo.tmp-*'))
    recovered = list(region.dir.glob('solo.failed-*-recovered-*'))
    assert len(recovered) == 1 and (recovered[0] / 'half.bin').stat().st_size == 1000
    assert sorted(p.name for p in (region.dir / 'solo').iterdir()) == ['whole.bin']


def test_the_second_crash_is_retained_before_the_attempt_limit_holds(tmp_path):
    script = tmp_path / 'crash.py'
    script.write_text(CRASH)
    out = tmp_path / 'out'
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
    for _ in range(2):
        proc = subprocess.run([sys.executable, str(script), str(out)],
                              env=env, capture_output=True, text=True, timeout=120)
        assert proc.returncode == 9, proc.stderr
    region = receipts.Region(out, 'tiny')
    assert len(list(region.dir.glob('solo.tmp-*'))) == 1, 'the second crash swept the first'
    assert receipt(region, 'solo')['attempt'] == 2
    calls = []
    held = run(simple(region, lambda out: calls.append(out)))
    assert held.state == 'held' and 'attempt limit (2)' in held.reason and calls == []
    assert not list(region.dir.glob('solo.tmp-*'))
    recovered = list(region.dir.glob('solo.failed-*-recovered-*'))
    assert len(recovered) == 2 and all((d / 'half.bin').stat().st_size == 1000 for d in recovered)
    assert not (region.dir / 'solo').exists()


def test_a_running_stage_is_busy_and_shown_as_running(tmp_path):
    region = receipts.Region(tmp_path / 'out', 'tiny')
    lock = region.lock_path('solo')
    lock.parent.mkdir(parents=True)
    with open(lock, 'w') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        result = run(simple(region, lambda out: None))
        assert (result.state, result.exit_code) == ('busy', 5)
        receipts.write_json_atomic(region.receipt_path('solo'), {
            'schema': receipts.SCHEMA, 'region': 'tiny', 'stage': 'solo', 'scope': None, 'generation': '0' * 64,
            'outputs': [], 'upstream': [], 'attempt': 1, 'status': 'failed', 'error': receipts.INTERRUPTED})
        assert states(region) == {'solo': 'running'}
    assert states(region) == {'solo': 'failed'}


def test_receipt_write_is_atomic(tiny, monkeypatch):
    path = tiny.receipt_path('select')
    before = path.read_bytes()

    def broken_replace(src, dst):
        raise OSError('simulated crash before rename')

    monkeypatch.setattr(receipts.os, 'replace', broken_replace)
    with pytest.raises(OSError):
        receipts.write_json_atomic(path, {'schema': 'half'})
    assert path.read_bytes() == before
    assert not list(path.parent.glob('*.tmp-*'))


def test_targets_and_names_are_confined(tmp_path):
    region = receipts.Region(tmp_path / 'out', 'tiny')
    for target in ('../escape', 'stages', 'stages/x'):
        with pytest.raises(receipts.ReceiptError):
            run(receipts.StageRun(region, 'solo', lambda out: None, 'c' * 64, target=target))
    for bad in ('../x', 'Morro', ''):
        with pytest.raises(receipts.ReceiptError):
            receipts.Region(tmp_path, bad)
    linked = run(simple(region, lambda out: os.symlink('/', out / 'link')))
    assert linked.state == 'failed' and 'is a symlink' in linked.reason
    assert not (region.dir / 'solo').exists()


# --- region.py: dispatch by name and status ---------------------------------------------------

@pytest.mark.parametrize('name', ['nosuch', 'receipts', 'status-x', 'Bad', '../x', 'os', '__init__', 'relief.x'])
def test_unknown_stage_is_refused(tmp_path, capsys, name):
    assert CLI.main([name, '--region', 'tiny', '--out', str(tmp_path)]) == 2
    assert 'unknown stage' in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def _fake_stage(tmp_path, monkeypatch, name='demo_stage', **attrs):
    source = tmp_path / f'{name}.py'
    source.write_text('# stand-in stage source\n')
    module = types.ModuleType(f'skippercast.relief.{name}')
    module.__file__ = str(source)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module, source


def test_stage_is_dispatched_by_name(tmp_path, monkeypatch, capsys):
    def build(ctx, out):
        (out / 'region.txt').write_text(f'{ctx.region.id} {ctx.args.flavour}')

    _module, source = _fake_stage(
        tmp_path, monkeypatch, build=build,
        add_arguments=lambda parser: parser.add_argument('--flavour', default='plain'),
        plan=lambda ctx: receipts.Plan(params={'flavour': ctx.args.flavour}))
    out = tmp_path / 'out'
    argv = ['demo-stage', '--region', 'tiny', '--out', str(out)]
    assert CLI.main(argv) == 0
    assert '[demo_stage] OK' in capsys.readouterr().out
    region = receipts.Region(out, 'tiny')
    assert (region.dir / 'demo_stage' / 'region.txt').read_text() == 'tiny plain'
    gen = receipt(region, 'demo_stage')['generation']
    assert CLI.main(argv) == 0
    assert '[demo_stage] DONE' in capsys.readouterr().out
    source.write_text('# stand-in stage source, edited\n')
    assert CLI.main(argv) == 0
    assert receipt(region, 'demo_stage')['generation'] != gen, 'a code change makes a new generation'
    assert CLI.main(argv + ['--flavour', 'spicy']) == 0
    assert (region.dir / 'demo_stage' / 'region.txt').read_text() == 'tiny spicy'


def test_scoped_stage_needs_a_listed_scope_and_upstream_must_be_done(tmp_path, monkeypatch, capsys):
    _fake_stage(tmp_path, monkeypatch, name='scoped', SCOPES=('public', 'private'), UPSTREAM=('select',),
                build=lambda ctx, out: (out / 'x').write_text(ctx.scope))
    out = tmp_path / 'out'
    with pytest.raises(SystemExit) as exc:
        CLI.main(['scoped', '--region', 'tiny', '--out', str(out)])
    assert exc.value.code == 2
    assert CLI.main(['scoped', '--region', 'tiny', '--out', str(out), '--scope', 'public']) == 3
    assert 'upstream select not done (missing' in capsys.readouterr().out


def test_main_only_module_gets_its_arguments(tmp_path, monkeypatch):
    seen = []
    _fake_stage(tmp_path, monkeypatch, name='live_check', main=lambda argv: seen.append(argv) or 0)
    assert CLI.main(['live-check', '--region', 'tiny']) == 0
    assert seen == [['--region', 'tiny']]


def test_status_prints_the_chain(tiny):
    cmd = [sys.executable, str(CLI_PATH), 'status', '--region', 'tiny', '--out', str(tiny.out_root)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert lines[0].startswith('region tiny')
    assert [line.split()[0] for line in lines[1:5]] == list(TINY.ORDER)
    assert all(line.split()[1] == 'done' for line in lines[1:5])
    assert 'normalize' in lines[1 + TINY.ORDER.index('normalize')] and '<- inventory@' in lines[2]
    assert lines[-1] == 'chain: 4 done'
    (tiny.dir / 'select' / 'selection.json').write_text('{}')
    proc = subprocess.run(cmd + ['--json'], capture_output=True, text=True, timeout=120)
    doc = json.loads(proc.stdout)
    assert [(s['key'], s['state']) for s in doc['stages']] == [
        ('inventory', 'done'), ('normalize', 'done'), ('select', 'unproved'), ('mosaic.public', 'stale')]


def test_status_of_an_empty_region(tmp_path, capsys):
    assert CLI.main(['status', '--region', 'tiny', '--out', str(tmp_path)]) == 0
    assert 'no stage receipts' in capsys.readouterr().out


def test_status_reports_a_receipt_with_a_non_list_upstream(tiny, capsys):
    doc = dict(receipt(tiny, 'select'), stage='broken', upstream=42)
    receipts.write_json_atomic(tiny.receipt_path('broken'), doc)
    rows = dict(receipts.chain(tiny))
    assert (rows['broken'].state, rows['broken'].reason) == ('invalid', 'upstream malformed')
    assert all(rows[key].done for key in TINY.ORDER)
    argv = ['status', '--region', 'tiny', '--out', str(tiny.out_root)]
    assert CLI.main(argv) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(line.split()[:2] == ['broken', 'invalid'] for line in lines)
    assert lines[-1] == 'chain: 4 done, 1 invalid'
    assert CLI.main(argv + ['--json']) == 0
    states = {s['key']: s['state'] for s in json.loads(capsys.readouterr().out)['stages']}
    assert states == {**{key: 'done' for key in TINY.ORDER}, 'broken': 'invalid'}


def test_fixture_grids_are_deterministic_geotiffs():
    grids = TINY.grids()
    assert sorted(grids) == ['bluetopo_like_3band.tif', 'geographic_1m.tif', 'projected_1m.tif']
    assert grids == TINY.grids()
    for data in grids.values():
        assert data[:4] == b'II*\x00'
