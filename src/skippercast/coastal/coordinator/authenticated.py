"""Versioned authenticated lane: metadata gates and reservation-owned workers.

Ordinary native jobs never inherit this lane through params or result fields.
No native bytes are resolved by these controller metadata helpers.
"""
import copy,hashlib,json,math,os,re,sqlite3,stat,sys,time
from pathlib import Path
from .stages import digest
from skippercast.coastal.handoff.common import epoch

EXECUTION_CONTRACT='coastal-authenticated-job-v1'
INPUT_CONTRACT='coastal-authenticated-input-v1'
RESULT_CONTRACT='coastal-authenticated-stage-result-v1'
OBSERVATION_CONTRACT='coastal-authenticated-observation-v1'
COMPLETION_CONTRACT='coastal-authenticated-completion-v1'
IDENTITY_FIELDS=('job_id','stage','segment_id','code_sha','deps_sha','params_sha','input_manifest_sha')
def metadata_document(root,artifact,contract,*,native_sha=None):
    """Only task-owned single-link bounded JSON metadata; never a source-ref resolver."""
    if native_sha is not None and artifact.get('sha256')==native_sha:raise ValueError('native bytes cannot be metadata')
    path=artifact.get('path')
    if (artifact.get('contract')!=contract or not isinstance(path,str)
        or not re.fullmatch(r'metadata/[A-Za-z0-9_-]+\.json',path)
        or type(artifact.get('bytes')) is not int or not 0<artifact['bytes']<=131072
        or not re.fullmatch('[a-f0-9]{64}',str(artifact.get('sha256','')))):
        raise ValueError('role-bound metadata namespace/identity required')
    root=Path(os.path.abspath(root))
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    file_fd=-1
    try:
        for part in (*root.parts[1:],'metadata'):
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            os.close(fd);fd=child
        name=path.split('/')[1]
        # Reject hardlink aliases BEFORE opening contents; fstat repeats after open.
        named=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode) or named.st_nlink!=1 or named.st_size!=artifact['bytes']:
            raise ValueError('single-link regular bounded metadata required')
        file_fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fd)
        opened=os.fstat(file_fd)
        if ((opened.st_dev,opened.st_ino,opened.st_size)!=(named.st_dev,named.st_ino,named.st_size)
            or opened.st_nlink!=1 or not stat.S_ISREG(opened.st_mode)):
            raise ValueError('metadata identity changed')
        data=b''
        while len(data)<artifact['bytes']:
            chunk=os.read(file_fd,artifact['bytes']-len(data))
            if not chunk:raise ValueError('metadata truncated')
            data+=chunk
        if os.read(file_fd,1) or hashlib.sha256(data).hexdigest()!=artifact['sha256']:
            raise ValueError('metadata bytes/hash changed')
        result=json.loads(data,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
        if not isinstance(result,dict) or result.get('schema')!=contract:
            raise ValueError('metadata schema mismatch')
        return result
    finally:
        if file_fd>=0:os.close(file_fd)
        os.close(fd)

def metadata_review_holds(document,facts_digest,*,now,deadline):
    """Frozen review predicates on an already confined immutable JSON byte-read."""
    holds=[]
    if (document.get('schema')!='coastal-private-input-review-v2' or document.get('independent') is not True
        or not isinstance(document.get('reviewer_id'),str) or not document['reviewer_id']
        or document['reviewer_id'].startswith('coastal.') or document.get('facts_digest')!=facts_digest):
        holds.append('independent_review_binding_invalid')
    try:
        if not epoch(document['checked_at'])<=epoch(now)<epoch(document['valid_until']):holds.append('review_expired_or_future')
        if epoch(document['valid_until'])<=epoch(deadline):holds.append('review_insufficient_validity')
    except (KeyError,ValueError,TypeError):holds.append('review_time_invalid')
    if document.get('decision') not in ('qualified_private_terrain','accept'):holds.append('review_not_accepted')
    added=document.get('holds_added')
    if not isinstance(added,list) or any(not isinstance(x,str) or not x for x in added):holds.append('review_holds_invalid')
    else:holds.extend(added)
    return sorted(set(holds))

def _owned_job_directory(job):
    if job.get('execution_contract')!=EXECUTION_CONTRACT or job.get('stage') not in ('acquire','qualify'):
        raise ValueError('versioned authenticated job required')
    if not re.fullmatch('job:[a-f0-9]{24}',str(job.get('job_id',''))) or not re.fullmatch('[a-f0-9]{32}',str(job.get('lease_token',''))):
        raise ValueError('job/lease identity invalid')
    root=Path(os.path.abspath(job['root']))
    return root/'var/coastal/jobs'/job['job_id'].replace(':','-')/job['lease_token']

def argv_for(job,request_path,output_path):
    _owned_job_directory(job)
    bootstrap=Path(__file__).parent.parent/'authenticated_v1/bootstrap.py'
    return [sys.executable,'-I',str(bootstrap),
            '--request',str(request_path),'--output',str(output_path)]

CLOCK_FIELDS=("mission_start_utc","mission_start_monotonic","overall_deadline_utc","overall_deadline_monotonic",
              "phase_unit_start_utc","phase_unit_start_monotonic","phase_deadline_utc","phase_deadline_monotonic",
              "deadline_utc","deadline_monotonic","mission_deadline_utc","boot_id")
def bounded_control_bytes(path,cap=2097152,*,expected=None):
    """Trusted runtime controls are still regular single-link bounded JSON."""
    path=Path(os.path.abspath(path));parent=os.open("/",os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC);fd=-1
    try:
        for part in path.parts[1:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
            os.close(parent);parent=child
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=parent)
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or not 0<st.st_size<=cap:raise ValueError("bounded runtime JSON required")
        data=b""
        while len(data)<st.st_size:
            block=os.read(fd,min(65536,st.st_size-len(data)))
            if not block:raise ValueError("runtime JSON truncated")
            data+=block
        if os.read(fd,1):raise ValueError("runtime JSON grew")
        if expected and (len(data)!=expected["bytes"] or hashlib.sha256(data).hexdigest()!=expected["sha256"]):raise ValueError("owned output bytes changed")
        return data
    finally:
        if fd>=0:os.close(fd)
        os.close(parent)

def bounded_control_json(path,cap=2097152):
    return json.loads(bounded_control_bytes(path,cap),parse_constant=lambda v:(_ for _ in ()).throw(ValueError("nonfinite JSON")))

def owned_output_bytes(root,job,token,artifact):
    """No general resolver: exact single-link per-lease output and content identity."""
    prefix=Path("var/coastal/jobs")/job["job_id"].replace(":","-")/token/"output"
    path=Path(artifact["path"])
    if (path.parent!=prefix or path.name in (".","..") or type(artifact.get("bytes")) is not int
        or not 0<artifact["bytes"]<=4194304 or artifact.get("sha256")==job["source_grant"]["sha256"]):
        raise ValueError("owned bounded output identity required")
    return bounded_control_bytes(Path(root)/path,4194304,expected=artifact)

def captured_result_ref(authority,job,token):
    with authority._lock():
        entry=authority._read()["reservations"][token];execution=authority._bound_execution(entry)
        stdout=Path(execution["intent_path"]).with_name("stdout.log")
        completion=bounded_control_json(stdout,16384)
    if completion.get("schema")!=COMPLETION_CONTRACT or completion.get("job_id")!=job["job_id"] or completion.get("lease_token")!=token:
        raise ValueError("captured completion identity invalid")
    ref=dict(path=(_owned_job_directory(dict(job,lease_token=token))/"output/result.json").relative_to(Path(job["root"])).as_posix(),
             bytes=completion["result_bytes"],sha256=completion["result_sha256"],contract=RESULT_CONTRACT,kind="result")
    owned_output_bytes(job["root"],job,token,ref)
    return ref


NATIVE_OUTPUT_KIB=dict(header=64,plan=64,observation=256,diagnostics=64,
    **{'policy-evaluation':32,'verification':128,'verified-diagnostics':64,
       'verified-policy':32,'finalized-authentication':128,'result':128})
NATIVE_OUTPUT_BRIDGE='coastal-eight-copy-managed-native-v1'
def managed_native_outputs(job,token=None,*,reserve=False):
    """One immutable native file envelope, admitted before the source reservation."""
    from skippercast.coastal.output_writer import ManagedOutputs
    from skippercast.coastal.authenticated_v1.profiles import grant_identity,CONTAINED
    grant=job.get('managed_output_grant')
    if (not isinstance(grant,dict) or grant.get('ordered_scope_contract')!='coastal-ordered-four128-v2'
        or grant.get('larger_runtime_contract')!='coastal-managed-eight-copy-four128-v1'
        or grant.get('output_retention',{}).get('profile') not in ('coastal-managed-output-32-v2','coastal-managed-output-32-v3')
        or grant.get('source_reuse_contract') is not None or grant.get('execution_authorized') is not True
        or grant_identity(grant)!=job.get('source_domain_grant')
        or grant.get('execution_profile')!=CONTAINED
        or grant.get('window_side')!=128 or grant.get('window_count')!=4):
        raise ValueError('explicit released eight-copy managed native grant required')
    owned=dict(job,lease_token=token or job.get('lease_token'))
    directory=_owned_job_directory(owned)/'output'
    manager=ManagedOutputs(grant['output_root'],grant,digest(grant))
    if not directory.is_relative_to(manager.root):
        raise ValueError('native output escapes immutable managed mission root')
    caps={name+'.json':kib*1024 for name,kib in NATIVE_OUTPUT_KIB.items()}
    if job['stage']=='acquire':
        for name in ('verification.json','verified-diagnostics.json','verified-policy.json'):caps.pop(name)
    else:caps.pop('header.json')
    caps.update({'arrays.npz':512*1024,'native-support.tif':64*1024})
    if sum(caps.values())>2*1024*1024:
        raise ValueError('native envelope exceeds finite per-phase allowance')
    declarations={}
    for filename,maximum in caps.items():
        name=manager.relative_path(directory/filename)
        intent=digest(dict(bridge=NATIVE_OUTPUT_BRIDGE,job_id=job['job_id'],lease_token=owned['lease_token'],
                           filename=filename,input_manifest=job['input_manifest'],code_sha=job['code_sha'],deps_sha=job['deps_sha']))
        declarations[filename]=dict(name=name,max_bytes=maximum,intent=intent)
        if reserve:manager.reserve_file(name,role='native',max_bytes=maximum,intent=intent)
    with manager.lock():
        state=manager._read();manager._audit(state)
        for declaration in declarations.values():
            entry=state['files'].get(declaration['name'])
            if (not entry or entry['role']!='native' or entry['bytes']!=declaration['max_bytes']
                or entry['intent']!=declaration['intent']):
                raise ValueError('native envelope was not admitted before source reservation')
    return manager,declarations


class _ManagedNativeRetention:
    """Compatibility adapter over the single managed ledger, never a second cap."""
    def __init__(self,job,*,reserve=False):
        self.job=job
        self.manager,self.declarations=managed_native_outputs(job,reserve=reserve)
        self.slot='managed-native-'+digest([job['window_key'],job['stage'],job['lease_token']])
        self.directory=_owned_job_directory(job).relative_to(Path(job['root'])).as_posix()
        self.intent=digest(dict(job_id=job['job_id'],stage=job['stage'],window_key=job['window_key'],
            input_manifest=job['input_manifest'],code_sha=job['code_sha'],deps_sha=job['deps_sha']))
    def reserve(self,slot,intent,directory,*,role):
        if (slot,intent,directory,role)!=(self.slot,self.intent,self.directory,'native'):
            raise ValueError('managed native phase identity changed')
        return self.audit()
    def audit(self):
        return self.manager.audit()
    def settle(self,slot,*,completed):
        if slot!=self.slot or completed is not True:raise ValueError('exact completed managed phase required')
        with self.manager.lock():
            state=self.manager._read();self.manager._audit(state)
            for declared in self.declarations.values():
                entry=state['files'][declared['name']]
                path=self.manager._target(declared['name'])
                if (entry['state']!='complete' or path.stat().st_size!=entry.get('actual_bytes')
                    or hashlib.sha256(path.read_bytes()).hexdigest()!=entry.get('sha256')):
                    raise ValueError('managed native output incomplete or changed before commit')
        return self.audit()

def output_retention(job,token=None,*,create=False):
    """Immutable grant-bound output slot, covering the entire owned lease tree."""
    from skippercast.coastal.authenticated_v1.profiles import grant_identity,profile
    from skippercast.coastal.retention import Retention
    if job.get('source_domain_grant',{}).get('ordered_scope_contract')=='coastal-ordered-four128-v2':
        managed=_ManagedNativeRetention(dict(job,lease_token=token or job.get('lease_token')),reserve=create)
        return managed,managed.slot,managed.intent,managed.directory
    selected=profile(job.get('execution_profile'),job)
    if not selected['name']:raise ValueError('larger profile output reservation required')
    grant=grant_identity(job['source_domain_grant'])
    if grant.get('execution_profile')!=selected['name']:raise ValueError('retention profile grant changed')
    if selected['name']=='coastal-contained-windows-v3' and any(job.get(k)!=grant.get(k) for k in ('window_side','window_count')):raise ValueError('retention contained grant changed')
    windows=grant['window_set'];keys=[digest(window) for window in windows]
    if job.get('window_key') not in keys or job.get('stage') not in ('acquire','qualify'):
        raise ValueError('retention outside finite native grant')
    slot='native-'+('ABCD'[keys.index(job['window_key'])])+'-'+job['stage']
    owned=dict(job,lease_token=token or job.get('lease_token'))
    directory=_owned_job_directory(owned).relative_to(Path(job['root'])).as_posix()
    intent=digest(dict(job_id=job['job_id'],stage=job['stage'],window_key=job['window_key'],
                      input_manifest=job['input_manifest'],code_sha=job['code_sha'],deps_sha=job['deps_sha']))
    retention=Retention(job['root'],digest(grant))
    if create and not retention.path.exists():retention=Retention.create(job['root'],digest(grant))
    retention.read()
    return retention,slot,intent,directory

def require_output_retention(job,token=None):
    retention,slot,intent,directory=output_retention(job,token)
    if isinstance(retention,_ManagedNativeRetention):return retention,slot
    entry=retention.read()['reservations'].get(slot)
    if (not entry or entry.get('role')!='native' or entry.get('directory')!=directory
        or entry.get('intent_digest')!=intent or entry.get('bytes')!=4*1024*1024):
        raise ValueError('native output reservation identity missing or changed')
    return retention,slot

def authorize_worker(job,request_path,output_path,now=None):
    """Actual persisted lease + Budget target capability, never caller assertions."""
    from .store import process_identity
    from .loop import implementation_hashes
    now=time.time() if now is None else epoch(now)
    domain=job.get('source_domain_grant',{})
    if domain.get('saved_area_continuation_contract') is not None:
        from .saved_area import continuation_grant
        continuation_grant(domain)
        if job.get('window_key')==digest(domain['window_set'][0]):
            raise ValueError('adopted A native worker forbidden')
    check_context(job,now=now)
    actual_unit_check(job)
    if job.get('execution_profile'):require_output_retention(job)[0].audit()
    directory=_owned_job_directory(job)
    if Path(os.path.abspath(request_path))!=directory/"job.json" or Path(os.path.abspath(output_path))!=directory/"output":
        raise ValueError("worker paths differ from owned lease")
    if tuple(implementation_hashes(job["root"]))!=(job["code_sha"],job["deps_sha"]):
        raise ValueError("current worker implementation differs")
    # Paths are fixed from the artifact root; arbitrary job JSON cannot select a ledger.
    root=Path(os.path.abspath(job["root"]))
    if Path(job["store_path"])!=root/"var/coastal/authenticated.sqlite":raise ValueError("owned authenticated Store path required")
    connection=sqlite3.connect("file:"+job["store_path"]+"?mode=ro",uri=True);connection.row_factory=sqlite3.Row
    try:
        stored=connection.execute("SELECT j.record_json,j.state,l.token,l.expires,s.region,s.record_json AS segment_json FROM jobs j JOIN leases l USING(job_id) JOIN segments s USING(segment_id) WHERE j.job_id=?",(job["job_id"],)).fetchone()
        if not stored or stored["token"]!=job["lease_token"] or stored["expires"]<=now or stored["state"] not in ("claimed","running"):
            raise ValueError("worker fenced lease")
        record=json.loads(stored["record_json"])
        immutable=(*IDENTITY_FIELDS,*CLOCK_FIELDS,"execution_contract","input_manifest","budget","root","source_root","source_relative_path","source_grant","store_path","budget_ledger","unit_context","carry_ref","execution_profile","source_domain_grant","window_key","window_side","window_count","managed_output_grant")
        if any(job.get(field)!=record.get(field) for field in immutable):raise ValueError("worker immutable job identity changed")
        if job.get("segment")!=json.loads(stored["segment_json"]) or job.get("region")!=stored["region"]:raise ValueError("worker segment/region changed")
        mission=connection.execute("SELECT * FROM authenticated_missions WHERE region=?",(stored["region"],)).fetchone()
        if not mission or (mission["started_utc"],mission["started_monotonic"],mission["deadline_utc"],mission["deadline_monotonic"],mission["boot_id"])!=(job["mission_start_utc"],job["mission_start_monotonic"],job["overall_deadline_utc"],job["overall_deadline_monotonic"],job["boot_id"]):
            raise ValueError("worker immutable mission origin changed")
        grant=dict(schema="coastal-authenticated-policy-v1",source=job["source_grant"],source_root=job["source_root"],source_relative_path=job["source_relative_path"])
        if job.get("execution_profile"):
            from skippercast.coastal.authenticated_v1.profiles import grant_identity
            grant=grant_identity(job["source_domain_grant"])
        if (digest(grant)!=mission["limits_sha"] or mission["source_sha"]!=job["source_grant"]["sha256"]
            or mission["source_bytes"]!=job["source_grant"]["bytes"]):raise ValueError("persisted source domain grant changed")
        managed=job.get('managed_output_grant')
        if grant.get('ordered_scope_contract')=='coastal-ordered-four128-v2':
            from skippercast.coastal.authenticated_v1.profiles import grant_identity
            if not isinstance(managed,dict) or grant_identity(managed)!=grant:
                raise ValueError('managed output release differs from persisted source domain')
        elif managed is not None:
            raise ValueError('managed output release requires explicit ordered scope')
        expected_ledger=Path(job["store_path"]).parent/("budget-"+digest([Path(job["store_path"]).name,stored["region"]])+".json")
        if Path(job["budget_ledger"])!=expected_ledger:raise ValueError("worker ledger path differs")
        ledger=bounded_control_json(expected_ledger)
        entry=ledger.get("reservations",{}).get(job["lease_token"],{});execution=entry.get("execution",{})
        intent=bounded_control_json(directory/"intent.json")
        argv=argv_for(job,directory/"job.json",directory/"output")
        if (entry.get("state")!="reserved" or entry.get("candidate")!=job["job_id"]
            or entry.get("reserved")!={"bytes":job["budget"]["bytes"],"requests":0,"tokens":0}
            or execution.get("state")!="launching" or execution.get("intent_path")!=str(directory/"intent.json")
            or execution.get("argv_sha256")!=digest(argv) or intent.get("state")!="running" or intent.get("argv")!=argv
            or intent.get("byte_reservation")!=job["budget"]["bytes"]
            or not execution.get("execution_binding") or intent.get("execution_binding")!=execution["execution_binding"]
            or intent.get("boot_id")!=job["boot_id"] or intent.get("boot_id")!=execution.get("launch_boot_id")
            or intent.get("ownership_protocol")!="subreaper-pidfd-v1"
            or intent.get("env",{}).get("COASTAL_AUTH_REQUEST_SHA256")!=hashlib.sha256(bounded_control_bytes(request_path)).hexdigest()):
            raise ValueError("worker actual Budget execution binding invalid")
        current=process_identity();child=intent.get("child",{});supervisor=intent.get("supervisor",{})
        if any(str(current.get(k))!=str(child.get(k)) for k in ("host","boot_id","pid","start_ticks","pgid","sid")) or current.get("state") in (None,"Z","X"):
            raise ValueError("worker is not the Budget target process")
        if Path("/proc/self/cmdline").read_bytes().rstrip(b"\0").split(b"\0")!=[os.fsencode(value) for value in argv]:
            raise ValueError("actual fixed worker argv differs")
        from skippercast.coastal import runner
        expected_parent=[sys.executable,"-I",str(Path(runner.__file__).with_name("_runner_bootstrap.py")),"--supervise",str(directory/"intent.json")]
        if Path("/proc/"+str(os.getppid())+"/cmdline").read_bytes().rstrip(b"\0").split(b"\0")!=[os.fsencode(value) for value in expected_parent]:
            raise ValueError("actual trusted supervisor argv differs")
        parent=process_identity(os.getppid())
        if any(str(parent.get(k))!=str(supervisor.get(k)) for k in ("host","boot_id","pid","start_ticks","pgid","sid")) or parent.get("state") in (None,"Z","X"):
            raise ValueError("worker actual supervisor identity differs")
        return validate_input(job["root"],job["input_manifest"],stage=job["stage"],segment=job["segment"],
            code_sha=job["code_sha"],deps_sha=job["deps_sha"],now=now,mission_deadline=job["overall_deadline_utc"],connection=connection,expected_source=job["source_grant"],
            source_root=job["source_root"],source_relative_path=job["source_relative_path"])
    finally:connection.close()


def _source_identity(source):
    if not isinstance(source,dict) or not isinstance(source.get('path'),str):raise ValueError('typed source ref required')
    path=Path(source['path'])
    if (path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]=='metadata'
        or path.suffix.lower()!='.bag' or not re.fullmatch('[a-f0-9]{64}',str(source.get('sha256','')))
        or type(source.get('bytes')) is not int or not 0<source['bytes']<=64*1024*1024):
        raise ValueError('confined BAG source identity required')

def committed_document(connection,root,artifact,contract):
    """SQL generation is authority; writable staging files alone never suffice."""
    if artifact.get('contract')!=contract or not isinstance(artifact.get('path'),str):
        raise ValueError('committed artifact contract invalid')
    path=Path(artifact['path'])
    if (path.is_absolute() or '..' in path.parts or path.suffix!='.json'
        or type(artifact.get('bytes')) is not int or not 0<artifact['bytes']<=2097152):
        raise ValueError('bounded committed JSON required')
    owner=connection.execute(
        "SELECT a.*,j.state,j.result_sha FROM authenticated_artifacts a JOIN jobs j ON j.job_id=a.job_id WHERE a.path=? AND a.sha256=? AND a.bytes=?",
        (path.as_posix(),artifact['sha256'],artifact['bytes'])).fetchone()
    if not owner or owner['state']!='done' or owner['result_sha']!=owner['committed_result_sha'] or owner['contract']!=contract:
        raise ValueError('artifact has no current committed owner/generation')
    record=json.loads(connection.execute("SELECT record_json FROM jobs WHERE job_id=?",(owner["job_id"],)).fetchone()[0])
    loaded=json.loads(owned_output_bytes(root,record,owner["lease_token"],artifact))
    if loaded.get('schema')!=contract:raise ValueError('committed JSON schema invalid')
    return loaded

def validate_input(root,manifest_ref,*,stage,segment,code_sha,deps_sha,now,mission_deadline,connection=None,expected_source=None,source_root=None,source_relative_path=None):
    """Bounded owned metadata only; no native source stat/resolve/open/hash."""
    if stage not in ('acquire','qualify'):raise ValueError('authenticated phase invalid')
    packet=metadata_document(root,manifest_ref,INPUT_CONTRACT,native_sha=expected_source["sha256"] if expected_source else None)
    from skippercast.coastal.authenticated_v1.policy import policy_sha
    from skippercast.coastal.authenticated_v1.profiles import profile
    selected=profile(packet.get("execution_profile"),packet);side=selected["side"];pairs=selected["pairs"]
    if packet.get("policy_sha256")!=policy_sha(selected["name"],packet):raise ValueError("fixed scientific quality policy changed")
    if packet.get('execution_contract')!=EXECUTION_CONTRACT or packet.get('stage')!=stage:
        raise ValueError('dedicated execution/input contract mismatch')
    source=packet['source'];_source_identity(source)
    if expected_source is not None and (source!=expected_source or packet.get("source_root")!=source_root or packet.get("source_relative_path")!=source_relative_path):
        raise ValueError("immutable source grant changed")
    def meta(artifact,contract):return metadata_document(root,artifact,contract,native_sha=source["sha256"])
    if not isinstance(packet.get("source_root"),str) or packet["source_root"]!=os.path.abspath(packet["source_root"]):
        raise ValueError("explicit lexical source root required")
    trial=meta(packet["trial_policy_evidence"],"coastal-bounded-patch-quality-policy-v3" if selected["name"]=="coastal-contained-windows-v3" else "coastal-bounded-patch-quality-policy-v2" if selected["name"] else "coastal-bounded-patch-quality-policy-v1")
    if selected['name']=='coastal-contained-windows-v3' and any(trial.get(k)!=packet.get(k) for k in ('window_side','window_count')):raise ValueError('contained trial binding invalid')
    if trial.get("execution_profile")!=selected["name"]:raise ValueError("trial profile binding invalid")
    from skippercast.coastal.authenticated_v1.policy import policy_for_profile
    from skippercast.coastal.authenticated_v1.profiles import support_policy
    partial=support_policy(selected["name"],packet)
    required=pairs if partial is None else "all_mask_valid"
    if (trial.get("support_policy")!=partial or partial is not None and (
            trial.get("minimum_supported_pairs")!=policy_for_profile(selected["name"],packet)["minimum_supported_pairs"]
            or trial.get("minimum_unsupported_pairs")!=1 or trial.get("unsupported_cells")!="mask_invalid_only_as_nodata")):
        raise ValueError("trial support policy binding invalid")
    if partial is not None:
        # The partial policy is admitted only inside its ordered four128 scope:
        # every native admission (enqueue, worker authorization, completion)
        # re-validates the bound independent geographic review and pinned
        # window geometry here, before any Budget reservation or source access.
        from skippercast.coastal.authenticated_v1.profiles import PARTIAL_WINDOWS
        from skippercast.coastal.coordinator.ordered_trial import validate_scope_packet
        scope=dict(schema="coastal-authenticated-policy-v1",window_set=PARTIAL_WINDOWS,
                   **{key:packet.get(key) for key in ("source","source_root","source_relative_path","execution_profile",
                      "window_side","window_count","support_policy","ordered_scope_contract","geographic_review",
                      "output_retention","output_root","larger_runtime_contract","source_reuse_contract",
                      "saved_area_continuation_contract")})
        validate_scope_packet(root,scope,packet,now=now,horizon=mission_deadline)
    if (packet.get("trial_policy_sha256")!=packet["trial_policy_evidence"]["sha256"] or trial.get("independent") is not True
        or trial.get("source",{}).get("sha256")!=source["sha256"] or trial.get("source",{}).get("bytes")!=source["bytes"]
        or trial.get("window_shape")!=[side,side] or trial.get("halo")!=0 or trial.get("total_pairs")!=pairs
        or trial.get("required_nominally_eligible_pairs")!=required or trial.get("legacy_25ft_minimum_applied") is not False
        or trial.get("nominal_depth",{}).get("minimum_m")!=0 or trial.get("nominal_depth",{}).get("maximum_m")!=91.44
        or trial.get("nominal_depth",{}).get("minimum_inclusive") is not True or trial.get("nominal_depth",{}).get("maximum_inclusive") is not True
        or trial.get("product_uncertainty",{}).get("units")!="m" or trial.get("product_uncertainty",{}).get("type")!="productUncert"
        or trial.get("product_uncertainty",{}).get("required_quality_pairs")!=required or trial.get("product_uncertainty",{}).get("minimum_m")!=0
        or trial.get("product_uncertainty",{}).get("minimum_inclusive") is not False or trial.get("product_uncertainty",{}).get("maximum_m")!=1
        or trial.get("product_uncertainty",{}).get("maximum_inclusive") is not True):
        raise ValueError("source-bound fixed trial policy invalid")
    if packet.get('code_sha')!=code_sha or packet.get('deps_sha')!=deps_sha:raise ValueError('input code identity stale')
    if packet.get('segment_id')!=segment['segment_id'] or type(packet.get('synthetic')) is not bool or packet['synthetic'] is not (segment.get('synthetic') is True):
        raise ValueError('input geographic/provenance binding invalid')
    record=meta(packet['segment'],'coastal-segment-v1')
    if any(record.get(key)!=segment.get(key) for key in ('schema','crs','bbox','segment_id','region')):
        raise ValueError('input segment geometry differs')
    row=packet['source_row']
    if row.get('sha256')!=source['sha256'] or row.get('kind')!='bathymetry' or row.get('format')!='bag':
        raise ValueError('source row identity invalid')
    from skippercast.platform.bottom_targets import source_url_allowed
    if not source_url_allowed(row.get('url','')):raise ValueError('source URL unsupported')
    metadata=packet.get('metadata_sha256')
    if not re.fullmatch('[a-f0-9]{64}',str(metadata or '')) and not (stage=='acquire' and packet['synthetic'] and metadata is None):
        raise ValueError('exact original metadata SHA required')
    spec=packet['fixed_center_plan']
    from skippercast.coastal.authenticated_v1.planner import validate_spec
    validate_spec(spec,source)
    if selected['name']=='coastal-contained-windows-v3' and any(spec.get(k)!=packet.get(k) for k in ('window_side','window_count')):raise ValueError('contained spec binding invalid')
    if spec.get('execution_profile')!=selected['name']:raise ValueError('spec profile binding invalid')
    if (spec.get('schema')!=('coastal-contained-native-window-spec-v3' if selected['name']=='coastal-contained-windows-v3' else 'coastal-fixed-native-window-spec-v2' if selected['name'] else 'coastal-fixed-window-spec-v1') or spec.get('source_sha256')!=source['sha256']
        or spec.get('window_shape')!=[side,side] or spec.get('halo')!=0 or spec.get('minimum_margin_m')!=0.1
        or spec.get('segment',{}).get('segment_id')!=segment['segment_id']):
        raise ValueError('fixed-center plan binding invalid')
    rights=packet['rights']
    if rights.get('private_use') is not True or not rights.get('evidence'):raise ValueError('private rights unresolved')
    for ref in rights['evidence']:
        evidence=meta(ref,'coastal-rights-evidence-v1')
        if (evidence.get('independent') is not True or not evidence.get('reviewer_id')
            or evidence.get('private_use') is not True
            or evidence.get('decision')!='accepted_private_processing_conditional_on_exact_expected_source_identity'
            or evidence.get('accepted_source_rights_for_declared_private_purpose') is not True
            or evidence.get('holds_added')!=[]
            or evidence.get('source_sha256')!=source['sha256'] or evidence.get('source_bytes')!=source['bytes']
            or evidence.get('source_id')!=row['id'] or evidence.get('source_url')!=row['url']
            or evidence.get('product_title')!=row['title'] or evidence.get('synthetic',False)!=packet['synthetic']):
            raise ValueError('independent source-specific rights binding invalid')
        if not epoch(evidence['checked_at'])<=epoch(now)<epoch(evidence['valid_until']) or epoch(evidence['valid_until'])<=epoch(mission_deadline):
            raise ValueError('rights validity does not cover whole mission')
    if stage=='acquire':
        if packet.get('window') is not None or packet.get('reviewed_observation') is not None:
            raise ValueError('factual phase derives its fixed window once')
    else:
        if connection is None:raise ValueError('committed producer registry required')
        observation=committed_document(connection,root,packet['reviewed_observation'],OBSERVATION_CONTRACT)
        plan=committed_document(connection,root,observation['plan'],'coastal-authenticated-window-plan-v1')
        for key in ('source','source_root','source_relative_path','source_row','metadata_sha256','segment','segment_id','rights','synthetic','policy_sha256','trial_policy_sha256','execution_profile','window_side','window_count','support_policy'):
            if observation.get(key)!=packet.get(key):raise ValueError('reviewed factual context changed: '+key)
        if observation.get('machine_holds') or observation.get('facts_digest')!=digest(observation['native_facts']) or observation.get('policy_ready') is not True or observation.get('policy_holds'):

            raise ValueError('factual holds/digest prohibit qualification')
        if observation['native_facts']['implementation']!=packet.get('scientific_implementation'):
            raise ValueError('scientific implementation identity changed')
        if plan.get('spec_sha256')!=digest(spec) or packet.get('window')!=plan.get('window') or observation.get('window')!=plan.get('window'):
            raise ValueError('fixed window/plan changed')
        if observation.get('declared_vertical')!=packet.get('vertical'):raise ValueError('reviewed vertical changed')
        review=meta(packet['review'],'coastal-private-input-review-v2')
        holds=metadata_review_holds(review,observation['facts_digest'],now=now,deadline=mission_deadline)
        if holds:raise ValueError('independent factual review blocked: '+','.join(holds))
        diagnostics=committed_document(connection,root,observation["diagnostics"],"coastal-same-return-pair-diagnostics-v1")
        if (review.get("quality_accepted") is not True or review.get("policy_sha256")!=packet["policy_sha256"]
            or review.get("trial_policy_sha256")!=packet["trial_policy_sha256"]
            or review.get("diagnostics_digest")!=diagnostics["diagnostics_digest"]
            or review.get("plan_sha256")!=observation["plan"]["sha256"]):
            raise ValueError("independent quality review binding invalid")
        packet["registered_diagnostics"]=diagnostics
        packet["registered_review"]=review
        packet['registered_observation']=observation
        packet['registered_plan']=plan
    return packet


def unit_context(root,ref,*,now,monotonic):
    from skippercast.coastal.runner import boot_id
    unit=metadata_document(root,ref,"coastal-authenticated-unit-v1")
    if (unit.get("boot_id")!=boot_id() or not unit.get("unit_name") or not unit.get("invocation_id")
        or not isinstance(unit.get("cgroup_path"),str) or not unit["cgroup_path"].startswith("/")
        or unit.get("runtime_max_s")!=180 or unit.get("kill_mode")!="control-group"
        or unit.get("kill_signal")!="SIGKILL" or unit.get("memory_max")!=1073741824
        or unit.get("cpu_max_percent")!=200 or unit.get("pids_max")!=32):
        raise ValueError("actual bounded unit metadata contract invalid")
    utc_start=epoch(unit["phase_unit_start_utc"]);mono_start=unit["phase_unit_start_monotonic"]
    if type(mono_start) not in (int,float) or not math.isfinite(mono_start) or mono_start<0 or mono_start>monotonic or utc_start>now or abs((now-utc_start)-(monotonic-mono_start))>2:
        raise ValueError("unit origin boot/future/skew invalid")
    unit["phase_unit_start_utc"]=utc_start
    return unit

def actual_unit_check(job):
    """Read existing unit properties/membership; never creates or changes a unit."""
    import subprocess
    unit=metadata_document(job["root"],job["unit_context"],"coastal-authenticated-unit-v1",native_sha=job["source_grant"]["sha256"])
    name=unit.get("unit_name")
    if not isinstance(name,str) or not re.fullmatch("[A-Za-z0-9_.][A-Za-z0-9_.-]{0,127}\\.service",name):
        raise ValueError("fixed transient unit identity invalid")
    keys=("InvocationID","ExecMainPID","ExecMainStartTimestampMonotonic","RuntimeMaxUSec","KillMode","KillSignal","ControlGroup",
          "MemoryMax","CPUQuotaPerSecUSec","TasksMax","ActiveState")
    process=subprocess.run(["/usr/bin/systemctl","--user","show",name,*["--property="+k for k in keys]],
        capture_output=True,text=True,timeout=3,check=True,env={"PATH":"/usr/bin:/bin","XDG_RUNTIME_DIR":os.environ.get("XDG_RUNTIME_DIR","/run/user/"+str(os.getuid()))})
    values=dict(line.split("=",1) for line in process.stdout.splitlines() if "=" in line)
    membership=next((line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::")),None)
    if (values.get("InvocationID")!=unit.get("invocation_id") or values.get("ActiveState")!="active"
        or values.get("ControlGroup")!=membership or values.get("ControlGroup")!=unit.get("cgroup_path")
        or values.get("RuntimeMaxUSec") not in ("3min","180s","180000000")
        or values.get("KillMode")!="control-group" or values.get("KillSignal")!="9"
        or values.get("MemoryMax")!="1073741824" or values.get("TasksMax")!="32"
        or values.get("CPUQuotaPerSecUSec") not in ("2s","2000000")
        or int(values.get("ExecMainPID","0"))!=unit.get("exec_main_pid")
        or abs(int(values.get("ExecMainStartTimestampMonotonic","0"))/1000000-job["phase_unit_start_monotonic"])>0.000002):
        raise ValueError("actual unit envelope/origin differs from immutable proof")
    return values


def check_context(job,*,now=None,monotonic=None,completion=False):
    from skippercast.coastal.runner import boot_id
    now=time.time() if now is None else epoch(now)
    monotonic=time.monotonic() if monotonic is None else monotonic
    if job["boot_id"]!=boot_id():raise ValueError("mission boot changed")
    for field in ("mission_start_utc","mission_start_monotonic","phase_unit_start_utc","phase_unit_start_monotonic","overall_deadline_utc","overall_deadline_monotonic","phase_deadline_utc","phase_deadline_monotonic","deadline_utc","deadline_monotonic"):
        if type(job[field]) not in (int,float) or not math.isfinite(job[field]):raise ValueError("typed finite clock anchors required")
    from skippercast.coastal.authenticated_v1.profiles import profile
    selected=profile(job.get("execution_profile"),job)
    if (job["overall_deadline_utc"]!=job["mission_start_utc"]+selected["mission_seconds"]
        or job["overall_deadline_monotonic"]!=job["mission_start_monotonic"]+selected["mission_seconds"]
        or job["phase_deadline_utc"]!=min(job["phase_unit_start_utc"]+180,job["overall_deadline_utc"])
        or job["phase_deadline_monotonic"]!=min(job["phase_unit_start_monotonic"]+180,job["overall_deadline_monotonic"])
        or job["deadline_utc"]>min(job["phase_unit_start_utc"]+120,job["overall_deadline_utc"]-60)
        or job["deadline_monotonic"]>min(job["phase_unit_start_monotonic"]+120,job["overall_deadline_monotonic"]-60)):
        raise ValueError("immutable overall/phase clock changed")
    end="phase_deadline" if completion else "deadline"
    if now>=job[end+"_utc"] or monotonic>=job[end+"_monotonic"] or monotonic<job["mission_start_monotonic"] or abs((now-job["mission_start_utc"])-(monotonic-job["mission_start_monotonic"]))>2:
        raise ValueError("phase expired/clock uncertain")
    if not selected["name"] and job["stage"]=="acquire" and (job["phase_unit_start_monotonic"]!=job["mission_start_monotonic"] or job["phase_unit_start_utc"]!=job["mission_start_utc"]):raise ValueError("factual phase origin cannot restart")
    if (selected["name"] or job["stage"]=="qualify") and job["phase_unit_start_monotonic"]>job["mission_start_monotonic"]+selected["launch_horizon"]:
        raise ValueError("review consumed qualification launch horizon")
    return True

def validate_completion(store,job,token,result_ref,result,authority):
    """Native-free finish: actual supervisor capture + fenced versioned outputs."""
    from .stages import verify_ref
    from skippercast.coastal.authenticated_v1.profiles import profile
    check_context(job,now=store.clock(),monotonic=store.progress_clock())
    if result_ref.get("contract")!=RESULT_CONTRACT or result.get("schema")!=RESULT_CONTRACT or result.get("lease_token")!=token:
        raise ValueError("versioned result/lease contract invalid")
    if any(result.get(key)!=job.get(key) for key in (*IDENTITY_FIELDS,"execution_contract","source_root","source_relative_path")):
        raise ValueError("authenticated result immutable identity differs")
    if result.get("state") not in ("done","held") or result.get("rc")!={"done":0,"held":3}[result["state"]]:
        raise ValueError("authenticated typed completion invalid")
    if result.get("accepted") is not False or result.get("qualification") is not False or result.get("next_job"):
        raise ValueError("authenticated output cannot grant downstream authority")
    holds=result.get("holds")
    if not isinstance(holds,list) or any(not isinstance(v,str) or not v for v in holds) or bool(holds)!=(result["state"]=="held"):
        raise ValueError("authenticated holds invalid")
    # Only the actual execute ledger can provide this proof; no supplied stdout JSON.
    with authority._lock():
        entry=authority._read()["reservations"].get(token)
        if not entry or entry.get("candidate")!=job["job_id"] or entry.get("reserved")!={"bytes":job["budget"]["bytes"],"requests":0,"tokens":0}:
            raise ValueError("completion reservation identity differs")
        execution=authority._bound_execution(entry)
        intent=bounded_control_json(execution["intent_path"])
        if (intent.get("ownership_protocol")!="subreaper-pidfd-v1" or intent.get("ownership_complete") is not True
            or intent.get("processes_stopped") is not True or intent.get("argv")!=argv_for(dict(job,lease_token=token),Path(execution["intent_path"]).with_name("job.json"),Path(execution["intent_path"]).parent/"output")):
            raise ValueError("actual owned stopped completion missing")
        stdout=Path(execution["intent_path"]).with_name("stdout.log")
        output=next((ref for ref in execution["outputs"] if ref["path"]==str(stdout)),None)
        if not output or not 0<output["bytes"]<=16384:raise ValueError("bounded captured completion absent")
        completion=bounded_control_json(stdout,16384)
    expected=dict(schema=COMPLETION_CONTRACT,job_id=job["job_id"],lease_token=token,code_sha=job["code_sha"],deps_sha=job["deps_sha"],
        result_sha256=result_ref["sha256"],result_bytes=result_ref["bytes"],artifacts_digest=digest(result["artifacts"]),
        finalized_authentication_sha256=result["finalized_authentication"]["sha256"],observation_sha256=result["observation"]["sha256"])
    if completion!=expected:raise ValueError("captured result digest envelope differs")
    packet=validate_input(store.root,job["input_manifest"],stage=job["stage"],
        segment=json.loads(store.db.execute("SELECT record_json FROM segments WHERE segment_id=?",(job["segment_id"],)).fetchone()[0]),
        code_sha=job["code_sha"],deps_sha=job["deps_sha"],now=store.clock(),mission_deadline=job["overall_deadline_utc"],
        connection=store.db,expected_source=job["source_grant"],source_root=job["source_root"],source_relative_path=job["source_relative_path"])
    prefix=Path("var/coastal/jobs")/job["job_id"].replace(":","-")/token/"output"
    artifacts=result.get("artifacts")
    if not isinstance(artifacts,list) or not artifacts or len(artifacts)>16:raise ValueError("bounded versioned artifact list required")
    paths=set()
    for artifact in artifacts:
        path=Path(artifact["path"])
        if path.parent!=prefix or path.name in paths or artifact.get("sha256")==packet["source"]["sha256"]:
            raise ValueError("output must have unique quarantined ownership")
        paths.add(path.name);owned_output_bytes(store.root,job,token,artifact)
    def doc(key,contract):
        ref=result[key]
        if ref not in artifacts or ref.get("contract")!=contract:raise ValueError("bound output contract absent:"+key)
        value=json.loads(owned_output_bytes(store.root,job,token,ref))
        if value.get("schema")!=contract:raise ValueError("output schema invalid:"+key)
        return value
    observation=doc("observation",OBSERVATION_CONTRACT)
    plan=doc("plan","coastal-authenticated-window-plan-v1")
    proof=doc("finalized_authentication","coastal-authenticated-finalized-proof-v1")
    if (observation.get("accepted") is not False or observation.get("commit_required") is not True
        or observation["facts_digest"]!=digest(observation["native_facts"]) or observation["facts_digest"]!=result["facts_digest"]
        or observation.get("plan")!=result["plan"] or observation["window"]!=plan["window"]
        or plan.get("spec_sha256")!=digest(packet["fixed_center_plan"]) or plan.get("halo")!=0
        or observation["window"][2:]!=[profile(packet.get("execution_profile"),packet)["side"]]*2):
        raise ValueError("scientific observation/plan binding invalid")
    for key in ("source","source_root","source_relative_path","source_row","segment","segment_id","rights","synthetic","policy_sha256","trial_policy_sha256","execution_profile","window_side","window_count","support_policy"):
        if observation.get(key)!=packet.get(key):raise ValueError("factual context mismatch:"+key)
    if (result["source"]!=packet["source"] or proof.get("source")!=packet["source"]
        or proof.get("source_root")!=job["source_root"] or proof.get("source_relative_path")!=job["source_relative_path"]
        or any(proof.get(k)!=job.get(k) for k in ("job_id","stage","code_sha","deps_sha"))
        or proof.get("lease_token")!=token or proof.get("observation_sha256")!=result["observation"]["sha256"]
        or proof.get("plan_sha256")!=result["plan"]["sha256"] or proof.get("facts_digest")!=observation["facts_digest"]):
        raise ValueError("finalized authentication context invalid")
    # Snapshot proof is separate from canonical facts; require dual digest and successful closure.
    snapshot=proof.get("snapshot",{})
    if (snapshot.get("sha256")!=packet["source"]["sha256"] or snapshot.get("bytes")!=packet["source"]["bytes"]
        or snapshot.get("sealed_snapshot_sha256")!=packet["source"]["sha256"] or snapshot.get("seals")!=15
        or snapshot.get("source_full_hash_passes")!=1 or snapshot.get("sealed_snapshot_full_hash_passes")!=1
        or snapshot.get("total_full_hash_passes")!=2 or snapshot.get("source_bytes_hashed")!=packet["source"]["bytes"]
        or snapshot.get("snapshot_bytes_written")!=packet["source"]["bytes"]
        or snapshot.get("source_bytes_read")!=packet["source"]["bytes"] or snapshot.get("sealed_snapshot_bytes_hashed")!=packet["source"]["bytes"]
        or snapshot.get("logical_source")!=packet["source"] or snapshot.get("origin",{}).get("root")!=job["source_root"]
        or snapshot.get("origin",{}).get("relative_path")!=job["source_relative_path"]
        or proof.get("capability_closed") is not True or proof.get("origin_unchanged_observed") is not True
        or proof.get("container_checked") is not True or proof.get("scientific_acceptance") is not False):
        raise ValueError("finalized immutable snapshot identity differs")
    for key in ("policy_sha256","trial_policy_sha256"):
        if result.get(key)!=packet[key] or proof.get(key)!=packet[key]:raise ValueError("finalized policy binding differs")
    policy=doc("policy_evaluation","coastal-fixed-patch-policy-evaluation-v1")
    if policy.get("facts_digest")!=observation["facts_digest"] or policy.get("policy_sha256")!=packet["policy_sha256"] or policy.get("trial_policy_sha256")!=packet["trial_policy_sha256"]:
        raise ValueError("policy evaluation binding invalid")
    if job["stage"]=="acquire":
        diagnostics=doc("diagnostics","coastal-same-return-pair-diagnostics-v1")
        if observation.get("diagnostics")!=result["diagnostics"] or policy.get("diagnostics_digest")!=diagnostics.get("diagnostics_digest"):
            raise ValueError("same-return diagnostics binding invalid")
        if result["arrays"] not in artifacts:raise ValueError("same-return arrays missing")
    else:
        verification=doc("verification","coastal-authenticated-verification-v1")
        verified_diagnostics=doc("verified_diagnostics","coastal-same-return-pair-diagnostics-v1")
        verified_policy=doc("verified_policy","coastal-fixed-patch-policy-evaluation-v1")
        if (verification.get("facts_digest")!=observation["facts_digest"] or digest(verification["facts"])!=observation["facts_digest"]
            or verified_diagnostics.get("facts_digest")!=observation["facts_digest"]
            or verified_diagnostics.get("diagnostics_digest")!=packet["registered_diagnostics"]["diagnostics_digest"]
            or verified_policy.get("facts_digest")!=observation["facts_digest"]
            or verified_policy.get("diagnostics_digest")!=verified_diagnostics.get("diagnostics_digest")
            or verified_policy.get("policy_sha256")!=packet["policy_sha256"]
            or verified_policy.get("trial_policy_sha256")!=packet["trial_policy_sha256"]
            or result["state"]=="done" and (verified_policy.get("paired_eligibility_quality_pass") is not True or verified_policy.get("holds"))):
            raise ValueError("independent returned verifier policy differs")
        if (result.get("producer_facts_digest")!=observation["facts_digest"] or result.get("verified_facts_digest")!=observation["facts_digest"]
            or result.get("facts_digest")!=packet["registered_observation"]["facts_digest"]
            or result["state"]=="done" and (verification.get("ready") is not True or verification.get("holds"))):
            raise ValueError("fresh producer/verifier scientific binding invalid")
    if result["state"]=="done" and (policy.get("paired_eligibility_quality_pass") is not True or policy.get("holds") or observation.get("machine_holds")):
        raise ValueError("fixed complete patch policy prohibits readiness")
    return observation

def managed_native_graph_plan(grant, *, initial_control_bytes, initial_control_files=64):
    """Pure prospective ceilings, not a reservation or execution grant.

    A release must independently bind and enforce the listed finite runtime
    families. Future retries, extra files or changed ceilings are not covered.
    """
    from ..authenticated_v1.profiles import grant_identity,MANAGED_EIGHT_COPY
    from ..output_writer import validate_output_plan
    validate_output_plan(grant)
    domain=grant_identity(grant)
    if (domain.get('larger_runtime_contract')!=MANAGED_EIGHT_COPY
        or grant.get('output_retention',{}).get('profile')!='coastal-managed-output-32-v3'
        or grant.get('source_reuse_contract') is not None):
        raise ValueError('exact compact-v3 eight-copy graph required')
    if type(initial_control_bytes) is not int or not 0<=initial_control_bytes<=524288:
        raise ValueError('all immutable initial controls must fit512KiB before source')
    if type(initial_control_files) is not int or not 0<=initial_control_files<=64:
        raise ValueError('at most64 initial control entries before source')
    native=(4*(sum(v for k,v in NATIVE_OUTPUT_KIB.items() if k not in
        ('verification','verified-diagnostics','verified-policy'))+512+64+128+256+32)
        +4*(sum(v for k,v in NATIVE_OUTPUT_KIB.items() if k!='header')+512+64+128+256+32))*1024
    families=[
        ('Store databases',2,524288),('Store journals',2,655360),
        ('ordered checkpoint and staging',2,131072),('two Budget checkpoints and staging',4,65536),
        ('finite launcher envelopes',24,69632),('independent immutable native reviews',8,65536),
        ('per-core producer proofs',4,32768),('per-core import manifests',4,32768),
        ('per-core producer SQLite snapshots',4,524288),('per-core snapshot receipts',4,8192),
        ('copied qualified native reference families',4,1310720),
        ('copied qualification scientific reviews',4,65536),('copied mapping input packets',4,16384),
        ('shared copied rights and grant',1,49152),
        ('initial immutable metadata and controls',1,524288),
        ('immutable first live preparation',1,8192),
        ('dynamic qualification inputs',4,65536),('dynamic mapping packets',4,16384),
        ('dynamic mapping plans',4,32768),('phase unit controls including probe',13,8192),
        ('ordered action controls',12,4096),('ordered step receipts',12,8192),
        ('launcher result receipts',24,4096),('result and plan descriptor files',20,1024),
        ('final clock/probe/envelope/start/stop/accounting controls',10,8192),
        ('managed ledger atomic replacement overhead',1,524288)]
    rows=[dict(family=n,count=c,ceiling_bytes=z,total_bytes=c*z) for n,c,z in families]
    control=sum(r['total_bytes'] for r in rows);mapping=4*638976
    limits=grant['output_retention']['limits']
    if any(x>limits[k] for k,x in [('native',native),('mapping',mapping),('control',control)]):
        raise ValueError('prospective full finite graph exceeds immutable role allocation')
    return dict(schema='coastal-managed-eight-copy-graph-bound-v1',
        execution_authorized=False,reservations_created=False,native_operations=0,
        grant_sha256=digest(grant),initial_control_bytes=initial_control_bytes,
        initial_control_files=initial_control_files,prospective_maximum_file_entries=508,
        native_bytes=native,mapping_bytes=mapping,control_bytes=control,
        total_bytes=native+mapping+control,control_families=rows,
        renderer_included=False,extra_attempts_included=False,
        typed_runtime_caps_required=True,disk_quota=False,physical_io_measured=False)

def managed_ledger_growth_bound(grant, initial_files):
    """Canonical size bound for the frozen finite graph, never writes a ledger.

    The bound requires the independently reviewed concrete future path/intent
    limits below. Generic names, arbitrary writers and JSON revision history
    are outside this finite graph and cannot inherit this result.
    """
    from ..output_writer import validate_output_plan,METADATA_MAX
    validate_output_plan(grant)
    if (not isinstance(initial_files,dict) or len(initial_files)>64
        or any(e.get('role')!='control' or e.get('state')!='complete' for e in initial_files.values())
        or sum(e['bytes'] for e in initial_files.values())>524288):
        raise ValueError('exact completed immutable initial control ledger required')
    files=dict(initial_files)
    # 444 future entries plus at most64 actual initial entries =508.
    # 39 primary checkpoints (8native+4map+24launcher+ordered+2Budget),
    # 72 runner logs also carry checkpoint-length relative-path intents.
    # Other immutable intents use64; eight science reviews allow96.
    for index in range(444):
        name='x'*134+f'{index:06d}'
        if name in files:raise ValueError('ledger model namespace collision')
        length=151 if index<111 else 96 if index<119 else 64
        files[name]=dict(role='mapping',bytes=1310720,intent='i'*length,
            state='uncertain',binding='b'*64,actual_bytes=1310720,sha256='s'*64,
            updates=1024,revisions=4)
    state=dict(schema=grant['output_retention']['profile'],grant_digest=digest(grant),
               plan=grant['output_retention'],files=files)
    size=len((json.dumps(state,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())
    if size>METADATA_MAX:raise ValueError('prospective completed ledger serialization exceeds256KiB')
    return dict(schema='coastal-managed-ledger-growth-bound-v1',grant_sha256=digest(grant),
        initial_entries=len(initial_files),future_entries=444,maximum_entries=len(files),
        canonical_worst_bytes=size,ceiling_bytes=METADATA_MAX,
        future_relative_path_ascii_max=140,checkpoint_intent_ascii_max=151,
        runner_log_intent_ascii_max=151,runner_log_entries=72,
        scientific_review_intent_ascii_max=96,other_intent_ascii_max=64,
        execution_authorized=False,reservations_created=False,native_operations=0,
        concrete_frozen_path_limits_required=True)
