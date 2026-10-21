"""Offline pilot populations and real CLI tests with explicitly synthetic receipts."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from tests._support import ROOT
from tests.coast_contract_factory import materialize, load_helper
from tests.unit.test_coast_sign_off import Cycle

refs = load_helper('coast_refs')
load_helper('validate_coast_receipt')
SCRIPT = ROOT / 'skills/coast-campaign-shared/scripts/metrics_rollup.py'
spec = importlib.util.spec_from_file_location('metrics_rollup', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SINCE = m.utc('2026-10-20T00:00:00Z')


class MappedCycle(Cycle):
    """Add native stage evidence to the sign-off fixture's synthetic map states."""
    def put(self, name, value):
        if isinstance(value, dict) and value.get('schema') == 'coast-run-summary-v1':
            for i, window in enumerate(value['windows']):
                window['stages'] = []
                for stage in ('acquire', 'qualify', 'map'):
                    state = 'held' if window['state'] == 'held' else 'done'
                    holds = ['synthetic_hold'] if state == 'held' else []
                    source = self.instances['admission']['plan_file']
                    job = f'synthetic-{i}-{stage}'
                    result = dict(schema='coastal-stage-result-v1', stage=stage, job_id=job,
                                  segment_id=value['coordinator_segment_id'], input_manifest_sha=source['sha256'],
                                  state=state, holds=holds, artifacts=[])
                    result_ref = super().put(name.removesuffix('.json') + f'-{i}-{stage}.json', result)
                    window['stages'].append(dict(stage=stage, job_id=job, state=state, holds=holds,
                        input_manifest=source, result=result_ref, products=[], missing_reason=None))
                    if state == 'held':
                        break
        return super().put(name, value)


class Inventory:
    def __init__(self, tmp):
        self.instances, _ = materialize(tmp)
        (tmp / 'queue').rename(tmp / 'synthetic')
        self.root = tmp
        self.queue = tmp / 'synthetic'
        self.bindings = {'queue:synthetic': str(self.queue)}
        self.resolver = refs.Resolver(self.bindings, allowed_root_ids=self.bindings)
        self.cohort = dict(schema='coast-metrics-cohort-v1', allowed_root_ids=list(self.bindings),
                           plans=[], ledgers=[], measurements={})
        self.cohort_ref = None

    def put(self, name, value):
        p = self.queue / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(refs.canonical(value))
        return dict(root_id='queue:synthetic', path=name, sha256=refs.sha256(p.read_bytes()), bytes=p.stat().st_size)

    def plan(self, states, name='plan01', replacement=None):
        a = copy.deepcopy(self.instances['admission'])
        template = a['windows'][0]
        a.update(plan_id=name, plan_sha256=refs.sha256(name.encode()), replacement_plan_of=replacement)
        a['windows'] = [dict(template, idx=i, window_key=template['window_key'].rsplit('#', 1)[0] + '#' + str(i)) for i in range(len(states))]
        sampler = load_helper('coast_sample')
        for w in a['windows']:
            w['window_dir'] = sampler.window_dir(w['window_key'])
        ar = self.put(f'plans/{name}/admission.json', a)
        run = copy.deepcopy(self.instances['run-summary'])
        run.update(**{k: a[k] for k in m.IDENTITY}, admission=ar, windows=[], partition={k: [] for k in run['partition']})
        for i, (ac, qu, ma) in enumerate(states):
            stages = []
            for stage_name, state in zip(('acquire', 'qualify', 'map'), (ac, qu, ma)):
                if state is None:
                    continue
                job = f'synthetic-{name}-{i}-{stage_name}'
                source = a['plan_file']
                holds = ['synthetic_hold'] if state == 'held' else []
                result = dict(schema='coastal-stage-result-v1', stage=stage_name, job_id=job,
                              segment_id=a['coordinator_segment_id'], input_manifest_sha=source['sha256'],
                              state=state, holds=holds, artifacts=[])
                result_ref = self.put(f'plans/{name}/products/{i}-{stage_name}.json', result)
                stages.append(dict(stage=stage_name, job_id=job, input_manifest=source, result=result_ref,
                                   state=state, products=[], holds=holds, missing_reason=None))
            state = 'held' if 'held' in (ac, qu, ma) else 'map_done' if ma == 'done' else 'unfinished'
            key = a['windows'][i]['window_key']
            run['windows'].append(dict(window_key=key, state=state, stages=stages, missing_stage_reasons=[]))
            run['partition'][state].append(key)
        rr = self.put(f'plans/{name}/runs/run-01.json', run)
        item = dict(admission=ar, runs=[rr], verdicts=[])
        self.cohort['plans'].append(item)
        return a, run, item

    def metrics(self, **kwargs):
        raw = refs.canonical(self.cohort)
        self.cohort_ref = m.local_evidence(self.root / 'cohort.json', raw)
        return m.rollup(self.resolver, self.root, self.cohort, SINCE, cohort_ref=self.cohort_ref, **kwargs)


def test_W4_A3_Q2_and_map_hold_is_not_qualify_hold(tmp_path):
    f = Inventory(tmp_path)
    f.plan([('held', None, None), ('done', None, None), ('done', 'done', 'held'), ('done', 'done', 'done')])
    out = f.metrics()
    assert (out['inventory']['W'], out['inventory']['A'], out['inventory']['Q']) == (4, 3, 2)
    assert out['metrics']['qualify_clean_all_admitted']['value'] == 0.5
    assert out['metrics']['qualify_clean_given_acquire_done']['value'] == pytest.approx(2/3)
    assert out['metrics']['map_done']['value'] == 1
    for group in ('acquire_held', 'qualify_pending', 'map_held', 'acquire_done_without_qualify'):
        assert out['inventory']['exclusions'][group]['count'] == 1


@pytest.mark.parametrize('states,group', [([('failed_terminal', None, None)], 'acquire_failed'),
    ([('queued', None, None)], 'acquire_pending'), ([('done', 'held', None)], 'qualify_held'),
    ([('done', 'failed_terminal', None)], 'qualify_failed')])
def test_explicit_exclusions(tmp_path, states, group):
    f = Inventory(tmp_path)
    f.plan(states)
    assert f.metrics()['inventory']['exclusions'][group]['count'] == 1


def test_missing_run_does_not_remove_admitted_windows(tmp_path):
    f = Inventory(tmp_path)
    _, _, item = f.plan([('done', 'done', 'done')])
    item['runs'] = []
    out = f.metrics()
    assert out['inventory']['W'] == 1
    assert out['inventory']['A'] == out['inventory']['Q'] == 0
    assert out['metrics']['qualify_clean_all_admitted']['value'] == 0
    assert out['metrics']['qualify_clean_given_acquire_done']['display'] == 'not measured'
    assert not out['evidence_complete']


def test_zero_population_is_never_pass(tmp_path):
    out = Inventory(tmp_path).metrics()
    assert out['inventory']['W'] == 0
    for name in ('qualify_clean_all_admitted', 'screener_recall', 'sampled_must_fix', 'accepted_plans_per_day'):
        assert out['metrics'][name]['value'] is None
        assert out['metrics'][name]['display'] == 'not measured'
        assert out['metrics'][name]['status'] == 'unavailable'


def test_replacement_deduplicates_inventory_and_uses_final_stage(tmp_path):
    f = Inventory(tmp_path)
    _, _, old = f.plan([('held', None, None)])
    _, _, new = f.plan([('done', 'done', 'done')], 'plan02', replacement=old['admission'])
    out = f.metrics()
    assert out['inventory']['W'] == out['inventory']['A'] == out['inventory']['Q'] == 1
    assert out['inventory']['replacement_exclusions'] == [old['admission']]
    assert len(out['final_plans']) == 1
    assert out['final_plans'][0]['inventory'] == 'synthetic/plan01'
    f.cohort['plans'].append(dict(new))
    with pytest.raises(ValueError, match='duplicate admission'):
        f.metrics()


def test_broken_run_keeps_W_and_never_trusts_done(tmp_path):
    f = Inventory(tmp_path)
    _, _, item = f.plan([('done', 'done', 'done')])
    item['runs'][0]['sha256'] = 'f' * 64
    out = f.metrics()
    assert out['inventory']['W'] == 1 and out['inventory']['Q'] == 0
    assert out['metrics']['broken_receipts']['value'] == 1
    assert not out['evidence_complete']


def test_Q_requires_acquire_and_actual_result(tmp_path):
    f = Inventory(tmp_path)
    _, run, item = f.plan([(None, 'done', 'done')])
    out = f.metrics()
    assert out['inventory']['Q'] == 0
    assert out['inventory']['exclusions']['integrity_unavailable']['count'] == 1
    run['windows'][0]['stages'][0]['result'] = None
    item['runs'] = [f.put('plans/plan01/runs/run-01.json', run)]
    assert f.metrics()['inventory']['Q'] == 0


def cycle_rollup(c, tmp):
    # Cycle's explicitly synthetic queue is renamed to the required campaign layout.
    old = c.queue
    c.queue = tmp / 'synthetic'
    old.rename(c.queue)
    c.bindings = {'queue:synthetic': str(c.queue)}
    c.resolver = refs.Resolver(c.bindings, allowed_root_ids=c.bindings)
    cohort = dict(schema='coast-metrics-cohort-v1', allowed_root_ids=list(c.bindings), measurements={},
                  plans=[dict(admission=c.context['admission'], runs=[c.context['run']], verdicts=[c.previous_verdict])],
                  ledgers=[m.pin(c.resolver, c.queue / 'ledger.jsonl')])
    # The campaign index is an explicit immutable snapshot inside its own root.
    dest = c.queue / 'campaign-index.jsonl'
    dest.write_bytes((tmp / 'campaign-ledger.jsonl').read_bytes())
    cohort['ledgers'].append(m.pin(c.resolver, dest))
    return cohort


def test_confusion_only_examined_complete_and_isolated_NA_passes(tmp_path):
    c = MappedCycle(tmp_path).round(('pass', 'pass', 'flag', 'unavailable', 'held'))
    assert c.open() == 0
    decisions = c.decisions('must_fix', [True, False, True, None, None])
    decisions['decisions'] = [d for i,d in enumerate(decisions['decisions']) if i != 1]
    c.write(decisions)
    cohort = cycle_rollup(c, tmp_path)
    out = m.rollup(c.resolver, tmp_path, cohort, SINCE, cohort_ref={'fixture': 'synthetic'})
    assert out['confusion']['counts'] == dict(tp=1, fp=0, fn=1, tn=0)
    assert len(out['confusion']['groups']['unexamined']) == 1
    assert len(out['confusion']['groups']['held']) == 1
    assert len(out['confusion']['groups']['unavailable_required']) == 1
    assert out['metrics']['screener_recall']['value'] == 0.5
    assert 'not whole-coast recall' in out['limitations']


def test_accepted_unavailable_cause_is_NOT_true_negative(tmp_path):
    c = MappedCycle(tmp_path).round(('unavailable',))
    assert c.open() == 0
    c.write(c.decisions(defects=[None]))
    cohort = cycle_rollup(c, tmp_path)
    out = m.rollup(c.resolver, tmp_path, cohort, SINCE, cohort_ref={'fixture': 'synthetic'})
    assert out['confusion']['counts']['tn'] == 0
    assert len(out['confusion']['groups']['unavailable_required']) == 1
    assert out['metrics']['screener_recall']['value'] is None


def test_isolated_not_applicable_neighbour_is_eligible(tmp_path):
    c = MappedCycle(tmp_path).round()
    assert c.open() == 0
    c.write(c.decisions())
    cohort = cycle_rollup(c, tmp_path)
    out = m.rollup(c.resolver, tmp_path, cohort, SINCE, cohort_ref={'fixture': 'synthetic'})
    assert out['confusion']['counts']['tn'] == 1
    assert out['metrics']['screener_precision']['value'] is None
    assert out['metrics']['contour_visual_clean']['value'] is None
    assert out['metrics']['n16_within_budget']['value'] is None
    assert out['metrics']['local_tokens']['value'] is None
    assert out['metrics']['reviewer_minutes_per_plan']['value'] == 2.0
    assert out['metrics']['tier2_packet_accuracy']['value'] is None
    assert out['metrics']['accepted_plans_per_day']['population']['numerator'] == 1


def test_interim_cycle1_shape_missing_values_stay_unknown(tmp_path):
    directory = tmp_path / 'interim'
    directory.mkdir()
    # Synthetic cycle-1 field names; receipt_dir is untrusted provenance, never followed.
    t1 = dict(run='synthetic-run', receipt_dir='/not-read', generated_at='2026-10-21T00:00:00+0000',
              files=[], posted_sha256_compare=dict(posted_count=1, computed_count=0),
              gate_fields=[], rows=[], thumbnails=[], deterministic_flags=[], model_flags=[], wall_seconds=0.0)
    (directory / 'tier1-R-C1-D1.json').write_bytes(refs.canonical(t1))
    (directory / 'packet-R-C1-D1.json').write_bytes(refs.canonical(dict(run_id='synthetic-run', flags_confirmed=2, flags_total=2)))
    out = Inventory(tmp_path / 'canonical').metrics(interim=directory)
    assert len(out['interim']) == 2
    assert all(r['label'] == 'interim' for r in out['interim'])
    assert all(r['tier2_packet_accuracy']['value'] is None for r in out['interim'])
    assert out['inventory']['W'] == 0


def test_exact_cli_write_once_and_documented_shape(tmp_path):
    f = Inventory(tmp_path)
    f.plan([('held', None, None)])
    roots = tmp_path / 'roots.json'
    cohort = tmp_path / 'cohort.json'
    out = tmp_path / 'metrics.json'
    roots.write_bytes(refs.canonical(f.bindings))
    cohort.write_bytes(refs.canonical(f.cohort))
    cmd = [sys.executable, str(SCRIPT), '--roots', str(roots), '--root', str(tmp_path), '--cohort', str(cohort),
           '--since', '2026-10-20T00:00:00Z', '--out', str(out)]
    run = subprocess.run(cmd, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    value = json.loads(out.read_text())
    text = (SCRIPT.parents[1] / 'references/metrics.md').read_text()
    schema = json.loads(text.split('<!-- OUTPUT-SCHEMA -->\n```json\n')[1].split('\n```')[0])
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    again = subprocess.run(cmd, capture_output=True, text=True)
    assert again.returncode == 3 and 'File exists' in again.stderr


def test_symlink_interim_refused(tmp_path):
    directory = tmp_path / 'interim'
    directory.mkdir()
    target = tmp_path / 'elsewhere.json'
    target.write_text('{}')
    (directory / 'tier1-R-C1-D1.json').symlink_to(target)
    with pytest.raises(OSError):
        m.interim_rollup(directory, SINCE)


def test_since_requires_UTC():
    for stamp in ('2026-10-20T01:00:00', '2026-10-20T01:00:00-07:00'):
        with pytest.raises(ValueError, match='UTC'):
            m.utc(stamp)


def test_r1_r2_is_one_final_plan_not_two_verdicts(tmp_path):
    class CorrectedCycle(MappedCycle):
        def put(self, name, value):
            if isinstance(value, dict) and value.get('schema') == 'coast-admission-v1':
                if hasattr(self, 'first_admission'):
                    assert refs.canonical(value) == self.first_admission[0]
                    return self.first_admission[1]
                result = super().put(name, value)
                self.first_admission = (refs.canonical(value), result)
                return result
            if isinstance(value, dict) and value.get('schema') == 'coast-run-summary-v1':
                # A corrective execution, not an ordinary continuation.
                value['sequence'] = 1
            return super().put(name, value)
    c = CorrectedCycle(tmp_path).round()
    assert c.open() == 0
    c.write(c.decisions('must_fix', [True]))
    r1 = c.previous_verdict
    original_bytes = {p: p.read_bytes() for p in c.r.rglob('*') if p.is_file()}
    c.round(number=2)
    assert c.open() == 0
    c.write(c.decisions())
    for path, raw in original_bytes.items():
        assert path.read_bytes() == raw
    cohort = cycle_rollup(c, tmp_path)
    cohort['plans'][0]['verdicts'].insert(0, r1)
    out = m.rollup(c.resolver, tmp_path, cohort, SINCE, cohort_ref={'fixture': 'synthetic'})
    assert len(out['final_plans']) == 1
    assert out['inventory']['W'] == 1
    assert out['metrics']['review_rounds_median']['value'] == 2
    assert out['metrics']['reviewer_minutes_per_plan']['value'] == 4
    assert out['metrics']['accepted_plans_per_day']['population']['numerator'] == 1


def test_sampled_unexamined_cannot_be_zero_must_fix_claim(tmp_path):
    c = MappedCycle(tmp_path).round(('pass', 'pass'))
    assert c.open() == 0
    decisions = c.decisions('must_fix', [True, False])
    decisions['decisions'] = decisions['decisions'][:1]
    c.write(decisions)
    cohort = cycle_rollup(c, tmp_path)
    out = m.rollup(c.resolver, tmp_path, cohort, SINCE, cohort_ref={'fixture': 'synthetic'})
    assert out['metrics']['sampled_must_fix']['value'] is None
    assert len(out['metrics']['sampled_must_fix']['population']['unavailable']) == 1


def test_board_export_scope_and_unknown_absence(tmp_path):
    f = Inventory(tmp_path)
    f.plan([('held', None, None)])
    assert f.metrics()['metrics']['operator_rescues']['value'] is None
    board = tmp_path / 'board.json'
    value = dict(schema='coast-board-events-v1', since='2026-10-20T00:00:00Z', until='2026-10-22T00:00:00Z',
                 cohort=f.cohort_ref, events=[dict(id='synthetic-event', created_utc='2026-10-21T00:00:00Z', operator_rescue=True)])
    board.write_bytes(refs.canonical(value))
    assert f.metrics(board=board)['metrics']['operator_rescues']['value'] == 1
    value['cohort']['sha256'] = 'f'*64
    board.write_bytes(refs.canonical(value))
    with pytest.raises(ValueError, match='cohort-bound'):
        f.metrics(board=board)


def test_supplementary_cannot_borrow_unrelated_acceptance(tmp_path):
    c = MappedCycle(tmp_path).round()
    assert c.open() == 0
    c.write(c.decisions())
    cohort = cycle_rollup(c, tmp_path)
    artifact = c.put('synthetic-preview.txt', b'Synthetic contour preview only.\n')
    supplementary = dict(schema='coast-pilot-measurement-v1', metric='contour_visual_clean',
                         measurement=dict(status='measured', value=True, reason=None, method_version='synthetic-v1'),
                         population=dict(scope='synthetic contour'), evidence=[artifact], reviewer_verdict=c.previous_verdict)
    cohort['measurements']['contour_visual_clean'] = c.put('synthetic-measurement.json', supplementary)
    out = m.rollup(c.resolver, tmp_path, cohort, SINCE, cohort_ref={'fixture': 'synthetic'})
    assert out['metrics']['contour_visual_clean']['value'] is None
    assert out['metrics']['contour_visual_clean']['reason'] == 'supplementary_artifacts_not_in_reviewer_decisions'


def test_skill_commands_and_boundary_no_board_writes():
    expected = '"$SC_PY" skills/coast-campaign-shared/scripts/metrics_rollup.py --roots "$ROOTS" --root "$COAST_ROOT" --cohort "$COHORT" --since "$CYCLE_START_UTC" --interim "$INTERIM_DIR" --board-events "$BOARD_EXPORT" --out "$METRICS_OUT"'
    for name in ('coast-pilot-audit', 'coast-pilot-replan'):
        skill = (ROOT / 'skills' / name / 'SKILL.md').read_text()
        assert expected in skill
        for heading in ('Purpose', 'Runs on', 'Inputs', 'Exact commands', 'Acceptance checks', 'Failure modes', 'Metrics emitted', 'Never'):
            assert '## ' + heading in skill
    source = SCRIPT.read_text()
    assert 'sqlite3' not in source and 'kanban_' not in source


def test_measured_tier2_accuracy_is_from_verdict_not_self_confirmation(tmp_path):
    c = MappedCycle(tmp_path).round(('flag',))
    assert c.open() == 0
    decisions = c.decisions()
    decisions['tier2_assessments'] = [dict(finding_index=0, confirmed=True)]
    c.write(decisions)
    cohort = cycle_rollup(c, tmp_path)
    out = m.rollup(c.resolver, tmp_path, cohort, SINCE, cohort_ref={'fixture': 'synthetic'})
    assert out['metrics']['tier2_packet_accuracy']['value'] == 1
    assert out['metrics']['tier2_packet_accuracy']['population']['unavailable_plans'] == 0


@pytest.mark.parametrize('name,number', [('contour_visual_clean', 1), ('n16_within_budget', 16)])
def test_separately_reviewed_artifact_and_synthetic_N16_limit(tmp_path, name, number):
    c = MappedCycle(tmp_path).round(('pass',) * number)
    artifact = c.put('synthetic-contour.txt', b'Synthetic reviewed contour preview.\n')
    evidence = artifact if name == 'contour_visual_clean' else c.context['run']
    assert c.open() == 0
    decisions = c.decisions()
    decisions['decisions'][0]['evidence'] = [evidence]
    c.write(decisions)
    cohort = cycle_rollup(c, tmp_path)
    supplementary = dict(schema='coast-pilot-measurement-v1', metric=name,
                         measurement=dict(status='measured', value=True, reason=None, method_version='synthetic-v1'),
                         population=dict(scope='explicit synthetic test only'), evidence=[evidence], reviewer_verdict=c.previous_verdict)
    cohort['measurements'][name] = c.put('synthetic-measurement.json', supplementary)
    out = m.rollup(c.resolver, tmp_path, cohort, SINCE, cohort_ref={'fixture': 'synthetic'})
    if name == 'contour_visual_clean':
        assert out['metrics'][name]['value'] is True
    else:
        assert out['metrics'][name]['value'] is None
        assert out['metrics'][name]['reason'] == 'no_single_actual_complete_N16_execution'
