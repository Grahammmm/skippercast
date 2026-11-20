"""Synthetic metadata prepare -> render -> managed assembly; NOT live authority.

Contract protected: actual prepare.main + admission render/assemble + ManagedOutputs carry the evidence root,
cumulative cap and prior retained bytes end to end, select strict/partial windows (never historical context windows),
and refuse bad roots/roles/priors/controls without touching preserved state. Believable bugs that fail it: assembly
copying stale context windows, dropping the prior retained bytes, refunding failed reservations, relaunching after a
failed preflight, or overwriting an existing stage/mission. Only the preflight transport and the executor-host
code-identity gate (adm.live_code, stubbed as in test_coastal_four128_admission.py) are replaced.
"""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from research.scripts import coastal_four128_admission as adm
from skippercast.coastal.handoff.common import load
from skippercast.coastal.output_writer import COMPACT_V3_PROFILE, ManagedOutputs, declaration
from skippercast.coastal.receipts import digest as receipt_digest
from tests._support import ROOT
from tests.contract.test_four128_candidate_documents import candidate_documents
from tests.unit.test_coastal_four128_admission import base_config, put, topology_receipt, topology_review
from tests.unit.test_coastal_four128_budget import amendment

NOW = 100.0


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    # Contain the legacy modules' own import side effects; no installed-home imports.
    with mock.patch.object(sys, 'path', list(sys.path)):
        from research.scripts import coastal_four128_prepare as prepare
        from research.scripts import coastal_four128_runtime as runtime
    monkeypatch.setattr(prepare, 'B', tmp_path)
    monkeypatch.setattr(adm.time, 'time', lambda: NOW)
    monkeypatch.delenv('SKIPPERCAST_FOUR128_RUN_TAG', raising=False)
    original_open = Path.open

    def metadata_only(path, *args, **kwargs):
        dependency_metadata = path.name == 'METADATA' and path.parent.name.endswith('.dist-info')
        assert path.is_relative_to(tmp_path) or path.is_relative_to(ROOT) or dependency_metadata, path
        assert path.suffix.lower() not in ('.bag', '.tif', '.tiff'), path
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', metadata_only)
    monkeypatch.setattr(runtime, 'Store', mock.Mock(side_effect=AssertionError('no Store')))
    calls = []

    def transport(argv, **options):
        calls.append(argv)
        assert argv == [sys.executable, '-I', '-B', str(ROOT / 'research/scripts/coastal_four128_runtime.py'), 'preflight']
        return SimpleNamespace(returncode=transport.rc, stdout='SIMULATED preflight; no native execution', stderr='')

    transport.rc = 0
    monkeypatch.setattr(adm.subprocess, 'run', transport)
    monkeypatch.setattr(adm, 'runtime', lambda cfg: runtime)
    controls = []  # filled by build() from the real control bytes; tests may tamper with it in place
    # The executor-host code-identity gate is replaced exactly as test_coastal_four128_admission.py does;
    # its own refusals stay covered by test_live_code_rejects_dirty_head_and_wrong_root and the source-guard tests.
    monkeypatch.setattr(adm, 'live_code', lambda cfg: (controls, cfg['head']))

    def build(partial=False):
        cfg = base_config(tmp_path)
        cfg.update(head='1' * 40, origin=dict(ref='synthetic-reviewed', head='1' * 40),
                   evidence_root=str(tmp_path / 'evidence'), docs=dict(adm.DOCS))
        cfg['retained'] = dict(prior=1234567, cap=1234567 + 33554432, trial=33554432)
        cfg['texts']['retained_meaning'] = 'SYNTHETIC prior includes failed/open reservations; no refunds.'
        grant, templates, docs = candidate_documents(tmp_path / 'templates', partial)
        policy = adm.PARTIAL_SUPPORT if partial else None
        cfg['windows'] = prepare.scope_for(policy)
        if partial:
            from skippercast.coastal.coordinator.ordered_trial import PARTIAL_BOUNDS
            cfg.update(support_policy=policy, bounds=list(PARTIAL_BOUNDS))
            raw = topology_receipt(cfg['head'])
            cfg['inputs']['selection'] = put(tmp_path / 'selection.json', json.loads(raw))
            cfg['inputs']['prescan_review'] = put(tmp_path / 'prescan-review.json', topology_review(raw))
        else:
            cfg['inputs']['selection'] = put(tmp_path / 'selection.json', dict(synthetic=True))
        cfg['inputs']['prior_carry'] = put(tmp_path / 'prior.json', dict(closed=True, synthetic=True))
        cfg['inputs']['historical_context'] = put(tmp_path / 'context.json', dict(
            source=grant['source'], metadata_sha256='e' * 64, windows=[[1, 2, 3, 4]],
            mode='real_continuation', rehearsal_synthetic=False, real_source_sha256=grant['source']['sha256']))
        roles = dict(zip(('scope', 'rights', 'trial', 'science'), (
            'independent-four128-scope-review', 'independent-four128-rights-review',
            'independent-four128-strict-trial-policy', 'independent-four128-scientific-preflight')))
        docs['scope'] = load(tmp_path / 'templates', grant['geographic_review'])
        for role, name in roles.items():
            docs[role].update(window_set=cfg['windows'], checked_at=adm.iso(50), valid_until=adm.iso(100000),
                              reviewer_id='independent-synthetic', prescan_evidence=[cfg['inputs']['selection']])
            if role == 'science':
                docs[role]['expected_metadata_sha256'] = 'e' * 64
            put(Path(cfg['evidence_root']) / (name + '.json'), docs[role])
        historical = tmp_path / 'outputs/source-reuse-admission-engineering-20261011'
        put(historical / 'independent-four128-segment.json', docs['segment'])
        put(historical / 'approved-trial-budget-arithmetic-v1.json', dict(schema='approved-trial-budget-arithmetic-v1', synthetic=True))
        old = tmp_path / 'outputs/ordered-coastal-rehearsed-live-20261010/execution/metadata'
        put(old / 'grant-real-released.json', grant)
        for label, template in zip('ABCD', templates):
            put(old / ('acquire_' + label + '_real_released.json'), template)
        a = amendment()
        # Bind a synthetic ledger head, not a signature claim or a bypassed validator.
        resource = sys.modules[prepare.budget_limits_bytes.__module__]
        ledger = copy.deepcopy(resource.CHARGE_LEDGER)
        a.update(signer=ledger['head']['signer'], signed_at=ledger['head']['signed_at'],
                 supersedes=dict(sha256=ledger['head']['supersedes_sha256']),
                 retained_output=dict(prior_retained_bytes=cfg['retained']['prior']))
        cfg['inputs']['amendment'] = put(tmp_path / 'amendment.json', a)
        ledger['head']['sha256'] = cfg['inputs']['amendment']['sha256']
        monkeypatch.setattr(resource, 'CHARGE_LEDGER', ledger)
        for rel in (*adm.CONTROL_PATHS, adm.LEDGER_PATH):
            cfg['controls'][rel] = adm.digest((ROOT / rel).read_bytes())
        controls[:] = [dict(path=rel, bytes=len((ROOT / rel).read_bytes()), sha256=sha) for rel, sha in cfg['controls'].items()]
        for key, rel in (('prepare_sha256', 'research/scripts/coastal_four128_prepare.py'),
                         ('controller_sha256', 'src/skippercast/coastal/coordinator/ordered_trial.py'),
                         ('bootstrap_sha256', 'src/skippercast/coastal/authenticated_v1/bootstrap.py')):
            cfg[key] = adm.digest((ROOT / rel).read_bytes())
        argv = ['prepare', '--staging-root', cfg['staging_root'], '--mission-root', cfg['mission_root'],
                '--evidence-root', cfg['evidence_root'], '--cumulative-cap-bytes', str(cfg['retained']['cap']),
                '--prior-retained-bytes', str(cfg['retained']['prior']), '--budget-amendment', cfg['inputs']['amendment']['path'],
                '--prospective-released-bytes']
        if partial:
            argv += ['--support-policy', policy]
        return cfg, argv

    def run(argv):
        monkeypatch.setattr(sys, 'argv', argv)
        prepare.main()
        stage = Path(argv[argv.index('--staging-root') + 1])
        return json.loads((stage / 'prospective-package.json').read_text())

    return SimpleNamespace(build=build, run=run, prepare=prepare, calls=calls, transport=transport, controls=controls)


def issued(s, cfg, argv):
    package = s.run(argv)
    index, grant, a = adm.prepare_inputs(cfg, package)
    docs = adm.evidence_summary(cfg, NOW)
    controls, _ = adm.live_code(cfg)
    observation = dict(checked_at=adm.iso(NOW), valid_until=adm.iso(NOW + 86400), reviewer=cfg['reviewer'],
                       task='synthetic-only', origin_ref_head=cfg['head'], procedure=dict(interpreter=sys.executable))
    outputs = adm.render(cfg, observation=observation, index=index, grant=grant, amendment=a,
                         package=package, controls=controls, docs=docs)
    for name, raw in outputs.items():
        adm.write_new(Path(cfg['staging_root']) / 'metadata' / name, raw)
    put(Path(cfg['issuance_receipt']), dict(schema='coastal-four128-config-issuance-v1', config_sha256='f' * 64,
        head=cfg['head'], run_tag=cfg['run_tag'],
        files=[adm.reference(n, raw, json.loads(raw)['schema']) for n, raw in outputs.items()]))
    return package, index, grant, outputs


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('preflight_rc', [0, 2])
def test_prepare_render_managed_assembly(scenario, partial, preflight_rc):
    s = scenario
    cfg, argv = s.build(partial)
    package, index, grant, outputs = issued(s, cfg, argv)
    s.transport.rc = preflight_rc
    if preflight_rc:
        with pytest.raises(ValueError, match='preflight failed'):
            adm.assemble(cfg, 'f' * 64)
    else:
        assert adm.assemble(cfg, 'f' * 64)['status'] == 'ASSEMBLED_PREFLIGHT_OK_REVIEW_REQUIRED'
    mission = Path(cfg['mission_root'])
    context = json.loads((mission / 'control/release-context.json').read_text())
    closed, review, live = (json.loads(outputs[n]) for n in adm.OUTPUT_NAMES)
    assert context['windows'] == grant['window_set'] == cfg['windows']
    assert context['assembled_from']['historical_windows'] == [[1, 2, 3, 4]] != context['windows']
    assert context['original_source_reads'] == 0 and context['prior_active_seconds'] == 0
    assert 'no clock created' in context['clock_status']
    assert index['prior_scratch_bytes'] == closed['scratch']['charged_prior_bytes'] == cfg['limits']['scratch_prior_bytes']
    assert closed['source']['prior_effective_bytes'] == cfg['limits']['source_prior_bytes']
    assert closed['source']['refunds'] is closed['scratch']['refunds'] is False
    assert closed['source']['failed_trial_charged_bytes'] == 73515136
    assert closed['scratch']['failed_trial_full_reservation_bytes'] == 536870912
    assert closed['retained_output']['cumulative_prior_bytes'] == review['accounting']['retained']['prior'] == 1234567
    assert closed['retained_output']['remaining_after_trial_bytes'] == 0
    assert live['grant'] == index['grant'] and live['prior_scratch_bytes'] != 1234567
    assert review['window_set'] == cfg['windows'] and review['execution_authorized'] is False
    assert review['limitations']['publication_authorized'] is False
    manager = ManagedOutputs(mission, grant, receipt_digest(grant))
    assert manager.plan == declaration(1234567, cfg['retained']['cap'], profile=COMPACT_V3_PROFILE)
    assert manager.audit()['unmanaged_control_bytes'] == 0
    for item in package['files']:
        assert (mission / 'execution' / item['path']).read_bytes() == adm.relative_metadata(Path(cfg['staging_root']), item)
    report = json.loads(Path(cfg['assembly_receipt']).read_text())
    assert report['preflight']['returncode'] == preflight_rc
    assert report['preflight']['stdout'].startswith('SIMULATED')
    assert report['units_started'] == report['source_reads'] == report['network_requests'] == 0
    assert len(s.calls) == 1
    assert not list(mission.rglob('*.sqlite*')) and not (mission / 'control/outer-clock.json').exists()
    before = {p.relative_to(mission): p.read_bytes() for p in mission.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='existing mission'):
        adm.assemble(cfg, 'f' * 64)
    assert before == {p.relative_to(mission): p.read_bytes() for p in mission.rglob('*') if p.is_file()}
    assert len(s.calls) == 1


@pytest.mark.parametrize('flag', ['--evidence-root', '--cumulative-cap-bytes', '--prior-retained-bytes'])
def test_required_flags_refuse_before_stage(scenario, flag):
    cfg, argv = scenario.build()
    i = argv.index(flag)
    del argv[i:i + 2]
    with pytest.raises(SystemExit) as exc:
        scenario.run(argv)
    assert exc.value.code == 2 and not Path(cfg['staging_root']).exists()


@pytest.mark.parametrize('prior', [-1, 1.5, True])
def test_invalid_prior_and_overcap_refuse(scenario, prior):
    cfg, argv = scenario.build()
    with pytest.raises(ValueError, match='exact nonnegative'):
        declaration(prior, cfg['retained']['cap'], profile=COMPACT_V3_PROFILE)
    argv[argv.index('--prior-retained-bytes') + 1] = str(prior)
    with pytest.raises((ValueError, SystemExit)):
        scenario.run(argv)
    assert not Path(cfg['staging_root']).exists()
    argv[argv.index('--prior-retained-bytes') + 1] = str(cfg['retained']['prior'] + 1)
    with pytest.raises(ValueError, match='exceeds cumulative'):
        scenario.run(argv)
    assert not Path(cfg['staging_root']).exists()


@pytest.mark.parametrize('bad', ['historical', 'alias', 'missing', 'expired', 'author', 'tampered', 'source', 'ledger'])
def test_metadata_refusals_preserve_stage(scenario, bad):
    cfg, argv = scenario.build()
    evidence = Path(cfg['evidence_root'])
    role = evidence / 'independent-four128-scope-review.json'
    if bad in ('historical', 'alias'):
        root = Path(cfg['project_root']) / 'outputs/source-reuse-admission-engineering-20261011'
        if bad == 'alias':
            root = evidence.parent / 'alias'
            root.symlink_to(evidence, target_is_directory=True)
        argv[argv.index('--evidence-root') + 1] = str(root)
    elif bad == 'missing':
        role.unlink()
    elif bad in ('expired', 'author', 'source'):
        doc = json.loads(role.read_text())
        if bad == 'expired':
            doc['valid_until'] = adm.iso(NOW)
        elif bad == 'author':
            doc['reviewer_id'] = 'opus-coder'
        else:
            doc['source']['sha256'] = '0' * 64
        put(role, doc)
    elif bad == 'ledger':
        p = Path(cfg['inputs']['amendment']['path'])
        p.write_bytes(p.read_bytes() + b' ')
    if bad in ('tampered', 'author'):
        # Prepare stages the role bytes; the admission evidence check is what refuses these two.
        package = scenario.run(argv)
        if bad == 'tampered':
            role.write_bytes(role.read_bytes() + b' ')
        with pytest.raises(ValueError, match='staged evidence differs' if bad == 'tampered' else 'independent evidence'):
            adm.evidence_summary(cfg, NOW)
        assert package['original_source_reads'] == 0
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            scenario.run(argv)
    stage = Path(cfg['staging_root'])
    if stage.exists():
        before = {p: p.read_bytes() for p in stage.rglob('*.json')}
        with pytest.raises(ValueError, match='fresh external scratch'):
            scenario.run(argv)
        assert before == {p: p.read_bytes() for p in stage.rglob('*.json')}
    assert not Path(cfg['mission_root']).exists() and scenario.calls == []


@pytest.mark.parametrize('existing', ['staging_root', 'mission_root', 'run_scratch'])
def test_existing_roots_refuse_without_cleanup(scenario, existing):
    cfg, argv = scenario.build()
    root = (Path(cfg['project_root']) / ('scratch/four128-approved-' + cfg['run_tag'])
            if existing == 'run_scratch' else Path(cfg[existing]))
    put(root / 'preserved.json', dict(synthetic=True))
    before = (root / 'preserved.json').read_bytes()
    with pytest.raises(ValueError):
        adm.fresh_run(cfg, stage_absent=True)
    if existing != 'run_scratch':
        with pytest.raises(ValueError, match='fresh external scratch'):
            scenario.run(argv)
    assert (root / 'preserved.json').read_bytes() == before and scenario.calls == []


def test_control_ledger_mismatch_refuses_assembly(scenario):
    # Contract: assemble refuses when the executor controls differ from those bound at issuance (edge case 8).
    cfg, argv = scenario.build()
    issued(scenario, cfg, argv)
    next(c for c in scenario.controls if c['path'] == adm.LEDGER_PATH)['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='assembly controls differ'):
        adm.assemble(cfg, 'f' * 64)
    assert not Path(cfg['mission_root']).exists() and scenario.calls == []
