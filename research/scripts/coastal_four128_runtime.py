"""Private ordered live controls. No native dispatch without parent release command."""
import argparse,json,os,sys,time,hashlib,subprocess
from pathlib import Path
# Mission root, code root and interpreter were pinned to the 2026-10-11 attempt.
# A fresh run names its own (absent) mission root and the exact checkout/venv it
# runs from; defaults keep the historical attempt's identity readable.
N=Path(os.environ.get('SKIPPERCAST_FOUR128_MISSION_ROOT','/home/user/skippercast-data/2026-10-07-pge-south/outputs/ordered-four128-approved-20261011'))
W=Path(os.environ.get('SKIPPERCAST_FOUR128_CODE_ROOT','/home/user/skippercast-data/2026-10-07-pge-south/work/source-reuse-admission-20261011'))
PYTHON=os.environ.get('SKIPPERCAST_FOUR128_PYTHON','/home/user/skippercast-data/2026-10-07-pge-south/repo/.venv/bin/python')
R=N/'execution'; M=N/'mapping-execution'
sys.dont_write_bytecode=True
sys.path.insert(0,str(W/'src'))
sys.path.insert(0,'/home/user/skippercast-data/2026-10-07-pge-south/work/combined-coastal-integration-20261009/var/python-integration-dependencies')
sys.path.insert(0,str(Path(__file__).parent))
from coastal_four128_resources import capture,UNITS
from skippercast.coastal.receipts import managed_writes, atomic_json, digest as receipt_digest
from skippercast.coastal.output_writer import ManagedOutputs

from skippercast.coastal.coordinator.packet_release import validate_acquisition_package
from skippercast.coastal.coordinator.ordered_trial import Controller,RealAdapter,prepare,inventory,ACTION
from skippercast.coastal.coordinator.authenticated import metadata_document,INPUT_CONTRACT,actual_unit_check,_source_identity

def policy_for(grant):
    """Native Store policy for one exact authenticated grant.

    Ported verbatim from the unmerged coordinator/authenticated_cli.py the 2026-10-11
    harness imported; main never shipped that module."""
    from importlib.resources import files
    from skippercast.coastal.authenticated_v1.profiles import profile,grant_identity
    grant_identity(grant);selected=profile(grant.get("execution_profile"),grant)
    _source_identity(grant["source"])
    if grant.get("schema")!="coastal-authenticated-policy-v1":raise ValueError("immutable authenticated grant required")
    policy=json.loads(files("skippercast.coastal.coordinator").joinpath("policy.json").read_text())
    policy.update(authenticated=grant,max_attempts=1,stagnation_s=selected["mission_seconds"],
        budgets=dict(wall_s=selected["mission_seconds"],reserve_s=60,bytes=selected["reservations"]*grant["source"]["bytes"],requests=0,tokens=0))
    policy["storage"]["job_output_bytes"]=4194304
    return policy
from skippercast.coastal.coordinator.loop import implementation_hashes
from skippercast.coastal.coordinator.store import Store
from skippercast.coastal.coordinator.source_free import policy as mapping_policy
from skippercast.coastal.handoff.common import load,write,ref,epoch
SLICE='skippercast-four128approved20261011.slice'
ROOTS=[str(N)]
SCRATCH=Path('/home/user/skippercast-data/2026-10-07-pge-south/scratch/four128-approved-20261011')
PRIOR_SOURCE=821491388
SOURCE_LIMIT=1115551932
WALL=3600

def control_ceiling(path):
    path=Path(path)
    if path.parent==R/'metadata':
        name=path.name
        if name.startswith('qualify-'):return 65536
        if name.startswith('map-packet-'):return 16384
        if name.startswith('map-plan-'):return 32768
        if name.startswith('unit-'):return 8192
        if name.startswith('action-'):return 4096
        if name.startswith('independent-') and name.endswith('-review.json'):return 65536
        if name.endswith('-descriptor.json'):return 1024
        if name=='live-preparation.json':return 8192
    if path.parent==N/'control':
        if path.name.startswith('step-'):return 8192
        if path.name.startswith('launch-'):return 4096
        if path.name in ('outer-clock.json','run-started.json','driver-envelope.json',
                         'parent-envelope.json','resource-probe.json','batch-completed.json','final-stop.json','native-clock-binding.json','finite-capacity-preflight.json','closed-finite-carry.json'):
            return 8192
    raise ValueError('unreviewed finite control family: '+str(path))

def put(path,doc,root=R):
    if path.exists():raise ValueError('preserve existing artifact: '+str(path))
    grant=load(R,json.loads((R/'metadata/live-index.json').read_text())['grant'])
    raw=(json.dumps(doc,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    if len(raw)>control_ceiling(path):raise ValueError('bounded immutable control family receipt')
    manager=ManagedOutputs(N,grant,receipt_digest(grant))
    if not manager.write_bytes(manager.relative_path(path),raw,role='control',max_bytes=len(raw),
                               intent='control:'+manager.relative_path(path)):
        raise ValueError('immutable control receipt already committed')
    return ref(root,path,doc['schema'])
def validate_science(science,grant,*,now,horizon):
    from skippercast.coastal.coordinator.ordered_trial import LARGER_WINDOWS
    windows=LARGER_WINDOWS
    if (science.get('schema')!='coastal-ordered-independent-scientific-preflight-v1'
            or science.get('independent') is not True
            or science.get('status')!='PASS_EXPECTED_SOURCE_METADATA_GEOMETRY_STRICT_POLICY'
            or science.get('source')!=grant['source']
            or science.get('native_window_set')!=windows
            or science.get('window_count')!=4 or type(science.get('window_count')) is not int
            or science.get('window_side')!=128 or type(science.get('window_side')) is not int
            or science.get('holds_added')!=[]
            or not epoch(science['checked_at'])<=now<horizon<epoch(science['valid_until'])
            or science.get('scientific_acceptance') is not False
            or science.get('current_source_identity_verified') is not False or science.get('rehearsal_synthetic',False) is not False):
        raise ValueError('independent preflight status/scope/source/freshness differs')
    return True
def validate_runtime_review(d,review,*,now,horizon=None):
    if review.get('independent') is not True or review.get('status')!='PASS_EXACT_FINITE_PRELAUNCH' or review.get('holds')!=[] or review.get('grant')!=d['grant']:
        raise ValueError('current independent runtime acceptance required')
    bindings=('runtime_controls','controller_sha256','code_sha','deps_sha','carry','independent_preflight','prior_output_carry','prior_scratch_carry','prior_scratch_bytes')
    if any(review.get(key)!=d.get(key) for key in bindings):
        raise ValueError('independent review differs from exact runtime/code/carry/science bindings')
    if not d['runtime_controls'] or {item['path'] for item in d['runtime_controls']}!={
            'research/scripts/coastal_four128_runtime.py','research/scripts/coastal_four128_resources.py',
            'research/scripts/coastal_four128_artifact_review.py'}:
        raise ValueError('complete independently reviewed control set required')
    horizon=now+3600 if horizon is None else horizon
    if not epoch(review['checked_at'])<=now<horizon<epoch(review['valid_until']):
        raise ValueError('independent runtime review expired')
    return True

def index():
    for root in (N,R,M):
        if root.is_symlink() or not root.is_dir() or root.stat().st_uid!=os.getuid():
            raise ValueError('exact owned runtime roots required')
    p=R/'metadata/live-index.json'
    if p.stat().st_size>131072:raise ValueError('index cap')
    d=json.loads(p.read_text())
    if d['schema']!='coastal-ordered-live-index-v1':raise ValueError('index contract')
    if hashlib.sha256((W/'src/skippercast/coastal/coordinator/ordered_trial.py').read_bytes()).hexdigest()!=d['controller_sha256']:raise ValueError('controller code changed')
    code,deps=implementation_hashes(R)
    if (code,deps)!=(d['code_sha'],d['deps_sha']):raise ValueError('implementation changed')
    grant=metadata_document(R,d['grant'],'coastal-authenticated-policy-v1')
    if grant.get('execution_authorized') is not True:raise ValueError('grant held')
    packets=[metadata_document(R,rr,INPUT_CONTRACT) for rr in d['requests']]
    context=json.loads((N/'control/release-context.json').read_text())
    if context['source']!=grant['source']:raise ValueError('context source differs from exact grant')
    science=metadata_document(R,d['independent_preflight'],d['independent_preflight']['contract'])
    if context['windows']!=grant['window_set'] or context['metadata_sha256']!=science['expected_metadata_sha256']:
        raise ValueError('exact metadata/grid review differs')
    if grant.get('larger_runtime_contract')!='coastal-managed-eight-copy-four128-v1' or grant.get('source_reuse_contract') is not None:
        raise ValueError('exact reviewed eight-copy runtime contract required')
    if grant['output_root']!=str(N) or grant['output_retention']['profile']!='coastal-managed-output-32-v3':
        raise ValueError('exact compact cumulative output admission required')
    review=metadata_document(R,d['independent_runtime_review'],'coastal-four128-independent-prelaunch-v1')
    review_now=time.time()
    review_horizon=load(R,prepref())['deadline_epoch'] if (R/'metadata/live-preparation.json').exists() else review_now+3600
    validate_runtime_review(d,review,now=review_now,horizon=review_horizon)
    for item in d['runtime_controls']:
        path=W/item['path']
        if path.is_symlink() or path.stat().st_size!=item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('runtime control code changed')
    output_carry=metadata_document(R,d['prior_output_carry'],'coastal-source-reuse-engineering-carry-v1')
    scratch_carry=metadata_document(R,d['prior_scratch_carry'],'coastal-source-reuse-engineering-carry-v1')
    if (output_carry.get('closed') is not True or scratch_carry.get('closed') is not True
            or output_carry['retained_output']['cumulative_prior_bytes']!=grant['output_retention']['prior_retained_bytes']
            or type(d['prior_scratch_bytes']) is not int
            or d['prior_scratch_bytes']!=scratch_carry['scratch']['charged_prior_bytes']
            or d['prior_scratch_bytes']+536870912>2147483648):
        raise ValueError('exact retained/scratch carry quantities differ from reviewed grant/index')
    metadata_document(R,d['carry'],'coastal-authenticated-carry-v1')
    science=metadata_document(R,d['independent_preflight'],d['independent_preflight']['contract'])
    if science.get('native_operations',0)!=0:raise ValueError('preflight native assertion differs')
    now=time.time()
    frozen=R/'metadata/live-preparation.json'
    horizon=load(R,prepref())['deadline_epoch'] if frozen.exists() else now+3600
    validate_science(science,grant,now=now,horizon=horizon)
    checked=validate_acquisition_package(R,d['grant'],d['requests'],now=now,horizon=horizon,validation_mode='released')
    if checked['status']!='PASS_METADATA_ONLY':raise ValueError('full exact released acquisition chain held: '+json.dumps(checked['packets']))
    return d,grant
def envelope(key):
    doc=capture(key)
    # Controller native preflight uses epoch arithmetic before Store unit_context.
    doc['phase_unit_start_utc_iso']=doc['phase_unit_start_utc']
    doc['phase_unit_start_utc']=epoch(doc['phase_unit_start_utc'])
    parent=Path('/sys/fs/cgroup'+doc['cgroup_path']).parent
    if parent.name!=SLICE:raise ValueError('lane outside shared parent slice')
    readings={f:(parent/f).read_text().strip() for f in ('memory.max','memory.swap.max','cpu.max','pids.max')}
    if readings!={'memory.max':'3221225472','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'96'}:raise ValueError('shared aggregate envelope mismatch')
    doc['shared_parent']=dict(slice=SLICE,path=str(parent),readings=readings)
    rr=put(R/('metadata/unit-'+key+'.json'),doc)
    actual_unit_check(dict(root=str(R),unit_context=rr,source_grant=index()[1]['source'],phase_unit_start_monotonic=doc['phase_unit_start_monotonic']))
    return rr,doc
def stores(grant):
    p=policy_for(grant)
    p['watermarks']=dict(high=3,low=1,held_cap=8)
    p['storage']['total_bytes']=33554432
    mp=mapping_policy();mp['managed_output_grant']=grant
    return Store(R/'var/coastal/authenticated.sqlite',root=R,policy=p),Store(M/'var/coastal/ordered-map.sqlite',root=M,policy=mp)
def prepref():
    p=R/'metadata/live-preparation.json'
    return ref(R,p,'coastal-ordered-trial-preparation-v1')
def execute(key,request=None,mapping_plan=None,hold=None):
    d,grant=index();gate(key);ur,unit=envelope(key)
    if key=='probe':
        put(N/'control/resource-probe.json',dict(schema='coastal-ordered-resource-probe-v1',unit=unit,native_operations=0,Store_created=False,Budget_created=False),root=N)
        return dict(state='resource_probe_pass',native_operations=0)
    label,stage=key.split('-');i='ABCD'.index(label)
    if not (R/'metadata/live-preparation.json').exists():
        if key!='A-acquire':raise ValueError('only first native scope may freeze parent')
        start=unit['phase_unit_start_utc']
        # Nativemission retains exactactual first-unit origin; earlierouterwatchdog remains authoritative.
        preparation=prepare(R,d['grant'],d['requests'],start_epoch=start,deadline_epoch=start+3600,
            start_monotonic=unit['phase_unit_start_monotonic'],boot_id=unit['boot_id'],
            cumulative_limit_bytes=SOURCE_LIMIT,prior_effective_bytes=PRIOR_SOURCE,
            output_roots=ROOTS,scratch_roots=[str(SCRATCH)],output_cap_bytes=33554432,scratch_cap_bytes=536870912)
        put(R/'metadata/live-preparation.json',preparation)
        outer=load_clock()
        put(N/'control/native-clock-binding.json',dict(schema='coastal-four128-clock-binding-v1',
            owner_outer_start_monotonic=outer['start_monotonic'],owner_outer_deadline_monotonic=outer['deadline_monotonic'],
            native_start_monotonic=unit['phase_unit_start_monotonic'],native_deadline_monotonic=unit['phase_unit_start_monotonic']+3600,
            startup_offset_seconds=unit['phase_unit_start_monotonic']-outer['start_monotonic'],
            actual_execution_deadline='earlier owner outer clock enforced by verified shared watchdog and every phase gate'),root=N)
    pr=prepref();frozen=load(R,pr)
    if time.time()+120>=frozen['deadline_epoch']:raise ValueError('parent drain horizon exhausted')
    action=dict(schema=ACTION,preparation=pr,index=i,stage='qualify' if stage=='hold' else stage)
    if stage in ('acquire','qualify'):
        action.update(released_grant=d['grant'],carry=d['carry'],unit=ur,
            request=d['requests'][i] if stage=='acquire' else supplied(request))
    elif stage=='map':action['mapping_plan']=supplied(mapping_plan)
    elif stage=='hold':action['review_hold']=supplied(hold)
    else:raise ValueError('finite stage')
    ar=put(R/('metadata/action-'+key+'.json'),action)
    native,mapping=stores(grant)
    try:
        c=Controller(R,pr);adapter=RealAdapter(native,mapping)
        outcome=c.step(adapter,ar)
        status=c.status(adapter)
        intents=status.pop('intents')
        status['durable_intents_summary']=dict(count=len(intents),sha256=receipt_digest(intents),
            authoritative_state='ordered-controller durable checkpoint; full intents retained there')
        result=dict(schema='coastal-ordered-live-step-v1',key=key,outcome=outcome,
            status=status,inventory=inventory(frozen),aggregate_inventory=audit(),native_budget=adapter.accounting(frozen),
            unit=ur,parent_preparation=pr)
        put(N/('control/step-'+key+'.json'),result,root=N)
        return result
    finally:mapping.close();native.close()
def supplied(path):
    if not path:raise ValueError('independently prepared exact descriptor file required')
    p=Path(path)
    if not p.is_relative_to(R/'metadata') or p.is_symlink() or p.stat().st_size>4096:raise ValueError('owned descriptor admission')
    d=json.loads(p.read_text())
    if set(d)!={'path','bytes','sha256','contract'}:raise ValueError('exact descriptor')
    load(R,d,contract=d['contract']);return d
def preflight():
    d,grant=index()
    now=time.time()
    p=prepare(R,d['grant'],d['requests'],start_epoch=now,deadline_epoch=now+3600,
        cumulative_limit_bytes=SOURCE_LIMIT,prior_effective_bytes=PRIOR_SOURCE,output_roots=ROOTS,scratch_roots=[str(SCRATCH)],output_cap_bytes=33554432,scratch_cap_bytes=536870912)
    return dict(schema='coastal-ordered-driver-preflight-v1',source_allowance_sufficient=p['source_allowance_sufficient'],
        execution_authorized=grant['execution_authorized'],actual_unit_unverified=True,native_operations=0,
        Store_created=False,Budget_created=False,inventory=inventory(p),aggregate_inventory=audit(),
        prospective_capacity=initial_capacity(),source_bytes_reserved=0)

def managed_configuration_for(grant,role,max_bytes):
    return dict(grant=grant,grant_digest=receipt_digest(grant),role=role,max_bytes=max_bytes)

def manager():
    d=json.loads((R/'metadata/live-index.json').read_text())
    grant=load(R,d['grant'])
    return ManagedOutputs(N,grant,receipt_digest(grant))

def audit():
    result=manager().audit()
    if result['unmanaged_control_bytes']:
        raise ValueError('unregistered retained output preserved; no downstream launch')
    scratch=0
    if SCRATCH.exists():
        for parent,dirs,files in os.walk(SCRATCH,followlinks=False):
            for name in dirs+files:
                path=Path(parent)/name
                if path.is_symlink():raise ValueError('trial scratch link')
                if path.is_file():scratch+=path.stat().st_size
    d=json.loads((R/'metadata/live-index.json').read_text())
    if scratch>536870912 or scratch+d['prior_scratch_bytes']>2147483648:
        raise ValueError('cumulative scratch allowance exhausted')
    return dict(**result,trial_scratch_bytes=scratch,prior_scratch_bytes=d['prior_scratch_bytes'])

def load_clock():
    path=N/'control/outer-clock.json'
    if path.is_symlink() or path.stat().st_size>4096:raise ValueError('bounded outer clock')
    d=json.loads(path.read_text())
    if d.get('schema')!='coastal-four128-outer-clock-v1' or d.get('wall_seconds')!=WALL:
        raise ValueError('immutable outer clock contract')
    for key in ('start_epoch','start_monotonic','deadline_epoch','deadline_monotonic'):
        if type(d.get(key)) not in (float,int) or not __import__('math').isfinite(d[key]):
            raise ValueError('finite outer clocks required')
    if d['deadline_epoch']!=d['start_epoch']+WALL or d['deadline_monotonic']!=d['start_monotonic']+WALL:
        raise ValueError('outer clock arithmetic changed')
    if d['boot_id']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise ValueError('outer boot changed')
    return d

def gate(key,*,duration=200):
    import math
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<=duration<=200:
        raise ValueError('bounded phase duration')
    d=load_clock();mono=time.monotonic()
    if not math.isfinite(mono) or mono<d['start_monotonic'] or mono+duration>=d['deadline_monotonic']-15:
        raise ValueError('outer drain horizon exhausted')
    if key in {w+'-'+phase for w in 'ABCD' for phase in ('acquire','qualify')}:
        if mono>d['deadline_monotonic']-1380 or mono+180>d['deadline_monotonic']-1200:
            raise ValueError('outer native cutoff exhausted')
    live_watchdog();audit();return d

def closed_sqlite(path):
    import sqlite3
    path=Path(path)
    for suffix in ('-wal','-journal'):
        pending=Path(str(path)+suffix)
        if pending.is_symlink() or pending.exists() and pending.stat().st_size:
            raise ValueError('closed producer required; nonempty journal preserved')
    connection=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
    connection.row_factory=sqlite3.Row
    return connection

def result(label,stage):
    from skippercast.coastal.handoff.common import digest
    d,g=index();wanted=digest(g['window_set']['ABCD'.index(label)])
    connection=closed_sqlite(R/'var/coastal/authenticated.sqlite')
    try:
        matches=[row for row in connection.execute('SELECT * FROM jobs WHERE stage=? AND state="done"',(stage,))
                 if json.loads(row['record_json']).get('window_key')==wanted]
        if len(matches)!=1:raise ValueError('exact unique committed window result required')
        row=matches[0]
        leases=connection.execute('SELECT DISTINCT lease_token FROM authenticated_artifacts WHERE job_id=? AND committed_result_sha=?',
                                  (row['job_id'],row['result_sha'])).fetchall()
        if len(leases)!=1:raise ValueError('exact committed lease required')
        path=R/'var/coastal/jobs'/row['job_id'].replace(':','-')/leases[0][0]/'output/result.json'
        rr=ref(R,path,'coastal-authenticated-stage-result-v1');doc=load(R,rr)
        if rr['sha256']!=row['result_sha'] or doc['stage']!=stage or doc['state']!='done':
            raise ValueError('committed result identity differs')
        return rr,doc
    finally:connection.close()

def qualify_request(label,review):
    d,g=index();rr,out=result(label,'acquire');observation=load(R,out['observation'])
    load(R,review,contract='coastal-private-input-review-v2')
    packet=load(R,d['requests']['ABCD'.index(label)])
    packet.update(stage='qualify',reviewed_observation=out['observation'],review=review,window=observation['window'],
                  vertical=observation['declared_vertical'],scientific_implementation=observation['native_facts']['implementation'])
    pr=put(R/('metadata/qualify-'+label+'.json'),packet)
    return put_descriptor('qualify-'+label,pr)

def map_request(label,review):
    d,g=index();rr,out=result(label,'qualify');observation=load(R,out['observation'])
    load(R,review,contract='coastal-derived-window-review-v1')
    packet=dict(schema='coastal-derived-window-v1',creator_id='private-four128-artifact-handoff',source_accessed=False,
                synthetic=observation['synthetic'],qualified_result=rr,scientific_review=review,rehearsal_synthetic=False)
    pr=put(R/('metadata/map-packet-'+label+'.json'),packet)
    plan=dict(schema='coastal-contained-mapping-plan-v1',side=128,packets=[pr],parent_grant=d['grant'],
              segment=load(R,d['requests'][0])['segment'],baselines=[],rehearsal_synthetic=False)
    plan_ref=put(R/('metadata/map-plan-'+label+'.json'),plan)
    return put_descriptor('map-plan-'+label,plan_ref)

def put_descriptor(name,descriptor):
    path=R/('metadata/'+name+'-descriptor.json')
    if path.exists():raise ValueError('preserve existing descriptor')
    raw=(json.dumps(descriptor,sort_keys=True,separators=(',',':'))+'\n').encode()
    if len(raw)>1024:raise ValueError('finite descriptor ceiling')
    m=manager();rel=m.relative_path(path)
    m.write_bytes(rel,raw,role='control',max_bytes=len(raw),intent='descriptor:'+rel)
    return str(path)

def unit_command(key,extra=(),*,runtime=180,wait=True):
    allowed={'probe'}|{w+'-'+phase for w in 'ABCD' for phase in ('acquire','qualify','map','review-acquire','review-qualify')}
    if key not in allowed and key not in ('watchdog','driver'):raise ValueError('exact finite unit key required')
    if type(runtime) is not int or not 0<runtime<=3600:raise ValueError('finite unit runtime')
    if key not in ('watchdog','driver') and runtime!=180:raise ValueError('fixed stage runtime')
    unit='skippercast-four128approved-'+key+'20261011.service' if key in ('watchdog','driver') else UNITS[key]
    argv=['/usr/bin/systemd-run','--user','--collect','--unit='+unit,'--slice='+SLICE,
          '--property=RuntimeMaxSec='+str(runtime),'--property=KillMode=control-group','--property=KillSignal=SIGKILL',
          '--property=MemoryMax=1073741824','--property=MemorySwapMax=0','--property=CPUQuota=200%',
          '--property=TasksMax=32','--property=LimitFSIZE=67108864','--property=WorkingDirectory='+str(W)]
    if wait:argv+=['--wait','--pipe']
    for k,v in {'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
                'MKL_NUM_THREADS':'1','GDAL_NUM_THREADS':'1','PROJ_NETWORK':'OFF',
                # Transient units do not inherit the caller's environment: carry the roots explicitly.
                'SKIPPERCAST_FOUR128_MISSION_ROOT':str(N),'SKIPPERCAST_FOUR128_CODE_ROOT':str(W),
                'SKIPPERCAST_FOUR128_PYTHON':PYTHON}.items():
        argv+=['--setenv='+k+'='+v]
    cpus=sorted(os.sched_getaffinity(0))[:2]
    argv+=['/usr/bin/taskset','-c',','.join(map(str,cpus)),
           PYTHON,'-I','-B']
    if '-review-' in key:
        label,_,phase=key.split('-')
        if len(extra)!=1:raise ValueError('one exact result descriptor required for review')
        argv+=[str(W/'research/scripts/coastal_four128_artifact_review.py'),label,phase,*extra]
    else:
        argv+=[str(Path(__file__).resolve()),key if key in ('watchdog','driver') else 'execute']
        if key not in ('watchdog','driver'):argv+=[key,*extra]
    return argv

def bounded_command(name,argv,*,seconds=200):
    from skippercast.coastal.runner import run_bounded
    d,grant=index()
    outcome=run_bounded(argv,intent=N/('control/launcher-'+name+'.json'),
                        scratch=N/('control/launcher-'+name),timeout_s=seconds,grace_s=1,
                        output_limit_bytes=2048,managed_output=managed_configuration_for(grant,'control',32768))
    receipt=dict(schema='coastal-four128-launch-v1',name=name,argv=argv,status=outcome.status,rc=outcome.rc,
                 elapsed_seconds=outcome.elapsed,intent=outcome.intent_path,stdout=outcome.stdout_path,stderr=outcome.stderr_path)
    put(N/('control/launch-'+name+'.json'),receipt,root=N)
    if outcome.status!='ok' or outcome.rc!=0:raise ValueError('finite command held; no retry: '+name)
    return receipt

def stop_trial(reason):
    completed=subprocess.run(['/usr/bin/systemctl','--user','stop',SLICE],capture_output=True,text=True,timeout=10)
    result=subprocess.run(['/usr/bin/systemctl','--user','show',SLICE,'--property=ActiveState','--property=ControlGroup'],
                          capture_output=True,text=True,timeout=5)
    props=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    empty=False
    cg=props.get('ControlGroup')
    if not cg and props.get('ActiveState')=='inactive':empty=True
    elif cg and cg.startswith('/') and '..' not in Path(cg).parts:
        cpath=Path('/sys/fs/cgroup'+cg)
        empty=not any(p.read_text().strip() for p in cpath.rglob('cgroup.procs')) if cpath.exists() else props.get('ActiveState')=='inactive'
    doc=dict(schema='coastal-four128-stop-proof-v1',reason=reason,stop_exit_code=completed.returncode,
             query_exit_code=result.returncode,properties=props,descendants_empty=empty,observed_monotonic=time.monotonic())
    if not (N/'control/final-stop.json').exists():put(N/'control/final-stop.json',doc,root=N)
    if completed.returncode or result.returncode or not empty:raise ValueError('trial stop proof uncertain')
    return doc

def duration_seconds(value):
    import re
    matches=re.findall(r'(\d+(?:\.\d+)?)(us|ms|s|min|h|d)',value)
    if not matches or ''.join(number+unit for number,unit in matches)!=value.replace(' ',''):
        raise ValueError('finite precise unit runtime required')
    factors={'us':.000001,'ms':.001,'s':1,'min':60,'h':3600,'d':86400}
    return sum(float(number)*factors[unit] for number,unit in matches)

def control_envelope(kind):
    import re
    if kind not in ('driver','watchdog'):raise ValueError('fixed control kind')
    clock=load_clock();mono=time.monotonic()
    membership=Path('/proc/self/cgroup').read_text().strip()
    if not membership.startswith('0::/') or '\n' in membership:raise ValueError('unified control membership')
    cg=membership[3:];leaf=Path('/sys/fs/cgroup'+cg);parent=leaf.parent
    unit='skippercast-four128approved-'+kind+'20261011.service'
    keys=('ExecMainPID','ControlGroup','RuntimeMaxUSec','ActiveState','InvocationID',
          'ExecMainStartTimestampMonotonic','KillMode','KillSignal','MemoryMax','TasksMax','CPUQuotaPerSecUSec')
    result=subprocess.run(['/usr/bin/systemctl','--user','show',unit,*['--property='+k for k in keys]],
                          capture_output=True,text=True,check=True,timeout=5)
    if len(result.stdout)>32768:raise ValueError('bounded unit response')
    props=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    expected={'memory.max':'3221225472','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'96'}
    readings={k:(parent/k).read_text().strip() for k in expected}
    leaf_expected=dict(expected,**{'memory.max':'1073741824','pids.max':'32'})
    leaf_readings={k:(leaf/k).read_text().strip() for k in leaf_expected}
    started=int(props.get('ExecMainStartTimestampMonotonic','0'))/1000000
    actual_runtime=duration_seconds(props.get('RuntimeMaxUSec',''))
    actual_deadline=started+actual_runtime
    if (parent.name!=SLICE or leaf.name!=unit or readings!=expected or leaf_readings!=leaf_expected
            or props.get('ExecMainPID')!=str(os.getpid()) or props.get('ControlGroup')!=cg
            or props.get('ActiveState')!='active' or not re.fullmatch('[0-9a-f]{32}',props.get('InvocationID',''))
            or props['InvocationID']=='0'*32 or props.get('KillMode')!='control-group' or props.get('KillSignal')!='9'
            or props.get('MemoryMax')!='1073741824' or props.get('TasksMax')!='32'
            or props.get('CPUQuotaPerSecUSec')!='2s' or not clock['start_monotonic']<=started<=mono
            or not 0<actual_runtime<=3600 or actual_deadline>clock['deadline_monotonic']-.5
            or len(os.sched_getaffinity(0))>2):
        raise ValueError('actual bounded shared control envelope differs')
    return dict(schema='coastal-four128-parent-envelope-v1',kind=kind,properties=props,
        cgroup=cg,readings=readings,leaf_readings=leaf_readings,boot_id=clock['boot_id'],
        deadline_monotonic=clock['deadline_monotonic']-15,actual_hard_deadline=actual_deadline,
        pid=os.getpid(),observed_monotonic=mono,original_source_reads=0)

def live_watchdog():
    clock=load_clock();path=N/'control/parent-envelope.json'
    if path.is_symlink() or path.stat().st_size>65536:raise ValueError('bounded watchdog receipt')
    doc=json.loads(path.read_text());props=doc['properties']
    unit='skippercast-four128approved-watchdog20261011.service'
    result=subprocess.run(['/usr/bin/systemctl','--user','show',unit,'--property=ActiveState',
                          '--property=ExecMainPID','--property=InvocationID','--property=ControlGroup'],
                          capture_output=True,text=True,check=True,timeout=5)
    current=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if (doc.get('kind')!='watchdog' or doc.get('boot_id')!=clock['boot_id']
            or current.get('ActiveState')!='active'
            or any(current.get(key)!=props.get(key) for key in ('ExecMainPID','InvocationID','ControlGroup'))
            or doc.get('deadline_monotonic')!=clock['deadline_monotonic']-15
            or not clock['start_monotonic']<=doc['observed_monotonic']<=time.monotonic()
            or doc['actual_hard_deadline']>clock['deadline_monotonic']-.5):
        raise ValueError('same live bounded watchdog invocation required')
    return True

def start():
    index();audit();clock=load_clock()
    put(N/'control/driver-envelope.json',control_envelope('driver'),root=N)
    runtime=__import__('math').floor(clock['deadline_monotonic']-time.monotonic())-2
    bounded_command('watchdog-start',unit_command('watchdog',runtime=runtime,wait=False),seconds=10)
    end=time.monotonic()+5
    while not (N/'control/parent-envelope.json').exists() and time.monotonic()<end:time.sleep(.1)
    if not (N/'control/parent-envelope.json').exists():raise ValueError('actual watchdog envelope absent')
    live_watchdog()
    bounded_command('probe',unit_command('probe'))
    if not (N/'control/resource-probe.json').exists():raise ValueError('actual stage resource probe absent')
    return clock

def watchdog():
    doc=control_envelope('watchdog');clock=load_clock()
    put(N/'control/parent-envelope.json',doc,root=N)
    while time.monotonic()<clock['deadline_monotonic']-15:
        time.sleep(min(1,max(0,clock['deadline_monotonic']-15-time.monotonic())))
    subprocess.run(['/usr/bin/systemctl','--user','stop',SLICE],timeout=10)

def review(label,phase):
    rr,out=result(label,phase);descriptor=put_descriptor('result-'+label+'-'+phase,rr)
    bounded_command(label+'-review-'+phase,unit_command(label+'-review-'+phase,[descriptor]))
    path=R/('metadata/independent-'+label+'-'+phase+'-review.json')
    doc=json.loads(path.read_text());review_ref=ref(R,path,doc['schema'])
    if doc.get('holds_added') or doc.get('quality_accepted') is not True:raise ValueError('native independent science HOLD')
    return review_ref

def launch_stage(label,phase,extra=()):
    key=label+'-'+phase;gate(key);bounded_command(key,unit_command(key,extra))
    step=json.loads((N/('control/step-'+key+'.json')).read_text())
    if step.get('outcome',{}).get('state')!='done':raise ValueError('semantic stage HOLD despite exit0')
    return step

def next_finite_phase(step):
    """The coordinator's own next decision, read from the durable step receipt.

    The 2026-10-11 driver walked A..D serially (acquire, qualify, map per window).
    The ordered coordinator pipelines instead: after A-qualify its bounded decision
    is B-acquire, and maps run once two qualified windows wait (or native work is
    exhausted). Controller.step refuses any action that differs from that decision,
    which is what stopped A-map. The driver therefore follows status.next and never
    picks a phase itself."""
    status=step.get('status') or {}
    if status.get('stop_reason') or status.get('archived'):raise ValueError('durable parent stopped or archived')
    decision=status.get('next') or {}
    if decision.get('state')=='complete':return None
    if (decision.get('state')!='ready' or decision.get('stage') not in ('acquire','qualify','map')
            or type(decision.get('index')) is not int or decision['index'] not in range(4)):
        raise ValueError('finite driver requires an exact ready coordinator decision: '+json.dumps(decision,sort_keys=True))
    return 'ABCD'[decision['index']],decision['stage']

def finite_driver():
    index();start()
    # Only A-acquire may freeze the parent preparation; every later phase is the
    # coordinator's recorded decision. Twelve phases at most (4 windows x 3 stages).
    phase=('A','acquire');seen=set();qualifiers={};mapping={}
    for _ in range(12):
        label,stage=phase;key=label+'-'+stage
        if key in seen:raise ValueError('duplicate finite phase decision: '+key)
        extra=()
        if stage=='qualify':
            if label not in qualifiers:raise ValueError('qualification lacks committed acquisition review')
            extra=['--request',qualifiers[label]]
        elif stage=='map':
            if label not in mapping:raise ValueError('mapping lacks committed qualification review')
            extra=['--mapping-plan',mapping[label]]
        step=launch_stage(label,stage,extra);seen.add(key)
        if stage=='acquire':qualifiers[label]=qualify_request(label,review(label,stage))
        elif stage=='qualify':mapping[label]=map_request(label,review(label,stage))
        phase=next_finite_phase(step)
        if phase is None:break
    else:raise ValueError('finite catalog exceeded twelve phases')
    if phase is not None or len(seen)!=12:raise ValueError('finite catalog did not complete')
    completed=dict(schema='coastal-four128-batch-completed-v1',windows=4,pairs=65536,
        original_source_bytes_reserved=294060544,downloads=0,completed_monotonic=time.monotonic())
    put(N/'control/batch-completed.json',completed,root=N)
    return dict(status='FINITE_DRIVER_COMPLETE_PENDING_EXTERNAL_STOP_PROOF',windows=4)

def initial_capacity():
    from skippercast.coastal.coordinator.authenticated import managed_native_graph_plan,managed_ledger_growth_bound
    d,grant=index();m=manager();m.audit()
    with m.lock():
        state=m._read()
        entries=state['files']
        if any(entry['role']!='control' or entry['state']!='complete' for entry in entries.values()):
            raise ValueError('only complete immutable initial controls allowed before clock')
        if any(not (name.startswith('execution/metadata/') or name=='control/release-context.json') for name in entries):
            raise ValueError('unexpected initial retained output family')
        reserved=sum(entry['bytes'] for entry in entries.values())
        bound=managed_native_graph_plan(grant,initial_control_bytes=reserved,initial_control_files=len(entries))
        bound["ledger_growth"]=managed_ledger_growth_bound(grant,entries)
    return bound

def run():
    # External observer owns no scientific subprocesses; all driver/phase supervisors are in SLICE.
    index();audit();bound=initial_capacity()
    if (N/'control/run-started.json').exists() or (N/'control/outer-clock.json').exists():
        raise ValueError('finite batch already attempted; no retry or clock reset')
    utc=time.time();mono=time.monotonic();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    clock=dict(schema='coastal-four128-outer-clock-v1',start_epoch=utc,start_monotonic=mono,
               deadline_epoch=utc+WALL,deadline_monotonic=mono+WALL,wall_seconds=WALL,boot_id=boot,
               source_prior_bytes=PRIOR_SOURCE,new_source_allowance=294060544,cleanup_reserve_seconds=15)
    put(N/'control/outer-clock.json',clock,root=N)
    put(N/'control/finite-capacity-preflight.json',bound,root=N)
    put(N/'control/run-started.json',dict(schema='coastal-four128-run-started-v1',started_epoch=utc,
        source_allowance=294060544,downloads=0,finite_windows=4),root=N)
    SCRATCH.mkdir(exist_ok=False)
    try:
        command=['/usr/bin/busctl','--user','call','org.freedesktop.systemd1','/org/freedesktop/systemd1',
                 'org.freedesktop.systemd1.Manager','StartTransientUnit','ssa(sv)a(sa(sv))',SLICE,'fail','5',
                 'Description','s','Skippercast private finite four128 trial','CPUQuotaPerSecUSec','t','2000000',
                 'MemoryMax','t','3221225472','MemorySwapMax','t','0','TasksMax','t','96','0']
        bounded_command('init-slice',command,seconds=10)
        remaining=__import__('math').floor(clock['deadline_monotonic']-time.monotonic())
        bounded_command('driver-start',unit_command('driver',runtime=remaining-2),seconds=remaining-15)
        marker=N/'control/batch-completed.json'
        if marker.is_symlink() or not marker.is_file():raise ValueError('no completed finite batch marker')
        doc=json.loads(marker.read_text())
        if (doc.get('windows'),doc.get('pairs'),doc.get('original_source_bytes_reserved'),doc.get('downloads'))!=(4,65536,294060544,0):
            raise ValueError('finite completion marker differs')
        if not clock['start_monotonic']<=doc['completed_monotonic']<clock['deadline_monotonic']-15:
            raise ValueError('finite completion exceeds outer deadline')
        stop_trial('finite four-area batch completed early')
        return dict(status='NATIVE_MAPPING_FINITE_BATCH_COMPLETE',original_source_bytes_reserved=294060544,
                    windows=4,pairs=65536,downloads=0,rendering='private artifact handoff pending separate acceptance')
    except BaseException:
        stop_trial('finite batch interrupted or held; no retry')
        raise

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['preflight','run','execute','watchdog','driver'])
    parser.add_argument('key',nargs='?');parser.add_argument('--request');parser.add_argument('--mapping-plan')
    args=parser.parse_args()
    if args.mode=='preflight':out=preflight()
    elif args.mode=='run':out=run()
    elif args.mode=='driver':out=finite_driver()
    elif args.mode=='watchdog':watchdog();return
    else:
        if args.key not in {'probe'}|{w+'-'+stage for w in 'ABCD' for stage in ('acquire','qualify','map')}:
            raise ValueError('fixed finite stage required')
        out=execute(args.key,args.request,args.mapping_plan)
        out=dict(key=args.key,state=out.get('state') or out.get('outcome',{}).get('state'),receipt='control/step-'+args.key+'.json')
    print(json.dumps(out,sort_keys=True))
if __name__=='__main__':main()
