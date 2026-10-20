"""Closed authenticated profiles; opt-in is part of the durable source grant."""
import copy
LARGER = 'coastal-four-window-128-v2'
CONTAINED = 'coastal-contained-windows-v3'
MANAGED_EIGHT_COPY = 'coastal-managed-eight-copy-four128-v1'
# SC-5 (G option A, 2026-10-20): a separate pinned support policy for contained
# windows. Mask-invalid cells stay unsupported/nodata instead of holding the
# window; every supported cell keeps the strict depth/uncertainty limits. Absent
# means the strict all-pairs policy, so strict identities and digests are unchanged.
PARTIAL_SUPPORT = 'coastal-contained-partial-support-v1'
ORDERED_SCOPE = 'coastal-ordered-four128-v2'
# The only window set the partial policy may admit: four non-overlapping,
# segment-contained 128 windows with 14/4/299/18 mask-invalid cells from the
# FIX3 pre-scan (hole-candidates.json sha256 024d474a8832...). Pinned here, at
# the shared authority boundary, so every grant/packet/policy path enforces it.
PARTIAL_WINDOWS = [[4402,3872,128,128],[3762,3744,128,128],[3634,3616,128,128],[4018,3488,128,128]]
def support_policy(name=None, configuration=None):
    config=configuration or {};value=config.get('support_policy')
    if value is None:return None
    if name!=CONTAINED or value!=PARTIAL_SUPPORT:raise ValueError('unsupported contained support policy')
    side=config.get('window_side');count=config.get('window_count')
    if type(side) is not int or side!=128 or type(count) is not int or count!=4:
        raise ValueError('partial support is pinned to the ordered four128 scope')
    return value
def _partial_grant(grant):
    """Fail closed: a partial grant always carries the pinned set and full ordered authority."""
    if grant.get('window_set')!=PARTIAL_WINDOWS:
        raise ValueError('partial support is pinned to the ordered four128 window set')
    if (grant.get('ordered_scope_contract')!=ORDERED_SCOPE
        or grant.get('larger_runtime_contract')!=MANAGED_EIGHT_COPY
        or any(grant.get(key) is None for key in ('geographic_review','output_retention','output_root'))
        or grant.get('source_reuse_contract') is not None
        or grant.get('saved_area_continuation_contract') is not None):
        raise ValueError('partial support requires the ordered four128 geographic/output/runtime authority')
def profile(name=None, configuration=None):
    if name not in (None,LARGER,CONTAINED):raise ValueError('unsupported authenticated execution profile')
    support_policy(name,configuration)
    side=128 if name else 16;count=4 if name else 1
    if name==CONTAINED:
        config=configuration or {};side=config.get('window_side');count=config.get('window_count')
        if type(side) is not int or not 1<=side<=128 or type(count) is not int or not 1<=count<=4 or count*side*side>65536:
            raise ValueError('explicit bounded contained side/count required')
    return dict(name=name,side=side,pairs=side*side,window_count=count,
                mission_seconds=3600 if name else 600,launch_horizon=3420 if name else 420,
                phase_seconds=180,worker_seconds=120,cleanup_seconds=60,
                reservations=2*count,memory_bytes=1073741824)
def grant_identity(grant):
    result={key:copy.deepcopy(grant[key]) for key in ('schema','source','source_root','source_relative_path')}
    chosen=profile(grant.get('execution_profile'),grant)
    if chosen['name']==CONTAINED:
        windows=grant.get('window_set');side=chosen['side'];count=chosen['window_count']
        if (not isinstance(windows,list) or len(windows)!=count or
            any(not isinstance(w,list) or len(w)!=4 or any(type(x) is not int for x in w) or min(w[:2])<0 or w[2:]!=[side,side] for w in windows)):
            raise ValueError('contained exact square native windows required')
        if windows!=sorted(windows,key=lambda w:(-w[1],w[0])):
            raise ValueError('contained windows must have deterministic southern-first west/east order')
        for i,a in enumerate(windows):
            for b in windows[i+1:]:
                if a[0]<b[0]+side and b[0]<a[0]+side and a[1]<b[1]+side and b[1]<a[1]+side:
                    raise ValueError('contained native windows overlap')
        result.update(execution_profile=CONTAINED,window_side=side,window_count=count,window_set=copy.deepcopy(windows))
        if support_policy(CONTAINED,grant) is not None:
            _partial_grant(grant)
            result['support_policy']=PARTIAL_SUPPORT
    elif chosen['name']:
        windows=grant.get('window_set')
        if (not isinstance(windows,list) or len(windows)!=4 or
            any(not isinstance(w,list) or len(w)!=4 or any(type(x) is not int for x in w)
                or min(w[:2])<0 or w[2:]!=[128,128] for w in windows)):
            raise ValueError('four exact128x128 native windows required')
        cols=sorted({w[0] for w in windows});rows=sorted({w[1] for w in windows})
        if (len(cols)!=2 or len(rows)!=2 or cols[1]-cols[0]!=128 or rows[1]-rows[0]!=128
            or {(w[0],w[1]) for w in windows}!={(x,y) for x in cols for y in rows}):
            raise ValueError('four distinct contiguous nonoverlapping native windows required')
        # Deterministic A,B,C,D is west/east southern row, west/east northern row.
        expected=[[cols[0],rows[1],128,128],[cols[1],rows[1],128,128],
                  [cols[0],rows[0],128,128],[cols[1],rows[0],128,128]]
        if windows!=expected:raise ValueError('finite window order must be A,B,C,D')
        result.update(execution_profile=chosen['name'],window_set=copy.deepcopy(windows))
    elif 'window_set' in grant:raise ValueError('window set requires explicit larger profile')
    if grant.get('ordered_scope_contract') is not None:
        if grant['ordered_scope_contract']!='coastal-ordered-four128-v2':
            raise ValueError('unsupported ordered scope contract')
        keys=('ordered_scope_contract','geographic_review','output_retention','output_root')
        if any(key not in grant for key in keys):
            raise ValueError('larger ordered grant requires geometry and output identity')
        result.update({key:copy.deepcopy(grant[key]) for key in keys})
    if grant.get('larger_runtime_contract') is not None:
        if (grant['larger_runtime_contract']!=MANAGED_EIGHT_COPY
            or grant.get('ordered_scope_contract')!='coastal-ordered-four128-v2'
            or grant.get('source_reuse_contract') is not None
            or grant.get('output_retention',{}).get('profile') not in ('coastal-managed-output-32-v2','coastal-managed-output-32-v3')):
            raise ValueError('unsupported larger managed runtime contract')
        result['larger_runtime_contract']=MANAGED_EIGHT_COPY
    if grant.get('source_reuse_contract') is not None:
        from .source_reuse import CONTRACT, source_volume_cap
        if grant['source_reuse_contract'] != CONTRACT:raise ValueError('unsupported source reuse contract')
        source_volume_cap(grant)
        result['source_reuse_contract']=CONTRACT
    if grant.get('saved_area_continuation_contract') is not None:
        from ..coordinator.saved_area import continuation_grant
        continuation_grant(grant)
        result.update({key:copy.deepcopy(grant[key]) for key in ('saved_area_continuation_contract','saved_area_adoption','source_volume_cap_bytes','prior_effective_bytes','cumulative_limit_bytes')})
    return result

def validate_grant_packet(grant,packet):
    domain=grant_identity(grant);selected=profile(domain.get('execution_profile'),domain)
    if packet.get('saved_area_continuation_contract')!=grant.get('saved_area_continuation_contract'):
        raise ValueError('packet continuation domain differs')
    if grant.get('saved_area_continuation_contract') is not None and any(packet.get(k)!=grant[k] for k in ('saved_area_adoption','source_volume_cap_bytes','prior_effective_bytes','cumulative_limit_bytes')):
        raise ValueError('packet adoption/cumulative authority differs')
    if packet.get('larger_runtime_contract')!=grant.get('larger_runtime_contract'):
        raise ValueError('packet managed runtime contract differs from immutable grant')
    if packet.get("source_reuse_contract")!=grant.get("source_reuse_contract"):
        raise ValueError("packet source reuse contract differs from immutable grant")
    if grant.get('ordered_scope_contract') is not None:
        if any(packet.get(k)!=grant[k] for k in ('ordered_scope_contract','geographic_review','output_retention','output_root')):
            raise ValueError('packet ordered geometry/output contract differs from immutable grant')
    if packet.get('execution_profile')!=selected['name']:raise ValueError('input profile differs from immutable grant')
    if packet.get('support_policy')!=domain.get('support_policy'):raise ValueError('packet support policy differs from immutable grant')
    if selected['name']==CONTAINED and any(packet.get(k)!=domain[k] for k in ('window_side','window_count')):
        raise ValueError('contained input shape/count differs from immutable grant')
    if any(packet.get(key)!=domain[key] for key in ('source','source_root','source_relative_path')):
        raise ValueError('packet differs from exact source domain')
    if selected['name'] and packet.get('fixed_center_plan',{}).get('native_window') not in domain['window_set']:
        raise ValueError('window outside immutable finite grant')
    return domain

def prepare_window_batch(grant,packets):
    """Pure metadata manifest, never a source probe, mission or reservation."""
    from skippercast.coastal.handoff.common import digest
    domain=grant_identity(grant);selected=profile(domain.get('execution_profile'),domain)
    if not selected['name'] or not isinstance(packets,list) or len(packets)!=selected['window_count']:
        raise ValueError('explicit larger four-packet preparation required')
    for window,packet in zip(domain['window_set'],packets):
        validate_grant_packet(grant,packet)
        if packet.get('stage')!='acquire' or packet['fixed_center_plan'].get('native_window')!=window:
            raise ValueError('finite preparation packets must be acquire in A,B,C,D order')
    prepared=dict(schema='coastal-contained-window-preparation-v3' if selected['name']==CONTAINED else 'coastal-four-window-preparation-v2',execution_authorized=False,native_operations=0,
                budget_created=False,grant_sha256=digest(domain),packet_sha256=[digest(p) for p in packets],
                window_set=domain['window_set'],source_volume_reservations=selected['reservations'],
                source_volume_bytes=selected['reservations']*domain['source']['bytes'],mission_seconds=3600,
                stage_order=['acquire','review','qualify','independent_mapping_acceptance'])
    if grant.get('source_reuse_contract') is not None:
        from .source_reuse import source_admissions,source_volume_cap
        prepared.update(source_volume_reservations=source_admissions(grant),
                        source_volume_bytes=source_volume_cap(grant),
                        runtime_phase_reservations=selected['reservations'],
                        source_reuse_execution_ready=False)
    return prepared
