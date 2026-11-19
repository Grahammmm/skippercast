"""A clean rerun must start every pass with the same staged inputs (F32-13)."""
import json

import pytest

from research.scripts import rerun_clean_twice as rerun


@pytest.mark.parametrize(('case', 'changed_pass', 'targets'), [
    ('same', 2, ()),
    ('content', 2, ('input.txt',)),
    ('missing-entry', 2, ('input.txt',)),
    ('renamed', 2, ('input.txt', 'renamed.txt')),
    ('content', 3, ('input.txt',)),
    ('missing-source', 2, ('input.txt',)),
])
def test_verdict_requires_the_same_staged_inputs(tmp_path, monkeypatch, case, changed_pass, targets):
    # A step can emit constant output and valid receipts despite staged-input drift.
    # Comparing only outputs (or only the first two passes) would miss that drift.
    source = tmp_path / 'source.txt'
    source.write_text('first')
    script = tmp_path / 'constant.py'
    script.write_text('from pathlib import Path\n'
                      'Path("out.txt").write_text("constant")\n'
                      'Path("receipt.json").write_text(\'{"verdict": "PASS"}\')\n')
    work = tmp_path / 'work'
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps(dict(
        schema=rerun.SPEC_SCHEMA, work_base=str(work), passes=changed_pass,
        stage_inputs=[{'from': str(source), 'to': 'input.txt'}],
        steps=[dict(id='constant', argv=['{python}', '-B', str(script)],
                    deterministic_outputs=['out.txt'], receipt='receipt.json',
                    receipt_checks=[dict(pointer='/verdict', equals='PASS')])],
        coast_prod={pid: dict(steps=['constant']) for pid in rerun.PROD_IDS},
    )))
    original_stage = rerun.stage

    def stage(spec, root):
        if root.name == f'pass-{changed_pass}':
            if case == 'content':
                source.write_text('other')
            elif case == 'missing-entry':
                spec = dict(spec, stage_inputs=[])
            elif case == 'renamed':
                spec = dict(spec, stage_inputs=[{'from': str(source), 'to': 'renamed.txt'}])
            elif case == 'missing-source':
                source.unlink()
        return original_stage(spec, root)

    monkeypatch.setattr(rerun, 'stage', stage)
    code = rerun.main(['--spec', str(spec)])
    report = json.loads((work / 'report.json').read_text())
    if case != 'missing-source':
        assert report['comparison']['constant']['identical'] is True
    assert (code, report['verdict']) == ((1, 'NOT_PASS') if targets else (0, 'PASS'))
    assert {entry['status'] for entry in report['coast_prod'].values()} == ({'FAIL'} if targets else {'PASS'})
    for target in targets:
        assert any(f'pass {changed_pass}' in reason and repr(target) in reason
                   for reason in report['verdict_reasons'])
