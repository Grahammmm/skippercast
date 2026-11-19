"""Explicit, hash-bound PC9v1 -> shared-v2 receipt adapter (offline; not product code).

PC9 (`skippercast.coastal.coordinator.bridge_run`) keeps writing its native
`coast-enqueue-receipt-v1` / `coast-run-summary-v1` bytes unchanged. Shared
campaign tooling consumes `coast-enqueue-receipt-v2` / `coast-run-summary-v2`,
which this adapter derives deterministically from those original bytes:

* every v2 record pins the original v1 receipt by Ref (`legacy_enqueue` /
  `legacy_run`); validators recompute the conversion and require equality;
* a multi-window run keeps ONE `window_cells` record per window, each with its
  own producer Ref (the map stage's `coastal-terrain-summary-v1` cells output),
  producer statistics copied verbatim and explicit unknowns. Nothing is
  aggregated, averaged or selected across windows;
* PC9's embedded `store_status` is carried only as `store_status_evidence`
  with kind `legacy_embedded`, bound to the original run receipt. It is NOT an
  independently produced or store-consistent snapshot. In v1 it is the global
  queue dump; native v3 (`coast-run-summary-v3`, SCA-358) embeds run-scoped
  counts (`coastal-coordinator-scope-v1`) there instead, so the digest binds
  exactly what the native receipt carries and nothing is synthesized;
* `sequence` stays zero-based exactly as PC9 run-00 / continuations.
"""
from coast_refs import REF_KEYS, object_digest

ENQUEUE_V1 = 'coast-enqueue-receipt-v1'
ENQUEUE_V2 = 'coast-enqueue-receipt-v2'
RUN_V1 = 'coast-run-summary-v1'
RUN_V2 = 'coast-run-summary-v2'
RUN_V3 = 'coast-run-summary-v3'  # native successor of v1: run-scoped store counts, digest-bound windows
NATIVE_RUNS = (RUN_V1, RUN_V3)
SCOPE = 'coastal-coordinator-scope-v1'
INTENT_V1 = 'coast-enqueue-intent-v1'
CELLS_CONTRACT = 'coastal-terrain-summary-v1'
STAGES = ('acquire', 'qualify', 'map', 'render')
STATES = ('map_done', 'held', 'failed_terminal', 'failed_uncertain', 'stale', 'cancelled', 'unfinished')
STATS = ('count', 'min', 'max', 'mean', 'p80')
HEADER = ('created_utc', 'author_profile', 'author_model', 'card_id', 'code_commit', 'skill_commit',
          'campaign_segment_id', 'coordinator_segment_id', 'plan_id', 'plan_sha256')


def typed(ref):
    """Drop PC9's descriptive contract/kind keys; root_id is already explicit."""
    if not isinstance(ref, dict) or not REF_KEYS <= set(ref) or set(ref) - REF_KEYS - {'contract', 'kind'}:
        raise ValueError('legacy reference must be a typed Ref with optional contract/kind')
    return {key: ref[key] for key in sorted(REF_KEYS)}


def _header(legacy, schema):
    return dict(schema=schema, **{key: legacy[key] for key in HEADER})


def enqueue_v2(legacy, legacy_ref):
    """Shared v2 enqueue receipt for one original PC9 v1 enqueue receipt."""
    if legacy.get('schema') != ENQUEUE_V1:
        raise ValueError('adapter requires coast-enqueue-receipt-v1')
    return dict(_header(legacy, ENQUEUE_V2), legacy_enqueue=typed(legacy_ref),
                admission=typed(legacy['admission']), bridge=typed(legacy['bridge']),
                code_sha256=legacy['code_sha'], deps_sha256=legacy['deps_sha'],
                store_path=legacy['store_path'], intent=typed(legacy['intent']),
                jobs=[dict(window_key=j['window_key'], source_id=j['source_id'], root_job_id=j['root_job_id'],
                           input_manifest=typed(j['input_manifest']), new_row=j['new_row']) for j in legacy['jobs']])


def _stages(window):
    stages, missing = [], []
    for stage in STAGES:
        info = window['stages'].get(stage)
        if info is None:
            missing.append(stage + ':absent_from_run_receipt')
        elif info['state'] == 'missing':
            missing.append(stage + ':' + info['missing_reason'])
        else:
            stages.append(dict(stage=stage, job_id=info['job_id'], state=info['state'],
                               input_manifest=typed(info['input_manifest']),
                               result=None if info['result_ref'] is None else typed(info['result_ref']),
                               products=[typed(info['products'][name]) for name in sorted(info['products'])],
                               holds=sorted(set(info['holds'])), missing_reason=info['missing_reason']))
    if not window['stages']:
        missing = ['all:' + (window.get('unfinished_reason') or 'no_stage_lineage')]
    return stages, missing


def window_cells(index, window):
    """One per-window producer cells record; never an aggregate across windows."""
    info = window['stages'].get('map') or {}
    record = dict(window_key=window['window_key'], window_index=index, state=window['state'],
                  producer=None, producer_contract=None, native_valid_count=None,
                  **{key: None for key in STATS}, unknown=[], absent=[])
    cells = (info.get('products') or {}).get('cells')
    if window['state'] != 'map_done' or info.get('state') != 'done' or cells is None:
        record['unknown'] = ['map_not_done:' + (info.get('state') or window['state'])]
        record['absent'] = sorted(STATS + ('native_valid_count',))
        return record
    if cells.get('contract') != CELLS_CONTRACT:
        raise ValueError('map cells product contract mismatch')
    depth = info.get('depth_m')
    if not isinstance(depth, dict):
        raise ValueError('map stage depth_m statistics missing')
    record.update(producer=typed(cells), producer_contract=CELLS_CONTRACT,
                  native_valid_count=info.get('native_valid_count'))
    absent, unknown = [], []
    for key in STATS:
        value = depth.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            record[key] = value
        elif value == 'unknown':
            unknown.append('depth_m.' + key)  # producer-declared unknown, kept explicit
        else:
            absent.append('depth_m.' + key)
    if record['native_valid_count'] is None:
        absent.append('native_valid_count')
    record['absent'] = sorted(absent)
    record['unknown'] = sorted(unknown + ['depth_m.' + key for key in set(depth) - set(STATS)])
    return record


def run_v3_schema(v1):
    """The native v3 run-summary schema, derived from the unchanged v1 schema.

    Only three things differ: the version, `store_status` (run-scoped counts,
    never foreign rows) and the `windows_sha256` digest of the inline windows;
    `problems` is bounded (the writer lists at most 64 plus one omitted-count line).
    """
    schema = {**v1, '$id': 'urn:skippercast:' + RUN_V3}
    count = {'minimum': 0, 'type': 'integer'}
    def closed(**fields):
        return {'additionalProperties': False, 'type': 'object', 'properties': fields, 'required': sorted(fields)}
    properties = dict(v1['properties'], schema={'enum': [RUN_V3]},
                      problems=dict(v1['properties']['problems'], maxItems=65),
                      windows_sha256={'pattern': '^[0-9a-f]{64}$', 'type': 'string'})
    properties['store_status'] = closed(
        schema={'enum': [SCOPE]}, store={'enum': ['present', 'uninitialized']},
        lineage_jobs={'additionalProperties': count, 'type': 'object'},
        lineage_charges=closed(rows=count, requests=count, bytes=count),
        foreign=closed(jobs=count, queued_jobs=count, charges=count),
        events=count, last_tick_epoch={'anyOf': [{'type': 'number'}, {'type': 'null'}]})
    schema.update(properties=properties, required=v1['required'] + ['windows_sha256'])
    return schema


def run_v2(legacy, legacy_ref, enqueue_ref, previous_ref=None):
    """Shared v2 run summary for one original PC9 v1 or v3 run receipt."""
    if legacy.get('schema') not in (RUN_V1, RUN_V3):
        raise ValueError('adapter requires coast-run-summary-v1 or coast-run-summary-v3')
    if (legacy['continuation_of'] is None) != (previous_ref is None):
        raise ValueError('continuation must convert against the converted predecessor')
    windows, partition = [], {state: [] for state in STATES}
    for window in legacy['windows']:
        stages, missing = _stages(window)
        windows.append(dict(window_key=window['window_key'], state=window['state'], stages=stages,
                            missing_stage_reasons=missing))
        partition[window['state']].append(window['window_key'])
    return dict(_header(legacy, RUN_V2), legacy_run=typed(legacy_ref),
                admission=typed(legacy['admission']), enqueue=typed(enqueue_ref), bridge=typed(legacy['bridge']),
                sequence=legacy['sequence'], continuation_of=None if previous_ref is None else typed(previous_ref),
                stop_reason=legacy['stop_reason'], reasons=sorted(set(legacy['problems'])), windows=windows,
                partition=partition, window_cells=[window_cells(i, w) for i, w in enumerate(legacy['windows'])],
                ticks_used=legacy['ticks_used'], max_ticks=legacy['max_ticks'], until_epoch=legacy['until_epoch'],
                started_utc=legacy['started_utc'], finished_utc=legacy['finished_utc'], wall_s=legacy['wall_s'],
                usage=dict(requests=legacy['usage']['requests'], bytes=legacy['usage']['bytes_in'], wall_s=legacy['wall_s']),
                store_status_evidence=dict(kind='legacy_embedded', field='store_status', source=typed(legacy_ref),
                                           status_sha256=object_digest(legacy['store_status']),
                                           independent_snapshot=False, store_consistent_claim=False))
