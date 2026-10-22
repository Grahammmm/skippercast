"""Independent artifact-only science review; requires actual shared review lane."""
import argparse,datetime as dt,hashlib,json,os,sys,time,subprocess
from pathlib import Path
# Same roots as coastal_four128_runtime (the review unit inherits them via --setenv);
# defaults keep the 2026-10-11 attempt's identity readable. One project root from the
# operator's home, never a literal home path (scripts/check_repository.py).
PROJECT=Path.home()/'skippercast-data'/'2026-10-07-pge-south'
N=Path(os.environ.get('SKIPPERCAST_FOUR128_MISSION_ROOT',str(PROJECT/'outputs/ordered-four128-approved-20261011')))
DEFAULT_ROOT=N
R=N/'execution'
CONTEXT_PATH=N/'control/release-context.json'
CONTEXT=None
FIXTURE=None

def require(condition, message):
    """A review gate must remain active under python -O."""
    if not condition:
        raise ValueError(message)

def configure(root=DEFAULT_ROOT):
    global N,R,CONTEXT_PATH,CONTEXT,FIXTURE
    N=Path(root);CONTEXT_PATH=N/'control/release-context.json'
    if CONTEXT_PATH.is_symlink() or CONTEXT_PATH.stat().st_size>65536:
        raise ValueError('bounded exact release context required')
    CONTEXT=json.loads(CONTEXT_PATH.read_text())
    require(CONTEXT['schema']=='coastal-release-runtime-context-v1', "artifact review check failed: CONTEXT['schema']=='coastal-release-runtime-context-v1'")
    require(Path(CONTEXT['root'])==N and Path(CONTEXT['execution_root'])==N/'execution', "artifact review check failed: Path(CONTEXT['root'])==N and Path(CONTEXT['execution_root'])==N/'execution'")
    require(CONTEXT['native_store']=='var/coastal/authenticated.sqlite', "artifact review check failed: CONTEXT['native_store']=='var/coastal/authenticated.sqlite'")
    FIXTURE=CONTEXT['mode']=='synthetic_rehearsal'
    require(CONTEXT['mode'] in ('synthetic_rehearsal','real_continuation'), "artifact review check failed: CONTEXT['mode'] in ('synthetic_rehearsal','real_continuation')")
    if FIXTURE:
        require(CONTEXT['rehearsal_synthetic'] is True and CONTEXT['source']['sha256']!=CONTEXT['real_source_sha256'], "artifact review check failed: CONTEXT['rehearsal_synthetic'] is True and CONTEXT['source']['sha256']!=CONTEXT['real_source_sha256']")
        allowed=PROJECT/'scratch/source-reuse-admission-engineering-20261011'
        require(N.is_relative_to(allowed), 'artifact review check failed: N.is_relative_to(allowed)')
    else:
        require(N==DEFAULT_ROOT and CONTEXT['source']['sha256']==CONTEXT['real_source_sha256'] and CONTEXT.get('rehearsal_synthetic') is False, "artifact review check failed: N==DEFAULT_ROOT and CONTEXT['source']['sha256']==CONTEXT['real_source_sha256'] and CONTEXT.get('rehearsal_synthetic') is False")
    R=Path(CONTEXT['execution_root'])

W=Path(os.environ.get('SKIPPERCAST_FOUR128_CODE_ROOT',str(PROJECT/'work/source-reuse-admission-20261011')))
sys.dont_write_bytecode=True;sys.path.insert(0,str(W/'src'))
sys.path.insert(0,str(Path(__file__).parent))
from coastal_four128_runtime import gate, index, put, closed_sqlite
from skippercast.coastal.handoff.common import load,ref,write,digest,epoch
from skippercast.coastal.receipts import managed_writes
from skippercast.coastal.derived_batch import arrays
from skippercast.coastal.authenticated_v1.supplement import summarize
from skippercast.coastal.authenticated_v1.policy import evaluate,policy_sha
from skippercast.coastal import vertical

def validate_review_resources(unit,props,cg,readings,parent_readings,affinity,pid):
    import re
    lane=Path('/sys/fs/cgroup'+cg);parent=lane.parent
    expected={'memory.max':'1073741824','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'32'}
    require(lane.name==unit and parent.name==CONTEXT['slice'], "artifact review check failed: lane.name==unit and parent.name==CONTEXT['slice']")
    require(readings==expected and parent_readings==dict(expected,**{'memory.max':'3221225472','pids.max':'96'}), "artifact review check failed: readings==expected and parent_readings==dict(expected,**{'memory.max':'3221225472','pids.max':'96'})")
    require(props['ExecMainPID']==str(pid) and props['ControlGroup']==cg and props['ActiveState']=='active', "artifact review check failed: props['ExecMainPID']==str(pid) and props['ControlGroup']==cg and props['ActiveState']=='active'")
    require(re.fullmatch('[0-9a-f]{32}',props.get('InvocationID','')) and props['InvocationID']!='0'*32, "artifact review check failed: re.fullmatch('[0-9a-f]{32}',props.get('InvocationID','')) and props['InvocationID']!='0'*32")
    require(props['KillMode']=='control-group' and props['KillSignal']=='9' and props['RuntimeMaxUSec'] in ('3min','180s'), "artifact review check failed: props['KillMode']=='control-group' and props['KillSignal']=='9' and props['RuntimeMaxUSec'] in ('3min','180s')")
    require(0<len(affinity)<=2, 'artifact review check failed: 0<len(affinity)<=2')
    return True

def resources(label,phase):
    unit=CONTEXT['unit_prefix']+label.lower()+'-review-'+phase+CONTEXT['unit_suffix']
    keys=['ExecMainPID','InvocationID','ControlGroup','ActiveState','RuntimeMaxUSec','KillMode','KillSignal']
    p=subprocess.run(['/usr/bin/systemctl','--user','show',unit,*['--property='+k for k in keys]],check=True,text=True,capture_output=True,timeout=3)
    props=dict(x.split('=',1) for x in p.stdout.splitlines() if '=' in x)
    cg=next(x[3:] for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
    lane=Path('/sys/fs/cgroup'+cg);parent=lane.parent
    expected={'memory.max':'1073741824','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'32'}
    readings={k:(lane/k).read_text().strip() for k in expected}
    validate_review_resources(unit,props,cg,readings,{k:(parent/k).read_text().strip() for k in expected},
                              sorted(os.sched_getaffinity(0)),os.getpid())
    return dict(unit=unit,properties=props,cgroup=cg,readings=readings,parent=str(parent))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('label',choices=list('ABCD'));ap.add_argument('phase',choices=['acquire','qualify']);ap.add_argument('descriptor');ap.add_argument('--root',type=Path,default=DEFAULT_ROOT);a=ap.parse_args()
    configure(a.root)
    gate(a.label+'-review-'+a.phase,duration=180)
    bounded=resources(a.label,a.phase)
    descriptor_path=Path(a.descriptor)
    require(descriptor_path.is_relative_to(R/'metadata') and not descriptor_path.is_symlink() and descriptor_path.stat().st_size<4096, "artifact review check failed: descriptor_path.is_relative_to(R/'metadata') and not descriptor_path.is_symlink() and descriptor_path.stat().st_size<4096")
    rr=json.loads(descriptor_path.read_text());result=load(R,rr,contract='coastal-authenticated-stage-result-v1')
    runtime_index=json.loads((R/'metadata/live-index.json').read_text())
    pre=load(R,runtime_index['independent_preflight'])
    require(pre['source']==CONTEXT['source'] and pre['native_window_set']==CONTEXT['windows'], "artifact review check failed: pre['source']==CONTEXT['source'] and pre['native_window_set']==CONTEXT['windows']")
    require(pre['expected_metadata_sha256']==CONTEXT['metadata_sha256'] and pre['expected_global_affine']==CONTEXT['header']['transform'], "artifact review check failed: pre['expected_metadata_sha256']==CONTEXT['metadata_sha256'] and pre['expected_global_affine']==CONTEXT['header']['transform']")
    require(bool(pre.get('rehearsal_synthetic',False))==FIXTURE, "artifact review check failed: bool(pre.get('rehearsal_synthetic',False))==FIXTURE")
    if FIXTURE: require(pre['fixture_scope']==CONTEXT['fixture_scope'], "artifact review check failed: pre['fixture_scope']==CONTEXT['fixture_scope']")
    frozen=load(R,ref(R,R/'metadata/live-preparation.json','coastal-ordered-trial-preparation-v1'))
    observation=load(R,result['observation'],contract='coastal-authenticated-observation-v1')
    facts=observation['native_facts'];fd=result['facts_digest'];window=pre['native_window_set']['ABCD'.index(a.label)]
    require(result['stage']==a.phase and result['source']==pre['source']==facts['source']==observation['source'], "artifact review check failed: result['stage']==a.phase and result['source']==pre['source']==facts['source']==observation['source']")
    require(digest(facts)==fd==observation['facts_digest'] and observation['window']==facts['header']['window']==window, "artifact review check failed: digest(facts)==fd==observation['facts_digest'] and observation['window']==facts['header']['window']==window")
    require(facts['source_lineage']['metadata_sha256']==pre['expected_metadata_sha256'], "artifact review check failed: facts['source_lineage']['metadata_sha256']==pre['expected_metadata_sha256']")
    require(facts['header']['shape']==[10495,10034] and facts['header']['driver']=='BAG', "artifact review check failed: facts['header']['shape']==[10495,10034] and facts['header']['driver']=='BAG'")
    require(type(observation['synthetic']) is bool and observation['synthetic'] is FIXTURE and observation['publication_prohibited'] is True, "artifact review check failed: type(observation['synthetic']) is bool and observation['synthetic'] is FIXTURE and observation['publication_prohibited'] is True")
    admitted_index=json.loads((R/'metadata/live-index.json').read_text())
    admitted_packet=load(R,admitted_index['requests']['ABCD'.index(a.label)],contract='coastal-authenticated-input-v1')
    require(admitted_packet['synthetic'] is observation['synthetic'] and admitted_packet['source']==pre['source'], "artifact review check failed: admitted_packet['synthetic'] is observation['synthetic'] and admitted_packet['source']==pre['source']")
    require(facts['rights']['private_use'] is True and facts['rights']['evidence'], "artifact review check failed: facts['rights']['private_use'] is True and facts['rights']['evidence']")
    import sqlite3
    dbpath=R/CONTEXT['native_store']
    db=closed_sqlite(dbpath)
    try:
        row=db.execute('SELECT * FROM jobs WHERE job_id=?',(result['job_id'],)).fetchone()
        require(row is not None and row['result_sha']==rr['sha256'] and row['stage']==a.phase and row['state']==result['state'], "artifact review check failed: row is not None and row['result_sha']==rr['sha256'] and row['stage']==a.phase and row['state']==result['state']")
        require(row['state'] in ('done','held') and row['attempts']==1 and row['max_attempts']==1, "artifact review check failed: row['state'] in ('done','held') and row['attempts']==1 and row['max_attempts']==1")
        record=json.loads(row['record_json'])
        require(record['source_domain_grant']==frozen['grant_identity'] and record['window_key']==digest(window), "artifact review check failed: record['source_domain_grant']==frozen['grant_identity'] and record['window_key']==digest(window)")
        require(db.execute('SELECT job_id FROM authenticated_window_phases WHERE window_key=? AND stage=?',(digest(window),a.phase)).fetchone()['job_id']==result['job_id'], "artifact review check failed: db.execute('SELECT job_id FROM authenticated_window_phases WHERE window_key=? AND stage=?',(digest(window),a.phase)).fetchone()['job_id']==result['job_id']")
        index_doc=json.loads((R/'metadata/live-index.json').read_text())
        require(result['code_sha']==index_doc['code_sha'] and result['deps_sha']==index_doc['deps_sha'], "artifact review check failed: result['code_sha']==index_doc['code_sha'] and result['deps_sha']==index_doc['deps_sha']")
        require(result['accepted'] is False and result['qualification'] is False and result['rc']==(0 if result['state']=='done' else 3), "artifact review check failed: result['accepted'] is False and result['qualification'] is False and result['rc']==(0 if result['state']=='done' else 3)")
        namespace=Path('var/coastal/jobs')/result['job_id'].replace(':','-')/result['lease_token']/'output'
        require(Path(rr['path'])==namespace/'result.json', "artifact review check failed: Path(rr['path'])==namespace/'result.json'")
        for role in ('arrays','observation','diagnostics','policy_evaluation','finalized_authentication'):
            r=result[role]
            require(Path(r['path']).parent==namespace and not (R/r['path']).is_symlink(), "artifact review check failed: Path(r['path']).parent==namespace and not (R/r['path']).is_symlink()")
            registry=db.execute('SELECT * FROM authenticated_artifacts WHERE path=? AND sha256=?',(r['path'],r['sha256'])).fetchone()
            require(registry is not None and registry['bytes']==r['bytes'] and registry['contract']==r['contract'], "artifact review check failed: registry is not None and registry['bytes']==r['bytes'] and registry['contract']==r['contract']")
            require(registry['job_id']==result['job_id'] and registry['lease_token']==result['lease_token'] and registry['committed_result_sha']==rr['sha256'], "artifact review check failed: registry['job_id']==result['job_id'] and registry['lease_token']==result['lease_token'] and registry['committed_result_sha']==rr['sha256']")
    finally:db.close()
    block=vertical.require_resolved(observation['declared_vertical'],facts['observed_vertical'])
    require(block['datum']=='MLLW' and block['datum_realization']=='unknown' and block['units']=='m' and block['sign']=='positive_up', "artifact review check failed: block['datum']=='MLLW' and block['datum_realization']=='unknown' and block['units']=='m' and block['sign']=='positive_up'")
    data=arrays(R,result['arrays'],side=128)
    import numpy as np
    valid=data['source_pair_valid']
    require(np.array_equal(vertical.to_depth(data['raw_elevation_data'],block,valid=valid),data['depth'],equal_nan=True), "artifact review check failed: np.array_equal(vertical.to_depth(data['raw_elevation_data'],block,valid=valid),data['depth'],equal_nan=True)")
    diag=summarize(data,fd)
    require(diag==load(R,result['diagnostics'],contract='coastal-same-return-pair-diagnostics-v1'), "artifact review check failed: diag==load(R,result['diagnostics'],contract='coastal-same-return-pair-diagnostics-v1')")
    cfg=dict(window_side=128,window_count=4)
    evaluation=evaluate(diag,facts,execution_profile='coastal-contained-windows-v3',configuration=cfg)
    evaluation['trial_policy_sha256']=result['trial_policy_sha256']
    require(evaluation==load(R,result['policy_evaluation'],contract='coastal-fixed-patch-policy-evaluation-v1'), "artifact review check failed: evaluation==load(R,result['policy_evaluation'],contract='coastal-fixed-patch-policy-evaluation-v1')")
    require(result['policy_sha256']==policy_sha('coastal-contained-windows-v3',cfg), "artifact review check failed: result['policy_sha256']==policy_sha('coastal-contained-windows-v3',cfg)")
    auth=load(R,result['finalized_authentication'],contract='coastal-authenticated-finalized-proof-v1')
    for key in ('facts_digest','policy_sha256','trial_policy_sha256','source','stage','code_sha','deps_sha'):
        require(auth[key]==result[key], 'artifact review check failed: auth[key]==result[key]')
    require(auth['observation_sha256']==result['observation']['sha256'] and auth['plan_sha256']==result['plan']['sha256'], "artifact review check failed: auth['observation_sha256']==result['observation']['sha256'] and auth['plan_sha256']==result['plan']['sha256']")
    require(auth['capability_closed'] and auth['container_checked'] and auth['origin_unchanged_observed'], "artifact review check failed: auth['capability_closed'] and auth['container_checked'] and auth['origin_unchanged_observed']")
    snap=auth['snapshot']
    require(snap['sha256']==snap['sealed_snapshot_sha256']==pre['source']['sha256'], "artifact review check failed: snap['sha256']==snap['sealed_snapshot_sha256']==pre['source']['sha256']")
    require(snap['bytes']==snap['source_bytes_read']==snap['sealed_snapshot_bytes_hashed']==pre['source']['bytes'] and snap['seals']==15, "artifact review check failed: snap['bytes']==snap['source_bytes_read']==snap['sealed_snapshot_bytes_hashed']==pre['source']['bytes'] and snap['seals']==15")
    require(snap['origin']['fd_before']==snap['origin']['fd_after'], "artifact review check failed: snap['origin']['fd_before']==snap['origin']['fd_after']")
    h=facts['header'];t=h['transform']
    require(h['scales']==[1.,1.] and h['offsets']==[0.,0.], "artifact review check failed: h['scales']==[1.,1.] and h['offsets']==[0.,0.]")
    from affine import Affine
    from pyproj import CRS
    affine=Affine(*t);global_affine=Affine(*pre['expected_global_affine'])
    require(affine.a==2 and affine.e==-2 and affine.b==affine.d==0, 'artifact review check failed: affine.a==2 and affine.e==-2 and affine.b==affine.d==0')
    # Actual header is window-local, offset once from retained full-grid corner affine.
    require(affine==global_affine*Affine.translation(window[0],window[1]), 'artifact review check failed: affine==global_affine*Affine.translation(window[0],window[1])')
    crs=CRS.from_user_input(h['horizontal_crs'])
    horizontal=crs.source_crs if crs.is_bound else crs
    require(horizontal.is_projected and horizontal.to_epsg()==26910 and all(x.unit_conversion_factor==1 for x in horizontal.axis_info[:2]), 'artifact review check failed: horizontal.is_projected and horizontal.to_epsg()==26910 and all(x.unit_conversion_factor==1 for x in horizontal.axis_info[:2])')
    for key,values in [('raw_valid_values_sha256',np.where(valid,data['raw_elevation_data'],0).astype('<f8')),('depth_values_sha256',np.where(valid,data['depth'],0).astype('<f4'))]:
        require(hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()==facts[key], 'artifact review check failed: hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()==facts[key]')
    require(int(valid.sum())==facts['valid_count'] and hashlib.sha256(valid.astype('uint8').tobytes()).hexdigest()==facts['support']['mask_sha256'], "artifact review check failed: int(valid.sum())==facts['valid_count'] and hashlib.sha256(valid.astype('uint8').tobytes()).hexdigest()==facts['support']['mask_sha256']")
    support_ref=observation['valid_support']
    require(Path(support_ref['path']).parent==namespace, "artifact review check failed: Path(support_ref['path']).parent==namespace")
    support=load(R,support_ref,contract=support_ref['contract']) if support_ref['contract'].endswith('json') else None
    import rasterio
    support_path=R/support_ref['path'];support_bytes=support_path.read_bytes()
    require(len(support_bytes)==support_ref['bytes'] and hashlib.sha256(support_bytes).hexdigest()==support_ref['sha256'], "artifact review check failed: len(support_bytes)==support_ref['bytes'] and hashlib.sha256(support_bytes).hexdigest()==support_ref['sha256']")
    with rasterio.open(support_path) as ds:
        require(ds.shape==(128,128) and tuple(ds.transform)[:6]==tuple(t), 'artifact review check failed: ds.shape==(128,128) and tuple(ds.transform)[:6]==tuple(t)')
        require(np.array_equal(ds.read(1).astype(bool),valid), 'artifact review check failed: np.array_equal(ds.read(1).astype(bool),valid)')
    holds=sorted(set(observation.get('machine_holds',[])+evaluation['holds']+result.get('holds',[])))
    if a.phase=='qualify':
        verified=load(R,result['verification'],contract='coastal-authenticated-verification-v1')
        require(digest(verified['facts'])==fd==result['producer_facts_digest']==result['verified_facts_digest'], "artifact review check failed: digest(verified['facts'])==fd==result['producer_facts_digest']==result['verified_facts_digest']")
        require(diag==load(R,result['verified_diagnostics'],contract='coastal-same-return-pair-diagnostics-v1'), "artifact review check failed: diag==load(R,result['verified_diagnostics'],contract='coastal-same-return-pair-diagnostics-v1')")
        require(evaluation==load(R,result['verified_policy'],contract='coastal-fixed-patch-policy-evaluation-v1'), "artifact review check failed: evaluation==load(R,result['verified_policy'],contract='coastal-fixed-patch-policy-evaluation-v1')")
        holds=sorted(set(holds+verified['holds']))
        require(verified['ready'] is (not bool(holds)), "artifact review check failed: verified['ready'] is (not bool(holds))")
    now=time.time();until=frozen['deadline_epoch']+120
    require(now<frozen['deadline_epoch'], "artifact review check failed: now<frozen['deadline_epoch']")
    doc=dict(schema='coastal-private-input-review-v2',reviewer_id=('SYNTHETIC_REHEARSAL-' if FIXTURE else 'independent-four128-')+a.label+'-'+a.phase,independent=True,decision='qualified_private_terrain' if not holds else 'hold',
       checked_at=dt.datetime.fromtimestamp(now,dt.timezone.utc).isoformat(),valid_until=dt.datetime.fromtimestamp(until,dt.timezone.utc).isoformat(),
       holds_added=holds,quality_accepted=not holds,facts_digest=fd,diagnostics_digest=diag['diagnostics_digest'],plan_sha256=result['plan']['sha256'],
       policy_sha256=result['policy_sha256'],trial_policy_sha256=result['trial_policy_sha256'],qualified_result=rr,synthetic=observation['synthetic'],rehearsal_synthetic=FIXTURE,fixture_scope=CONTEXT.get('fixture_scope') if FIXTURE else None,
       window=window,counts=diag['counts'],uncertainty=diag['uncertainty'],vertical=vertical.normalized(block),
       limitations=['Private terrain only; MLLW realization unknown; producer uncertainty is not calibrated accuracy; native grid support is not continuous coverage; no habitat/publication/navigation acceptance.'],
       original_source_reads=0,review_resources=bounded,release_context_sha256=hashlib.sha256(CONTEXT_PATH.read_bytes()).hexdigest())
    if a.phase=='qualify':
        doc.update(schema='coastal-derived-window-review-v1',scope='qualified-array-mapping',decision='accept' if not holds else 'hold',
            native_facts_digest=fd,facts_digest=digest(dict(qualified_result=rr,facts_digest=fd)))
    out=R/'metadata'/('independent-'+a.label+'-'+a.phase+'-review.json')
    if out.exists():raise ValueError('preserve original review')
    d,grant=index()
    put(out,doc,root=R)
    print(json.dumps(dict(review=ref(R,out,doc['schema']),quality_accepted=not holds,original_source_reads=0)))
if __name__=='__main__':main()
