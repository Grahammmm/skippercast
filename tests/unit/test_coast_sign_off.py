"""Synthetic offline T1/T2 evidence: no live models, producers or board writes."""
import copy
import importlib.util
import subprocess
import sys

import pytest

from tests.coast_contract_factory import materialize, load_helper
from tests._support import ROOT

SCRIPTS = ROOT / 'skills/coast-sign-off/scripts'
refs = load_helper('coast_refs')
sampler = load_helper('coast_sample')
validator = load_helper('validate_coast_receipt')
ledger_module = load_helper('coast_ledger')


def module(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


common = module('review_common')
prepare = module('prepare_round')
opener = module('open_packet')
writer = module('write_verdict')


class Cycle:
    def __init__(self, tmp):
        self.instances, self.bindings = materialize(tmp)
        self.queue = tmp / 'queue'
        self.bindings = {'queue:synthetic': str(self.queue)}
        self.resolver = refs.Resolver(self.bindings, allowed_root_ids=self.bindings)
        self.roots = tmp / 'roots.json'
        self.roots.write_bytes(refs.canonical(self.bindings))
        self.runtime = dict(actual_model='synthetic-reviewer', family='review-family', profile='synthetic-reviewer',
                            card_id='t_d34cf3aa', code_commit='3'*40, skill_commit='3'*40,
                            created_utc='2026-10-21T01:00:00Z', session_id='synthetic-session', provider='offline')
        self.reviewer_ref = self.put('provenance/reviewer.txt', self.runtime)
        author = dict(self.runtime, actual_model='synthetic-author', family='author-family')
        self.author_ref = self.put('provenance/author.txt', author)
        identity = {k: self.instances['review-context'][k] for k in common.IDENTITY}
        identity.update(run_author_model='synthetic-author', run_card_id='t_366d24e2')
        self.identity_ref = self.put('provenance/identity.txt', identity)
        self.routing = copy.deepcopy(self.instances['review-routing'])
        self.routing.update(allowed_pairs=[dict(author_model='synthetic-author', reviewer_model='synthetic-reviewer')],
                            qualified_reviewers=[dict(actual_model='synthetic-reviewer', family='review-family', provenance=self.reviewer_ref)])
        self.routing_ref = self.put('provenance/routing.json', self.routing)
        self.previous_context = None
        self.previous_verdict = None

    def put(self, name, value):
        path = self.queue / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = value if isinstance(value, bytes) else refs.canonical(value)
        refs.write_once(path, value) if not isinstance(value, bytes) else path.write_bytes(raw)
        return dict(root_id='queue:synthetic', path=name, sha256=refs.sha256(raw), bytes=len(raw))

    def path(self, ref):
        return self.queue / ref['path']

    def round(self, statuses=('pass',), number=1, flags=(), states=None):
        self.r = self.queue / f'plans/plan01/review/r{number:02d}/a01'
        for tier in ('tier1', 'tier2', 'tier3'):
            (self.r / tier).mkdir(parents=True)
        run = copy.deepcopy(self.instances['run-summary'])
        admission = copy.deepcopy(self.instances['admission'])
        first = admission['windows'][0]
        admission['windows'] = []
        run['windows'] = []
        run['partition'] = {k: [] for k in run['partition']}
        self.keys = []
        for idx, status in enumerate(statuses):
            key = sampler.window_key(first['source_id'], first['grid_sha256'], idx)
            self.keys.append(key)
            w = dict(first, idx=idx, window_key=key, window_dir=sampler.window_dir(key))
            admission['windows'].append(w)
            state = states[idx] if states else 'held' if status == 'held' else 'map_done'
            run['windows'].append(dict(window_key=key, state=state, stages=[], missing_stage_reasons=[]))
            run['partition'][state].append(key)
        admission['grids'][0].update(total=len(statuses), cols=len(statuses), width=len(statuses))
        ar = self.put(f'plans/plan01/admission-{number:02d}.json', admission)
        enqueue = copy.deepcopy(self.instances['enqueue-receipt'])
        enqueue['admission'] = ar
        en = self.put(f'plans/plan01/enqueue-{number:02d}.json', enqueue)
        run.update(admission=ar, enqueue=en, sequence=number)
        run_ref = self.put(f'plans/plan01/runs/run-{number:02d}.json', run)
        context = copy.deepcopy(self.instances['review-context'])
        context.update(root_ids=list(self.bindings), run=run_ref, admission=ar, enqueue=en,
                       identity_provenance=self.identity_ref, run_author_provenance=self.author_ref,
                       routing=self.routing_ref, review_round=number,
                       supersedes=self.previous_context, correction_verdict=self.previous_verdict)
        context['posted_hashes'] = self.put(f'provenance/posted-{number:02d}.txt', {k: context[k] for k in common.PINS})
        self.context_input = self.put(f'provenance/context-input-{number:02d}.txt', context)
        self.context_ref, diagnostic = prepare.prepare(self.resolver, context, number, 1, self.r / 'context.json')
        assert not diagnostic
        self.context = common.document(self.resolver, self.context_ref)
        t1 = copy.deepcopy(self.instances['tier1-screen'])
        template = copy.deepcopy(t1['windows'][0])
        t1.update(context=self.context_ref, review_round=number, run=run_ref, windows=[])
        for idx, status in enumerate(statuses):
            w = copy.deepcopy(template)
            w.update(window_key=self.keys[idx], stage_state=run['windows'][idx]['state'], status=status)
            if w['stage_state'] == 'map_done':
                for name in opener.REQUIRED:
                    w['measurements'][name] = dict(status='measured', value=0.5, reason=None, inputs=[], method_version='synthetic')
                w['measurements']['neighbour_delta']['reason'] = 'no_geometric_neighbours'
                if len(statuses) > 1:
                    w['measurements']['neighbour_delta'] = dict(status='measured', value=0, reason=None, inputs=[], method_version='synthetic')
                w['measurements']['catalog_range']['reason'] = 'catalog_range_absent'
            if status == 'unavailable':
                w['measurements']['valid_fraction'] = dict(status='unavailable', value=None, reason='synthetic missing', inputs=[], method_version='synthetic')
            if status == 'flag':
                w['flags'] = [common.finding('SYNTHETIC_FLAG', 'offline quality flag', self.keys[idx])]
                w['flags'][0]['severity'] = 'should'
            t1['windows'].append(w)
        t1['counts'] = dict(pass_count=statuses.count('pass'), flag=statuses.count('flag'), held=statuses.count('held'), unavailable=statuses.count('unavailable'))
        t1_ref = self.put(self.relative('tier1/flagged-windows.json'), t1)
        checks = {}
        for mode in ('rehash', 'budgets', 'neighbours'):
            check = copy.deepcopy(self.instances['tier2-check'])
            check.update(context=self.context_ref, review_round=number, mode=mode, verified_inputs=[t1_ref])
            checks[mode] = self.put(self.relative(f'tier2/{mode}.json'), check)
        packet = copy.deepcopy(self.instances['review-packet'])
        packet.update(context=self.context_ref, review_round=number, admission=ar, run=run_ref, tier1=t1_ref,
                      checks=checks, routing=self.routing_ref, run_author_provenance=self.author_ref,
                      flags=list(flags) + [f for w in t1['windows'] for f in w['flags']])
        packet['population'] = opener.population(self.resolver, self.context, packet)
        packet['sample'] = sampler.sample(packet['population']['map_done'], packet['population']['eligible'],
                                          plan_sha256=context['plan_sha256'], bridge_sha256=context['bridge']['sha256'])
        self.packet = packet
        self.packet_ref = self.put(self.relative('tier2/review-packet.json'), packet)
        self.previous_context = self.context_ref
        return self

    def relative(self, leaf):
        return (self.r / leaf).relative_to(self.queue).as_posix()

    def open(self):
        self.report_ref, code = opener.open_packet(self.resolver, self.context_ref, self.path(self.packet_ref),
                                                  self.packet_ref['sha256'], 'synthetic-reviewer', self.reviewer_ref,
                                                  self.r / 'tier3/open-report.json')
        return code

    def decisions(self, verdict='accept', defects=None):
        defects = defects or [False] * len(self.keys)
        return dict(verdict=verdict, decisions=[dict(window_key=k, defect=d, accepted_cause='synthetic accepted closure' if self.packet['population']['flagged'] else None,
                    detail='Synthetic offline reference judgement', evidence=[]) for k, d in zip(self.keys, defects)],
                    must_fix=[], tier2_assessments=[], external_blocker=None)

    def write(self, decisions):
        result = writer.write_verdict(self.resolver, self.context_ref, self.report_ref, decisions, 2.0,
                                      self.r / 'tier3/verdict.json', self.queue / 'ledger.jsonl',
                                      self.queue.parent / 'campaign-ledger.jsonl')
        self.previous_verdict = result['verdict']
        return result

    def cli(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), '--roots', str(self.roots),
                               '--allowed-root-id', 'queue:synthetic', *map(str, args)], capture_output=True, text=True)


def test_normal_sample_and_chain_idempotency(tmp_path):
    c = Cycle(tmp_path).round(('pass',) * 16)
    assert c.open() == 0
    assert c.packet['sample']['size'] == 8
    result = c.write(c.decisions())
    assert result['board_action']['action'] == 'complete_review_and_create_next_admission'
    verdict = common.document(c.resolver, result['verdict'])
    assert verdict['tier1_confusion']['tn'] == 16
    for path in (c.queue / 'ledger.jsonl', c.queue.parent / 'campaign-ledger.jsonl'):
        assert len(ledger_module.verify(path)) == 1
    before = (c.queue / 'ledger.jsonl').read_bytes()
    assert c.write(c.decisions()) == result
    assert (c.queue / 'ledger.jsonl').read_bytes() == before
    validator.validate(verdict, c.resolver, root_id='queue:synthetic')
    for row in result['ledgers'].values():
        if isinstance(row, dict):
            validator.validate(row, c.resolver, root_id='queue:synthetic')


@pytest.mark.parametrize('target', ['tier1', 'run'])
def test_changed_input_cli_corrective_error_is_valid(tmp_path, target):
    c = Cycle(tmp_path).round()
    ref = c.packet['tier1'] if target == 'tier1' else c.context['run']
    path = c.path(ref)
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + b' ')
    opened = c.cli('open_packet.py', '--context', c.path(c.context_ref), '--expected-context-sha256', c.context_ref['sha256'],
                   '--packet', c.path(c.packet_ref), '--expected-packet-sha256', c.packet_ref['sha256'],
                   '--reviewer-model', 'synthetic-reviewer', '--reviewer-provenance', c.path(c.reviewer_ref),
                   '--out', c.r / 'tier3/open-report.json')
    assert opened.returncode == 3, opened.stderr
    c.report_ref = refs.loads(opened.stdout)['open_report']
    report = common.document(c.resolver, c.report_ref)
    assert not report['measurements_trusted']
    decisions_ref = c.put(c.relative('tier3/decisions.txt'), c.decisions('accept'))
    written = c.cli('write_verdict.py', '--context', c.path(c.context_ref), '--expected-context-sha256', c.context_ref['sha256'],
                    '--open-report', c.path(c.report_ref), '--expected-open-report-sha256', c.report_ref['sha256'],
                    '--decisions', c.path(decisions_ref), '--minutes', 2, '--out', c.r / 'tier3/verdict.json',
                    '--ledger', c.queue / 'ledger.jsonl', '--campaign-ledger', c.queue.parent / 'campaign-ledger.jsonl')
    assert written.returncode == 0, written.stderr
    result = refs.loads(written.stdout)
    verdict = common.document(c.resolver, result['verdict'])
    assert verdict['verdict'] == 'must_fix'  # attempted accept cannot override error
    assert verdict['packet'] is verdict['population'] is verdict['tier1_confusion'] is verdict['tier2_packet_accuracy'] is None
    assert verdict['validation_scope'] == 'identity_snapshot'
    assert verdict['windows_examined'] == []
    assert not verdict['next_tile_card_authorized']
    for path in (c.r / 'tier3/open-report.json', c.r / 'tier3/verdict.json'):
        checked = subprocess.run([sys.executable, str(validator.SHARED / 'scripts/validate_coast_receipt.py'), str(path),
                                  '--roots', str(c.roots), '--allowed-root-id', 'queue:synthetic', '--root-id', 'queue:synthetic'], capture_output=True, text=True)
        assert checked.returncode == 0, checked.stderr
    for path in (c.queue / 'ledger.jsonl', c.queue.parent / 'campaign-ledger.jsonl'):
        rows = ledger_module.verify(path)
        assert len(rows) == 1
        validator.validate(rows[0], c.resolver, root_id='queue:synthetic')


def test_two_rounds_never_rewrite_previous_files(tmp_path):
    c = Cycle(tmp_path).round(('flag',))
    assert c.open() == 0
    result = c.write(c.decisions('must_fix', [True]))
    assert result['board_action']['next_round'] == 2
    r1 = c.r
    original = {p: refs.sha256(p.read_bytes()) for p in r1.rglob('*') if p.is_file()}
    first_run = c.context['run']
    c.round(('pass',), number=2)
    assert c.context['run'] != first_run
    assert c.open() == 0
    result = c.write(c.decisions())
    assert result['board_action']['next_inventory_authorized']
    assert original == {p: refs.sha256(p.read_bytes()) for p in original}
    assert c.context['correction_verdict']['path'].endswith('r01/a01/tier3/verdict.json')
    for path in (c.queue / 'ledger.jsonl', c.queue.parent / 'campaign-ledger.jsonl'):
        assert len(ledger_module.verify(path)) == 2


@pytest.mark.parametrize('statuses,defects,expected', [
    (('flag', 'flag', 'pass', 'pass'), [True, False, True, False], dict(tp=1, fp=1, fn=1, tn=1)),
    (('held', 'unavailable', 'pass'), [False, False, False], dict(tp=0, fp=0, fn=0, tn=1)),
])
def test_confusion_named_population_excludes_held_and_unavailable(tmp_path, statuses, defects, expected):
    c = Cycle(tmp_path).round(statuses)
    assert c.open() == 0
    decisions = c.decisions('must_fix' if any(defects) else 'accept', defects)
    result = c.write(decisions)
    verdict = common.document(c.resolver, result['verdict'])
    assert {k: verdict['tier1_confusion'][k] for k in expected} == expected
    if statuses[0] == 'held':
        assert result['metrics']['exclusions']['held'] == [c.keys[0]]
        assert result['metrics']['exclusions']['unavailable_required'] == [c.keys[1]]
    else:
        assert result['metrics']['recall'] == result['metrics']['precision'] == 0.5
        assert result['metrics']['misses'] == 1


@pytest.mark.parametrize('mode', ['same_model', 'same_family', 'forbidden', 'unqualified', 'wrong_provenance'])
def test_reviewer_refusals(tmp_path, mode):
    c = Cycle(tmp_path)
    if mode == 'same_model':
        c.runtime['actual_model'] = 'synthetic-author'
    elif mode == 'same_family':
        c.runtime['family'] = 'author-family'
    elif mode == 'forbidden':
        c.routing['disallowed_family_pairs'] = [['author-family', 'review-family']]
    elif mode == 'unqualified':
        c.routing['allowed_pairs'] = []
    else:
        c.runtime['actual_model'] = 'not-the-reviewer'
    c.reviewer_ref = c.put('provenance/refused-reviewer.txt', c.runtime)
    c.routing_ref = c.put('provenance/refused-routing.json', c.routing)
    c.round()
    with pytest.raises(ValueError):
        c.open()
    assert not (c.r / 'tier3/verdict.json').exists()


@pytest.mark.parametrize('code', ['HASH_MISMATCH', 'REQUESTS_NONZERO', 'CAP_EXCEEDED'])
def test_accept_refuses_packet_must(tmp_path, code):
    c = Cycle(tmp_path).round(flags=[common.finding(code, 'synthetic global must finding')])
    assert c.open() == 0
    with pytest.raises(ValueError, match='accept refused'):
        c.write(c.decisions())
    assert not (c.queue / 'ledger.jsonl').exists()


def test_hold_requires_external_blocker_and_prints_block_action(tmp_path):
    c = Cycle(tmp_path).round()
    assert c.open() == 0
    decisions = c.decisions('hold')
    with pytest.raises(ValueError, match='genuine external'):
        c.write(decisions)
    decisions['external_blocker'] = dict(kind='medium', detail='Synthetic admitted archive medium offline')
    result = c.write(decisions)
    assert result['board_action']['action'] == 'block_current_review_external_dependency'


def test_sample_tamper_is_corrective(tmp_path):
    c = Cycle(tmp_path).round(('pass',) * 16)
    packet = copy.deepcopy(c.packet)
    packet['sample']['selected'] = c.keys[:8]
    if packet['sample']['selected'] == c.packet['sample']['selected']:
        packet['sample']['selected'] = c.keys[-8:]
    c.packet_ref = c.put(c.relative('tier2/wrong-sample.json'), packet)
    assert c.open() == 3
    result = c.write(c.decisions())
    assert common.document(c.resolver, result['verdict'])['verdict'] == 'must_fix'


def test_changed_context_requires_new_authenticated_context(tmp_path):
    c = Cycle(tmp_path).round()
    path = c.path(c.context_ref)
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='hash mismatch'):
        common.pin(c.resolver, path, c.context_ref['sha256'])
    with pytest.raises(ValueError, match='mismatch'):
        c.open()
    assert not (c.r / 'tier3/open-report.json').exists()


def test_prepare_cli_and_write_once(tmp_path):
    c = Cycle(tmp_path).round()
    out = c.r / 'context.json'
    result = c.cli('prepare_round.py', '--inputs', c.path(c.context_input), '--round', 1, '--attempt', 1, '--out', out)
    assert result.returncode == 3
    assert 'File exists' in result.stderr


def test_unexamined_undetermined_and_zero_denominators(tmp_path):
    c = Cycle(tmp_path).round(('pass', 'pass'))
    confusion, summary = writer.metrics(c.resolver, c.packet, [])
    assert confusion['tn'] == 0
    assert summary['recall'] is summary['precision'] is None
    assert summary['exclusions']['unexamined'] == sorted(c.keys)
    decision = c.decisions()['decisions'][0]
    decision['defect'] = None
    _, summary = writer.metrics(c.resolver, c.packet, [decision])
    assert summary['exclusions']['reference_undetermined'] == [c.keys[0]]


def test_all_new_output_json_receipts_validate(tmp_path):
    c = Cycle(tmp_path).round(('held',))
    assert c.open() == 0
    c.write(c.decisions())
    for path in c.r.rglob('*.json'):
        validator.validate(refs.loads(path.read_bytes()), c.resolver, root_id='queue:synthetic')


@pytest.mark.parametrize('done,flagged,size', [(0, 0, 0), (1, 0, 1), (4, 0, 4), (16, 12, 4), (16, 16, 0), (16, 2, 8)])
def test_open_rederives_all_clamped_samples(tmp_path, done, flagged, size):
    # A zero-map cohort still has its admitted held window, never vanishes.
    statuses = ('flag',) * flagged + ('pass',) * (done - flagged) if done else ('held',)
    c = Cycle(tmp_path).round(statuses)
    assert c.open() == 0
    assert c.packet['sample']['size'] == size


def test_prepare_diagnostic_context_from_changed_run(tmp_path):
    c = Cycle(tmp_path).round()
    path = c.path(c.context['run'])
    path.write_bytes(path.read_bytes() + b' ')
    context = copy.deepcopy(c.context)
    context.update(attempt=2, supersedes=c.context_ref)
    r2 = c.r.parent / 'a02'
    (r2 / 'tier3').mkdir(parents=True)
    ref, diagnostic = prepare.prepare(c.resolver, context, 1, 2, r2 / 'context.json')
    assert diagnostic
    assert common.trusted_context(c.resolver, ref)['mode'] == 'diagnostic'
    report_ref, code = opener.open_packet(c.resolver, ref, c.path(c.packet_ref), c.packet_ref['sha256'],
                                          'synthetic-reviewer', c.reviewer_ref, r2 / 'tier3/open-report.json')
    assert code == 3
    result = writer.write_verdict(c.resolver, ref, report_ref, c.decisions(), 1, r2 / 'tier3/verdict.json',
                                  c.queue / 'ledger.jsonl', c.queue.parent / 'campaign-ledger.jsonl')
    assert common.document(c.resolver, result['verdict'])['validation_scope'] == 'identity_snapshot'


@pytest.mark.parametrize('mode', ['missing', 'malformed', 'changed_hash', 'posted_hash_absent'])
def test_bad_packet_observations_not_refs(tmp_path, mode):
    c = Cycle(tmp_path).round()
    expected = c.packet_ref['sha256']
    path = c.path(c.packet_ref)
    if mode == 'missing':
        path.unlink()  # Only our owned synthetic fixture, never campaign evidence.
    elif mode == 'malformed':
        path.write_bytes(b'not-json')
        expected = refs.sha256(path.read_bytes())
    elif mode == 'changed_hash':
        path.write_bytes(path.read_bytes() + b' ')
    else:
        expected = None
    c.report_ref, code = opener.open_packet(c.resolver, c.context_ref, path, expected,
                                           'synthetic-reviewer', c.reviewer_ref, c.r / 'tier3/open-report.json')
    assert code == 3
    decisions = c.decisions('hold')
    decisions['external_blocker'] = dict(kind='endpoint', detail='Synthetic external endpoint unavailable')
    result = c.write(decisions)
    verdict = common.document(c.resolver, result['verdict'])
    assert verdict['verdict'] == 'must_fix'
    validator.validate(verdict, c.resolver, root_id='queue:synthetic')


def test_cross_ledger_crash_reconciliation(tmp_path, monkeypatch):
    c = Cycle(tmp_path).round()
    assert c.open() == 0
    original = writer.append_index
    def interrupted(segment, campaign, payload, **kwargs):
        ledger_module.append(segment, payload, **kwargs)
        raise OSError('synthetic crash after segment append')
    monkeypatch.setattr(writer, 'append_index', interrupted)
    with pytest.raises(OSError, match='synthetic crash'):
        c.write(c.decisions())
    verdict_bytes = (c.r / 'tier3/verdict.json').read_bytes()
    segment_bytes = (c.queue / 'ledger.jsonl').read_bytes()
    monkeypatch.setattr(writer, 'append_index', original)
    c.write(c.decisions())
    assert verdict_bytes == (c.r / 'tier3/verdict.json').read_bytes()
    assert segment_bytes == (c.queue / 'ledger.jsonl').read_bytes()
    assert len(ledger_module.verify(c.queue.parent / 'campaign-ledger.jsonl')) == 1


def test_normal_write_revalidates_changed_inputs(tmp_path):
    c = Cycle(tmp_path).round()
    assert c.open() == 0
    path = c.path(c.packet['tier1'])
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='mismatch'):
        c.write(c.decisions())
    assert not (c.queue / 'ledger.jsonl').exists()


@pytest.mark.parametrize('choice,action', [
    ('accept', 'complete_review_and_create_next_admission'),
    ('must_fix', 'complete_review_and_create_correction_chain'),
    ('hold', 'block_current_review_external_dependency'),
])
def test_cli_printed_board_actions(tmp_path, choice, action):
    c = Cycle(tmp_path).round()
    assert c.open() == 0
    decisions = c.decisions(choice, [choice == 'must_fix'])
    if choice == 'hold':
        decisions['external_blocker'] = dict(kind='operator_decision', detail='Synthetic decision pending')
    dr = c.put(c.relative('tier3/decisions.txt'), decisions)
    result = c.cli('write_verdict.py', '--context', c.path(c.context_ref), '--expected-context-sha256', c.context_ref['sha256'],
                   '--open-report', c.path(c.report_ref), '--expected-open-report-sha256', c.report_ref['sha256'],
                   '--decisions', c.path(dr), '--minutes', 1, '--out', c.r / 'tier3/verdict.json',
                   '--ledger', c.queue / 'ledger.jsonl', '--campaign-ledger', c.queue.parent / 'campaign-ledger.jsonl')
    assert result.returncode == 0, result.stderr
    assert refs.loads(result.stdout)['board_action']['action'] == action


def test_prepare_cli_new_attempt(tmp_path):
    c = Cycle(tmp_path).round()
    context = dict(c.context, supersedes=c.context_ref, attempt=2)
    cr = c.put('provenance/context-retry.txt', context)
    r2 = c.r.parent / 'a02'
    r2.mkdir()
    result = c.cli('prepare_round.py', '--inputs', c.path(cr), '--round', 1, '--attempt', 2, '--out', r2 / 'context.json')
    assert result.returncode == 0, result.stderr
    ref = refs.loads(result.stdout)['context']
    validator.GraphValidator(c.resolver).reference(ref, contract='coast-review-context-v1')


def test_tier2_accuracy_is_measured_not_inferred(tmp_path):
    c = Cycle(tmp_path).round(('flag', 'flag'))
    assert c.open() == 0
    decisions = c.decisions()
    decisions['tier2_assessments'] = [dict(finding_index=0, confirmed=True), dict(finding_index=1, confirmed=False)]
    result = c.write(decisions)
    verdict = common.document(c.resolver, result['verdict'])
    assert verdict['tier2_packet_accuracy'] == 0.5
    assert result['metrics']['tier2_accuracy_population'] == dict(assessed=2, total=2)
