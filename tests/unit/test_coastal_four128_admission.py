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
from tests.unit.test_coastal_four128_budget import amendment, _load

CATALOG = ROOT / 'research/catalog/four128-admission'
NOW = adm.epoch('2026-10-20T07:40:15.247665+00:00')


def put(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = adm.encoded(value)
    p.write_bytes(raw)
    return dict(path=str(p), bytes=len(raw), sha256=adm.digest(raw))


def base_config(tmp_path):
    cfg = json.loads((CATALOG / 'doc5g.json').read_text())
    cfg.update(mode='live', run_tag='20261020test', used_run_tags=['20261020r2'],
        project_root=str(tmp_path), staging_root=str(tmp_path / 'scratch/staging'),
        mission_root=str(tmp_path / 'outputs/mission'), code_root=str(ROOT),
        issuance_receipt=str(tmp_path / 'outputs/issued.json'), assembly_receipt=str(tmp_path / 'outputs/assembly.json'),
        window_scope_change='synthetic fixture windows only', interpreter=sys.executable,
        reviewer=dict(profile='sol-reviewer', model='test-independent', reviewer_id='synthetic-only'), task='synthetic-test')
    cfg['controls'][adm.LEDGER_PATH] = 'a' * 64
    return cfg


def fixture(tmp_path):
    cfg = base_config(tmp_path)
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
        output_retention=declaration(cfg['retained']['prior'], cfg['retained']['cap'], profile=COMPACT_V3_PROFILE))
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
        prior_scratch_bytes=cfg['limits']['scratch_prior_bytes'], scratch_limit_bytes=cfg['limits']['scratch_limit_bytes'])
    index_ref = meta('prospective-index.json', index)
    package = dict(status='PASS_METADATA_ONLY', units_started=0, original_source_reads=0,
        staging_root=str(stage), mission_root=cfg['mission_root'], files=references, index=index_ref)
    cfg['inputs']['historical_context'] = put(tmp_path / 'context.json', dict(source=source, metadata_sha256='d' * 64,
        mode='real_continuation', rehearsal_synthetic=False, real_source_sha256=source['sha256'], windows=[[1, 2, 3, 4]]))
    cfg['inputs']['prior_carry'] = put(tmp_path / 'prior.json', dict(closed=True))
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


@pytest.mark.parametrize('preflight_rc', [0, 2])
def test_assembly_real_managed_writes_with_simulated_preflight(tmp_path, monkeypatch, preflight_rc):
    cfg, kwargs = fixture(tmp_path)
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


def test_issue_pipeline_with_synthetic_prepare_and_real_renderer(tmp_path, monkeypatch):
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
        shutil.copytree(prepared, stage)
        return SimpleNamespace(stdout=json.dumps(kwargs['package']))

    monkeypatch.setattr(adm.subprocess, 'run', prepare)
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
