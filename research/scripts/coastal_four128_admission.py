"""Config-driven four128 admission metadata; never starts units or opens sources.

Historical replay rebuilds the three issuance documents from archived prepare
outputs, not from the expected documents. Its receipt is evidence of byte
reproduction only. Live issuance and assembly require a separately reviewed
live config and the existing runtime/coordinator gates.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'coastal-four128-admission-config-v1'
OUTPUT_NAMES = ('closed-fresh-carry.json', 'independent-runtime-review.json', 'live-index.json')
CONTROL_PATHS = ('research/scripts/coastal_four128_runtime.py',
                 'research/scripts/coastal_four128_resources.py',
                 'research/scripts/coastal_four128_artifact_review.py')
LEDGER_PATH = 'research/catalog/coastal-four128-charge-ledger.json'
# Literal copy of profiles.PARTIAL_SUPPORT: config parsing must not import project
# code before live_code() has run the source guard. issue() re-checks the pin.
PARTIAL_SUPPORT = 'coastal-contained-partial-support-v1'
PARTIAL_SCIENCE_STATUS = 'PASS_EXPECTED_SOURCE_METADATA_GEOMETRY_PARTIAL_POLICY'
TOPOLOGY_SCRIPT = 'research/scripts/coastal_four128_mask_topology.py'
DOCS = {
    'independent-four128-scientific-preflight': 'coastal-ordered-independent-scientific-preflight-v1',
    'independent-four128-scope-review': 'coastal-ordered-scope-review-v1',
    'independent-four128-rights-review': 'coastal-rights-evidence-v1',
    'independent-four128-strict-trial-policy': 'coastal-bounded-patch-quality-policy-v3',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def path(value):
    p = Path(value).expanduser().absolute()
    require('..' not in p.parts and not any(q.is_symlink() for q in (p, *p.parents)),
            'normalised non-symlink path required')
    return p


def read_metadata(p):
    p = path(p)
    require(p.suffix in ('.json', '.py'), 'only code/JSON metadata may be read')
    require(p.is_file() and p.stat().st_size <= 2_000_000, 'bounded regular metadata file required')
    return p.read_bytes()


def pinned(item):
    raw = read_metadata(item['path'])
    require(len(raw) == item['bytes'] and digest(raw) == item['sha256'], 'input bytes/hash changed: ' + item['path'])
    return raw


def reference(name, raw, contract):
    return dict(path='metadata/' + name, bytes=len(raw), sha256=digest(raw), contract=contract)


def relative_metadata(stage, item):
    rel = Path(item['path'])
    require(not rel.is_absolute() and '..' not in rel.parts and rel.parts[:1] == ('metadata',), 'metadata reference escapes staging')
    return pinned(dict(item, path=str(stage / rel)))


def epoch(value):
    parsed = dt.datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, 'aware timestamp required')
    return parsed.timestamp()


def iso(value):
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()


def config_file(filename):
    raw = read_metadata(filename)
    cfg = json.loads(raw)
    require(cfg.get('schema') == SCHEMA and cfg.get('mode') in ('historical-replay', 'live'), 'admission config schema/mode')
    require(re.fullmatch(r'[0-9]{8}[a-z0-9]{0,8}', cfg['run_tag']), 'invalid run tag')
    require(re.fullmatch(r'[0-9a-f]{40}', cfg['head']), 'exact head required')
    require(cfg['layout'] in (5, 6), 'unknown historical layout')
    require(cfg['docs'] == DOCS, 'all four independent evidence roles required')
    expected = set(CONTROL_PATHS) | ({LEDGER_PATH} if cfg['mode'] == 'live' else set())
    require(set(cfg['controls']) == expected, 'complete reviewed controls required')
    for value in cfg['controls'].values():
        require(re.fullmatch(r'[0-9a-f]{64}', value), 'exact control hash required')
    # Opt-in partial support (SC-5): absent means the strict policy, so every
    # historical config and its replay bytes are unchanged.
    if 'support_policy' in cfg:
        require(cfg['mode'] == 'live' and cfg['support_policy'] == PARTIAL_SUPPORT, 'unsupported support policy')
        require(set(cfg['inputs']) >= {'selection', 'prescan_review'}, 'partial support needs the reviewed mask-topology pre-scan')
    return cfg, digest(raw)


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True).stdout


def archived_controls(cfg):
    controls = []
    for rel, expected in cfg['controls'].items():
        raw = git('show', cfg['head'] + ':' + rel)
        require(digest(raw) == expected, 'archived control differs from config')
        controls.append(dict(path=rel, bytes=len(raw), sha256=digest(raw)))
    # Historical output order is significant inside the JSON list.
    return sorted(controls, key=lambda item: CONTROL_PATHS.index(item['path']))


def accounting(doc):
    require(doc['schema'] == 'coastal-four128-budget-amendment-v1'
            and doc['status'] == 'SIGNED_DELEGATED_BUDGET_AUTHORITY'
            and doc['signer']['profile'] in ('fable-2nd-look', 'astra-orchestrator')
            and doc['author_under_review'] == 'opus-coder'
            and doc['signer']['model'] and 'opus' not in doc['signer']['model'].lower(), 'signed delegated amendment required')
    s, t = doc['source'], doc['scratch']
    for block in (s, t):
        require(all(type(v) is int and v >= 0 for k, v in block.items() if k.endswith('_bytes')), 'exact integer accounting required')
        require(block['refunds'] is False, 'refunds forbidden')
    prior = sum(v for k, v in s.items() if k == 'pre_failure_prior_bytes' or k.endswith('_charged_bytes'))
    require(type(s['downloads']) is int and s['downloads'] == 0 and prior == s['prior_effective_bytes'], 'source prior/downloads differ')
    require(s['additional_bytes'] == max(0, prior + s['fresh_allowance_bytes'] - s['previous_cumulative_limit_bytes'])
            and s['cumulative_limit_bytes'] == s['previous_cumulative_limit_bytes'] + s['additional_bytes'], 'source shortfall differs')
    require(t['additional_bytes'] == max(0, t['charged_prior_bytes'] + t['trial_reservation_bytes'] - t['previous_cumulative_maximum_bytes'])
            and t['cumulative_maximum_bytes'] == t['previous_cumulative_maximum_bytes'] + t['additional_bytes'], 'scratch shortfall differs')
    return dict(source_prior_bytes=prior, source_limit_bytes=s['cumulative_limit_bytes'],
                scratch_prior_bytes=t['charged_prior_bytes'], scratch_limit_bytes=t['cumulative_maximum_bytes'])


def prepare_inputs(cfg, package):
    stage = path(cfg['staging_root'])
    require(package['status'] == 'PASS_METADATA_ONLY' and package['units_started'] == 0
            and package['original_source_reads'] == 0 and package['mission_root'] == str(path(cfg['mission_root']))
            and package['staging_root'] == str(stage), 'prepare scope differs')
    files = {}
    for item in package['files']:
        require(Path(item['path']).name not in OUTPUT_NAMES and item['path'] not in files, 'issuance output/duplicate in prepare inputs')
        files[item['path']] = json.loads(relative_metadata(stage, item))
    index = files[package['index']['path']]
    require(json.loads(relative_metadata(stage, package['index'])) == index, 'prepare index differs')
    grant = json.loads(relative_metadata(stage, index['grant']))
    carry = json.loads(relative_metadata(stage, index['carry']))
    amendment = json.loads(pinned(cfg['inputs']['amendment']))
    limits = accounting(amendment)
    require(limits == cfg['limits'], 'config limits differ from signed accounting')
    require(grant['approved_budget_amendment']['sha256'] == cfg['inputs']['amendment']['sha256']
            and carry['budget_amendment'] == grant['approved_budget_amendment'], 'amendment binding differs')
    require(grant['execution_authorized'] is True and grant['output_root'] == str(path(cfg['mission_root']))
            and grant['window_set'] == cfg['windows'] and grant['window_count'] == 4 and grant['window_side'] == 128, 'grant scope differs')
    require((grant['code_sha'], grant['deps_sha']) == (index['code_sha'], index['deps_sha']), 'grant implementation binding differs')
    require((grant['prior_effective_bytes'], grant['cumulative_limit_bytes'], grant['source_volume_cap_bytes']) ==
            (limits['source_prior_bytes'], limits['source_limit_bytes'], amendment['source']['fresh_allowance_bytes']), 'grant accounting differs')
    require((carry['prior_effective_bytes'], carry['cumulative_limit_bytes'], carry['remaining_bytes'], carry['refunds']) ==
            (limits['source_prior_bytes'], limits['source_limit_bytes'], amendment['source']['fresh_allowance_bytes'], False), 'carry accounting differs')
    require((index['prior_scratch_bytes'], index['scratch_limit_bytes']) ==
            (limits['scratch_prior_bytes'], limits['scratch_limit_bytes']), 'index scratch differs')
    policy = cfg.get('support_policy')
    require(grant.get('support_policy') == policy and index.get('support_policy') == policy
            and package.get('support_policy') == policy, 'support policy binding differs')
    retained = cfg['retained']
    require((grant['output_retention']['prior_retained_bytes'], grant['output_retention']['cumulative_cap_bytes'],
             grant['output_retention']['total_bytes'], grant['output_retention']['profile']) ==
            (retained['prior'], retained['cap'], retained['trial'], 'coastal-managed-output-32-v3'), 'retention differs')
    require(retained['prior'] == amendment['retained_output']['prior_retained_bytes'], 'signed retained prior differs')
    return index, grant, amendment


def evidence_summary(cfg, now):
    summary = {}
    for name, contract in cfg['docs'].items():
        p = path(cfg['evidence_root']) / (name + '.json')
        raw = read_metadata(p)
        doc = json.loads(raw)
        require(doc['schema'] == contract and doc['window_set'] == cfg['windows'], 'evidence contract/windows differ')
        require(doc.get('support_policy') == cfg.get('support_policy'), 'evidence support policy differs')
        require(epoch(doc['checked_at']) <= now and epoch(doc['valid_until']) > now + 7200, 'evidence freshness margin exhausted')
        require('HOLD' not in str(doc.get('status', '')).upper() and not doc.get('holds', doc.get('holds_added', [])), 'evidence held')
        require(doc.get('reviewer_id') and 'opus' not in doc['reviewer_id'].lower(), 'independent evidence required')
        selection = cfg['inputs']['selection']
        prescan = doc.get('prescan_evidence', [])
        require(any(e['path'] == str(path(selection['path'])) and e['sha256'] == selection['sha256'] for e in prescan), 'selection evidence missing')
        for item in prescan:
            require(digest(read_metadata(item['path'])) == item['sha256'], 'prescan evidence changed')
        require(read_metadata(path(cfg['staging_root']) / 'metadata' / p.name) == raw, 'staged evidence differs')
        summary[name] = dict(path=str(p), sha256=digest(raw), bytes=len(raw), status=str(doc.get('status', '')),
                             checked_at=doc['checked_at'], valid_until=doc['valid_until'], reviewer_id=doc.get('reviewer_id'))
    return summary


def render(cfg, *, observation, index, grant, amendment, package, controls, docs):
    """Pure construction shared by live issuance and historical byte replay."""
    now = epoch(observation['checked_at'])
    require(iso(now + 86400) == observation['valid_until'], 'issuance validity differs')
    reviewer = observation['reviewer']
    require(reviewer['profile'] != 'opus-coder' and 'opus' not in reviewer['model'].lower(), 'issuer must differ from harness author')
    common = dict(reviewer_id=reviewer['reviewer_id'], reviewer_model=reviewer['model'], reviewer_profile=reviewer['profile'],
                  review_task=observation['task'], independent=True, checked_at=observation['checked_at'], valid_until=observation['valid_until'],
                  review_procedure=observation['procedure'])
    lim, ret = cfg['limits'], cfg['retained']
    source, scratch = amendment['source'], amendment['scratch']
    remaining = ret['cap'] - ret['prior'] - ret['trial']
    require(remaining >= 0, 'retained output shortfall')
    prior = cfg['inputs']['prior_carry']
    closed = dict(schema='coastal-source-reuse-engineering-carry-v1', closed=True, **common,
        predecessor=dict(path=str(path(prior['path'])), sha256=prior['sha256'], expected_sha256=prior['sha256']),
        budget_amendment=grant['approved_budget_amendment'],
        retained_output=dict(cumulative_prior_bytes=ret['prior'], cumulative_limit_bytes=ret['cap'], trial_allocation_bytes=ret['trial'],
            remaining_after_trial_bytes=remaining, meaning=cfg['texts']['retained_meaning']),
        scratch=dict(charged_prior_bytes=lim['scratch_prior_bytes'], previous_cumulative_maximum_bytes=scratch['previous_cumulative_maximum_bytes'],
            cumulative_maximum_bytes=lim['scratch_limit_bytes'], trial_reservation_bytes=scratch['trial_reservation_bytes'],
            failed_trial_full_reservation_bytes=scratch['trial_reservation_bytes'], refunds=False,
            basis=cfg['texts']['scratch_basis'] + cfg['inputs']['amendment']['sha256']),
        source=dict(prior_effective_bytes=lim['source_prior_bytes'], cumulative_limit_bytes=lim['source_limit_bytes'],
            fresh_allowance_bytes=source['fresh_allowance_bytes'], **{k: v for k, v in source.items() if k.endswith('_charged_bytes')}, downloads=0, refunds=False),
        b4_fresh_download_budget=dict(cap_bytes=1500000000, used_bytes=0), native_operations=0, original_source_reads=0, downloads=0)
    closed_raw = encoded(closed)
    closed_ref = reference(OUTPUT_NAMES[0], closed_raw, closed['schema'])
    bindings: dict = dict(grant=index['grant'], carry=index['carry'], independent_preflight=index['independent_preflight'],
        prior_output_carry=closed_ref, prior_scratch_carry=closed_ref, prior_scratch_bytes=lim['scratch_prior_bytes'],
        runtime_controls=controls, controller_sha256=cfg['controller_sha256'], code_sha=index['code_sha'], deps_sha=index['deps_sha'])
    identity: dict = dict(commit=cfg['head'], checkout=str(path(cfg['code_root'])), slice='skippercast-four128approved'+cfg['run_tag']+'.slice',
                    run_tag=cfg['run_tag'], interpreter=observation['procedure']['interpreter'])
    if cfg['layout'] == 6:
        identity.update(origin_ref_head=observation['origin_ref_head'], origin_descendant_approved=False, prepare_sha256=cfg['prepare_sha256'])
    selection = dict(cfg['inputs']['selection'], path=str(path(cfg['inputs']['selection']['path'])))
    partial = cfg.get('support_policy') is not None
    if partial:
        # Opt-in only: strict documents keep their exact historical keys and bytes.
        prescan = dict(receipt=selection, review=dict(cfg['inputs']['prescan_review'],
                                                      path=str(path(cfg['inputs']['prescan_review']['path']))),
                       require_holes_met=True, independently_reviewed=True,
                       meaning='Reviewed one-open mask-topology observation; not native quality or scientific acceptance.')
        bindings.update(support_policy=cfg['support_policy'], mask_topology_prescan=prescan)
    scope = ('Exact four pinned partial-support 128 windows (mask-invalid cells unsupported nodata), private native '
             'acquisition/qualification and mapping only; rendering allocation 0.' if partial else
             'Exact four canonical 128 windows, private native acquisition/qualification and mapping only; rendering allocation 0.')
    doc5 = dict(schema='coastal-four128-independent-prelaunch-v1', status='PASS_EXACT_FINITE_PRELAUNCH', holds=[], **common, **bindings,
        scope=scope,
        code_identity=identity, window_set=cfg['windows'], native_bounds=cfg['bounds'], block_selection=selection,
        accounting=dict(retained=dict(prior=ret['prior'], cap=ret['cap'], trial=ret['trial'], remaining_after_trial=remaining),
            source=dict(prior=lim['source_prior_bytes'], cap=lim['source_limit_bytes'], fresh=source['fresh_allowance_bytes'], downloads=0),
            scratch=dict(prior=lim['scratch_prior_bytes'], cap=lim['scratch_limit_bytes'], trial=scratch['trial_reservation_bytes']),
            b4=dict(cap=1500000000, used=0), amendment_sha256=cfg['inputs']['amendment']['sha256']),
        documents_1_to_4=docs, prospective_package=dict(staging_root=str(path(cfg['staging_root'])), files=package['files']),
        checks_performed=cfg['texts']['checks'],
        limitations=dict(current_original_source_identity_verified=False, native_quality_accepted=False, production_ready=False,
            publication_authorized=False, meaning=cfg['texts']['limitation']),
        execution_authorized=False, native_operations=0, original_source_reads=0, downloads=0, network_requests=0)
    if cfg['layout'] == 6:
        doc5['mission_root'] = str(path(cfg['mission_root']))
    if partial:
        doc5['accounting']['source'].update(prescan_charged_in_prior=source['sc5_geometry_prescan_charged_bytes'],
                                            run_admissions=8)
    doc5_raw = encoded(doc5)
    live = dict(index)
    live.pop('status', None)
    live.update(independent_runtime_review=reference(OUTPUT_NAMES[1], doc5_raw, doc5['schema']),
                runtime_review_pending=False, execution_authorized=True, **bindings)
    return dict(zip(OUTPUT_NAMES, (closed_raw, doc5_raw, encoded(live))))


def write_new(filename, raw):
    p = path(filename)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('xb') as stream:
        stream.write(raw)


def replay(cfg, output):
    require(cfg['mode'] == 'historical-replay', 'historical config required')
    output = path(output)
    require(not output.exists() and not output.is_relative_to(path(cfg['project_root'])), 'fresh replay root outside project data required')
    receipt = json.loads(pinned(cfg['inputs']['receipt']))
    issuer_raw = pinned(cfg['inputs']['issuer'])
    package = json.loads(pinned(cfg['inputs']['package']))
    for name in ('selection', 'prior_carry'):
        pinned(cfg['inputs'][name])
    require(receipt['head'] == cfg['head'] and receipt['run_tag'] == cfg['run_tag'] and not receipt['failures'], 'historical receipt differs')
    require(receipt['staging_root'] == str(path(cfg['staging_root'])) and receipt['mission_root'] == str(path(cfg['mission_root'])), 'historical roots differ')
    require(digest(issuer_raw) == receipt['script_sha256'], 'historical issuer identity differs')
    index, grant, amendment = prepare_inputs(cfg, package)
    controls = archived_controls(cfg)
    require(controls == receipt['runtime_controls'], 'historical controls differ')
    controller = git('show', cfg['head'] + ':src/skippercast/coastal/coordinator/ordered_trial.py')
    require(digest(controller) == cfg['controller_sha256'], 'archived controller differs')
    if cfg['prepare_sha256']:
        require(digest(git('show', cfg['head'] + ':research/scripts/coastal_four128_prepare.py')) == cfg['prepare_sha256'], 'archived prepare differs')
    require((index['code_sha'], index['deps_sha']) == (receipt['code_sha'], receipt['deps_sha']), 'recorded implementation identity differs')
    docs = evidence_summary(cfg, epoch(receipt['checked_at']))
    observation = dict(checked_at=receipt['checked_at'], valid_until=receipt['valid_until'], reviewer=receipt['reviewer'], task=receipt['task'],
        origin_ref_head=receipt.get('origin_ref_head'),
        procedure=dict(script=str(path(cfg['inputs']['issuer']['path'])), script_sha256=digest(issuer_raw), interpreter=str(Path(cfg['interpreter']).expanduser())))
    outputs = render(cfg, observation=observation, index=index, grant=grant, amendment=amendment, package=package, controls=controls, docs=docs)
    results = []
    # Expected output bytes are opened ONLY after reconstruction has finished.
    for name, key in zip(OUTPUT_NAMES, ('closed_carry', 'document5', 'live_index')):
        raw = outputs[name]
        expected = receipt[key]
        require(raw == relative_metadata(path(cfg['staging_root']), expected), 'byte replay differs: ' + name)
        results.append(dict(name=name, bytes=len(raw), sha256=digest(raw), byte_equal=True))
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in outputs.items():
        write_new(output / name, raw)
    report = dict(status='HISTORICAL_BYTES_REPRODUCED_REVIEW_REQUIRED', label=cfg['label'], files=results,
        execution_authorized=False, current_review=False, source_reads=0, network_requests=0, units_started=0,
        limitations=['Prepare outputs are archived inputs, not rerun.', 'Historical code/dependency aggregate hashes are recorded bindings, not current environment acceptance.',
                     'Historical review identity and timestamps are reproduced, not issued anew.'])
    write_new(output / 'REPLAY_ONLY.json', encoded(report))
    return report


def fresh_run(cfg, *, stage_absent):
    """No I/O with source data, no writes, no imports of native workers."""
    require(cfg['mode'] == 'live', 'historical configs cannot issue or assemble')
    require(cfg['layout'] == 6, 'live issuance requires current layout')
    require(cfg['run_tag'] not in cfg['used_run_tags'], 'run tag was already used')
    require(os.environ.get('SKIPPERCAST_FOUR128_RUN_TAG', cfg['run_tag']) == cfg['run_tag'], 'environment run tag differs')
    project = path(cfg['project_root'])
    stage, mission = path(cfg['staging_root']), path(cfg['mission_root'])
    require(stage.is_relative_to(project / 'scratch') and stage != project / 'scratch', 'stage must be under project scratch')
    require(mission.is_relative_to(project / 'outputs') and mission != project / 'outputs', 'mission must be under project outputs')
    require(not mission.exists(), 'preserve existing mission')
    require(not path(project / ('scratch/four128-approved-' + cfg['run_tag'])).exists(), 'preserve used trial scratch')
    require(not stage.exists() if stage_absent else stage.is_dir(), 'staging clean state differs')
    receipts = [path(cfg[name]) for name in ('issuance_receipt', 'assembly_receipt')]
    require(receipts[0] != receipts[1] and all(p.suffix == '.json' and p.is_relative_to(project / 'outputs')
            and not p.is_relative_to(mission) and not p.is_relative_to(stage) for p in receipts),
            'distinct JSON receipts outside mission/staging under project outputs required')
    require(not path(cfg['issuance_receipt']).exists() if stage_absent else True, 'preserve issuance receipt')
    return stage, mission


def live_code(cfg):
    require(path(cfg['code_root']) == ROOT, 'run admission tool from the reviewed code root')
    require(str(Path(cfg['interpreter']).expanduser()) == sys.executable, 'use the configured interpreter')
    require(git('rev-parse', 'HEAD').decode().strip() == cfg['head'], 'executor head differs')
    require(not git('status', '--porcelain').strip(), 'executor checkout is not clean')
    origin = git('rev-parse', cfg['origin']['ref']).decode().strip()
    require(origin == cfg['origin']['head'], 'origin head differs')
    if origin != cfg['head']:
        require(git('merge-base', cfg['head'], origin).decode().strip() == cfg['head'], 'origin is not a descendant')
        changed = set(git('diff', '--name-only', cfg['head'], origin).decode().splitlines())
        allowed = set(cfg['origin']['allowed_test_files'])
        require(changed == allowed and all(p.startswith('tests/') and '..' not in Path(p).parts for p in allowed), 'unreviewed origin delta')
    controls = []
    for rel, expected in cfg['controls'].items():
        raw = read_metadata(ROOT / rel)
        require(digest(raw) == expected, 'current control hash differs: ' + rel)
        controls.append(dict(path=rel, bytes=len(raw), sha256=digest(raw)))
    for rel, expected in [('research/scripts/coastal_four128_prepare.py', cfg['prepare_sha256']),
                          ('src/skippercast/coastal/coordinator/ordered_trial.py', cfg['controller_sha256']),
                          ('src/skippercast/coastal/authenticated_v1/bootstrap.py', cfg['bootstrap_sha256'])]:
        require(digest(read_metadata(ROOT / rel)) == expected, 'reviewed code differs: ' + rel)
    # Run the same source guard as the supervisor before importing project code.
    guard_path = ROOT / 'src/skippercast/coastal/_source_bootstrap.py'
    ns: dict = {'__name__': '_coastal_source_guard'}
    exec(compile(read_metadata(guard_path), str(guard_path), 'exec'), ns)
    ns['guard_project_source'](ROOT / 'src/skippercast')
    return controls, origin


def runtime(cfg):
    os.environ.update(SKIPPERCAST_FOUR128_RUN_TAG=cfg['run_tag'],
        SKIPPERCAST_FOUR128_MISSION_ROOT=str(path(cfg['mission_root'])),
        SKIPPERCAST_FOUR128_CODE_ROOT=str(ROOT), SKIPPERCAST_FOUR128_PYTHON=sys.executable)
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'research/scripts')]
    import coastal_four128_runtime as rt
    require(rt.RUN_TAG == cfg['run_tag'] and rt.N == path(cfg['mission_root']) and rt.W == ROOT, 'runtime imported with different roots/tag')
    return rt


def issue(cfg, config_sha):
    stage, mission = fresh_run(cfg, stage_absent=True)
    controls, origin = live_code(cfg)
    reviewer = cfg['reviewer']
    require(reviewer['profile'] != 'opus-coder' and 'opus' not in reviewer['model'].lower(), 'issuer must differ from harness author')
    rt = runtime(cfg)
    from coastal_four128_resources import budget_limits_bytes
    require(rt.PROJECT == path(cfg['project_root']), 'configured project differs from runtime/prepare project')
    from skippercast.coastal.coordinator.loop import implementation_hashes
    from skippercast.coastal.coordinator.ordered_trial import scope_windows
    from skippercast.coastal.authenticated_v1.profiles import CONTAINED, PARTIAL_SUPPORT as PINNED_PARTIAL
    require(PINNED_PARTIAL == PARTIAL_SUPPORT, 'partial support pin differs from profiles')
    policy = cfg.get('support_policy')
    # The shared scope pin chooses the geometry; a config cannot name its own windows.
    windows, bounds = scope_windows(dict(execution_profile=CONTAINED, window_side=128, window_count=4,
                                         **({'support_policy': policy} if policy else {})))
    require(cfg['windows'] == windows and cfg['bounds'] == bounds, 'ruled windows differ from controller')
    for name in ('selection', 'prior_carry') + (('prescan_review',) if policy else ()):
        pinned(cfg['inputs'][name])
    selection_raw = pinned(cfg['inputs']['selection'])
    selection = json.loads(selection_raw)
    if policy is None:
        require(selection['LARGER_WINDOWS'] == cfg['windows'] and selection['LARGER_BOUNDS'] == cfg['bounds'], 'selection geometry differs')
    else:
        # Final launch stays unavailable until the ONE-open topology receipt meets the
        # --require-holes intent AND an independent different-model review accepts it.
        import coastal_four128_mask_topology as topology
        require(digest(read_metadata(ROOT / TOPOLOGY_SCRIPT)) == selection['script']['sha256'], 'pre-scan script differs from receipt')
        topology.validate_review(json.loads(pinned(cfg['inputs']['prescan_review'])), selection_raw)
        require([w['window'] for w in selection['windows']] == cfg['windows'] and selection['native_bounds'] == cfg['bounds'],
                'selection geometry differs')
    require(re.fullmatch('[0-9a-f]{40}', selection['code_head'])
            and git('merge-base', cfg['head'], selection['code_head']).decode().strip() == selection['code_head'], 'selection ancestor differs')
    require(budget_limits_bytes(pinned(cfg['inputs']['amendment'])) == cfg['limits'], 'live signed budget differs')
    argv = [sys.executable, '-I', '-B', str(ROOT / 'research/scripts/coastal_four128_prepare.py'),
        '--staging-root', str(stage), '--mission-root', str(mission), '--evidence-root', str(path(cfg['evidence_root'])),
        '--cumulative-cap-bytes', str(cfg['retained']['cap']), '--prior-retained-bytes', str(cfg['retained']['prior']),
        '--budget-amendment', str(path(cfg['inputs']['amendment']['path'])), '--prospective-released-bytes']
    if policy:
        argv += ['--support-policy', policy]
    try:
        result = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=300)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ''
        lines = (exc.stdout or '').strip().splitlines()
        last_stdout = lines[-1] if lines else ''
        if stderr:
            print(stderr, file=sys.stderr, end='' if stderr.endswith('\n') else '\n')
        if last_stdout:
            print(last_stdout, file=sys.stderr)
        # assemble() requires the successful issuance schema at issuance_receipt.
        # Keep failure diagnostics beside it, never masquerading as that authority
        # or modifying any partial stage bytes. Exclusive creation preserves prior
        # diagnostics too; failure to save them must not hide the child output.
        failed_receipt = str(cfg['issuance_receipt']) + '.failed.json'
        report = dict(schema='coastal-four128-config-issuance-failure-v1',
            status='ISSUANCE_FAILED_STAGE_PRESERVED', config_sha256=config_sha,
            head=cfg['head'], run_tag=cfg['run_tag'], checked_at=iso(time.time()),
            staging_root=str(stage), mission_root=str(mission), execution_authorized=False,
            prepare=dict(returncode=exc.returncode, stderr=stderr, last_stdout_line=last_stdout))
        try:
            write_new(failed_receipt, encoded(report))
        except (OSError, ValueError) as receipt_error:
            print('Failed issuance receipt not written: ' + str(receipt_error), file=sys.stderr)
        raise SystemExit(1) from exc
    package = json.loads(result.stdout.strip().splitlines()[-1])
    index, grant, amendment = prepare_inputs(cfg, package)
    require((index['code_sha'], index['deps_sha']) == implementation_hashes(ROOT), 'current implementation identity differs')
    now = time.time()
    docs = evidence_summary(cfg, now)
    observation = dict(checked_at=iso(now), valid_until=iso(now + 86400), reviewer=reviewer, task=cfg['task'], origin_ref_head=origin,
        procedure=dict(script=str(Path(__file__).resolve()), script_sha256=digest(read_metadata(__file__)), interpreter=sys.executable))
    outputs = render(cfg, observation=observation, index=index, grant=grant, amendment=amendment, package=package, controls=controls, docs=docs)
    rt.validate_runtime_review(json.loads(outputs['live-index.json']), json.loads(outputs['independent-runtime-review.json']), now=time.time())
    fresh_run(cfg, stage_absent=False)
    live_code(cfg)
    for name, raw in outputs.items():
        write_new(stage / 'metadata' / name, raw)
    report = dict(schema='coastal-four128-config-issuance-v1', status='ISSUED_REVIEW_REQUIRED', config_sha256=config_sha,
        head=cfg['head'], run_tag=cfg['run_tag'], checked_at=observation['checked_at'],
        files=[reference(name, raw, json.loads(raw)['schema']) for name, raw in outputs.items()],
        source_reads=0, network_requests=0, units_started=0)
    write_new(cfg['issuance_receipt'], encoded(report))
    return report


def assemble(cfg, config_sha):
    stage, mission = fresh_run(cfg, stage_absent=False)
    controls, _ = live_code(cfg)
    target = path(cfg['assembly_receipt'])
    require(not target.exists(), 'preserve assembly receipt')
    issuance = json.loads(read_metadata(cfg['issuance_receipt']))
    require(issuance['schema'] == 'coastal-four128-config-issuance-v1' and issuance['config_sha256'] == config_sha
            and issuance['head'] == cfg['head'] and issuance['run_tag'] == cfg['run_tag'], 'issuance config/head differs')
    for item in issuance['files']:
        relative_metadata(stage, item)
    rt = runtime(cfg)
    from skippercast.coastal.handoff.common import load
    from skippercast.coastal.receipts import digest as receipt_digest
    from skippercast.coastal.output_writer import ManagedOutputs
    d = json.loads(read_metadata(stage / 'metadata/live-index.json'))
    review = load(stage, d['independent_runtime_review'], contract='coastal-four128-independent-prelaunch-v1')
    now = time.time()
    rt.validate_runtime_review(d, review, now=now)
    require(epoch(review['valid_until']) > now + 4500, 'document 5 expires within 75 minutes')
    require(d['runtime_controls'] == controls, 'assembly controls differ from issuance')
    grant = load(stage, d['grant'], contract='coastal-authenticated-policy-v1')
    require(grant['output_root'] == str(mission) and grant['execution_authorized'] is True, 'grant mission/authority differs')
    science = load(stage, d['independent_preflight'], contract=d['independent_preflight']['contract'])
    hist_raw = pinned(cfg['inputs']['historical_context'])
    hist = json.loads(hist_raw)
    require(hist['source'] == grant['source'] and hist['metadata_sha256'] == science['expected_metadata_sha256'], 'historical context differs')
    require(hist['mode'] == 'real_continuation' and hist.get('rehearsal_synthetic') is False
            and hist['real_source_sha256'] == grant['source']['sha256'], 'context source/mode differs')
    context = copy.deepcopy(hist)
    context.update(root=str(mission), execution_root=str(mission / 'execution'), mapping_root=str(mission / 'mapping-execution'),
        implementation_root=str(ROOT), slice=rt.SLICE, unit_suffix='-' + cfg['run_tag'] + '.service',
        clock_status='no clock created; clean-state four128 run (run tag ' + cfg['run_tag'] + '), outer clock written by run()',
        prior_active_seconds=0, remaining_active_seconds=3600, original_source_reads=0, windows=copy.deepcopy(grant['window_set']),
        assembled_from=dict(staging_root=str(stage), historical_context=str(path(cfg['inputs']['historical_context']['path'])),
            historical_context_sha256=digest(hist_raw), assembled_at=iso(now), assembler_sha256=digest(read_metadata(__file__)),
            historical_windows=hist['windows'], window_scope_change=cfg['window_scope_change'], config_sha256=config_sha))
    payloads = {}
    for p in sorted((stage / 'metadata').iterdir()):
        require(p.suffix == '.json', 'unexpected non-JSON staging entry')
        payloads['execution/metadata/' + p.name] = read_metadata(p)
    payloads['control/release-context.json'] = encoded(context)
    mission.mkdir(parents=True, exist_ok=False)
    manager = ManagedOutputs.create(mission, grant, receipt_digest(grant))
    for name, raw in payloads.items():
        require(manager.write_bytes(name, raw, role='control', max_bytes=len(raw), intent='initial:' + name), 'managed write refused')
    (mission / 'mapping-execution').mkdir(exist_ok=False)
    audit = manager.audit()
    require(not audit['unmanaged_control_bytes'], 'unmanaged controls after assembly')
    pre = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'research/scripts/coastal_four128_runtime.py'), 'preflight'],
                         capture_output=True, text=True, timeout=300)
    report = dict(schema='coastal-four128-config-assembly-v1', config_sha256=config_sha,
        status='ASSEMBLED_PREFLIGHT_OK_REVIEW_REQUIRED' if pre.returncode == 0 else 'ASSEMBLED_PREFLIGHT_FAILED',
        head=cfg['head'], run_tag=cfg['run_tag'], mission_root=str(mission), managed_audit=audit,
        preflight=dict(returncode=pre.returncode, stdout=pre.stdout[-4000:], stderr=pre.stderr[-4000:]),
        files=[dict(path=name, bytes=len(raw), sha256=digest(raw)) for name, raw in payloads.items()],
        source_reads=0, network_requests=0, units_started=0)
    write_new(target, encoded(report))
    require(pre.returncode == 0, 'assembly runtime preflight failed; preserve root and receipt')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['replay', 'issue', 'assemble'])
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--config-sha256', help='independently reviewed live config pin (required for issue/assemble)')
    args = ap.parse_args()
    cfg, config_sha = config_file(args.config)
    if args.action == 'replay':
        require(args.output is not None, 'replay output required')
        report = replay(cfg, args.output)
    else:
        require(args.config_sha256 == config_sha, 'exact reviewed live config SHA256 required')
        require(args.output is None, 'live outputs are fixed by reviewed config')
        report = issue(cfg, config_sha) if args.action == 'issue' else assemble(cfg, config_sha)
    report['config_sha256'] = config_sha
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
