"""Offline admission construction and refusal checks; never run a real mission."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from research.scripts import coastal_four128_admission as adm
from research.scripts import coastal_four128_resources as resources
from skippercast.coastal.output_writer import COMPACT_V3_PROFILE, declaration
from tests._support import ROOT
from tests.unit.test_coastal_four128_budget import amendment, _load, V7_LIMITS
from research.scripts import coastal_four128_mask_topology as topo
from skippercast.coastal.authenticated_v1.profiles import PARTIAL_WINDOWS
from skippercast.coastal.coordinator.ordered_trial import LARGER_WINDOWS, PARTIAL_BOUNDS

CATALOG = ROOT / 'research/catalog/four128-admission'
NOW = adm.epoch('2026-10-20T07:40:15.247665+00:00')


def put(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = adm.encoded(value)
    p.write_bytes(raw)
    return dict(path=str(p), bytes=len(raw), sha256=adm.digest(raw))


def put_raw(p, raw):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    return dict(path=str(p), bytes=len(raw), sha256=adm.digest(raw))


def topology_receipt(head, *, enclosed=True):
    """Synthetic one-open receipt built by the real topology code (no source)."""
    grids = []
    for i in range(4):
        grid = [[False] * 128 for _ in range(128)]
        grid[0][i] = True  # a border notch in every window
        if enclosed and i == 2:
            grid[60][60] = grid[60][61] = True
        grids.append(grid)
    windows = [dict(topo.window_topology(g), label=label, window=list(w))
               for label, g, w in zip('ABCD', grids, topo.WINDOWS)]
    met, reasons = topo.require_holes(windows)
    return topo.encoded(dict(schema=topo.SCHEMA, run_tag=topo.RUN_TAG, windows=windows, native_bounds=list(topo.BOUNDS),
        code_head=head, script=dict(path=adm.TOPOLOGY_SCRIPT, sha256=adm.digest((ROOT / adm.TOPOLOGY_SCRIPT).read_bytes())),
        source=dict(opens=1, sha256_recomputed=False), require_holes=dict(topo.REQUIRE_HOLES, met=met, reasons=reasons)))


def topology_review(raw, **changes):
    review = dict(schema=topo.REVIEW_SCHEMA, status='ACCEPTED_TOPOLOGY_OBSERVATION_ONLY', independent=True,
                  receipt=dict(sha256=adm.digest(raw), bytes=len(raw)), require_holes_met=True,
                  scientific_acceptance=False, holds=[], reviewer=dict(profile='sol-reviewer', model='gpt-6.1-sol'))
    review.update(changes)
    return review


def base_config(tmp_path):
    cfg = json.loads((CATALOG / 'doc5g.json').read_text())
    cfg.update(mode='live', run_tag='20261020test', used_run_tags=['20261020r2'],
        project_root=str(tmp_path), staging_root=str(tmp_path / 'scratch/staging'),
        mission_root=str(tmp_path / 'outputs/mission'), code_root=str(ROOT),
        issuance_receipt=str(tmp_path / 'outputs/issued.json'), assembly_receipt=str(tmp_path / 'outputs/assembly.json'),
        window_scope_change='synthetic fixture windows only', interpreter=sys.executable,
        reviewer=dict(profile='sol-reviewer', model='test-independent', reviewer_id='synthetic-only'), task='synthetic-test')
    # Live fixtures follow the current signed head (revision 7); historical configs keep theirs.
    cfg['limits'] = dict(V7_LIMITS)
    cfg['controls'][adm.LEDGER_PATH] = 'a' * 64
    return cfg


def fixture(tmp_path, partial=False):
    cfg = base_config(tmp_path)
    policy = {}
    if partial:
        cfg.update(support_policy=adm.PARTIAL_SUPPORT, windows=copy.deepcopy(PARTIAL_WINDOWS),
                   bounds=list(PARTIAL_BOUNDS), run_tag='20261020p1')
        policy = dict(support_policy=adm.PARTIAL_SUPPORT)
    stage = Path(cfg['staging_root'])
    controls = [dict(path=k, bytes=1, sha256=v) for k, v in cfg['controls'].items()]
    a = amendment()
    a['retained_output'] = dict(prior_retained_bytes=cfg['retained']['prior'])
    cfg['inputs']['amendment'] = put(tmp_path / 'amendment.json', a)
    source = dict(sha256='a' * 64)
    grant = dict(schema='coastal-authenticated-policy-v1', execution_authorized=True,
        output_root=cfg['mission_root'], window_set=cfg['windows'], window_count=4, window_side=128,
        prior_effective_bytes=cfg['limits']['source_prior_bytes'], cumulative_limit_bytes=cfg['limits']['source_limit_bytes'],
        source_volume_cap_bytes=a['source']['fresh_allowance_bytes'], source=source, code_sha='b' * 64, deps_sha='c' * 64,
        output_retention=declaration(cfg['retained']['prior'], cfg['retained']['cap'], profile=COMPACT_V3_PROFILE), **policy)
    references = []

    def meta(name, doc):
        raw = adm.encoded(doc)
        adm.write_new(stage / 'metadata' / name, raw)
        ref = adm.reference(name, raw, doc['schema'])
        references.append(ref)
        return ref

    grant['approved_budget_amendment'] = meta('amendment.json', a)
    carry = dict(schema='coastal-authenticated-carry-v1', budget_amendment=grant['approved_budget_amendment'],
        prior_effective_bytes=cfg['limits']['source_prior_bytes'], cumulative_limit_bytes=cfg['limits']['source_limit_bytes'],
        remaining_bytes=a['source']['fresh_allowance_bytes'], refunds=False)
    science = dict(schema='coastal-ordered-independent-scientific-preflight-v1', expected_metadata_sha256='d' * 64)
    index = dict(schema='coastal-ordered-live-index-v1', grant=meta('grant.json', grant), carry=meta('carry.json', carry),
        independent_preflight=meta('science.json', science), code_sha=grant['code_sha'], deps_sha=grant['deps_sha'],
        prior_scratch_bytes=cfg['limits']['scratch_prior_bytes'], scratch_limit_bytes=cfg['limits']['scratch_limit_bytes'],
        **policy)
    index_ref = meta('prospective-index.json', index)
    package = dict(status='PASS_METADATA_ONLY', units_started=0, original_source_reads=0,
        staging_root=str(stage), mission_root=cfg['mission_root'], files=references, index=index_ref, **policy)
    cfg['inputs']['historical_context'] = put(tmp_path / 'context.json', dict(source=source, metadata_sha256='d' * 64,
        mode='real_continuation', rehearsal_synthetic=False, real_source_sha256=source['sha256'], windows=[[1, 2, 3, 4]]))
    cfg['inputs']['prior_carry'] = put(tmp_path / 'prior.json', dict(closed=True))
    if partial:
        receipt_raw = topology_receipt(cfg['head'])
        cfg['inputs']['selection'] = put_raw(tmp_path / 'mask-topology-receipt.json', receipt_raw)
        cfg['inputs']['prescan_review'] = put(tmp_path / 'mask-topology-review.json', topology_review(receipt_raw))
    else:
        cfg['inputs']['selection'] = put(tmp_path / 'selection.json', dict(synthetic=True))
    observation = dict(checked_at=adm.iso(NOW), valid_until=adm.iso(NOW + 86400), reviewer=cfg['reviewer'], task=cfg['task'],
        origin_ref_head=cfg['head'], procedure=dict(script='synthetic-issuer.py', script_sha256='e' * 64, interpreter='synthetic-python'))
    kwargs = dict(observation=observation, index=index, grant=grant, amendment=a, package=package, controls=controls, docs={})
    return cfg, kwargs


@pytest.mark.parametrize('layout', [5, 6])
def test_renderer_deterministic_refs_and_accounting(tmp_path, layout):
    cfg, kwargs = fixture(tmp_path)
    cfg['layout'] = layout
    outputs = adm.render(cfg, **kwargs)
    assert outputs == adm.render(cfg, **kwargs)
    closed, doc5, index = (json.loads(outputs[name]) for name in adm.OUTPUT_NAMES)
    assert doc5['prior_output_carry']['sha256'] == adm.digest(outputs['closed-fresh-carry.json'])
    assert index['independent_runtime_review']['sha256'] == adm.digest(outputs['independent-runtime-review.json'])
    assert closed['source']['rerun_1_charged_bytes'] == 294060544
    assert doc5['execution_authorized'] is False
    assert doc5['limitations']['publication_authorized'] is False
    assert ('mission_root' in doc5) == (layout == 6)
    assert ('origin_ref_head' in doc5['code_identity']) == (layout == 6)
    assert all(raw.endswith(b'\n') for raw in outputs.values())


def test_prepare_inputs_verify_hashes_accounting_and_scope(tmp_path):
    cfg, kwargs = fixture(tmp_path)
    assert adm.prepare_inputs(cfg, kwargs['package']) == (kwargs['index'], kwargs['grant'], kwargs['amendment'])
    cfg['limits']['source_prior_bytes'] -= 1
    with pytest.raises(ValueError, match='config limits'):
        adm.prepare_inputs(cfg, kwargs['package'])
    cfg['limits']['source_prior_bytes'] += 1
    (Path(cfg['staging_root']) / 'metadata/carry.json').write_bytes(b'{}\n')
    with pytest.raises(ValueError, match='bytes/hash changed'):
        adm.prepare_inputs(cfg, kwargs['package'])


@pytest.mark.parametrize('label', ['e', 'f', 'g'])
def test_historical_configs_and_local_byte_replay(tmp_path, label):
    cfg, _ = adm.config_file(CATALOG / f'doc5{label}.json')
    assert cfg['mode'] == 'historical-replay'
    with pytest.raises(ValueError, match='historical configs'):
        adm.fresh_run(cfg, stage_absent=True)
    # Like the existing signed-amendment tests: CI covers synthetic construction;
    # the maintainer machine additionally exercises the pinned archived inputs.
    if not Path(cfg['inputs']['receipt']['path']).expanduser().is_file():
        return
    result = adm.replay(cfg, tmp_path / 'replay')
    assert result['status'] == 'HISTORICAL_BYTES_REPRODUCED_REVIEW_REQUIRED'
    assert len(result['files']) == 3
    assert all(item['byte_equal'] for item in result['files'])
    assert result['execution_authorized'] is False
    assert (tmp_path / 'replay/REPLAY_ONLY.json').is_file()
    with pytest.raises(ValueError, match='fresh replay root'):
        adm.replay(cfg, tmp_path / 'replay')


def test_renderer_refuses_author_or_wrong_validity(tmp_path):
    cfg, kwargs = fixture(tmp_path)
    kwargs['observation']['reviewer']['model'] = 'claude-opus'
    with pytest.raises(ValueError, match='issuer must differ'):
        adm.render(cfg, **kwargs)
    kwargs['observation']['reviewer']['model'] = 'independent-test'
    kwargs['observation']['valid_until'] = adm.iso(NOW + 100)
    with pytest.raises(ValueError, match='validity differs'):
        adm.render(cfg, **kwargs)


@pytest.mark.parametrize('violation', ['used', 'environment', 'mission', 'scratch', 'stage', 'receipt', 'escape', 'symlink'])
def test_clean_state_refusals(tmp_path, monkeypatch, violation):
    cfg = base_config(tmp_path)
    if violation == 'used':
        cfg['used_run_tags'].append(cfg['run_tag'])
    elif violation == 'environment':
        monkeypatch.setenv('SKIPPERCAST_FOUR128_RUN_TAG', '20261020other')
    elif violation == 'escape':
        cfg['mission_root'] = str(tmp_path / 'outside')
    elif violation == 'symlink':
        (tmp_path / 'outputs').symlink_to(tmp_path / 'missing', target_is_directory=True)
    else:
        p = {'mission': cfg['mission_root'], 'stage': cfg['staging_root'], 'receipt': cfg['issuance_receipt'],
             'scratch': str(tmp_path / ('scratch/four128-approved-' + cfg['run_tag']))}[violation]
        Path(p).mkdir(parents=True)
    with pytest.raises(ValueError):
        adm.fresh_run(cfg, stage_absent=True)


def test_clean_state_success_and_exclusive_write(tmp_path):
    cfg = base_config(tmp_path)
    stage, mission = adm.fresh_run(cfg, stage_absent=True)
    assert not stage.exists() and not mission.exists()
    p = tmp_path / 'receipt.json'
    adm.write_new(p, b'first')
    with pytest.raises(FileExistsError):
        adm.write_new(p, b'second')
    assert p.read_bytes() == b'first'


def test_source_and_traversal_reads_refused(tmp_path):
    for name in ('source.bag', 'source.tif'):
        with pytest.raises(ValueError, match='only code/JSON'):
            adm.read_metadata(tmp_path / name)
    with pytest.raises(ValueError, match='escapes staging'):
        adm.relative_metadata(tmp_path, dict(path='metadata/../../source.json'))
    (tmp_path / 'alias.json').symlink_to(tmp_path / 'missing.json')
    with pytest.raises(ValueError, match='non-symlink'):
        adm.read_metadata(tmp_path / 'alias.json')


def test_ledger_dynamic_charge_without_python_change(tmp_path):
    ledger = copy.deepcopy(resources.CHARGE_LEDGER)
    s = ledger['source']
    s['future_failed_run_charged_bytes'] = 17
    for key in ('prior_effective_bytes', 'additional_bytes', 'cumulative_limit_bytes'):
        s[key] += 17
    ledger['head']['revision'] += 1
    module_path = tmp_path / 'research/scripts/coastal_four128_resources.py'
    module_path.parent.mkdir(parents=True)
    module_path.write_bytes((ROOT / 'research/scripts/coastal_four128_resources.py').read_bytes())
    put(tmp_path / resources.LEDGER_RELATIVE, ledger)
    spec = importlib.util.spec_from_file_location('synthetic_charge_resources', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    doc = amendment()
    doc['source'] = copy.deepcopy(s)
    assert module.budget_limits(doc)['source_prior_bytes'] == resources.SOURCE_PRIOR_FLOOR + 17
    with pytest.raises(ValueError, match='exact integer'):
        module.budget_limits(amendment())


@pytest.mark.parametrize('bad', ['bool', 'negative', 'unbalanced', 'refund', 'signer'])
def test_bad_ledger_refused(tmp_path, bad):
    doc = copy.deepcopy(resources.CHARGE_LEDGER)
    if bad in ('bool', 'negative', 'unbalanced'):
        doc['source']['rerun_1_charged_bytes'] = {'bool': True, 'negative': -1, 'unbalanced': 3}[bad]
    elif bad == 'refund':
        doc['scratch']['refunds'] = True
    else:
        doc['head']['signer']['profile'] = 'opus-coder'
    p = tmp_path / 'ledger.json'
    put(p, doc)
    with pytest.raises(ValueError):
        resources.load_charge_ledger(p)


def test_signed_bytes_binding_and_original_projection():
    p = Path(resources.CHARGE_LEDGER['head']['path']).expanduser()
    # Always test refusal, even on CI without the archived signed document.
    with pytest.raises(ValueError, match='charge ledger head'):
        resources.budget_limits_bytes(adm.encoded(amendment()))
    if p.is_file():
        raw = p.read_bytes()
        assert resources.budget_limits_bytes(raw) == resources.budget_limits(amendment())
        original = json.loads(raw)
        for kind in ('source', 'scratch'):
            assert resources.CHARGE_LEDGER[kind] == {k: original[kind][k] for k in resources.CHARGE_LEDGER[kind]}
        with pytest.raises(ValueError, match='charge ledger head'):
            resources.budget_limits_bytes(raw + b' ')


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('preflight_rc', [0, 2])
def test_assembly_real_managed_writes_with_simulated_preflight(tmp_path, monkeypatch, preflight_rc, partial):
    cfg, kwargs = fixture(tmp_path, partial=partial)
    outputs = adm.render(cfg, **kwargs)
    stage = Path(cfg['staging_root'])
    for name, raw in outputs.items():
        adm.write_new(stage / 'metadata' / name, raw)
    put(Path(cfg['issuance_receipt']), dict(schema='coastal-four128-config-issuance-v1', config_sha256='f' * 64,
        head=cfg['head'], run_tag=cfg['run_tag'],
        files=[adm.reference(name, raw, json.loads(raw)['schema']) for name, raw in outputs.items()]))
    rt = _load('coastal_four128_runtime', {})
    monkeypatch.setattr(adm, 'runtime', lambda cfg: rt)
    monkeypatch.setattr(adm, 'live_code', lambda cfg: (kwargs['controls'], cfg['head']))
    monkeypatch.setattr(adm.time, 'time', lambda: NOW)
    calls = []

    def preflight(argv, **options):
        calls.append(argv)
        assert argv[-1] == 'preflight'
        assert not any('systemd' in part for part in argv)
        return SimpleNamespace(returncode=preflight_rc, stdout='synthetic preflight stub', stderr='')

    monkeypatch.setattr(adm.subprocess, 'run', preflight)
    if preflight_rc:
        with pytest.raises(ValueError, match='preflight failed'):
            adm.assemble(cfg, 'f' * 64)
    else:
        result = adm.assemble(cfg, 'f' * 64)
        assert result['managed_audit']['unmanaged_control_bytes'] == 0
    assert len(calls) == 1
    mission = Path(cfg['mission_root'])
    for name, raw in outputs.items():
        assert (mission / 'execution/metadata' / name).read_bytes() == raw
    assert (mission / 'managed-output.json').is_file()
    report = json.loads(Path(cfg['assembly_receipt']).read_text())
    assert report['preflight']['returncode'] == preflight_rc
    assert report['units_started'] == 0
    with pytest.raises(ValueError, match='existing mission'):
        adm.assemble(cfg, 'f' * 64)


def test_cli_refuses_historical_config_for_live_action(tmp_path):
    cfg, sha = adm.config_file(CATALOG / 'doc5g.json')
    for action in ('issue', 'assemble'):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'research/scripts/coastal_four128_admission.py'),
            action, '--config', str(CATALOG / 'doc5g.json'), '--config-sha256', sha], capture_output=True, text=True)
        assert result.returncode != 0
        assert 'historical configs cannot issue or assemble' in result.stderr


@pytest.mark.parametrize('failure', [None, 'diagnostics', 'empty', 'existing_receipt', 'unwritable_receipt'])
def test_issue_pipeline_with_synthetic_prepare_and_real_renderer(tmp_path, monkeypatch, capsys, failure):
    cfg, kwargs = fixture(tmp_path)
    stage = Path(cfg['staging_root'])
    prepared = tmp_path / 'prepared'
    stage.rename(prepared)
    cfg['inputs']['selection'] = put(tmp_path / 'selected.json', dict(
        LARGER_WINDOWS=cfg['windows'], LARGER_BOUNDS=cfg['bounds'], code_head=cfg['head']))
    rt = _load('coastal_four128_runtime', {})
    monkeypatch.setattr(rt, 'PROJECT', tmp_path)
    monkeypatch.setattr(adm, 'runtime', lambda cfg: rt)
    monkeypatch.setattr(adm, 'live_code', lambda cfg: (kwargs['controls'], cfg['head']))
    monkeypatch.setattr(adm, 'git', lambda *args: (cfg['head'] + '\n').encode())
    monkeypatch.setattr(adm.time, 'time', lambda: NOW)
    # Budget gate is tested separately against the real archived signed bytes;
    # this fixture is expressly synthetic, never represented as an attestation.
    import coastal_four128_resources as runtime_resources
    from skippercast.coastal.coordinator import loop
    monkeypatch.setattr(runtime_resources, 'budget_limits_bytes', lambda raw: cfg['limits'])
    monkeypatch.setattr(loop, 'implementation_hashes', lambda root: (kwargs['index']['code_sha'], kwargs['index']['deps_sha']))
    monkeypatch.setattr(adm, 'evidence_summary', lambda cfg, now: {})
    calls = []

    def prepare(argv, **options):
        calls.append(argv)
        assert argv[3].endswith('coastal_four128_prepare.py')
        assert '--prospective-released-bytes' in argv
        assert options['check'] is True and options['capture_output'] is True and options['text'] is True
        shutil.copytree(prepared, stage)
        if failure:
            raise subprocess.CalledProcessError(7, argv,
                output=None if failure == 'empty' else 'earlier progress\nlast stdout line\n',
                stderr=None if failure == 'empty' else 'ValueError: independent source-specific rights binding invalid\n')
        return SimpleNamespace(stdout=json.dumps(kwargs['package']))

    monkeypatch.setattr(adm.subprocess, 'run', prepare)
    if failure:
        failed_path = Path(cfg['issuance_receipt'] + '.failed.json')
        if failure == 'existing_receipt':
            adm.write_new(failed_path, b'prior failure receipt\n')
        elif failure == 'unwritable_receipt':
            monkeypatch.setattr(adm, 'write_new', mock.Mock(side_effect=PermissionError('fixture permission denial')))
        with pytest.raises(SystemExit) as error:
            adm.issue(cfg, 'f' * 64)
        assert error.value.code == 1
        assert len(calls) == 1  # never retry prepare
        captured = capsys.readouterr()
        assert not captured.out
        if failure != 'empty':
            assert 'ValueError: independent source-specific rights binding invalid\n' in captured.err
            assert 'last stdout line\n' in captured.err and 'earlier progress' not in captured.err
        if failure in ('existing_receipt', 'unwritable_receipt'):
            assert 'Failed issuance receipt not written:' in captured.err
            if failure == 'existing_receipt':
                assert failed_path.read_bytes() == b'prior failure receipt\n'
            else:
                assert not failed_path.exists()
        else:
            report = json.loads(failed_path.read_text())
            assert report['schema'] == 'coastal-four128-config-issuance-failure-v1'
            assert report['status'] == 'ISSUANCE_FAILED_STAGE_PRESERVED'
            assert report['config_sha256'] == 'f' * 64
            assert (report['head'], report['run_tag']) == (cfg['head'], cfg['run_tag'])
            assert (report['staging_root'], report['mission_root']) == (str(stage), cfg['mission_root'])
            assert report['execution_authorized'] is False
            assert report['prepare'] == dict(returncode=7,
                stderr='' if failure == 'empty' else 'ValueError: independent source-specific rights binding invalid\n',
                last_stdout_line='' if failure == 'empty' else 'last stdout line')
        assert not Path(cfg['issuance_receipt']).exists()
        assert not Path(cfg['assembly_receipt']).exists()
        assert not Path(cfg['mission_root']).exists()
        assert {p.relative_to(stage): p.read_bytes() for p in stage.rglob('*.json')} == {
            p.relative_to(prepared): p.read_bytes() for p in prepared.rglob('*.json')}
        with pytest.raises(ValueError, match='staging clean state differs'):
            adm.issue(cfg, 'f' * 64)
        with pytest.raises(ValueError, match='bounded regular metadata file required'):
            adm.assemble(cfg, 'f' * 64)
        assert len(calls) == 1
        return
    report = adm.issue(cfg, 'f' * 64)
    assert len(calls) == 1
    assert report['status'] == 'ISSUED_REVIEW_REQUIRED'
    assert len(report['files']) == 3
    assert not Path(cfg['mission_root']).exists()
    for item in report['files']:
        adm.relative_metadata(stage, item)
    assert json.loads(Path(cfg['issuance_receipt']).read_text()) == report


@pytest.mark.parametrize('mutation', ['expired', 'held', 'author', 'selection', 'staged'])
def test_evidence_negative_controls(tmp_path, mutation):
    cfg = base_config(tmp_path)
    cfg['evidence_root'] = str(tmp_path / 'evidence')
    cfg['inputs']['selection'] = put(tmp_path / 'selection.json', dict(synthetic=True))
    for name, schema in cfg['docs'].items():
        doc = dict(schema=schema, window_set=cfg['windows'], checked_at=adm.iso(NOW - 1),
            valid_until=adm.iso(NOW + 86400), reviewer_id='synthetic-independent', status='PASS', holds=[],
            prescan_evidence=[cfg['inputs']['selection']])
        if mutation == 'expired':
            doc['valid_until'] = adm.iso(NOW + 7199)
        elif mutation == 'held':
            doc['holds'] = ['hold']
        elif mutation == 'author':
            doc['reviewer_id'] = 'opus-coder'
        elif mutation == 'selection':
            doc['prescan_evidence'] = []
        put(Path(cfg['evidence_root']) / (name + '.json'), doc)
        put(Path(cfg['staging_root']) / 'metadata' / (name + '.json'), {} if mutation == 'staged' else doc)
    with pytest.raises(ValueError):
        adm.evidence_summary(cfg, NOW)


def test_live_code_rejects_dirty_head_and_wrong_root(tmp_path):
    cfg = base_config(tmp_path)
    cfg['origin'] = dict(ref='origin/reviewed', head=cfg['head'], allowed_test_files=[])
    with mock.patch.object(adm, 'git', side_effect=[b'0' * 40]):
        with pytest.raises(ValueError, match='head differs'):
            adm.live_code(cfg)
    with mock.patch.object(adm, 'git', side_effect=[cfg['head'].encode(), b' M source.py\n']):
        with pytest.raises(ValueError, match='not clean'):
            adm.live_code(cfg)
    cfg['code_root'] = str(tmp_path)
    with pytest.raises(ValueError, match='reviewed code root'):
        adm.live_code(cfg)


def test_current_runtime_requires_ledger_control(tmp_path):
    cfg, kwargs = fixture(tmp_path)
    output = adm.render(cfg, **kwargs)
    review = json.loads(output['independent-runtime-review.json'])
    index = json.loads(output['live-index.json'])
    rt = _load('coastal_four128_runtime', {})
    assert rt.validate_runtime_review(index, review, now=NOW)
    for doc in (index, review):
        doc['runtime_controls'] = [item for item in doc['runtime_controls'] if item['path'] != adm.LEDGER_PATH]
    with pytest.raises(ValueError, match='complete independently reviewed control set'):
        rt.validate_runtime_review(index, review, now=NOW)


# ------------------------------------------------------------------ SC-5b opt-in partial support

def test_strict_render_carries_no_partial_keys(tmp_path):
    cfg, kwargs = fixture(tmp_path)
    outputs = adm.render(cfg, **kwargs)
    for name in adm.OUTPUT_NAMES:
        doc = json.loads(outputs[name])
        assert 'support_policy' not in doc and 'mask_topology_prescan' not in doc
    doc5 = json.loads(outputs['independent-runtime-review.json'])
    assert doc5['scope'].startswith('Exact four canonical 128 windows')
    assert 'prescan_charged_in_prior' not in doc5['accounting']['source']


def test_partial_render_binds_policy_and_reviewed_prescan(tmp_path):
    cfg, kwargs = fixture(tmp_path, partial=True)
    outputs = adm.render(cfg, **kwargs)
    assert outputs == adm.render(cfg, **kwargs)
    closed, doc5, index = (json.loads(outputs[name]) for name in adm.OUTPUT_NAMES)
    assert doc5['support_policy'] == index['support_policy'] == adm.PARTIAL_SUPPORT
    assert doc5['window_set'] == PARTIAL_WINDOWS and doc5['native_bounds'] == PARTIAL_BOUNDS
    prescan = doc5['mask_topology_prescan']
    assert prescan == index['mask_topology_prescan'] and prescan['require_holes_met'] is True
    assert prescan['receipt']['sha256'] == cfg['inputs']['selection']['sha256']
    assert prescan['review']['sha256'] == cfg['inputs']['prescan_review']['sha256']
    # Every carry quantity: old charges, rerun 2, the precharged pre-scan, eight fresh admissions.
    assert closed['source']['rerun_1_charged_bytes'] == closed['source']['rerun_2_charged_bytes'] == 294060544
    assert closed['source']['sc5_geometry_prescan_charged_bytes'] == 36757568
    assert closed['source']['prior_effective_bytes'] == 2365309244 and closed['source']['cumulative_limit_bytes'] == 2659369788
    assert closed['source']['fresh_allowance_bytes'] == 8 * 36757568
    assert doc5['accounting']['source'] == dict(prior=2365309244, cap=2659369788, fresh=294060544, downloads=0,
                                                prescan_charged_in_prior=36757568, run_admissions=8)
    assert doc5['accounting']['scratch'] == dict(prior=1616905649, cap=2153776561, trial=536870912)
    assert doc5['execution_authorized'] is False and doc5['limitations']['publication_authorized'] is False
    rt = _load('coastal_four128_runtime', {})
    assert rt.validate_runtime_review(index, doc5, now=NOW)
    for mutate in (lambda d: d['mask_topology_prescan'].update(require_holes_met=False),
                   lambda d: d['mask_topology_prescan'].update(independently_reviewed=False),
                   lambda d: d['mask_topology_prescan']['review'].update(sha256=''),
                   lambda d: d.pop('mask_topology_prescan')):
        bad_review, bad_index = copy.deepcopy(doc5), copy.deepcopy(index)
        mutate(bad_review)
        mutate(bad_index)
        with pytest.raises(ValueError):
            rt.validate_runtime_review(bad_index, bad_review, now=NOW)
    # The index and review must carry the same policy binding.
    stripped = copy.deepcopy(index)
    stripped.pop('support_policy')
    with pytest.raises(ValueError, match='bindings'):
        rt.validate_runtime_review(stripped, doc5, now=NOW)
    # runtime.index() binds both to the exact grant's policy.
    assert rt.policy_bindings(index, doc5, kwargs['grant']) == adm.PARTIAL_SUPPORT
    strict_grant = dict(kwargs['grant'])
    strict_grant.pop('support_policy')
    with pytest.raises(ValueError, match='support policy differs from the exact grant'):
        rt.policy_bindings(index, doc5, strict_grant)
    assert rt.policy_bindings({}, {}, strict_grant) is None


def test_prepare_inputs_refuses_policy_mismatch(tmp_path):
    cfg, kwargs = fixture(tmp_path, partial=True)
    assert adm.prepare_inputs(cfg, kwargs['package'])[1]['support_policy'] == adm.PARTIAL_SUPPORT
    strict_cfg = copy.deepcopy(cfg)
    strict_cfg.pop('support_policy')
    with pytest.raises(ValueError, match='support policy binding'):
        adm.prepare_inputs(strict_cfg, kwargs['package'])
    package = dict(kwargs['package'])
    package.pop('support_policy')
    with pytest.raises(ValueError, match='support policy binding'):
        adm.prepare_inputs(cfg, package)


def test_config_support_policy_is_opt_in_live_only(tmp_path):
    def write(cfg):
        p = tmp_path / 'config.json'
        p.write_bytes(adm.encoded(cfg))
        return p
    cfg, _ = fixture(tmp_path, partial=True)
    assert adm.config_file(write(cfg))[0]['support_policy'] == adm.PARTIAL_SUPPORT
    for mutate in (lambda c: c.update(support_policy='coastal-contained-anything-v1'),
                   lambda c: c.update(support_policy=None),
                   lambda c: c['inputs'].pop('prescan_review'),
                   lambda c: c.update(mode='historical-replay', layout=6)):
        bad = copy.deepcopy(cfg)
        mutate(bad)
        if bad['mode'] == 'historical-replay':
            bad['controls'].pop(adm.LEDGER_PATH)
        with pytest.raises(ValueError):
            adm.config_file(write(bad))
    for label in 'efg':  # historical configs stay strict and unchanged
        assert 'support_policy' not in adm.config_file(CATALOG / f'doc5{label}.json')[0]


def test_evidence_support_policy_must_match(tmp_path):
    cfg, _ = fixture(tmp_path, partial=True)
    cfg['evidence_root'] = str(tmp_path / 'evidence')
    for name, schema in cfg['docs'].items():
        doc = dict(schema=schema, window_set=cfg['windows'], checked_at=adm.iso(NOW - 1),
            valid_until=adm.iso(NOW + 86400), reviewer_id='synthetic-independent', status='PASS', holds=[],
            prescan_evidence=[cfg['inputs']['selection']], support_policy=adm.PARTIAL_SUPPORT)
        put(Path(cfg['evidence_root']) / (name + '.json'), doc)
        put(Path(cfg['staging_root']) / 'metadata' / (name + '.json'), doc)
    assert len(adm.evidence_summary(cfg, NOW)) == 4
    strict = copy.deepcopy(cfg)
    strict.pop('support_policy')
    with pytest.raises(ValueError, match='support policy'):
        adm.evidence_summary(strict, NOW)


def partial_issue(tmp_path, monkeypatch, cfg, kwargs):
    stage = Path(cfg['staging_root'])
    prepared = tmp_path / 'prepared'
    stage.rename(prepared)
    rt = _load('coastal_four128_runtime', {})
    monkeypatch.setattr(rt, 'PROJECT', tmp_path)
    monkeypatch.setattr(adm, 'runtime', lambda cfg: rt)
    monkeypatch.setattr(adm, 'live_code', lambda cfg: (kwargs['controls'], cfg['head']))
    monkeypatch.setattr(adm, 'git', lambda *args: (cfg['head'] + '\n').encode())
    monkeypatch.setattr(adm.time, 'time', lambda: NOW)
    import coastal_four128_resources as runtime_resources
    from skippercast.coastal.coordinator import loop
    monkeypatch.setattr(runtime_resources, 'budget_limits_bytes', lambda raw: cfg['limits'])
    monkeypatch.setattr(loop, 'implementation_hashes', lambda root: (kwargs['index']['code_sha'], kwargs['index']['deps_sha']))
    monkeypatch.setattr(adm, 'evidence_summary', lambda cfg, now: {})
    calls = []

    def prepare(argv, **options):
        calls.append(argv)
        assert argv[-2:] == ['--support-policy', adm.PARTIAL_SUPPORT]
        shutil.copytree(prepared, stage)
        return SimpleNamespace(stdout=json.dumps(kwargs['package']))

    monkeypatch.setattr(adm.subprocess, 'run', prepare)
    return adm.issue(cfg, 'f' * 64), calls


def test_partial_issue_pipeline_with_reviewed_prescan(tmp_path, monkeypatch):
    cfg, kwargs = fixture(tmp_path, partial=True)
    report, calls = partial_issue(tmp_path, monkeypatch, cfg, kwargs)
    assert len(calls) == 1 and report['status'] == 'ISSUED_REVIEW_REQUIRED'
    assert not Path(cfg['mission_root']).exists()
    stage = Path(cfg['staging_root'])
    doc5 = json.loads((stage / 'metadata/independent-runtime-review.json').read_text())
    assert doc5['support_policy'] == adm.PARTIAL_SUPPORT and doc5['mask_topology_prescan']['require_holes_met'] is True


@pytest.mark.parametrize('violation,message', [
    ('strict_windows', 'ruled windows differ'),
    ('no_holes', 'independently reviewed --require-holes'),
    ('author_review', 'independently reviewed --require-holes'),
    ('stale_review', 'independently reviewed --require-holes'),
    ('script', 'pre-scan script differs'),
    ('wrong_geometry_receipt', 'native bounds differ')])
def test_partial_issue_refusals(tmp_path, monkeypatch, violation, message):
    cfg, kwargs = fixture(tmp_path, partial=True)
    if violation == 'strict_windows':
        cfg['windows'] = copy.deepcopy(LARGER_WINDOWS)
    elif violation == 'no_holes':
        raw = topology_receipt(cfg['head'], enclosed=False)
        cfg['inputs']['selection'] = put_raw(tmp_path / 'notch-receipt.json', raw)
        cfg['inputs']['prescan_review'] = put(tmp_path / 'notch-review.json', topology_review(raw))
    elif violation == 'author_review':
        raw = Path(cfg['inputs']['selection']['path']).read_bytes()
        cfg['inputs']['prescan_review'] = put(tmp_path / 'author-review.json', topology_review(
            raw, reviewer=dict(profile='opus-coder', model='claude-opus-5-5')))
    elif violation == 'stale_review':
        other = topology_receipt('0' * 40)
        cfg['inputs']['prescan_review'] = put(tmp_path / 'stale-review.json', topology_review(other))
    elif violation == 'script':
        doc = json.loads(Path(cfg['inputs']['selection']['path']).read_bytes())
        doc['script']['sha256'] = '0' * 64
        raw = topo.encoded(doc)
        cfg['inputs']['selection'] = put_raw(tmp_path / 'script-receipt.json', raw)
        cfg['inputs']['prescan_review'] = put(tmp_path / 'script-review.json', topology_review(raw))
    else:
        doc = json.loads(Path(cfg['inputs']['selection']['path']).read_bytes())
        doc['native_bounds'] = list(LARGER_WINDOWS[0])
        raw = topo.encoded(doc)
        cfg['inputs']['selection'] = put_raw(tmp_path / 'geometry-receipt.json', raw)
        cfg['inputs']['prescan_review'] = put(tmp_path / 'geometry-review.json', topology_review(raw))
    with pytest.raises(ValueError, match=message):
        partial_issue(tmp_path, monkeypatch, cfg, kwargs)
    assert not Path(cfg['issuance_receipt']).exists()
    assert not Path(cfg['mission_root']).exists()


def science_doc(policy, windows):
    doc = dict(schema='coastal-ordered-independent-scientific-preflight-v1', independent=True,
               status='PASS_EXPECTED_SOURCE_METADATA_GEOMETRY_' + ('PARTIAL' if policy else 'STRICT') + '_POLICY',
               source=dict(sha256='a' * 64), native_window_set=copy.deepcopy(windows), window_count=4, window_side=128,
               holds_added=[], checked_at=adm.iso(NOW - 10), valid_until=adm.iso(NOW + 86400),
               scientific_acceptance=False, current_source_identity_verified=False)
    if policy:
        doc['support_policy'] = policy
    return doc


def science_grant(policy, windows):
    grant = dict(source=dict(sha256='a' * 64), window_set=copy.deepcopy(windows), window_side=128, window_count=4)
    if policy:
        grant['support_policy'] = policy
    return grant


def test_runtime_science_status_follows_the_grant_policy():
    rt = _load('coastal_four128_runtime', {})
    check = lambda science, grant: rt.validate_science(science, grant, now=NOW, horizon=NOW + 3600)  # noqa: E731
    partial = adm.PARTIAL_SUPPORT
    assert check(science_doc(None, LARGER_WINDOWS), science_grant(None, LARGER_WINDOWS))
    assert check(science_doc(partial, PARTIAL_WINDOWS), science_grant(partial, PARTIAL_WINDOWS))
    cases = [
        (science_doc(partial, LARGER_WINDOWS), science_grant(None, LARGER_WINDOWS)),     # partial science, strict grant
        (science_doc(None, PARTIAL_WINDOWS), science_grant(partial, PARTIAL_WINDOWS)),   # strict science, partial grant
        (dict(science_doc(partial, PARTIAL_WINDOWS), support_policy=None), science_grant(partial, PARTIAL_WINDOWS)),
        (dict(science_doc(None, LARGER_WINDOWS), support_policy=partial), science_grant(None, LARGER_WINDOWS)),
        (science_doc(partial, LARGER_WINDOWS), science_grant(partial, PARTIAL_WINDOWS)),  # strict windows
        (science_doc(partial, PARTIAL_WINDOWS), science_grant(partial, LARGER_WINDOWS)),  # grant windows
        (science_doc(None, PARTIAL_WINDOWS), science_grant(None, PARTIAL_WINDOWS)),      # partial windows, strict
        (dict(science_doc(partial, PARTIAL_WINDOWS), status='PASS_EXPECTED_SOURCE_METADATA_GEOMETRY_STRICT_POLICY'),
         science_grant(partial, PARTIAL_WINDOWS)),
    ]
    for science, grant in cases:
        with pytest.raises(ValueError):
            check(science, grant)
    with pytest.raises(ValueError, match='unsupported contained support policy'):
        check(science_doc('coastal-other-v1', PARTIAL_WINDOWS), science_grant('coastal-other-v1', PARTIAL_WINDOWS))


def test_prepare_scope_comes_from_the_shared_pin():
    from research.scripts import coastal_four128_prepare as prepare
    assert prepare.scope_for(None) == LARGER_WINDOWS
    assert prepare.scope_for(adm.PARTIAL_SUPPORT) == PARTIAL_WINDOWS
    with pytest.raises(ValueError):
        prepare.scope_for('coastal-other-v1')
    strict = dict(support_policy='stale', window_set=[])
    assert prepare.apply_scope(strict, None) == LARGER_WINDOWS and 'support_policy' not in strict
    partial = {}
    prepare.apply_scope(partial, adm.PARTIAL_SUPPORT)
    assert partial == dict(window_set=PARTIAL_WINDOWS, support_policy=adm.PARTIAL_SUPPORT)
    text = (ROOT / 'research/scripts/coastal_four128_prepare.py').read_text()
    assert 'LARGER_WINDOWS' not in text and '--support-policy' in text
