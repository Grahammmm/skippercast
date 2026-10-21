"""Rev4 schema source and synthetic fixture factory; no product or live inputs.

Run this file to regenerate the committed schemas/config/fixtures/references.
Tests compare generated schemas to committed bytes. Shared helpers stay script-local.
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / 'skills/coast-campaign-shared'
SCRIPTS = SHARED / 'scripts'


def load_helper(name):
    # Script modules use sibling imports when invoked via CLI. Tests load explicitly,
    # without making skills a product package or modifying sys.path.
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


refs = load_helper('coast_refs')
load_helper('coast_sample')
load_helper('coast_native')


def obj(**properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def arr(items, **kw):
    return dict(type='array', items=items, **kw)


def enum(*values):
    return dict(enum=list(values))


def nullable(shape):
    return dict(anyOf=[shape, dict(type='null')])


S = dict(type='string', minLength=1)
H = dict(type='string', pattern='^[0-9a-f]{64}$')
I = dict(type='integer', minimum=0)
N = dict(type='number', minimum=0)
B = dict(type='boolean')
NULL = dict(type='null')
REF = obj(root_id=dict(type='string', pattern=refs.ROOT_ID.pattern.replace('\\Z', '$')),
          path=dict(type='string', minLength=1, pattern=r'^(?!/)(?!.*\\)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)[^\u0000-\u001f]+$'),
          sha256=H, bytes=I)
REFS = arr(REF)
STRINGS = arr(S, uniqueItems=True)
IDENTITY = dict(campaign_segment_id=dict(type='string', pattern='^[A-Za-z0-9_-]+$'),
                coordinator_segment_id=dict(type='string', pattern='^seg:3310:-?[0-9]+:-?[0-9]+:5000$'),
                plan_id=dict(type='string', pattern='^[A-Za-z0-9_-]+$'), plan_sha256=H)
HEADER = dict(created_utc=dict(type='string', format='date-time', pattern='Z$'), author_profile=S,
              author_model=S, card_id=dict(type='string', pattern='^t_[0-9a-f]{8}$'),
              code_commit=dict(type='string', pattern='^[0-9a-f]{40}$'),
              skill_commit=dict(type='string', pattern='^[0-9a-f]{40}$'))
REVIEW = dict(review_round=dict(type='integer', minimum=1), attempt=dict(type='integer', minimum=1), context=REF)
FINDING = obj(window_key=nullable(S), severity=enum('must', 'should', 'info'), code=S, detail=S, evidence=REFS)
OBS_EXPECTED = obj(root_id=REF['properties']['root_id'], path=REF['properties']['path'], expected_sha256=nullable(H), expected_bytes=nullable(I))
OBSERVED = obj(status=enum('present', 'missing', 'unreadable'), observed_sha256=nullable(H), observed_bytes=nullable(I))
PROBLEM = obj(code=S, path=S, expected=nullable(S), observed=nullable(S))
POPULATION = obj(map_done=STRINGS, eligible=STRINGS, flagged=STRINGS, held=STRINGS, unfinished=STRINGS, unavailable=STRINGS)
SAMPLE = obj(method_version=enum('coast-sample-v1'), seed=H, target=I, size=I, map_done=STRINGS, eligible=STRINGS, selected=STRINGS)
MEASUREMENT = dict(oneOf=[obj(status=enum('measured'), value=dict(type='number'), reason=NULL, inputs=REFS, method_version=S),
                              obj(status=enum('not_applicable', 'unavailable'), value=NULL, reason=S, inputs=REFS, method_version=S)])
STATES = ('map_done', 'held', 'failed_terminal', 'failed_uncertain', 'stale', 'cancelled', 'unfinished')
USAGE = obj(requests=I, bytes=I, wall_s=N)
BUDGET = obj(requests=enum(0), bytes=I, wall_s=N, cells=I)
STAGE = obj(stage=enum('acquire', 'qualify', 'map', 'render'), job_id=S, state=S,
            input_manifest=REF, result=nullable(REF), products=REFS, holds=STRINGS, missing_reason=nullable(S))
WINDOW = obj(window_key=S, window_dir=H, source_id=S, grid_sha256=H, idx=I,
             pixel_window=obj(col_off=I, row_off=I, width=dict(type='integer', minimum=1), height=dict(type='integer', minimum=1)),
             owner_segment_id=S, footprint=arr(dict(type='number'), minItems=4, maxItems=4), overlapping_segment_ids=STRINGS)
METRICS = obj(tp=I, fp=I, fn=I, tn=I, excluded=STRINGS, population_definition=S)


def schema(name, payload, *, plan=True, review=False):
    properties = dict(schema=enum('coast-' + name + '-v1'), **HEADER)
    if plan:
        properties.update(IDENTITY)
    if review:
        properties.update(REVIEW)
    properties.update(payload)
    return dict({'$schema': 'https://json-schema.org/draft/2020-12/schema',
                 '$id': 'urn:skippercast:coast-' + name + '-v1'}, **obj(**properties))


def schemas():
    result = {}
    def add(name, payload, **kw):
        result[name] = schema(name, payload, **kw)
    pixel = arr(I, minItems=4, maxItems=4)
    definition = obj(source_sha256=H, raster_crs=S, affine_transform=arr(dict(type='number'), minItems=6, maxItems=6),
                     width=dict(type='integer', minimum=1), height=dict(type='integer', minimum=1),
                     tile_width=dict(type='integer', minimum=1), tile_height=dict(type='integer', minimum=1),
                     tiling_version=enum('single-selected-v1'), pixel_window=pixel)
    execution_grid = obj(source_id=S, grid_sha256=H, definition=definition, cols=enum(1), rows=enum(1), total=enum(1))
    admission_window = copy.deepcopy(WINDOW)
    admission_window['properties']['pixel_window'] = pixel
    add('campaign', dict(campaign_segment_id=IDENTITY['campaign_segment_id'], bbox_crs84=arr(dict(type='number'), minItems=4, maxItems=4),
                         lane=S, source_inventory=STRINGS, intended_windows=STRINGS), plan=False)
    add('discovery-evidence', dict(catalog=REF, evidence=REFS), plan=False)
    add('admission', dict(campaign=REF, plan_file=REF, segment_record=REF, catalog=REF, discovery=REF,
        sources=arr(obj(source_id=S, raw_provenance=REFS, retained_inputs=REFS, hot_cache=REFS, rights=S, datum=S, reader=S)),
        grids=arr(execution_grid),
        windows=arr(admission_window, minItems=1), budgets=BUDGET, usage_before=USAGE, usage_delta=USAGE,
        dry_run=REF, would_enqueue_count=I, selected_source_ids=STRINGS, held_source_ids=STRINGS,
        preconditions=obj(exclusive_writer=enum(True), attested_by=S), holds=STRINGS, replacement_plan_of=nullable(REF)))
    add('enqueue-receipt', dict(admission=REF, bridge=REF, code_sha256=H, deps_sha256=H,
        store_path=enum('var/coastal/coordinator.sqlite'), intent=REF,
        jobs=arr(obj(window_key=S, source_id=S, root_job_id=S, input_manifest=REF, new_row=B), minItems=1)))
    cells = obj(count=I, min=nullable(dict(type='number')), max=nullable(dict(type='number')),
                mean=nullable(dict(type='number')), p80=nullable(dict(type='number')), unknown=STRINGS, absent=STRINGS, source=REF)
    add('run-summary', dict(admission=REF, enqueue=REF, bridge=REF, sequence=dict(type='integer', minimum=1), continuation_of=nullable(REF),
        stop_reason=enum('terminal', 'deadline', 'max_ticks', 'not_claimable', 'preflight_refused', 'integrity_error', 'failed_uncertain'),
        reasons=STRINGS, windows=arr(obj(window_key=S, state=enum(*STATES), stages=arr(STAGE), missing_stage_reasons=STRINGS)),
        partition=obj(**{state: STRINGS for state in STATES}), cells=cells, ticks_used=I, max_ticks=I, until_epoch=N,
        started_utc=HEADER['created_utc'], finished_utc=HEADER['created_utc'], wall_s=N, usage=USAGE, store_snapshot=REF))
    context = dict(review_round=dict(type='integer', minimum=1), attempt=dict(type='integer', minimum=1),
        identity_provenance=REF, run_author_model=S, run_author_provenance=REF, run_card_id=S,
        root_ids=STRINGS, posted_hashes=REF, routing=REF, thresholds=REF, prompts=REFS,
        supersedes=nullable(REF), correction_verdict=nullable(REF), ledger_snapshot=nullable(REF))
    context_normal = dict(context, mode=enum('normal'), admission=REF, run=REF, bridge=REF, enqueue=REF, observations=arr(PROBLEM, maxItems=0))
    context_error = dict(context, mode=enum('diagnostic'), admission=nullable(REF), run=nullable(REF), bridge=nullable(REF), enqueue=nullable(REF), observations=arr(PROBLEM, minItems=1))
    result['review-context'] = dict(oneOf=[schema('review-context', context_normal), schema('review-context', context_error)],
        **{'$schema': 'https://json-schema.org/draft/2020-12/schema'})
    add('tier1-screen', dict(run=REF, windows=arr(obj(window_key=S, stage_state=enum(*STATES), status=enum('pass', 'flag', 'held', 'unavailable'),
        producer_fields=arr(obj(field_path=S, source=REF, value=nullable(dict(type=['string', 'number', 'boolean'])))),
        measurements=obj(**{key: MEASUREMENT for key in ('valid_fraction', 'depth_median_m', 'depth_p99_m', 'nodata_fraction', 'edge_valid_fraction', 'slope_p99_deg', 'neighbour_delta', 'catalog_range')}),
        text_response=nullable(REF), vision_response=nullable(REF), text_verdict=S, vision_verdict=S, thumbnail=nullable(REF), flags=arr(FINDING))),
        counts=obj(pass_count=I, flag=I, held=I, unavailable=I), telemetry=obj(wall_s=N, tokens=nullable(I), endpoint=S, model=S, prompt_sha256=H, slots=I)), review=True)
    add('tier2-check', dict(mode=enum('rehash', 'budgets', 'neighbours'), integrity_ok=B, verified_inputs=REFS,
        observations=arr(PROBLEM), findings=arr(FINDING), counts=obj(must=I, should=I, info=I), wall_s=N), review=True)
    packet = dict(admission=nullable(REF), run=nullable(REF), tier1=nullable(REF),
        checks=obj(rehash=REF, budgets=REF, neighbours=REF), sources=STRINGS, lane=S, run_author_model=S,
        run_author_provenance=REF, flags=arr(FINDING), routing=REF, reviewer_requirement=S, author_minutes=nullable(N))
    result['review-packet'] = dict(oneOf=[schema('review-packet', dict(packet, integrity_ok=enum(True), population=POPULATION, sample=SAMPLE), review=True),
        schema('review-packet', dict(packet, integrity_ok=enum(False), population=NULL, sample=NULL), review=True)],
        **{'$schema': 'https://json-schema.org/draft/2020-12/schema'})
    add('open-report', dict(expected_packet=OBS_EXPECTED, observed_packet=OBSERVED, integrity_ok=B,
        problems=arr(PROBLEM), verified_refs=REFS, measurements_trusted=B,
        reviewer_model=S, reviewer_provenance=REF, evidence_snapshots=REFS), review=True)
    verdict = dict(open_report=REF, reviewer_model=S, reviewer_provenance=REF, minutes=N, must_fix=arr(FINDING),
        decisions=arr(obj(window_key=S, defect=nullable(B), accepted_cause=nullable(S), detail=S, evidence=REFS)),
        windows_examined=STRINGS, next_tile_card_authorized=B, expected_packet=OBS_EXPECTED, observed_packet=OBSERVED)
    normal = dict(verdict, evidence_status=enum('valid'), verdict=enum('accept', 'must_fix', 'hold'), packet=REF,
        population=POPULATION, tier1_confusion=METRICS, tier2_packet_accuracy=nullable(N), metrics_unavailable_reason=nullable(S),
        validation_scope=enum('full_graph'))
    error = dict(verdict, evidence_status=enum('invalid'), verdict=enum('must_fix'), packet=NULL,
        population=NULL, tier1_confusion=NULL, tier2_packet_accuracy=NULL,
        metrics_unavailable_reason=enum('integrity_failure'), validation_scope=enum('identity_snapshot'))
    error.update(windows_examined=arr(S, maxItems=0), decisions=arr(S, maxItems=0), next_tile_card_authorized=enum(False), must_fix=arr(FINDING, minItems=1))
    result['review-verdict'] = dict(oneOf=[schema('review-verdict', normal, review=True), schema('review-verdict', error, review=True)],
        **{'$schema': 'https://json-schema.org/draft/2020-12/schema'})
    ledger = dict(seq=dict(type='integer', minimum=1), prev_row_sha256=H, ledger_role=enum('segment', 'campaign'), segment_row_sha256=nullable(H))
    normal_row = dict(ledger, kind=enum('verdict'), review_round=I, attempt=I, verdict=enum('accept', 'must_fix', 'hold'),
        verdict_file=REF, context=REF, packet=REF, open_report=REF, validation_scope=enum('full_graph'))
    bad_row = dict(normal_row, verdict=enum('must_fix'), packet=NULL, validation_scope=enum('identity_snapshot'))
    archived = dict(ledger, kind=enum('archived'), close_id=S, manifest=REF, inventory=REF,
        previous_segment_tip_sha256=H, previous_campaign_tip_sha256=H)
    result['segment-ledger'] = dict(oneOf=[schema('segment-ledger', normal_row), schema('segment-ledger', bad_row), schema('segment-ledger', archived)],
        **{'$schema': 'https://json-schema.org/draft/2020-12/schema'})
    add('archive-manifest', dict(campaign_segment_id=IDENTITY['campaign_segment_id'], close_id=S,
        inventory=REF, selected_verdicts=REFS, original_segment_tip_sha256=H, original_campaign_tip_sha256=H,
        files=arr(obj(source_ref=REF, retained_ref=REF)), lineage_snapshot=REF,
        cache_candidates=arr(obj(source_ref=REF, device=I, inode=I, size=I, mtime_ns=I))), plan=False)
    add('release-list', dict(campaign_segment_id=IDENTITY['campaign_segment_id'], close_id=S,
        manifest=REF, segment_ledger_snapshot=REF, campaign_ledger_snapshot=REF, inventory=REF,
        segment_tip_sha256=H, campaign_tip_sha256=H,
        candidates=arr(obj(source_ref=REF, raw_or_retained=REF, device=I, inode=I, size=I, mtime_ns=I)),
        validation_observations=arr(PROBLEM), total_files=I, total_bytes=I), plan=False)
    add('review-routing', dict(version=dict(type='integer', minimum=1), policy_status=enum('operator_required'),
        require_actual_model=enum(True), require_runtime_provenance=enum(True), allow_profile_fallback=enum(False),
        disallowed_family_pairs=arr(arr(S, minItems=2, maxItems=2)),
        qualified_reviewers=arr(obj(actual_model=S, family=S, provenance=REF)),
        allowed_pairs=arr(obj(author_model=S, reviewer_model=S)), history=arr(obj(version=I, reason=S))), plan=False)
    return result


THRESHOLDS = dict(version=1, edge_step_should_m=2, edge_step_must_m=10, mask_continuity_min=0.8,
                  tier1_valid_fraction_min=0.5, tier1_edge_valid_min=0.5, tier1_slope_p99_max_deg=60,
                  history=[dict(version=1, reason='Rev4 defaults; changes require measured review, not per-run tuning')])


def materialize(destination):
    """Complete tiny fixture graph, all hashes real, rooted only under destination.

    Admission edges pin real producer-native JSON and a complete actual lattice.
    Other downstream synthetic leaves are not evidence of mapping or execution.
    """
    destination = Path(destination)
    queue = destination / 'queue'
    queue.mkdir(parents=True, exist_ok=True)
    def put(name, value):
        raw = value if isinstance(value, bytes) else refs.canonical(value)
        path = queue / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return dict(root_id='queue:synthetic', path=name, sha256=refs.sha256(raw), bytes=len(raw))
    leaf = put('provenance/synthetic.txt', b'Synthetic offline evidence only. Not a scientific acceptance.\n')
    h = leaf['sha256']
    common = dict(created_utc='2026-10-21T00:00:00Z', author_profile='fixture', author_model='synthetic-author', card_id='t_366d24e2', code_commit='1'*40, skill_commit='2'*40)
    identity = dict(campaign_segment_id='synthetic', coordinator_segment_id='seg:3310:-5000:0:5000', plan_id='plan01', plan_sha256=h)
    def base(name, *, plan=True):
        return dict(schema='coast-' + name + '-v1', **common, **(identity if plan else {}))
    def save(name, value):
        instances[name] = value
        return put('valid/' + name + '.json', value)
    instances = {}
    save('campaign', dict(base('campaign', plan=False), campaign_segment_id='synthetic', bbox_crs84=[-120.60,34.45,-120.59,34.46],
                         lane='offline-synthetic', source_inventory=['source/a'], intended_windows=[]))
    save('discovery-evidence', dict(base('discovery-evidence', plan=False), catalog=leaf, evidence=[leaf]))
    routing = dict(base('review-routing', plan=False), version=1, policy_status='operator_required', require_actual_model=True,
        require_runtime_provenance=True, allow_profile_fallback=False, disallowed_family_pairs=[], qualified_reviewers=[], allowed_pairs=[],
        history=[dict(version=1, reason='No operational routing granted; operator must supply qualified actual-model policy')])
    rr = save('review-routing', routing)
    window = dict(window_key='source/a#' + h + '#0', window_dir=sys.modules['coast_sample'].window_dir('source/a#' + h + '#0'), source_id='source/a', grid_sha256=h, idx=0,
        pixel_window=dict(col_off=0, row_off=0, width=1, height=1), owner_segment_id=identity['coordinator_segment_id'],
        footprint=[-121,35,-120,36], overlapping_segment_ids=[identity['coordinator_segment_id']])
    key = window['window_key']
    usage = dict(requests=0, bytes=0, wall_s=0)
    admission = dict(base('admission'), campaign=leaf, plan_file=leaf, segment_record=leaf, catalog=leaf, discovery=leaf,
        sources=[dict(source_id='source/a', raw_provenance=[leaf], retained_inputs=[leaf], hot_cache=[leaf], rights='synthetic', datum='synthetic', reader='synthetic')],
        grids=[dict(source_id='source/a', source_sha256=h, grid_sha256=h, raster_crs='EPSG:3310', affine_transform=[1,0,0,0,-1,0], width=1,height=1,tile_width=1,tile_height=1,tiling_version='fixture-v1',cols=1,rows=1,total=1)],
        windows=[window], budgets=dict(requests=0,bytes=1024,wall_s=1,cells=1), usage_before=usage, usage_delta=usage,
        dry_run=leaf, would_enqueue_count=1, selected_source_ids=['source/a'], held_source_ids=[], preconditions=[], holds=[], replacement_plan_of=None)
    from tests.coast_real_admission_factory import populate_admission
    admission, bindings = populate_admission(admission, {'queue:synthetic':str(queue.absolute())}, destination)
    identity.update(coordinator_segment_id=admission['coordinator_segment_id'], plan_sha256=admission['plan_sha256'])
    key = admission['windows'][0]['window_key']
    # Normal fixtures now pin real producer-native JSON, not opaque text leaves.
    instances['campaign'] = refs.loads((queue/admission['campaign']['path']).read_bytes())
    put('valid/campaign.json', instances['campaign'])
    instances['discovery-evidence'] = refs.loads((queue/admission['discovery']['path']).read_bytes())
    put('valid/discovery-evidence.json', instances['discovery-evidence'])
    ar = save('admission', admission)
    en = save('enqueue-receipt', dict(base('enqueue-receipt'), admission=ar, bridge=leaf, code_sha256=h, deps_sha256=h,
        store_path='var/coastal/coordinator.sqlite', intent=leaf, jobs=[dict(window_key=key,source_id='source/a',root_job_id='synthetic-root',input_manifest=leaf,new_row=True)]))
    run = save('run-summary', dict(base('run-summary'), admission=ar, enqueue=en, bridge=leaf, sequence=1,continuation_of=None,stop_reason='terminal', reasons=[],
        windows=[dict(window_key=key,state='held',stages=[],missing_stage_reasons=['synthetic held input'])],
        partition={state: ([key] if state == 'held' else []) for state in STATES},
        cells=dict(count=0,min=None,max=None,mean=None,p80=None,unknown=['held'],absent=['depth_m'],source=leaf),
        ticks_used=0,max_ticks=1,until_epoch=1,started_utc=common['created_utc'],finished_utc=common['created_utc'],wall_s=0,usage=usage,store_snapshot=leaf))
    cr = save('review-context', dict(base('review-context'), review_round=1,attempt=1,identity_provenance=leaf, run_author_model='synthetic-author',run_author_provenance=leaf,
        run_card_id='t_366d24e2',root_ids=['queue:synthetic'],posted_hashes=leaf,routing=rr,thresholds=leaf,prompts=[leaf],supersedes=None,correction_verdict=None,ledger_snapshot=None,
        mode='normal',admission=ar,run=run,bridge=leaf,enqueue=en,observations=[]))
    review = dict(review_round=1,attempt=1,context=cr)
    t1 = save('tier1-screen', dict(base('tier1-screen'), **review,run=run,
        windows=[dict(window_key=key,stage_state='held',status='held',producer_fields=[],
            measurements={name:dict(status='not_applicable',value=None,reason='pipeline_not_mapped',inputs=[],method_version='fixture-v1') for name in ('valid_fraction','depth_median_m','depth_p99_m','nodata_fraction','edge_valid_fraction','slope_p99_deg','neighbour_delta','catalog_range')},
            text_response=None,vision_response=None,text_verdict='not_mapped',vision_verdict='not_mapped',thumbnail=None,flags=[])],
        counts=dict(pass_count=0,flag=0,held=1,unavailable=0),telemetry=dict(wall_s=0,tokens=None,endpoint='offline-fixture',model='synthetic',prompt_sha256=h,slots=0)))
    check = dict(base('tier2-check'), **review, mode='rehash',integrity_ok=True,verified_inputs=[t1],observations=[],findings=[],counts=dict(must=0,should=0,info=0),wall_s=0)
    t2 = save('tier2-check', check)
    pop = dict(map_done=[],eligible=[],flagged=[key],held=[key],unfinished=[],unavailable=[])
    sample = sys.modules['coast_sample'].sample([],[],plan_sha256=identity['plan_sha256'],bridge_sha256=h)
    packet = save('review-packet', dict(base('review-packet'), **review,admission=ar,run=run,tier1=t1,checks=dict(rehash=t2,budgets=t2,neighbours=t2),sources=['source/a'],lane='synthetic',
        run_author_model='synthetic-author',run_author_provenance=leaf,flags=[],routing=rr,reviewer_requirement='independent qualified actual-model',author_minutes=None,
        integrity_ok=True,population=pop,sample=sample))
    expected = dict(root_id=packet['root_id'],path=packet['path'],expected_sha256=packet['sha256'],expected_bytes=packet['bytes'])
    observed = dict(status='present',observed_sha256=packet['sha256'],observed_bytes=packet['bytes'])
    report = save('open-report', dict(base('open-report'), **review,expected_packet=expected,observed_packet=observed,integrity_ok=True,problems=[],verified_refs=[packet],
        measurements_trusted=True,reviewer_model='synthetic-reviewer',reviewer_provenance=leaf,evidence_snapshots=[]))
    verdict = save('review-verdict', dict(base('review-verdict'), **review,open_report=report,reviewer_model='synthetic-reviewer',reviewer_provenance=leaf,minutes=0,must_fix=[],windows_examined=[],
        decisions=[],
        next_tile_card_authorized=False,expected_packet=expected,observed_packet=observed,evidence_status='valid',verdict='hold',packet=packet,population=pop,
        tier1_confusion=dict(tp=0,fp=0,fn=0,tn=0,excluded=[key],population_definition='synthetic held-only; no scientific decisions'),tier2_packet_accuracy=None,
        metrics_unavailable_reason='synthetic_no_semantic_review',validation_scope='full_graph'))
    ledger = save('segment-ledger', dict(base('segment-ledger'),seq=1,prev_row_sha256='0'*64,ledger_role='segment',segment_row_sha256=None,
        kind='verdict',review_round=1,attempt=1,verdict='hold',verdict_file=verdict,context=cr,packet=packet,open_report=report,validation_scope='full_graph'))
    archive_root = destination/'archive'
    archive_root.mkdir(exist_ok=True)
    raw = (queue/leaf['path']).read_bytes()
    (archive_root/'synthetic.txt').write_bytes(raw)
    retained = dict(root_id='archive:synthetic:close01',path='synthetic.txt',sha256=refs.sha256(raw),bytes=len(raw))
    manifest = save('archive-manifest', dict(base('archive-manifest',plan=False),campaign_segment_id='synthetic',close_id='close01',inventory=leaf,selected_verdicts=[verdict],
        original_segment_tip_sha256=ledger['sha256'],original_campaign_tip_sha256='0'*64,files=[dict(source_ref=leaf,retained_ref=retained)],lineage_snapshot=leaf,cache_candidates=[]))
    save('release-list', dict(base('release-list',plan=False),campaign_segment_id='synthetic',close_id='close01',manifest=manifest,
        segment_ledger_snapshot=ledger,campaign_ledger_snapshot=ledger,inventory=leaf,segment_tip_sha256=ledger['sha256'],campaign_tip_sha256=ledger['sha256'],
        candidates=[],validation_observations=[],total_files=0,total_bytes=0))
    for name, value in instances.items():
        invalid = copy.deepcopy(value)
        invalid['self_sha256'] = h
        put('invalid/' + name + '.json', invalid)
    # Identity-only corrective graph: expected run has deliberately impossible hash.
    bad_context = copy.deepcopy(instances['review-context'])
    bad_context['run']['sha256'] = 'f'*64
    bc = put('diagnostic/context.json', bad_context)
    bad_report = copy.deepcopy(instances['open-report'])
    bad_report.update(context=bc,integrity_ok=False,measurements_trusted=False,verified_refs=[],
        problems=[dict(code='HASH_MISMATCH',path='run',expected='posted run hash',observed='changed run bytes')])
    br = put('diagnostic/open-report.json', bad_report)
    bad_verdict = copy.deepcopy(instances['review-verdict'])
    bad_verdict.update(context=bc,open_report=br,evidence_status='invalid',verdict='must_fix',packet=None,population=None,
        tier1_confusion=None,tier2_packet_accuracy=None,metrics_unavailable_reason='integrity_failure',validation_scope='identity_snapshot',
        must_fix=[dict(window_key=None,severity='must',code='HASH_MISMATCH',detail='Synthetic corrupted run; corrective only',evidence=[])])
    put('diagnostic/verdict.json',bad_verdict)
    bindings['archive:synthetic:close01'] = str(archive_root.absolute())
    return instances, bindings


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, help='Optional admitted rev4 source; exact hash is checked before copying excerpts')
    args = parser.parse_args()
    for name, value in schemas().items():
        path = SHARED/'schemas'/f'coast-{name}-v1.schema.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(refs.canonical(value))
    (SHARED/'config').mkdir(parents=True,exist_ok=True)
    (SHARED/'config/tier2-thresholds.json').write_bytes(refs.canonical(THRESHOLDS))
    fixtures, _ = materialize(ROOT/'tests/fixtures/coast')
    routing = dict(fixtures['review-routing'], author_profile='opus-coder', author_model='gpt-6.1-sol', version=4,
        code_commit='228b1bcd33398675d6ebc206ddc8aa24784a6796', skill_commit='228b1bcd33398675d6ebc206ddc8aa24784a6796',
        history=[dict(version=4, reason='Rev4 requires operator-supplied qualified actual-model pairs and provenance; no operational route is granted by this template')])
    (SHARED/'config/review-routing.json').write_bytes(refs.canonical(routing))
    threshold_schema = dict({'$schema':'https://json-schema.org/draft/2020-12/schema'}, **obj(version=dict(type='integer',minimum=1),
        edge_step_should_m=N, edge_step_must_m=N, mask_continuity_min=dict(type='number',minimum=0,maximum=1),
        tier1_valid_fraction_min=dict(type='number',minimum=0,maximum=1), tier1_edge_valid_min=dict(type='number',minimum=0,maximum=1),
        tier1_slope_p99_max_deg=dict(type='number',minimum=0,maximum=90), history=arr(obj(version=I,reason=S),minItems=1)))
    (SHARED/'config/tier2-thresholds.schema.json').write_bytes(refs.canonical(threshold_schema))
    if args.design:
        raw = args.design.read_bytes()
        if refs.sha256(raw) != 'c8fabf7e2e1451af762ee9c9e52c32cab5831877e34cae3f7a5a98b00bb6d433':
            raise ValueError('unadmitted design bytes')
        text = raw.decode('utf-8')
        directory = SHARED/'references'
        directory.mkdir(exist_ok=True)
        layout = text[text.index('## 1. Identity'):text.index('## 3. Immutable')]
        # Preserve contracts verbatim; the layout's one host-specific interpreter
        # spelling is made portable to satisfy the repository privacy scan.
        import re
        layout = re.sub(r'/home/[^/\s]+/repos/skippercast/\.venv/bin/python', '$HOME/repos/skippercast/.venv/bin/python', layout)
        (directory/'directory-layout.md').write_text(layout.rstrip('\n')+'\n',encoding='utf-8')
        contracts = text[text.index('## 3. Immutable'):text.index('## 7. Ten skill')]
        (directory/'contracts.md').write_text(contracts.rstrip('\n')+'\n',encoding='utf-8')
    print(f'Generated {len(fixtures)} strict schemas and valid/invalid fixture pairs (synthetic only).')


if __name__ == '__main__':
    main()
