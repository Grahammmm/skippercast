"""Serialize and fully validate metadata admission; never enqueue or accept maps."""
from admit_common import (absolute, bridge, canonical, check_stage, cli, context,
                          file_ref, freeze, geometry, header, object_digest,
                          read_json, resolver_for, sha256, validate, verify_provenance)


def write_admission(*, roots, campaign, plan_dir, selection, cache_receipt, ledger_snapshot, out):
    """Bind all producers and explicit campaign/owner reservations, then write once."""
    camp, sel, root, queue_id = context(campaign, selection)
    resolver = resolver_for(roots, sel, root, queue_id)
    stage = check_stage(read_json(cache_receipt), camp, sel)
    for w in sel['windows']:
        verify_provenance(w, resolver)
    record, grids, windows = geometry(camp, sel, stage, root)
    plan_dir = absolute(plan_dir)
    if plan_dir.parent != root/'plans':
        raise ValueError('plan must be inside campaign plans')
    plan = read_json(plan_dir/'plan.json')
    if read_json(plan_dir/'segment.json') != record:
        raise ValueError('frozen segment ID/projected bbox/CRS84 differs from generated record')
    if plan['segment'] != {k: record[k] for k in ('segment_id', 'bbox_crs84')}:
        raise ValueError('plan differs from full segment record')
    if plan['budget'] != sel['budget'] or plan['max_total_bytes'] != sel['max_total_bytes']:
        raise ValueError('plan budget differs from admitted selection')
    for p,w,s in zip(plan['selections'],sel['windows'],stage['sources'],strict=True):
        expected = dict(source_id=w['source_id'], source=dict(contract=w['reader'], **{k:s['hot_cache'][k] for k in ('path','sha256','bytes')}),
                        window=w['pixel_window'], vertical=w['vertical'], rights=w['rights'])
        if p != expected:
            raise ValueError('plan selection differs from admitted selection')
    ledger_ref = file_ref(ledger_snapshot, queue_id, root)
    if ledger_ref != sel['ledger_snapshot']:
        raise ValueError('budget snapshot differs from independent selection pin')
    snapshot = read_json(ledger_snapshot)
    if (set(snapshot) != {'schema','campaign_sha256','coordinator_segment_id','attested_by',
                         'campaign_usage_before','segment_usage_before','campaign_limits','segment_limits'}
            or snapshot.get('schema') != 'coast-budget-snapshot-v1'
            or snapshot.get('campaign_sha256') != sha256(canonical(camp))
            or snapshot.get('coordinator_segment_id') != record['segment_id']
            or not snapshot.get('attested_by')):
        raise ValueError('budget snapshot identity/attestation mismatch')
    delta = dict(requests=0, bytes=sum(s['hot_cache']['bytes'] for s in stage['sources']),
                 wall_s=sel['budget']['wall_s']*len(windows))
    for scope in ('campaign', 'segment'):
        before, limits = snapshot[scope+'_usage_before'], snapshot[scope+'_limits']
        if set(before) != set(delta) or set(limits) != set(delta):
            raise ValueError('budget snapshot needs requests/bytes/wall_s')
        for key in delta:
            if (isinstance(before[key], bool) or isinstance(limits[key], bool)
                    or not isinstance(before[key], (int,float)) or not isinstance(limits[key], (int,float))
                    or before[key] < 0 or limits[key] < 0 or before[key]+delta[key] > limits[key]):
                raise ValueError(scope+' budget cap exceeded: '+key)
    dry_path = plan_dir/'dry/bridge-dry-run-receipt.json'
    dry = read_json(dry_path)
    if not isinstance(dry['would_enqueue'], list):
        raise ValueError('dry would_enqueue must be a LIST')
    # Re-evaluate without writes: expired candidates or changed metadata cannot
    # reuse a historically clean dry-run as current admission.
    evaluated = bridge.evaluate(root, resolver.bindings[sel['catalog']['root_id']]/sel['catalog']['path'], plan)
    if evaluated['decisions'] != dry['decisions']:
        raise ValueError('dry-run decisions no longer current')
    sources = [dict(source_id=w['source_id'], raw_provenance=w['raw_provenance'], retained_inputs=w['retained_inputs'],
                    hot_cache=[s['hot_cache']], rights=w['rights_summary'], datum=w['datum'], reader=w['reader'])
               for w,s in zip(sel['windows'],stage['sources'])]
    holds = sorted({reason for d in dry['decisions'] for reason in d['holds']})
    result = dict(schema='coast-admission-v1', **header(sel), campaign_segment_id=camp['campaign_segment_id'],
                  coordinator_segment_id=record['segment_id'], plan_id=plan_dir.name, plan_sha256=object_digest(plan),
                  campaign=file_ref(campaign,queue_id,root), plan_file=file_ref(plan_dir/'plan.json',queue_id,root),
                  segment_record=file_ref(plan_dir/'segment.json',queue_id,root), catalog=sel['catalog'], discovery=sel['discovery'],
                  sources=sources, grids=grids, windows=windows,
                  budgets=dict(requests=0, bytes=plan['max_total_bytes'], wall_s=plan['budget']['wall_s'], cells=bridge.MAX_WINDOW_CELLS),
                  usage_before=snapshot['campaign_usage_before'], usage_delta=delta,
                  dry_run=file_ref(dry_path,queue_id,root), would_enqueue_count=len(dry['would_enqueue']),
                  selected_source_ids=dry['selected_source_ids'], held_source_ids=dry['held_source_ids'],
                  preconditions=sel['preconditions'], holds=holds, replacement_plan_of=sel.get('replacement_plan_of'))
    validate(result, resolver, root_id=queue_id)
    out = absolute(out)
    if out != plan_dir/'admission.json':
        raise ValueError('admission output must be P/admission.json')
    freeze(out,result)
    return dict(status='held' if holds else 'metadata_admitted_review_required',
                would_enqueue_count=result['would_enqueue_count'], holds=holds, scientific_acceptance=False)


if __name__ == '__main__':
    cli(write_admission, ('roots','campaign','plan-dir','selection','cache-receipt','ledger-snapshot','out'))
