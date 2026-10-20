"""T15 clean-state double-rerun driver: verdicts fail closed and passes never share state."""
import json
from pathlib import Path
import sys

import pytest

from research.scripts import rerun_clean_twice as module

PROD = module.PROD_IDS


def write_script(directory, name, body):
    path = Path(directory) / name
    path.write_text(body)
    return str(path)


@pytest.fixture
def tools(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    guard = tmp_path / 'guard'
    guard.mkdir()
    (guard / 'ledger.json').write_text('{"canonical": true}\n')
    return dict(
        root=tmp_path, guard=guard,
        # Deterministic output + receipt; refuses to run if HOME already holds a
        # marker, so a pass that inherits state from an earlier pass fails.
        good=write_script(scripts, 'good.py', '\n'.join([
            'import json, os, sys, pathlib',
            'home = pathlib.Path(os.environ["HOME"])',
            'marker = home / "seen"',
            'if marker.exists() or pathlib.Path("out.txt").exists(): sys.exit(9)',
            'marker.write_text("x")',
            'assert pathlib.Path(os.environ["HOME"]).is_relative_to(pathlib.Path.cwd())',
            'assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"',
            'pathlib.Path("out.txt").write_text(pathlib.Path("input/data.txt").read_text().upper())',
            'json.dump({"verdict": "PASS", "n": 1}, open("receipt.json", "w"))'])),
        noisy=write_script(scripts, 'noisy.py', '\n'.join([
            'import os, pathlib, json',
            'pathlib.Path("noisy.txt").write_text(os.environ["SKIPPERCAST_CLEAN_RERUN_PASS"])',
            'json.dump({"verdict": "PASS"}, open("noisy.json", "w"))'])),
        mutate=write_script(scripts, 'mutate.py', '\n'.join([
            'import sys, pathlib',
            'pathlib.Path(sys.argv[1], "ledger.json").write_text("{}")'])),
        fail=write_script(scripts, 'fail.py', 'raise SystemExit(4)\n'),
        source=_source(tmp_path))


def _source(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.txt').write_text('terrain\n')
    return source


def spec_for(tools, step_list, prod, **extra):
    spec = dict(schema=module.SPEC_SCHEMA, name='fixture', work_base=str(tools['root'] / 'work'), passes=2,
                guard_paths=[str(tools['guard'])],
                stage_inputs=[dict({'from': str(tools['source'])}, to='input')],
                steps=step_list, coast_prod=prod)
    spec.update(extra)
    path = tools['root'] / 'spec.json'
    path.write_text(json.dumps(spec))
    return path


def good_step(tools, sid='good'):
    return dict(id=sid, argv=['{python}', '-B', tools['good']], expect_exit=[0],
                deterministic_outputs=['out.txt'], receipt='receipt.json',
                receipt_checks=[dict(pointer='/verdict', equals='PASS')])


def all_six(step_id='good'):
    return {pid: dict(steps=[step_id]) for pid in PROD}


def run(spec, capsys):
    code = module.main(['--spec', str(spec)])
    out = json.loads(capsys.readouterr().out)
    return code, out


def report(tools):
    return json.loads((tools['root'] / 'work' / 'report.json').read_text())


def test_all_six_pass_twice_from_clean_roots(tools, capsys):
    code, out = run(spec_for(tools, [good_step(tools)], all_six()), capsys)
    assert code == 0 and out['verdict'] == 'PASS'
    data = report(tools)
    assert set(data['coast_prod']) == set(PROD)
    assert all(v['status'] == 'PASS' for v in data['coast_prod'].values())
    assert data['comparison']['good'] == dict(compared=1, differing=[], identical=True)
    assert [p['root'] for p in data['passes']] == [str(tools['root'] / 'work' / f'pass-{n}') for n in (1, 2)]
    assert data['guards_unchanged'] is True
    assert (tools['root'] / 'work' / 'report.md').read_text().count('| PASS |') == 6
    assert all(r['sha256'] for v in data['coast_prod'].values() for r in v['receipts'])


def test_unmapped_ids_are_no_receipt_and_held_is_not_pass(tools, capsys):
    prod = {'COAST-PROD-01': dict(steps=['good']), 'COAST-PROD-06': dict(held='GPU held')}
    code, out = run(spec_for(tools, [good_step(tools)], prod), capsys)
    assert code == 1 and out['verdict'] == 'NOT_PASS'
    assert out['coast_prod'] == {'COAST-PROD-01': 'PASS', 'COAST-PROD-02': 'NO_RECEIPT', 'COAST-PROD-03': 'NO_RECEIPT',
                                 'COAST-PROD-04': 'NO_RECEIPT', 'COAST-PROD-05': 'NO_RECEIPT', 'COAST-PROD-06': 'HELD'}


def test_output_that_differs_between_passes_fails(tools, capsys):
    noisy = dict(id='noisy', argv=['{python}', '-B', tools['noisy']], deterministic_outputs=['noisy.txt'],
                 receipt='noisy.json', receipt_checks=[dict(pointer='/verdict', equals='PASS')])
    prod = all_six()
    prod['COAST-PROD-05'] = dict(steps=['noisy'])
    code, out = run(spec_for(tools, [good_step(tools), noisy], prod), capsys)
    assert code == 1 and out['coast_prod']['COAST-PROD-05'] == 'FAIL'
    assert out['coast_prod']['COAST-PROD-01'] == 'PASS'
    assert report(tools)['comparison']['noisy']['differing'] == ['noisy.txt']


def test_changed_guard_fails_every_mapped_id(tools, capsys):
    mutate = dict(id='mutate', argv=['{python}', '-B', tools['mutate'], str(tools['guard'])])
    code, out = run(spec_for(tools, [good_step(tools), mutate], all_six()), capsys)
    assert code == 1
    assert set(out['coast_prod'].values()) == {'FAIL'}
    data = report(tools)
    assert data['guards_unchanged'] is False
    assert data['passes'][0]['guards_changed'] == [str(tools['guard'])]


def test_failed_step_stops_later_steps_and_fails_its_ids(tools, capsys):
    fail = dict(id='fail', argv=['{python}', '-B', tools['fail']])
    prod = all_six()
    prod['COAST-PROD-02'] = dict(steps=['fail'])
    prod['COAST-PROD-03'] = dict(steps=['late'])
    code, out = run(spec_for(tools, [fail, good_step(tools, 'late'), good_step(tools)], prod), capsys)
    assert code == 1
    assert out['coast_prod']['COAST-PROD-02'] == 'FAIL' and out['coast_prod']['COAST-PROD-03'] == 'FAIL'
    late = next(s for s in report(tools)['passes'][0]['steps'] if s['id'] == 'late')
    assert late['problems'] == ['not run: an earlier step failed']


def test_receipt_check_mismatch_and_missing_receipt_fail(tools, capsys):
    wrong = good_step(tools)
    wrong['receipt_checks'] = [dict(pointer='/verdict', equals='FAIL')]
    code, out = run(spec_for(tools, [wrong], all_six()), capsys)
    assert code == 1 and set(out['coast_prod'].values()) == {'FAIL'}

    missing = good_step(tools)
    missing['receipt'] = 'absent.json'
    (tools['root'] / 'work').rename(tools['root'] / 'work-old')
    code, out = run(spec_for(tools, [missing], all_six()), capsys)
    assert code == 1
    assert 'receipt missing: absent.json' in report(tools)['coast_prod']['COAST-PROD-01']['reasons'][0]


def test_existing_work_base_is_refused(tools, capsys):
    (tools['root'] / 'work').mkdir()
    code, out = run(spec_for(tools, [good_step(tools)], all_six()), capsys)
    assert code == 2 and 'work_base exists' in out['error']


@pytest.mark.parametrize('change', [
    dict(coast_prod={'COAST-PROD-07': dict(steps=['good'])}),
    dict(coast_prod={'COAST-PROD-01': dict(steps=['nope'])}),
    dict(coast_prod={'COAST-PROD-01': dict(steps=['good'], held='x')}),
    dict(passes=1),
    dict(work_base='relative/dir'),
    dict(steps=[dict(id='good', argv=['x'], receipt='../escape.json')]),
    dict(steps=[dict(id='good', argv=['x'], receipt_checks=[dict(pointer='/v', equals=1)])]),
    dict(stage_inputs=[{'from': 'relative', 'to': 'x'}]),
])
def test_invalid_specs_are_refused_before_running(tools, capsys, change):
    spec = spec_for(tools, [good_step(tools)], all_six(), **change)
    code, out = run(spec, capsys)
    assert code == 2 and out['error']
    assert not (tools['root'] / 'work').exists()


def test_work_base_inside_a_guard_is_refused(tools, capsys):
    spec = spec_for(tools, [good_step(tools)], all_six(), work_base=str(tools['guard'] / 'work'))
    code, out = run(spec, capsys)
    assert code == 2 and 'inside guard' in out['error']


def test_dry_run_prints_plan_without_creating_anything(tools, capsys):
    spec = spec_for(tools, [good_step(tools)], all_six())
    assert module.main(['--spec', str(spec), '--dry-run']) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['steps'][0]['argv'][0] == sys.executable
    assert not (tools['root'] / 'work').exists()
