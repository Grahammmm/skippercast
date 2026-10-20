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
    fail = dict(id='fail', argv=['{python}', '-B', tools['fail']], receipt='fail.json', receipt_checks=PASS_CHECK)
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
    dict(coast_prod={'COAST-PROD-01': dict(evidence=[dict(path='relative.json')])}),
    dict(coast_prod={'COAST-PROD-01': dict(held='x', evidence=[dict(path='/abs.json')])}),
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


def cited(tools, name='earlier.json', verdict='PASS', body=None):
    path = tools['root'] / name
    path.write_text(json.dumps(dict(verdict=verdict)) if body is None else body)
    return path


PASS_CHECK = [dict(pointer='/verdict', equals='PASS')]


def citation(path, **extra):
    item = dict(path=str(path), sha256=module.sha256_file(path), receipt_checks=PASS_CHECK)
    item.update(extra)
    return item


def all_cited(path):
    return {pid: dict(evidence=[citation(path)]) for pid in PROD}


def test_cited_receipts_count_only_when_present_pinned_and_checked(tools, capsys):
    good = cited(tools)
    prod = all_six()
    prod['COAST-PROD-02'] = dict(evidence=[citation(good)])
    prod['COAST-PROD-03'] = dict(evidence=[dict(path=str(tools['root'] / 'absent.json'), sha256='0' * 64,
                                               receipt_checks=PASS_CHECK)])
    prod['COAST-PROD-05'] = dict(evidence=[citation(good, sha256='0' * 64)])
    prod['COAST-PROD-06'] = dict(evidence=[citation(cited(tools, 'held.json', 'HELD'))])
    code, out = run(spec_for(tools, [good_step(tools)], prod), capsys)
    assert code == 1
    assert out['coast_prod'] == {'COAST-PROD-01': 'PASS', 'COAST-PROD-02': 'PASS', 'COAST-PROD-03': 'FAIL',
                                 'COAST-PROD-04': 'PASS', 'COAST-PROD-05': 'FAIL', 'COAST-PROD-06': 'FAIL'}
    data = report(tools)
    receipts = data['coast_prod']['COAST-PROD-02']['receipts']
    assert receipts == [dict(cited=True, path=str(good), sha256=module.sha256_file(good), bytes=good.stat().st_size)]
    # A cited receipt that exists but fails is never listed as a receipt.
    assert data['coast_prod']['COAST-PROD-05']['receipts'] == []
    assert data['coast_prod']['COAST-PROD-06']['receipts'] == []


def test_all_cited_evidence_can_pass_with_the_rerun_steps(tools, capsys):
    good = cited(tools)
    prod = all_cited(good)
    prod['COAST-PROD-04'] = dict(steps=['good'], evidence=[citation(good)])
    code, out = run(spec_for(tools, [good_step(tools)], prod), capsys)
    assert code == 0 and out['verdict'] == 'PASS'
    assert report(tools)['verdict_reasons'] == []


# --- round-1 review (sol-reviewer): failed or nondeterministic reruns can never be covered by citations ---

def test_failed_unreferenced_step_fails_the_verdict_even_with_all_six_cited(tools, capsys):
    good = cited(tools)
    fail = dict(id='fails', argv=['{python}', '-B', tools['fail']])
    code, out = run(spec_for(tools, [fail], all_cited(good)), capsys)
    assert code == 1 and out['verdict'] == 'NOT_PASS'
    assert set(out['coast_prod'].values()) == {'PASS'}  # the ids themselves are backed...
    reasons = report(tools)['verdict_reasons']
    assert 'pass 1 step fails: exit 4 not in [0]' in reasons and 'pass 2 step fails: exit 4 not in [0]' in reasons
    assert 'pass 2 step fails' in (tools['root'] / 'work' / 'report.md').read_text()


def test_nondeterministic_unreferenced_step_fails_the_verdict_even_with_all_six_cited(tools, capsys):
    good = cited(tools)
    noisy = dict(id='noisy', argv=['{python}', '-B', tools['noisy']], deterministic_outputs=['noisy.txt'])
    code, out = run(spec_for(tools, [good_step(tools), noisy], all_cited(good)), capsys)
    assert code == 1 and out['verdict'] == 'NOT_PASS'
    assert set(out['coast_prod'].values()) == {'PASS'}
    assert any(r.startswith('step noisy: deterministic outputs not identical') for r in report(tools)['verdict_reasons'])


def test_missing_deterministic_output_in_unreferenced_step_fails_the_verdict(tools, capsys):
    good = cited(tools)
    quiet = dict(id='quiet', argv=['{python}', '-B', '-c', 'pass'], deterministic_outputs=['never.txt'])
    code, out = run(spec_for(tools, [quiet], all_cited(good)), capsys)
    assert code == 1 and out['verdict'] == 'NOT_PASS'


# --- round-1 review: evidence is mandatory, pinned and checked ---

@pytest.mark.parametrize('label, prod_for', [
    ('receipt-less mapped step', lambda t, p: {pid: dict(steps=['noop']) for pid in PROD}),
    ('citation without pin', lambda t, p: {pid: dict(evidence=[dict(path=str(p), receipt_checks=PASS_CHECK)])
                                           for pid in PROD}),
    ('citation with short pin', lambda t, p: {'COAST-PROD-01': dict(evidence=[citation(p, sha256='abc')])}),
    ('citation with uppercase pin', lambda t, p: {'COAST-PROD-01': dict(
        evidence=[citation(p, sha256=module.sha256_file(p).upper())])}),
    ('citation without checks', lambda t, p: {pid: dict(evidence=[dict(path=str(p), sha256=module.sha256_file(p))])
                                              for pid in PROD}),
    ('citation with exists-only checks', lambda t, p: {'COAST-PROD-01': dict(
        evidence=[citation(p, receipt_checks=[dict(pointer='/verdict', exists=True)])])}),
])
def test_unbacked_evidence_is_refused_before_running(tools, capsys, label, prod_for):
    good = cited(tools)
    noop = dict(id='noop', argv=['{python}', '-B', '-c', 'pass'])
    code, out = run(spec_for(tools, [noop, good_step(tools)], prod_for(tools, good)), capsys)
    assert code == 2 and out['error'], label
    assert not (tools['root'] / 'work').exists()


@pytest.mark.parametrize('checks', [None, [], [dict(pointer='/verdict', exists=True)]])
def test_step_receipt_without_an_equals_check_is_refused(tools, capsys, checks):
    step = good_step(tools)
    if checks is None:
        del step['receipt_checks']
    else:
        step['receipt_checks'] = checks
    code, out = run(spec_for(tools, [step], all_six()), capsys)
    assert code == 2 and 'equals check' in out['error']


@pytest.mark.parametrize('name, body, checks', [
    ('not-json.json', 'verdict: PASS\n', PASS_CHECK),
    ('array.json', '["PASS"]', [dict(pointer='/0', equals='PASS')]),
    ('held-self-check.json', '{"verdict": "HELD"}', [dict(pointer='/verdict', equals='HELD')]),
    ('fail-status.json', '{"status": "FAIL", "n": 1}', [dict(pointer='/n', equals=1)]),
    ('blocked-outcome.json', '{"outcome": "blocked", "n": 1}', [dict(pointer='/n', equals=1)]),
])
def test_non_json_and_held_or_failed_citations_never_pass(tools, capsys, name, body, checks):
    bad = cited(tools, name, body=body)
    prod = all_six()
    prod['COAST-PROD-03'] = dict(evidence=[citation(bad, receipt_checks=checks)])
    code, out = run(spec_for(tools, [good_step(tools)], prod), capsys)
    assert code == 1 and out['coast_prod']['COAST-PROD-03'] == 'FAIL'
    entry = report(tools)['coast_prod']['COAST-PROD-03']
    assert entry['receipts'] == [] and entry['reasons']


def test_held_step_receipt_fails_even_when_its_checks_hold(tools, capsys):
    held = write_script(tools['root'] / 'scripts', 'held.py',
                        'import json\njson.dump({"verdict": "HELD", "n": 1}, open("receipt.json", "w"))\n')
    step = dict(id='held', argv=['{python}', '-B', held], receipt='receipt.json',
                receipt_checks=[dict(pointer='/n', equals=1)])
    code, out = run(spec_for(tools, [step], all_six('held')), capsys)
    assert code == 1 and set(out['coast_prod'].values()) == {'FAIL'}
    assert "verdict = 'HELD', not PASS" in report(tools)['coast_prod']['COAST-PROD-01']['reasons'][0]


# --- round-1 review: the driver owns per-pass isolation variables ---

@pytest.mark.parametrize('key', ['HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'PYTHONDONTWRITEBYTECODE',
                                 'SKIPPERCAST_CLEAN_RERUN_PASS'])
def test_spec_env_cannot_override_isolation(tools, capsys, key):
    spec = spec_for(tools, [good_step(tools)], all_six(), env={key: str(tools['root'] / 'shared')})
    code, out = run(spec, capsys)
    assert code == 2 and 'isolation variables' in out['error'] and key in out['error']
    assert not (tools['root'] / 'work').exists()


@pytest.mark.parametrize('key', ['HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'PYTHONDONTWRITEBYTECODE',
                                 'SKIPPERCAST_CLEAN_RERUN_PASS'])
def test_step_env_cannot_override_isolation(tools, capsys, key):
    step = good_step(tools)
    step['env'] = {key: str(tools['root'] / 'shared')}
    code, out = run(spec_for(tools, [step], all_six()), capsys)
    assert code == 2 and 'isolation variables' in out['error'] and key in out['error']
    assert not (tools['root'] / 'work').exists()


def test_isolation_wins_even_if_spec_validation_is_bypassed(tools):
    """Defence in depth: run_step applies the driver's values last, so passes never share HOME."""
    shared = tools['root'] / 'shared-home'
    shared.mkdir()
    worker = write_script(tools['root'] / 'scripts', 'home.py', '\n'.join([
        'import os, pathlib, json',
        'home = pathlib.Path(os.environ["HOME"])',
        'marker = home / "state"',
        'previous = marker.exists()',
        'marker.write_text("persisted")',
        'json.dump({"verdict": "PASS", "reused_home": previous, "home": str(home),',
        '           "tmp": os.environ["TMPDIR"], "bytecode": os.environ["PYTHONDONTWRITEBYTECODE"],',
        '           "pass": os.environ["SKIPPERCAST_CLEAN_RERUN_PASS"]}, open("receipt.json", "w"))']))
    hostile = {k: str(shared) for k in module.ISOLATION_ENV_KEYS}
    spec = dict(env=dict(hostile))
    step = dict(id='home', argv=['{python}', '-B', worker], env=dict(hostile), receipt='receipt.json',
                receipt_checks=[dict(pointer='/reused_home', equals=False)])
    for number in (1, 2):
        root = tools['root'] / f'pass-{number}'
        root.mkdir()
        mapping = dict(root=str(root), python=sys.executable, spec_dir=str(tools['root']),
                       work_base=str(tools['root']), **{'pass': str(number)})
        outcome = module.run_step(step, spec, root, mapping)
        assert outcome['ok'], outcome['problems']
        written = json.loads((root / 'receipt.json').read_text())
        assert written == dict(verdict='PASS', reused_home=False, home=str(root / '.home'), tmp=str(root / '.tmp'),
                               bytecode='1', **{'pass': str(number)})
    assert not (shared / 'state').exists()


def test_non_isolation_env_still_applies(tools, capsys):
    probe = write_script(tools['root'] / 'scripts', 'envprobe.py', '\n'.join([
        'import json, os',
        'json.dump({"verdict": "PASS", "a": os.environ.get("SPEC_VAR"), "b": os.environ.get("STEP_VAR")},'
        ' open("receipt.json", "w"))']))
    step = dict(id='env', argv=['{python}', '-B', probe], env=dict(STEP_VAR='step-{pass}'), receipt='receipt.json',
                receipt_checks=[dict(pointer='/a', equals='spec'), dict(pointer='/verdict', equals='PASS')])
    code, out = run(spec_for(tools, [step], all_six('env'), env=dict(SPEC_VAR='spec')), capsys)
    assert code == 0, report(tools)['verdict_reasons']
    receipts = [json.loads((tools['root'] / 'work' / f'pass-{n}' / 'receipt.json').read_text()) for n in (1, 2)]
    assert [r['b'] for r in receipts] == ['step-1', 'step-2']


def test_dry_run_prints_plan_without_creating_anything(tools, capsys):
    spec = spec_for(tools, [good_step(tools)], all_six())
    assert module.main(['--spec', str(spec), '--dry-run']) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['steps'][0]['argv'][0] == sys.executable
    assert not (tools['root'] / 'work').exists()
