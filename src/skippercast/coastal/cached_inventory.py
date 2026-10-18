"""Bounded cached metadata inventory; never opens, hashes or decodes source payloads."""
import argparse,fcntl,hashlib,json,math,os,re,stat
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

PLAN="coastal-cached-inventory-plan-v2"
MANIFEST="coastal-usable-metadata-inputs-v1"
CHECKPOINT="coastal-cached-inventory-checkpoint-v1"
MAX_RECORDS=40
MAX_METADATA=16*1024*1024
MAX_FILE=131072
MAX_OUTPUT=524288

def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()
def encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def epoch(value):
    if isinstance(value,str):value=datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError("finite clock required")
    return value
def integer(value,maximum):
    if type(value) is not int or not 0<value<=maximum:raise ValueError("bounded positive integer required")
    return value
def owned(root,name):
    if not isinstance(name,str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:raise ValueError("owned relative path required")
    current=Path(root).resolve(strict=True)
    for part in Path(name).parts:
        current=current/part
        if current.is_symlink():raise ValueError("symlink metadata/cache path rejected")
    if not current.resolve(strict=False).is_relative_to(Path(root).resolve(strict=True)):raise ValueError("path escaped root")
    return current
def bounded_metadata_read(root,name,expected):
    """Open every component without following aliases and bound concurrent growth."""
    identity=lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_nlink,info.st_mtime_ns,info.st_ctime_ns)
    fd=os.open(Path(root).resolve(strict=True),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        parts=Path(name).parts
        for part in parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        child=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        os.close(fd);fd=child
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or identity(before)!=identity(expected):raise ValueError("metadata changed before bounded read")
        remaining=expected.st_size+1;chunks=[]
        while remaining:
            data=os.read(fd,min(65536,remaining))
            if not data:break
            chunks.append(data);remaining-=len(data)
        payload=b"".join(chunks)
        after=os.fstat(fd)
        if len(payload)!=expected.st_size or identity(after)!=identity(expected):raise ValueError("metadata changed during bounded read")
        current=owned(root,name).lstat()
        if identity(current)!=identity(expected):raise ValueError("metadata replaced during bounded read")
        return payload
    finally:os.close(fd)

def read_metadata(root,descriptor,cache,usage):
    if not isinstance(descriptor,dict) or set(descriptor)!={"path","sha256","bytes","contract"}:raise ValueError("exact metadata descriptor required")
    integer(descriptor["bytes"],MAX_FILE)
    if not re.fullmatch("[a-f0-9]{64}",str(descriptor["sha256"])):raise ValueError("metadata hash required")
    path=owned(root,descriptor["path"])
    if path.suffix.lower()!=".json":raise ValueError("only JSON metadata admitted")
    key=digest(descriptor)
    if key in cache:return cache[key]
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=descriptor["bytes"]:raise ValueError("metadata identity changed")
    if usage["metadata_bytes"]+info.st_size+1>MAX_METADATA:raise ValueError("metadata allowance exhausted")
    data=bounded_metadata_read(root,descriptor["path"],info)
    usage["metadata_bytes"]+=len(data);usage["metadata_files"]+=1
    if hashlib.sha256(data).hexdigest()!=descriptor["sha256"]:raise ValueError("metadata hash changed")
    value=json.loads(data)
    if descriptor["contract"]!="cached-source-json-v1" and value.get("schema")!=descriptor["contract"]:raise ValueError("metadata schema changed")
    cache[key]=value
    return value
def compatible_source(document,source):
    other=document.get("source")
    if not isinstance(other,dict):other=dict(sha256=document.get("source_sha256"),bytes=document.get("source_bytes"))
    return other.get("sha256")==source["sha256"] and other.get("bytes")==source["bytes"]
def freshness(doc,now,horizon):
    try:return epoch(doc["checked_at"])<=now and epoch(doc["valid_until"])>=horizon
    except (KeyError,ValueError):return False

def inventory(root,plan,*,now,horizon):
    now=epoch(now);horizon=epoch(horizon)
    if not now<horizon<=now+3600:raise ValueError("prospective discovery horizon at most60min required")
    if (plan.get("schema")!=PLAN or not isinstance(plan.get("region"),str) or not plan["region"]
        or plan.get("network_bytes")!=0 or plan.get("source_read_bytes")!=0
        or plan.get("metadata_bytes")!=MAX_METADATA or plan.get("output_bytes")!=MAX_OUTPUT):
        raise ValueError("fixed source-free inventory contract required")
    candidates=plan.get("candidates")
    if not isinstance(candidates,list) or not 1<=len(candidates)<=MAX_RECORDS:raise ValueError("finite1..40 explicit candidates required")
    usage=dict(metadata_bytes=0,metadata_files=0,source_read_bytes=0,source_hashes=0,
        network_requests=0,network_bytes=0,source_stat_checks=0)
    cache={};entries=[];groups={}
    for item in sorted(candidates,key=digest):
        source=read_metadata(root,item["source_manifest"],cache,usage)
        integer(source["bytes"],2**63-1)
        if not re.fullmatch("[a-f0-9]{64}",str(source["sha256"])):raise ValueError("source SHA required")
        url=urlsplit(source.get("url",""))
        if url.scheme!="https" or not url.hostname or url.username or url.password or url.fragment:raise ValueError("exact HTTPS acquisition locator required")
        holds=[];evidence={};header={};rights={};scope={}
        if source["bytes"]>64*1024*1024:holds.append("source_exceeds_native_reader_cap")
        for role in ("header","rights","scope","prepared_acquisition"):
            if role not in item:holds.append(role+"_metadata_missing");continue
            evidence[role]=item[role]
            value=read_metadata(root,item[role],cache,usage)
            if role=="header":header=value
            elif role=="rights":rights=value
            elif role=="scope":scope=value
            elif not compatible_source(value,source):holds.append("prepared_source_changed")
        path=owned(root,item["cache_path"])
        usage["source_stat_checks"]+=1
        if not path.exists():holds.append("cached_source_missing");present=False
        else:
            info=path.lstat();present=stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size==source["bytes"]
            if not present:holds.append("cached_source_stat_mismatch")
        if header:
            if not compatible_source(header,source):holds.append("header_source_changed")
            v=header.get("vertical",{})
            if (v.get("conflicts")!=[] or v.get("datum")!="MLLW" or v.get("sign")!="positive_up"
                or v.get("units")!="m" or v.get("datum_realization")!="unknown"
                or any(isinstance(v.get(k),bool) or not isinstance(v.get(k),(int,float)) or not math.isfinite(v[k]) for k in ("scale","offset"))
                or v.get("scale")!=1 or v.get("offset")!=0 or v.get("scale_offset_applied") is not False):
                holds.append("vertical_metadata_unresolved")
            shape=header.get("shape",[]);affine=header.get("transform",[])
            if (len(shape)!=2 or any(type(n) is not int or n<=0 for n in shape)
                or len(affine)!=6 or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in affine)
                or header.get("resolution_m")!=[2,2] or header.get("driver")!="BAG" or header.get("count")!=2
                or affine[0:2]!=[2,0] or affine[3:5]!=[0,-2] or not header.get("horizontal_crs")):
                holds.append("native_grid_metadata_unresolved")
        windows=item.get("window_set")
        if not isinstance(windows,list) or not 1<=len(windows)<=4:raise ValueError("explicit1..4 window scope required")
        for window in windows:
            if len(window)!=4 or any(type(n) is not int for n in window) or min(window[:2])<0 or not 1<=window[2]==window[3]<=128:
                raise ValueError("native square window required")
            if header and len(header.get("shape",[]))==2 and (window[0]+window[2]>header["shape"][1] or window[1]+window[3]>header["shape"][0]):
                holds.append("window_outside_native_grid")
        if len({tuple(w) for w in windows})!=len(windows):raise ValueError("duplicate native window")
        for i,a in enumerate(windows):
            for b in windows[i+1:]:
                if a[0]<b[0]+b[2] and b[0]<a[0]+a[2] and a[1]<b[1]+b[3] and b[1]<a[1]+a[3]:raise ValueError("overlapping native windows")
        if scope and (scope.get("status")!="accepted_scope_only" or scope.get("independent") is not True
            or scope.get("holds")!=[] or not compatible_source(scope,source) or not freshness(scope,now,horizon)
            or scope.get("window_set")!=windows or scope.get("product_region")!=plan["region"]
            or scope.get("native_quality_accepted") is not False
            or scope.get("global_affine")!=header.get("transform") or scope.get("grid_shape")!=header.get("shape")):
            holds.append("prospective_geographic_scope_unreviewed")
        if rights and (rights.get("independent") is not True or rights.get("private_use") is not True
            or rights.get("accepted_source_rights_for_declared_private_purpose") is not True
            or rights.get("holds_added")!=[] or not compatible_source(rights,source) or not freshness(rights,now,horizon)):
            holds.append("private_source_rights_unreviewed")
        entry=dict(source_id=source["sha256"],source=source,cache_path=item["cache_path"],
            cache_state="present_stat_only_identity_unverified" if present else "missing_or_unsafe",
            window_set=windows,evidence=evidence,source_manifest=item["source_manifest"],
            native_header=header,holds=sorted(set(holds)),usable_for_acquisition_request=not holds,
            native_identity_verified=False,native_quality_accepted=False,accepted_pairs=0,
            actual_data_support=None,habitat="unassessed",publication_prohibited=True,
            acquisition_recipe=dict(url=source["url"],expected_bytes=source["bytes"],expected_sha256=source["sha256"],
                download_required=not present,download_authorized=False,native_read_authorized=False,
                requires_fresh_full_packet_validation=True,requires_actual_source_authentication=True,
                requires_independent_native_quality=True))
        groups.setdefault(source["sha256"],[]).append(entry)
    for key,duplicates in sorted(groups.items()):
        first=duplicates[0]
        signatures={digest({k:e[k] for k in ("source","window_set","native_header","evidence","cache_path")}) for e in duplicates}
        if len(signatures)>1:
            first["holds"]=sorted(set(first["holds"]+["duplicate_source_metadata_conflict"]))
            first["usable_for_acquisition_request"]=False
        first["duplicate_records"]=len(duplicates)-1
        entries.append(first)
    usable=[e["source_id"] for e in entries if e["usable_for_acquisition_request"]]
    result=dict(schema=MANIFEST,plan_sha256=digest(plan),region=plan["region"],now=now,prospective_horizon=horizon,
        status="USABLE_METADATA_ONLY" if usable else "HELD_METADATA_ONLY",sources=entries,
        lead_source_ids=[e["source_id"] for e in entries],usable_source_ids=usable,
        sample_observed_source_ids=[],native_quality_accepted_source_ids=[],
        cached_bytes_present_stat_only=sum(e["source"]["bytes"] for e in entries if e["cache_state"].startswith("present")),
        prospective_download_bytes=sum(e["source"]["bytes"] for e in entries if e["acquisition_recipe"]["download_required"]),
        proposed_network_metadata_bytes=0,usage=usage,execution_authorized=False,
        imagery="not_required_for_private_terrain_discovery",rendering_accepted=False,
        acceptance="Metadata readiness only; no present payload identity, native quality, continuous support, habitat or publication credit.")
    if len(encoded(result))>MAX_OUTPUT:raise ValueError("bounded inventory output ceiling")
    return result

def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def output_tree_bytes(output):
    observed=0
    for folder,dirs,names in os.walk(output,followlinks=False):
        for name in dirs+names:
            info=(Path(folder)/name).lstat()
            if stat.S_ISLNK(info.st_mode):raise ValueError("symlink output tree rejected")
            if stat.S_ISREG(info.st_mode):observed+=info.st_size
            elif not stat.S_ISDIR(info.st_mode):raise ValueError("regular owned output tree required")
    return observed

def metadata_reservation(plan):
    if plan.get("schema")!=PLAN or not isinstance(plan.get("candidates"),list) or not 1<=len(plan["candidates"])<=MAX_RECORDS:
        raise ValueError("finite inventory plan required")
    if plan.get("metadata_bytes")!=MAX_METADATA or plan.get("output_bytes")!=MAX_OUTPUT or plan.get("network_bytes")!=0 or plan.get("source_read_bytes")!=0:
        raise ValueError("fixed source-free inventory contract required")
    descriptors={}
    for candidate in plan["candidates"]:
        for role in ("source_manifest","header","rights","scope","prepared_acquisition"):
            if role not in candidate:continue
            d=candidate[role]
            if not isinstance(d,dict) or set(d)!={"path","sha256","bytes","contract"}:raise ValueError("exact metadata descriptor required")
            integer(d["bytes"],MAX_FILE)
            name=d["path"]
            if not isinstance(name,str) or not name or Path(name).is_absolute() or ".." in Path(name).parts or Path(name).suffix.lower()!=".json":raise ValueError("relative JSON metadata required")
            if not re.fullmatch("[a-f0-9]{64}",str(d["sha256"])):raise ValueError("metadata hash required")
            descriptors[digest(d)]=d["bytes"]+1
    # Reserve the bounded CLI-plan read even for in-memory callers: no refund.
    reservation=sum(descriptors.values())+MAX_FILE+1
    if reservation>MAX_METADATA:raise ValueError("cumulative metadata allowance exceeded")
    return reservation

def produce(root,plan,output,*,now,horizon,plan_descriptor=None):
    now=epoch(now);horizon=epoch(horizon)
    if not now<horizon<=now+3600:raise ValueError("prospective discovery horizon at most60min required")
    if len(encoded(plan))>MAX_FILE:raise ValueError("canonical plan bound")
    reservation=metadata_reservation(plan)
    output=Path(output).absolute()
    if plan.get("output_root")!=str(output):raise ValueError("immutable plan output root required; no fresh-root reset")
    if output.is_symlink():raise ValueError("owned inventory output directory")
    for parent in output.parents:
        if parent.is_symlink():raise ValueError("symlink output ancestor")
    output.mkdir(exist_ok=True)
    sync_directory(output.parent)
    if output_tree_bytes(output)+4096>MAX_OUTPUT:raise ValueError("inventory output reservation ceiling")
    lock=output/"inventory.lock"
    if lock.exists() and (not lock.is_file() or lock.stat().st_nlink!=1):raise ValueError("owned inventory lock")
    with lock.open("a+b") as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        checkpoint=output/"checkpoint.json";manifest=output/"usable-inputs.json"
        admission=output/"metadata-admission.json";intent=output/"result-intent.json";pending=output/"usable-inputs.pending"
        for path in (checkpoint,manifest,admission,intent,pending):
            if path.exists() and (not path.is_file() or path.stat().st_nlink!=1):raise ValueError("owned regular inventory artifact required")
        catalog_root=str(Path(root).resolve(strict=True))
        identity=digest(dict(plan=plan,now=now,horizon=horizon,plan_descriptor=plan_descriptor,catalog_root=catalog_root))
        if checkpoint.exists():
            state=json.loads(bounded_metadata_read(output,checkpoint.name,checkpoint.lstat()))
            if state.get("identity")!=identity:raise ValueError("inventory contract changed; no reset")
        else:
            if any(path.exists() for path in (manifest,admission,intent,pending)):raise ValueError("unbound preserved output; preserve and hold")
            state=dict(schema=CHECKPOINT,identity=identity,state="prepared",source_read_bytes=0,network_bytes=0,plan=plan,plan_descriptor=plan_descriptor,catalog_root=catalog_root)
            if output_tree_bytes(output)+len(encoded(state))+4096>MAX_OUTPUT:raise ValueError("inventory output reservation ceiling")
            with checkpoint.open("xb") as stream:stream.write(encoded(state));stream.flush();os.fsync(stream.fileno())
            sync_directory(output)
        expected_admission=dict(schema="coastal-cached-metadata-admission-v1",identity=identity,
            cumulative_cap_bytes=MAX_METADATA,reserved_bytes=reservation,max_catalog_passes=1,catalog_root=catalog_root,
            source_read_bytes=0,network_bytes=0,refunds=False)
        if admission.exists():
            actual=json.loads(bounded_metadata_read(output,admission.name,admission.lstat()))
            if actual!=expected_admission:raise ValueError("metadata admission changed; no reset")
            if not intent.exists():raise ValueError("interrupted or refused metadata pass remains charged; no retry")
        elif intent.exists() or manifest.exists() or pending.exists():raise ValueError("result without durable metadata admission; preserve and hold")
        if intent.exists():
            prepared=json.loads(bounded_metadata_read(output,intent.name,intent.lstat()))
            if prepared.get("identity")!=identity or prepared.get("admission_sha256")!=digest(expected_admission):raise ValueError("result admission binding changed")
            path=manifest if manifest.exists() else pending
            if not path.exists():raise ValueError("prepared result missing; preserve and hold")
            integer(prepared.get("bytes"),MAX_OUTPUT)
            if path.stat().st_size!=prepared["bytes"]:raise ValueError("prepared result differs; preserve and hold")
            payload=bounded_metadata_read(output,path.name,path.lstat())
            if hashlib.sha256(payload).hexdigest()!=prepared.get("sha256"):raise ValueError("prepared result differs; preserve and hold")
            result=json.loads(payload)
            if result.get("plan_sha256")!=digest(plan) or result.get("now")!=now or result.get("prospective_horizon")!=horizon:raise ValueError("prepared result contract changed")
            if manifest.exists():return dict(status="completed_reused",manifest_sha256=prepared["sha256"],catalog_metadata_bytes_this_call=0,result=result)
            os.link(pending,manifest);sync_directory(output);pending.unlink();sync_directory(output)
            return dict(status="completed_recovered",manifest_sha256=prepared["sha256"],catalog_metadata_bytes_this_call=0,result=result)
        # Immutable nonrefundable admission precedes every catalog metadata open.
        with admission.open("xb") as stream:stream.write(encoded(expected_admission));stream.flush();os.fsync(stream.fileno())
        sync_directory(output)
        result=inventory(root,plan,now=now,horizon=horizon)
        result["metadata_accounting"]=expected_admission
        payload=encoded(result)
        if output_tree_bytes(output)+2*len(payload)+4096>MAX_OUTPUT:raise ValueError("inventory output reservation ceiling")
        prepared=dict(identity=identity,admission_sha256=digest(expected_admission),bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
        with intent.open("xb") as stream:stream.write(encoded(prepared));stream.flush();os.fsync(stream.fileno())
        sync_directory(output)
        with pending.open("xb") as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
        sync_directory(output)
        os.link(pending,manifest);sync_directory(output);pending.unlink();sync_directory(output)
        return dict(status="completed",manifest_sha256=prepared["sha256"],catalog_metadata_bytes_this_call=result["usage"]["metadata_bytes"],result=result)

def resource_inventory(retained_root,scratch_root):
    """Conservative regular-file accounting; never follows fixture aliases."""
    values={}
    for role,root,cap in (("retained",Path(retained_root),524288),("scratch",Path(scratch_root),268435456)):
        if root.is_symlink():raise ValueError("resource root alias")
        total=files=links=0
        if root.exists():
            for folder,dirs,names in os.walk(root,followlinks=False):
                for name in dirs+names:
                    path=Path(folder)/name;info=path.lstat()
                    if stat.S_ISLNK(info.st_mode):links+=1
                    elif stat.S_ISREG(info.st_mode):total+=info.st_size;files+=1
        if total>cap:raise ValueError(role+" engineering allowance exceeded")
        values[role]=dict(root=str(root.absolute()),regular_bytes=total,regular_files=files,symlinks_preserved_not_followed=links,cap_bytes=cap)
    return values

def write_engineering_receipt(retained_root,scratch_root,name,value):
    resources=resource_inventory(retained_root,scratch_root)
    if Path(name).name!=name or not name.endswith(".json"):raise ValueError("receipt leaf required")
    payload=encoded(value);path=Path(retained_root)/name
    if path.exists() or path.is_symlink():raise ValueError("preserve existing engineering receipt")
    if resources["retained"]["regular_bytes"]+len(payload)>524288:raise ValueError("retained engineering allowance exceeded")
    with path.open("xb") as stream:stream.write(payload)
    return dict(path=str(path),bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())

def main():
    a=argparse.ArgumentParser();a.add_argument("--root",type=Path,required=True);a.add_argument("--plan",type=Path,required=True)
    a.add_argument("--out",type=Path,required=True);a.add_argument("--now",type=float,required=True);a.add_argument("--horizon",type=float,required=True)
    a.add_argument("--plan-sha256",required=True);a.add_argument("--plan-bytes",type=int,required=True)
    x=a.parse_args()
    integer(x.plan_bytes,MAX_FILE)
    if not re.fullmatch("[a-f0-9]{64}",x.plan_sha256) or x.plan.suffix.lower()!=".json":raise ValueError("byte-bound JSON plan required")
    descriptor=dict(path=str(x.plan.absolute()),sha256=x.plan_sha256,bytes=x.plan_bytes)
    output=x.out.absolute()
    if output.is_symlink() or any(parent.is_symlink() for parent in output.parents):raise ValueError("owned CLI output root required")
    output.mkdir(exist_ok=True)
    sync_directory(output.parent)
    if output_tree_bytes(output)+4096>MAX_OUTPUT:raise ValueError("inventory output reservation ceiling")
    checkpoint=output/"checkpoint.json";plan_admission=output/"cli-plan-admission.json"
    expected_plan_admission=dict(schema="coastal-cached-plan-admission-v1",descriptor=descriptor,
        root=str(x.root.absolute()),now=epoch(x.now),horizon=epoch(x.horizon),reserved_bytes=MAX_FILE+1,refunds=False)
    if checkpoint.exists():
        info=checkpoint.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_FILE+4096:raise ValueError("checkpoint bound")
        state=json.loads(bounded_metadata_read(x.out,checkpoint.name,info))
        if state.get("plan_descriptor")!=descriptor:raise ValueError("CLI plan contract changed; no reset")
        plan=state["plan"];bytes_read=0
    else:
        if plan_admission.exists():raise ValueError("interrupted or refused plan read remains charged; no retry")
        payload=encoded(expected_plan_admission)
        if output_tree_bytes(output)+len(payload)+4096>MAX_OUTPUT:raise ValueError("inventory output reservation ceiling")
        with plan_admission.open("xb") as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
        sync_directory(output)
        info=x.plan.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=x.plan_bytes:raise ValueError("plan bound")
        data=bounded_metadata_read(x.plan.parent,x.plan.name,info)
        if hashlib.sha256(data).hexdigest()!=x.plan_sha256:raise ValueError("plan hash changed")
        plan=json.loads(data);bytes_read=len(data)
    info=plan_admission.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>4096:raise ValueError("plan admission bound")
    admitted=json.loads(bounded_metadata_read(output,plan_admission.name,info))
    if admitted!=expected_plan_admission:raise ValueError("CLI plan admission changed; no reset")
    result=produce(x.root,plan,x.out,now=x.now,horizon=x.horizon,plan_descriptor=descriptor)
    result["control_plan_bytes_read_this_call"]=bytes_read
    print(json.dumps(result,sort_keys=True))
if __name__=="__main__":main()
