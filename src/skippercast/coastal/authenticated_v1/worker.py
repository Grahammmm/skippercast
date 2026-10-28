"""Fixed reserved worker. Native reads require live lease authority; results stay quarantined."""
import argparse,copy,hashlib,json,math,os,stat,sys,time
from pathlib import Path
from skippercast.coastal.handoff.common import digest,epoch,ref,write
from .authority import bind_reserved_source
from .snapshot import authenticate
from .planner import read_header,plan_header
from .observer import produce_snapshot,verify_snapshot,libraries,implementation
from .supplement import summarize
from .policy import POLICY_SHA,policy_sha,evaluate,require_quality_review
from .profiles import profile

RESULT='coastal-authenticated-stage-result-v1'
AUTH='coastal-authenticated-finalized-proof-v1'
MAX_OUTPUT=4*1024*1024
def read_job(path):
    path=Path(os.path.abspath(path))
    if path.name!='job.json' or tuple(path.parts[-6:-3])!=('var','coastal','jobs'):
        raise ValueError('fixed owned job request namespace required')
    parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC);fd=-1
    try:
        for part in path.parts[1:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
            os.close(parent);parent=child
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=parent)
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or not 0<st.st_size<=2*1024*1024:raise ValueError('bounded single-link request required')
        data=b''
        while len(data)<st.st_size:
            part=os.read(fd,min(65536,st.st_size-len(data)))
            if not part:raise ValueError('request truncated')
            data+=part
        after=os.fstat(fd)
        if os.read(fd,1) or (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise ValueError('request changed')
        document=json.loads(data,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite request')))
        if not isinstance(document,dict):raise ValueError('object request required')
        return document
    finally:
        if fd>=0:os.close(fd)
        os.close(parent)
def validate_clock(job,*,utc_now=None,monotonic_now=None):
    """One same-boot persisted unit/mission clock; no reset or UTC rollback extension."""
    utc_now=time.time() if utc_now is None else utc_now
    monotonic_now=time.monotonic() if monotonic_now is None else monotonic_now
    selected=profile(job.get('execution_profile'),job)
    keys=('mission_start','overall_deadline','phase_unit_start','phase_deadline','deadline')
    utc={key:epoch(job[key+'_utc']) for key in keys}
    mono={key:job[key+'_monotonic'] for key in keys}
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (*utc.values(),*mono.values(),utc_now,monotonic_now)):
        raise ValueError('finite immutable unit/mission clocks required')
    for clock in (utc,mono):
        if (clock['overall_deadline']!=clock['mission_start']+selected['mission_seconds']
            or not clock['mission_start']<=clock['phase_unit_start']<=clock['mission_start']+selected['launch_horizon']
            or clock['phase_deadline']!=min(clock['phase_unit_start']+180,clock['overall_deadline'])
            or clock['deadline']!=min(clock['phase_unit_start']+120,clock['overall_deadline']-60)):
            raise ValueError('immutable overall/phase/cleanup clock contract invalid')
        if not selected['name'] and job['stage']=='acquire' and clock['phase_unit_start']!=clock['mission_start']:
            raise ValueError('mission starts at first actual acquire unit')
    if (utc_now<utc['phase_unit_start'] or monotonic_now<mono['phase_unit_start']
        or not utc_now<utc['deadline'] or not monotonic_now<mono['deadline']
        or abs((utc_now-utc['phase_unit_start'])-(monotonic_now-mono['phase_unit_start']))>2):
        raise ValueError('phase expired or UTC/monotonic anchor changed')
    return utc['deadline']
def runtime_limits():
    """Read existing actual cgroup caps, membership and affinity; never configures a service."""
    affinity=sorted(os.sched_getaffinity(0))
    if not affinity or len(affinity)>2:raise ValueError('two-CPU affinity enforcement unavailable')
    group=None
    for line in Path('/proc/self/cgroup').read_text().splitlines():
        if line.startswith('0::'):group=Path(os.path.normpath('/sys/fs/cgroup/'+line[3:].lstrip('/')))
    base=Path('/sys/fs/cgroup')
    if group is None or not group.is_relative_to(base):raise ValueError('cgroupv2 limits unavailable')
    leaf=group;memory=[];pids=[];cpu=[];chain=[]
    while True:
        st=group.stat();record=dict(path=str(group),device=st.st_dev,inode=st.st_ino)
        for filename,values in (('memory.max',memory),('pids.max',pids)):
            try:value=(group/filename).read_text().strip()
            except FileNotFoundError:
                if group!=base:raise
                record[filename]='root_unbounded';continue
            record[filename]=value
            if value!='max':
                number=int(value)
                if number<=0:raise ValueError('positive actual hard limit required')
                values.append(number)
        try:quota,period=(group/'cpu.max').read_text().split()
        except FileNotFoundError:
            if group!=base:raise
            quota,period='max','100000'
        record['cpu.max']=[quota,period]
        if int(period)<=0:raise ValueError('positive CPU period required')
        if quota!='max':
            if int(quota)<=0:raise ValueError('positive CPU quota required')
            cpu.append(int(quota)/int(period))
        chain.append(record)
        if group==base:break
        group=group.parent
    if not memory or min(memory)>1073741824 or not pids or min(pids)>32 or not cpu or min(cpu)>2:
        raise ValueError('hard1GiB/2CPU/32task limits unavailable')
    return dict(memory_bytes=min(memory),cpu_quota_capacity=min(cpu),pids_max=min(pids),affinity=affinity,
                cgroup_path=str(leaf),cgroup_chain=chain)
def limit_artifact_file_size():
    """Lower only the soft per-file limit AFTER the source-sized memfd exists."""
    import resource
    soft,hard=resource.getrlimit(resource.RLIMIT_FSIZE)
    target=MAX_OUTPUT if soft==resource.RLIM_INFINITY else min(soft,MAX_OUTPUT)
    if hard!=resource.RLIM_INFINITY:target=min(target,hard)
    if target<=0:raise ValueError('positive artifact file-size limit required')
    resource.setrlimit(resource.RLIMIT_FSIZE,(target,hard))
    return target
def output_check(out):
    total=0
    for directory,dirs,files in os.walk(out,followlinks=False):
        for name in (*dirs,*files):
            path=Path(directory)/name;st=path.lstat()
            if stat.S_ISLNK(st.st_mode) or (name in files and not stat.S_ISREG(st.st_mode)):raise ValueError('regular owned output only')
            if name in files:total+=st.st_size
    if total>MAX_OUTPUT:raise ValueError('known output aggregate exceeds4MiB')
    return total
def flush_outputs(out):
    for path in out.iterdir():
        if path.is_file():
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
    fd=os.open(out,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
def run(request_path,output_path):
    job=read_job(request_path)
    if job.get('execution_contract')!='coastal-authenticated-job-v1' or job.get('stage') not in ('acquire','qualify'):
        raise ValueError('explicit versioned acquire/qualify job required')
    domain=job.get('source_domain_grant', {})
    if domain.get('source_reuse_contract') is not None:
        raise ValueError('source reuse requires native FD/output bridge; original fallback forbidden')
    managed_scope=domain.get('ordered_scope_contract')=='coastal-ordered-four128-v2'
    if managed_scope and (not isinstance(job.get('managed_output_grant'),dict) or domain.get('larger_runtime_contract')!='coastal-managed-eight-copy-four128-v1'):
        raise ValueError('larger ordered scope requires native FD/output bridge; original fallback forbidden')
    caps=runtime_limits()
    packet,authority=bind_reserved_source(job,request_path,output_path)
    try:
        root=Path(os.path.abspath(job['root']));out=Path(os.path.abspath(output_path))
        phase=job['stage'];source=packet['source'];source_root=job['source_root'];started=time.time()
        selected=profile(packet.get('execution_profile'),packet);selected_sha=policy_sha(selected['name'],packet)
        if selected['name']=='coastal-contained-windows-v3' and any(packet.get(k)!=job.get(k) for k in ('window_side','window_count')):raise ValueError('contained worker binding changed')
        if packet.get('execution_profile')!=job.get('execution_profile'):raise ValueError('execution profile grant changed')
        if packet.get('support_policy')!=(job.get('source_domain_grant') or {}).get('support_policy'):raise ValueError('support policy grant changed')
        if packet.get('policy_sha256')!=selected_sha or packet.get('trial_policy_sha256')!=packet.get('trial_policy_evidence',{}).get('sha256'):
            raise ValueError('exact fixed-patch code policy and independently approved evidence required')
        deadline=validate_clock(job)
        if not started<deadline:raise ValueError('immutable phase deadline expired')
        if not out.is_relative_to(root/'var/coastal/jobs'/job['job_id'].replace(':','-')/job['lease_token']):
            raise ValueError('per-job/per-lease quarantine required')
        if out.exists() and any(out.iterdir()):raise ValueError('empty quarantine required')
        out.mkdir(parents=True,exist_ok=True)
        relative=out.relative_to(root).as_posix()
        manager=declarations=None
        if managed_scope:
            from skippercast.coastal.coordinator.authenticated import managed_native_outputs
            from skippercast.coastal.coordinator.ordered_trial import validate_scope_packet
            manager,declarations=managed_native_outputs(job)
            validate_scope_packet(root,job['managed_output_grant'],packet,now=time.time(),horizon=epoch(job['overall_deadline_utc']))
        def emit(path,document):
            if manager is None:return write(path,document)
            declared=declarations[Path(path).name]
            return manager.write_json(declared['name'],document,role='native',
                                      max_bytes=declared['max_bytes'],intent=declared['intent'])
        def mask_writer(path,values,mask_profile,description):
            declared=declarations[Path(path).name]
            return manager.write_geotiff(declared['name'],values,mask_profile,role='native',
                max_bytes=declared['max_bytes'],intent=declared['intent'],description=description)
        refs=[];captured=[]
        with authenticate(source_root,job['source_relative_path'],source['sha256'],source['bytes'],authority=authority) as view:
            limit_artifact_file_size()
            if phase=='acquire':
                expected=packet.get('metadata_sha256')
                if expected is None and packet['synthetic'] is not True:raise ValueError('native embedded metadata lineage required')
                # inspect/read_header validates expected metadata; derive only test fixture digest when absent.
                if expected is None:
                    from .metadata_bag import inspect_metadata
                    from urllib.parse import urlparse
                    expected=inspect_metadata(view,Path(urlparse(packet['source_row']['url']).path).name.split('_')[0])['metadata_sha256']
                header=read_header(view,source,packet['source_row'],expected,packet.get('vertical'))
                plan=plan_header(header,packet['fixed_center_plan'])
                window=plan['window'];block=header['vertical']
                emit(out/'header.json',header);refs.append(ref(root,out/'header.json','coastal-authenticated-header-v1'))
            else:
                reviewed=packet['registered_observation'];plan=packet['registered_plan']
                window=plan['window'];block=reviewed['declared_vertical'];expected=reviewed['metadata_sha256']
                require_quality_review(packet['registered_review'],facts_digest=reviewed['facts_digest'],
                    diagnostics_digest=packet['registered_diagnostics']['diagnostics_digest'],
                    plan_sha256=reviewed['plan']['sha256'],trial_policy_sha256=packet['trial_policy_sha256'],execution_profile=selected['name'],configuration=packet)
                if (window!=reviewed['window'] or plan['source']!=source
                    or plan['spec_sha256']!=digest(packet['fixed_center_plan'])
                    or plan.get('halo')!=0 or window[2:]!=[selected['side']]*2):
                    raise ValueError('fresh phase2 must use exact registered reviewed indices')
            emit(out/'plan.json',plan);plan_ref=ref(root,out/'plan.json','coastal-authenticated-window-plan-v1');refs.append(plan_ref)
            args=dict(segment_id=packet['segment_id'],segment=packet['segment'],window=window,vertical=block,
                      rights=packet['rights'],synthetic=packet['synthetic'],source_row=packet['source_row'],metadata_sha256=expected)
            observation=produce_snapshot(view,root,source,output_dir=relative,
                collector=captured.append,
                review=packet.get('review') if phase=='qualify' else None,
                mask_writer=mask_writer if manager else None,write_observation=manager is None,**args)
            if selected['name']:observation['execution_profile']=selected['name']
            if selected['name']=='coastal-contained-windows-v3':observation.update(window_side=selected['side'],window_count=selected['window_count'])
            if packet.get('support_policy') is not None:observation['support_policy']=packet['support_policy']
            observation['plan']=plan_ref
            observation['source_root']=source_root
            observation['source_relative_path']=job['source_relative_path']
            observation['accepted']=False
            observation['commit_required']=True
            observation_ref=None
            if manager is None:
                emit(out/'observation.json',observation)
                observation_ref=ref(root,out/'observation.json','coastal-authenticated-observation-v1')
            refs.append(observation['valid_support'])
            if observation_ref is not None:refs.append(observation_ref)
            result=dict(schema=RESULT,state='done' if not observation['machine_holds'] else 'held',rc=0 if not observation['machine_holds'] else 3,
                        accepted=False,qualification=False,holds=observation['machine_holds'],source=source,source_root=source_root,source_relative_path=job['source_relative_path'],
                        plan=plan_ref,observation=observation_ref,facts_digest=observation['facts_digest'],
                        provenance=dict(libs=libraries(),implementation=implementation(),synthetic=packet['synthetic'],
                                        runtime_limits=caps,scientific_observations=1 if phase=='acquire' else 2,
                                        paired_cells_per_observation=selected['pairs'],logical_pair_visits=selected['pairs'] if phase=='acquire' else 2*selected['pairs']))
            if len(captured)!=1:raise ValueError('exactly one producer same-return collector required')
            diagnostics=summarize(captured[0],observation['facts_digest'])
            evaluation=evaluate(diagnostics,observation['native_facts'],execution_profile=selected['name'],configuration=packet)
            evaluation['trial_policy_sha256']=packet['trial_policy_sha256']
            emit(out/'diagnostics.json',diagnostics)
            emit(out/'policy-evaluation.json',evaluation)
            import numpy as np
            array_payload={k:v for k,v in captured[0].items() if v is not None}
            if manager is None:np.savez_compressed(out/'arrays.npz',**array_payload)
            else:
                declared=declarations['arrays.npz']
                manager.write_npz(declared['name'],array_payload,role='native',
                                  max_bytes=declared['max_bytes'],intent=declared['intent'])
            result['diagnostics']=ref(root,out/'diagnostics.json','coastal-same-return-pair-diagnostics-v1')
            result['arrays']=ref(root,out/'arrays.npz','coastal-authenticated-arrays-v1')
            result['policy_evaluation']=ref(root,out/'policy-evaluation.json','coastal-fixed-patch-policy-evaluation-v1')
            result['policy_sha256']=selected_sha;result['trial_policy_sha256']=packet['trial_policy_sha256']
            result['policy_holds']=evaluation['holds']
            refs.extend([result['diagnostics'],result['arrays'],result['policy_evaluation']])
            observation.update(policy_sha256=selected_sha,trial_policy_sha256=packet['trial_policy_sha256'],
                diagnostics=result['diagnostics'],policy_ready=evaluation['paired_eligibility_quality_pass'],
                policy_holds=evaluation['holds'])
            previous_observation_ref=observation_ref
            emit(out/'observation.json',observation)
            observation_ref=ref(root,out/'observation.json','coastal-authenticated-observation-v1')
            if previous_observation_ref is None:refs.append(observation_ref)
            else:refs[refs.index(previous_observation_ref)]=observation_ref
            result['observation']=observation_ref
            if phase=='qualify':
                if observation['facts_digest']!=packet['registered_observation']['facts_digest']:raise ValueError('fresh producer facts differ from reviewed observation')
                verified_arrays=[]
                verified=verify_snapshot(view,root,observation,now=time.time(),
                    minimum_valid_until=epoch(job['overall_deadline_utc']),collector=verified_arrays.append)
                if verified['facts_digest']!=observation['facts_digest'] or len(verified_arrays)!=1:raise ValueError('producer/verifier facts/collector differ')
                verified_diagnostics=summarize(verified_arrays[0],verified['facts_digest'])
                verified_policy=evaluate(verified_diagnostics,verified['facts'],execution_profile=selected['name'],configuration=packet)
                verified_policy['trial_policy_sha256']=packet['trial_policy_sha256']
                if (verified_diagnostics['diagnostics_digest']!=diagnostics['diagnostics_digest']
                    or diagnostics['diagnostics_digest']!=packet['registered_diagnostics']['diagnostics_digest']):
                    raise ValueError('actual producer/verifier/reviewed diagnostics differ')
                emit(out/'verification.json',verified)
                emit(out/'verified-diagnostics.json',verified_diagnostics)
                emit(out/'verified-policy.json',verified_policy)
                result['verification']=ref(root,out/'verification.json','coastal-authenticated-verification-v1')
                result['verified_diagnostics']=ref(root,out/'verified-diagnostics.json','coastal-same-return-pair-diagnostics-v1')
                result['verified_policy']=ref(root,out/'verified-policy.json','coastal-fixed-patch-policy-evaluation-v1')
                refs.extend([result['verification'],result['verified_diagnostics'],result['verified_policy']])
                result.update(producer_facts_digest=observation['facts_digest'],verified_facts_digest=verified['facts_digest'])
                policy_holds=sorted(set(evaluation['holds']+verified_policy['holds']))
                result['policy_holds']=policy_holds
                result['holds']=sorted(set(verified['holds']+policy_holds))
            else:
                result['holds']=sorted(set(observation['machine_holds']+evaluation['holds']))
            result['state']='held' if result['holds'] else 'done'
            result['rc']=3 if result['holds'] else 0
            validate_clock(job)
            if runtime_limits()!=caps:raise ValueError('actual resource envelope changed')
            receipt=view.finalize()
        # No proof file/result/success stdout exists until normal validated context closure.
        proof=receipt.payload()
        proof.update(schema=AUTH,job_id=job['job_id'],lease_token=job['lease_token'],stage=phase,source=source,source_root=source_root,source_relative_path=job['source_relative_path'],
                     code_sha=job['code_sha'],deps_sha=job['deps_sha'],plan_sha256=plan_ref['sha256'],
                     observation_sha256=observation_ref['sha256'],facts_digest=observation['facts_digest'],
                     policy_sha256=selected_sha,trial_policy_sha256=packet['trial_policy_sha256'],
                     diagnostics_sha256=result['diagnostics']['sha256'],policy_evaluation_sha256=result['policy_evaluation']['sha256'])
        authority.check(source_root,job['source_relative_path'],source['sha256'],source['bytes'])
        validate_clock(job)
        if runtime_limits()!=caps:raise ValueError('actual resource envelope changed after closure')
        emit(out/'finalized-authentication.json',proof)
        auth_ref=ref(root,out/'finalized-authentication.json',AUTH);refs.append(auth_ref)
        result['finalized_authentication']=auth_ref
        for name in ('job_id','lease_token','stage','segment_id','code_sha','deps_sha','params_sha','input_manifest_sha','execution_contract'):
            result[name]=job[name]
        result['artifacts']=refs
        result['known_output_bytes_before_result']=output_check(out)
        emit(out/'result.json',result)
        output_check(out);flush_outputs(out)
        validate_clock(job)
        if runtime_limits()!=caps:raise ValueError('actual resource envelope changed before completion')
        result_ref=ref(root,out/'result.json',RESULT)
        completion=dict(schema='coastal-authenticated-completion-v1',job_id=job['job_id'],lease_token=job['lease_token'],
            code_sha=job['code_sha'],deps_sha=job['deps_sha'],result_sha256=result_ref['sha256'],result_bytes=result_ref['bytes'],
            artifacts_digest=digest(refs),finalized_authentication_sha256=auth_ref['sha256'],observation_sha256=observation_ref['sha256'])
        # Fixed bounded FINAL envelope is captured/hash-bound by actual supervisor.
        print(json.dumps(completion,sort_keys=True,separators=(',',':'),allow_nan=False),flush=True)
        return result['rc']
    finally:authority.close()
def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    try:return run(args.request,args.output)
    except (ValueError,TypeError,KeyError,OSError,RuntimeError) as error:
        print('authenticated worker refused: '+type(error).__name__+': '+str(error)[:1024],file=sys.stderr,flush=True)
        return 4
if __name__=='__main__':raise SystemExit(main())
