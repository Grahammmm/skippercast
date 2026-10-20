"""Canonical held acquisition packets and full source-free metadata admission.

This prepares a future package; it neither releases execution authority nor
creates a runtime clock, Store, Budget or source snapshot. Live unit/resource
verification remains mandatory in RealAdapter.preflight.
"""
import copy,math,os
from pathlib import Path
from .authenticated import INPUT_CONTRACT,metadata_document,validate_input,_source_identity
from .loop import implementation_hashes
from .ordered_trial import LARGER_SCOPE,SUPPORTED_WINDOW_SIDES,scope_windows,validate_scope_review,validate_scope_packet,validate_larger_runtime
from ..authenticated_v1.profiles import profile,grant_identity,prepare_window_batch
from ..authenticated_v1.policy import policy_for_profile,policy_sha
from ..handoff.common import digest,epoch,ref,write

VALIDATION='coastal-acquisition-package-validation-v1'
PACKAGE='coastal-held-acquisition-package-v1'

def _horizon(now,horizon):
    if isinstance(now,bool) or isinstance(horizon,bool):raise ValueError('boolean metadata clock rejected')
    start=epoch(now);end=epoch(horizon)
    if not all(math.isfinite(x) for x in (start,end)) or not start<end<=start+3600:
        raise ValueError('finite prospective metadata horizon at most3600seconds required')
    return start,end

def _grant_context(grant,code,deps):
    grant_identity(grant);_source_identity(grant['source'])
    selected=profile(grant.get('execution_profile'),grant)
    if selected['name']!='coastal-contained-windows-v3' or selected['side'] not in SUPPORTED_WINDOW_SIDES or selected['window_count']!=4:
        raise ValueError('only contained-v3 four-window 32/64/128 admission supported')
    if selected['side']==128 and (grant.get('ordered_scope_contract')!=LARGER_SCOPE or grant.get('window_set')!=scope_windows(grant)[0]):
        raise ValueError('explicit exact ordered four128 scope required')
    if grant.get('code_sha')!=code or grant.get('deps_sha')!=deps:
        raise ValueError('grant current code/dependency identity mismatch')
    return selected

def canonical_packet(template,grant,*,rights,trial,segment,code_sha,deps_sha):
    """Derive final science content and SHA after typed scope selection."""
    selected=_grant_context(grant,code_sha,deps_sha)
    if grant.get('execution_authorized') is not False:
        raise ValueError('packet preparation requires explicitly held grant')
    if template.get('schema')!=INPUT_CONTRACT or template.get('stage')!='acquire':
        raise ValueError('acquisition template required')
    packet=copy.deepcopy(template)
    packet.update(execution_profile=selected['name'],source=copy.deepcopy(grant['source']),
        source_root=grant['source_root'],source_relative_path=grant['source_relative_path'],
        execution_authorized=False,code_sha=code_sha,deps_sha=deps_sha,code_freeze_pending=False,
        segment=copy.deepcopy(segment),rights=dict(private_use=True,evidence=copy.deepcopy(rights)),
        trial_policy_evidence=copy.deepcopy(trial),trial_policy_sha256=trial['sha256'])
    if selected['name']=='coastal-contained-windows-v3':
        packet.update(window_side=selected['side'],window_count=selected['window_count'])
    if grant.get('support_policy') is not None:packet['support_policy']=grant['support_policy']
    else:packet.pop('support_policy',None)
    if selected['side']==128:
        packet.update(ordered_scope_contract=LARGER_SCOPE,geographic_review=copy.deepcopy(grant['geographic_review']),output_retention=copy.deepcopy(grant['output_retention']),output_root=grant['output_root'])
        if grant.get('larger_runtime_contract') is not None:
            packet['larger_runtime_contract']=grant['larger_runtime_contract']
        else:packet.pop('larger_runtime_contract',None)
    if grant.get('saved_area_continuation_contract') is not None:
        for key in ('saved_area_continuation_contract','saved_area_adoption','source_volume_cap_bytes','prior_effective_bytes','cumulative_limit_bytes'):
            packet[key]=grant[key]
    else:
        for key in ('saved_area_continuation_contract','saved_area_adoption','source_volume_cap_bytes','prior_effective_bytes','cumulative_limit_bytes'):packet.pop(key,None)
    if grant.get('source_reuse_contract') is not None:
        packet['source_reuse_contract']=grant['source_reuse_contract']
    else:
        packet.pop('source_reuse_contract',None)
    packet['scientific_policy']=copy.deepcopy(policy_for_profile(selected['name'],packet))
    packet['policy_sha256']=policy_sha(selected['name'],packet)
    assert digest(packet['scientific_policy'])==packet['policy_sha256']
    return packet

def validate_acquisition_package(root,grant_ref,request_refs,*,now,horizon,validation_mode='held'):
    """Read-only check of exact held or released bytes; never authorize launch."""
    now,horizon=_horizon(now,horizon)
    root=Path(os.path.abspath(root))
    grant=metadata_document(root,grant_ref,'coastal-authenticated-policy-v1')
    if validation_mode not in ('held','released'):raise ValueError('explicit held or released validation mode required')
    expected_execution=validation_mode=='released'
    if grant.get('execution_authorized') is not expected_execution:raise ValueError('grant execution state differs from validation mode')
    code,deps=implementation_hashes(root)
    selected=_grant_context(grant,code,deps)
    scope_review=validate_scope_review(root,grant,now=now,horizon=horizon)
    if len(request_refs)!=selected.get('window_count',len(grant.get('window_set',[]))):
        raise ValueError('complete finite grant packet membership required')
    rows=[];packets=[]
    for index,descriptor in enumerate(request_refs):
        try:
            packet=metadata_document(root,descriptor,INPUT_CONTRACT)
            if packet.get('source_reuse_contract')!=grant.get('source_reuse_contract'):
                raise ValueError('packet source reuse differs from immutable grant')
            segment=metadata_document(root,packet['segment'],'coastal-segment-v1')
            validate_scope_packet(root,grant,packet,now=now,horizon=horizon,review=scope_review)
            # Same complete scientific/rights/source/spec/code predicates used
            # immediately before runtime dispatch; no predicates are stubbed.
            validate_input(root,descriptor,stage='acquire',segment=segment,code_sha=code,deps_sha=deps,
                now=now,mission_deadline=horizon,expected_source=grant['source'],
                source_root=grant['source_root'],source_relative_path=grant['source_relative_path'])
            expected=policy_for_profile(selected['name'],packet)
            if packet.get('scientific_policy')!=expected or digest(expected)!=packet['policy_sha256']:
                raise ValueError('canonical scientific policy content changed')
            if packet.get('execution_authorized') is not expected_execution:raise ValueError('packet execution state differs from validation mode')
            if selected['name'] and packet['fixed_center_plan']['native_window']!=grant['window_set'][index]:
                raise ValueError('ordered complete native window membership changed')
            packets.append(packet);rows.append(dict(index=index,status='PASS_METADATA_ONLY',request=descriptor))
        except (ValueError,KeyError,TypeError,OSError) as exc:
            rows.append(dict(index=index,status='HOLD',request=descriptor,reason=str(exc)))
    if len(packets)==len(request_refs):
        try:prepare_window_batch(grant,packets)
        except (ValueError,KeyError,TypeError) as exc:
            rows[0].update(status='HOLD',reason='finite batch contract: '+str(exc))
    validation=dict(schema=VALIDATION,status='PASS_METADATA_ONLY' if all(x['status']=='PASS_METADATA_ONLY' for x in rows) else 'HOLD',
        packets=rows,grant=grant_ref,code_sha=code,deps_sha=deps,checked_at=now,prospective_horizon=horizon,
        validation_mode=validation_mode,validated_execution_state=expected_execution,
        execution_authorized=False,native_operations=0,source_bytes_reserved=0,Store_created=False,
        Budget_created=False,unit_clock_created=False,actual_source_identity='UNVERIFIED',
        live_gate='Actual unchanged unit/resource/boot/mission/carry validation remains required before any native admission.')
    if selected['side']==128:
        validation['larger_execution_ready']=validate_larger_runtime(grant)
    if grant.get('source_reuse_contract') is not None:
        validation['source_reuse_execution_ready']=False
    return validation


def build_acquisition_package(root,grant_ref,template_refs,*,rights,trial,segment,now,horizon,prefix='held-acquisition'):
    """Write fresh held candidates, then validate the entire byte-bound chain."""
    now,horizon=_horizon(now,horizon);root=Path(os.path.abspath(root))
    if not prefix or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in prefix):
        raise ValueError('lowercase owned artifact prefix required')
    grant=metadata_document(root,grant_ref,'coastal-authenticated-policy-v1')
    code,deps=implementation_hashes(root)
    selected=_grant_context(grant,code,deps)
    scope_review=validate_scope_review(root,grant,now=now,horizon=horizon)
    if grant.get('execution_authorized') is not False:raise ValueError('builder requires held grant')
    if len(template_refs)!=selected['window_count']:raise ValueError('all finite templates required')
    # Resolve every caller-provided role before candidate writes.
    templates=[metadata_document(root,x,INPUT_CONTRACT) for x in template_refs]
    metadata_document(root,segment,'coastal-segment-v1')
    for role in rights:metadata_document(root,role,'coastal-rights-evidence-v1')
    metadata_document(root,trial,'coastal-bounded-patch-quality-policy-v3' if selected['name']=='coastal-contained-windows-v3' else 'coastal-bounded-patch-quality-policy-v2')
    paths=[root/'metadata'/f'{prefix}-{i}.json' for i in range(len(templates))]
    result_path=root/'metadata'/f'{prefix}-validation.json'
    if any(p.exists() for p in [*paths,result_path]):raise ValueError('preserve existing packet package')
    generated=[canonical_packet(t,grant,rights=rights,trial=trial,segment=segment,code_sha=code,deps_sha=deps) for t in templates]
    for packet in generated:
        validate_scope_packet(root,grant,packet,now=now,horizon=horizon,review=scope_review)
    descriptors=[]
    for path,packet in zip(paths,generated):
        write(path,packet);descriptors.append(ref(root,path,INPUT_CONTRACT))
    validation=validate_acquisition_package(root,grant_ref,descriptors,now=now,horizon=horizon)
    write(result_path,validation)
    return dict(schema=PACKAGE,grant=grant_ref,requests=descriptors,
        validation=ref(root,result_path,VALIDATION),status=validation['status'],execution_authorized=False,
        native_operations=0,Store_created=False,Budget_created=False,unit_clock_created=False)
