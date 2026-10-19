"""Finite ordered orchestration. Preparation is metadata-only; Store owns credit."""
import argparse
import json
import math
import os
import sqlite3
import tempfile
import time
from pathlib import Path

from ..handoff.common import load, ref, write, digest, confined, epoch
from ..authenticated_v1.profiles import grant_identity, validate_grant_packet, CONTAINED
from .authenticated import INPUT_CONTRACT, actual_unit_check, metadata_document, _source_identity
from .loop import Coordinator, controller_lock, implementation_hashes
from .store import Store
from ..runner import boot_id as current_boot_id

PREPARATION = "coastal-ordered-trial-preparation-v1"
ACTION = "coastal-ordered-trial-action-v1"
STATE = "coastal-ordered-trial-state-v1"
WINDOWS = [[4046,3531,32,32],[3958,3474,32,32],[3764,3429,32,32],[3859,3366,32,32]]
SUPPORTED_WINDOW_SIDES = (32, 64, 128)
LARGER_SCOPE = "coastal-ordered-four128-v2"
LARGER_RUNTIME = "coastal-managed-eight-copy-four128-v1"
SCOPE_REVIEW = "coastal-ordered-scope-review-v1"
LARGER_WINDOWS = [[3890,3488,128,128],[4018,3488,128,128],[3890,3360,128,128],[4018,3360,128,128]]
LARGER_BOUNDS = [728871,3818923,729383,3819435]
LARGER_AFFINE = [2,0,721091,0,-2,3826155]

def validate_larger_runtime(grant):
    if grant.get('larger_runtime_contract') is None:return False
    from ..output_writer import COMPACT_V2_PROFILE,COMPACT_V3_PROFILE,validate_output_plan
    plan=validate_output_plan(grant)
    if (grant.get('ordered_scope_contract')!=LARGER_SCOPE
            or grant.get('larger_runtime_contract')!=LARGER_RUNTIME
            or grant.get('source_reuse_contract') is not None
            or plan['profile'] not in {COMPACT_V2_PROFILE,COMPACT_V3_PROFILE}):
        raise ValueError('explicit managed eight-copy larger runtime required')
    return True

def require_larger_runtime(preparation):
    if preparation.get('ordered_scope_contract')!=LARGER_SCOPE:return
    if (preparation.get('larger_runtime_contract')!=LARGER_RUNTIME
            or preparation.get('source_reuse_contract') is not None
            or preparation.get('output_retention',{}).get('profile') not in {'coastal-managed-output-32-v2','coastal-managed-output-32-v3'}):
        raise ValueError('larger ordered runtime/output integration is not implemented; execution held')

def validate_scope_review(root,grant,*,now,horizon):
    """Accept new geography only; never infer native quality or source authority."""
    domain=grant_identity(grant)
    if domain.get("execution_profile")!=CONTAINED or domain.get("window_count")!=4:
        raise ValueError("contained four-window admission required")
    side=domain.get("window_side")
    if side in SUPPORTED_WINDOW_SIDES and side != 128:
        if grant.get("ordered_scope_contract") is not None or grant.get("geographic_review") is not None:
            raise ValueError("legacy scope cannot inherit a new geographic admission")
        return None
    if (side!=128 or grant.get("ordered_scope_contract")!=LARGER_SCOPE
            or domain.get("window_set")!=LARGER_WINDOWS):
        raise ValueError("explicit exact ordered four128 scope required")
    from ..output_writer import validate_output_plan
    validate_output_plan(grant)
    validate_larger_runtime(grant)
    _roots([grant["output_root"]],grant["source_root"])
    review=metadata_document(root,_descriptor(grant.get("geographic_review"),SCOPE_REVIEW),SCOPE_REVIEW)
    if (review.get("status")!="accepted_scope_only" or review.get("independent") is not True
            or not isinstance(review.get("reviewer_id"),str) or not review["reviewer_id"]
            or review.get("holds")!=[] or review.get("source")!=grant["source"]
            or review.get("ordered_scope_contract")!=LARGER_SCOPE
            or review.get("execution_profile")!=CONTAINED
            or type(review.get("window_side")) is not int or review["window_side"]!=128
            or type(review.get("window_count")) is not int or review["window_count"]!=4
            or review.get("window_set")!=LARGER_WINDOWS):
        raise ValueError("independent exact larger geographic scope binding")
    for key,length in (("grid_shape",2),("global_affine",6),("native_bounds",4)):
        values=review.get(key)
        if (not isinstance(values,list) or len(values)!=length
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in values)):
            raise ValueError("finite nonboolean larger grid geometry")
    if (review.get("grid_shape")!=[10495,10034] or review.get("global_affine")!=LARGER_AFFINE
            or review.get("native_crs")!="EPSG:26910" or review.get("native_bounds")!=LARGER_BOUNDS
            or review.get("scope_basis")!="new_native_grid_target"
            or review.get("historical_support_qualified") is not False
            or review.get("native_quality_accepted") is not False
            or review.get("publication_prohibited") is not True
            or review.get("habitat")!="unassessed"
            or review.get("segment_contained") is not True
            or review.get("product_region_contained") is not True):
        raise ValueError("larger geographic review cannot promote historical or native support")
    safety=review.get("safety_bbox_native")
    if (not isinstance(safety,list) or len(safety)!=4
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in safety)
            or safety[0]>LARGER_BOUNDS[0]-1 or safety[1]>LARGER_BOUNDS[1]-1
            or safety[2]<LARGER_BOUNDS[2]+1 or safety[3]<LARGER_BOUNDS[3]+1):
        raise ValueError("larger whole-block safety margin")
    segment=review.get("segment")
    if (not isinstance(segment,dict) or segment.get("schema")!="coastal-segment-v1"
            or not isinstance(segment.get("segment_id"),str) or not segment["segment_id"]
            or review.get("product_region")!="point-arguello-conception"):
        raise ValueError("explicit larger geographic segment/product region")
    checked=_finite(epoch(review.get("checked_at")));until=_finite(epoch(review.get("valid_until")))
    now=_finite(epoch(now));horizon=_finite(epoch(horizon))
    if not checked<=now<horizon<until:raise ValueError("larger geographic review prospective horizon")
    return review

def validate_scope_packet(root,grant,packet,*,now,horizon,review=None):
    if grant.get("window_side")!=128:return
    review=review or validate_scope_review(root,grant,now=now,horizon=horizon)
    if (packet.get("ordered_scope_contract")!=LARGER_SCOPE
            or packet.get("geographic_review")!=grant["geographic_review"]
            or packet.get("output_retention")!=grant["output_retention"]
            or packet.get("output_root")!=grant["output_root"]
            or packet.get("larger_runtime_contract")!=grant.get("larger_runtime_contract")):
        raise ValueError("packet larger geographic review differs from grant")
    segment=metadata_document(root,packet["segment"],"coastal-segment-v1")
    if segment!=review["segment"] or packet.get("segment_id")!=segment["segment_id"]:
        raise ValueError("packet larger segment differs from independent scope")
    spec=packet["fixed_center_plan"];window=spec["native_window"];c,r,w,h=window
    center=[721091+2*(c+w/2),3826155-2*(r+h/2)]
    if (window not in LARGER_WINDOWS or spec.get("center_native")!=center
            or spec.get("safety_bbox_native")!=review["safety_bbox_native"]
            or spec.get("segment")!=segment
            or spec.get("ordered_scope_contract")!=LARGER_SCOPE
            or spec.get("scope_basis")!="new_native_grid_target"
            or spec.get("historical_support_qualified") is not False
            or spec.get("native_interest")!={"crs":"EPSG:26910","bbox":review["safety_bbox_native"]}
            or any(key in spec for key in ("historical_support","legacy_bounds","historical_support_evidence"))):
        raise ValueError("larger native plan geometry differs from scope review")

TERMINAL = {"done", "held"}
COMMON_STOP = {"failed_uncertain", "failed_terminal", "cancelled", "stale"}

def _descriptor(value,contract):
    if (not isinstance(value,dict) or not {"path","sha256","bytes","contract"}<=set(value)
            or value["contract"]!=contract):
        raise ValueError("explicit byte-bound descriptor required")
    return value

def _roots(values,source_root,*,empty=False):
    if not isinstance(values,list) or (not values and not empty) or len(values)>8:
        raise ValueError("bounded owned root list required")
    roots=[]
    for value in values:
        if not isinstance(value,str) or value!=os.path.abspath(value) or ".." in Path(value).parts:
            raise ValueError("lexical absolute owned root required")
        p=Path(value);source=Path(source_root)
        if p==Path("/") or p==source or p.is_relative_to(source) or source.is_relative_to(p):
            raise ValueError("artifact/scratch roots must be disjoint from source domain")
        if any(p==q or p.is_relative_to(q) or q.is_relative_to(p) for q in roots):
            raise ValueError("duplicate/nested aggregate roots")
        roots.append(p)
    return [str(p) for p in roots]

def inventory(preparation):
    """Observed admission/checkpoint caps, not a filesystem quota."""
    def count(roots):
        total=0;files=0
        for text in roots:
            root=Path(text)
            if any(p.is_symlink() for p in [root,*root.parents]):
                raise ValueError("aggregate root symlink")
            if not root.exists():continue
            if not root.is_dir():raise ValueError("aggregate root must be directory")
            for directory,dirs,names in os.walk(root,followlinks=False):
                for name in dirs+names:
                    p=Path(directory)/name
                    if p.is_symlink():raise ValueError("aggregate owned symlink")
                    if p.is_file():
                        total+=p.stat().st_size;files+=1
                    elif name in names:raise ValueError("aggregate nonregular artifact")
        return dict(bytes=total,regular_files=files)
    output=count(preparation["output_roots"]);scratch=count(preparation["scratch_roots"])
    if output["bytes"]>preparation["output_cap_bytes"] or scratch["bytes"]>preparation["scratch_cap_bytes"]:
        raise ValueError("parent aggregate output/scratch checkpoint cap")
    return dict(output=output,scratch=scratch,cap_mode="observed admission/checkpoint; not filesystem quota")

def _finite(value):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
        raise ValueError("finite parent clock required")
    return float(value)

def _inventoried(path,roots):
    path=Path(path).absolute()
    return any(path==Path(root) or path.is_relative_to(Path(root)) for root in roots)

def prepare(root, grant_ref, request_refs, *, start_epoch, deadline_epoch,
            cumulative_limit_bytes, prior_effective_bytes, start_monotonic=None, boot_id=None,
            output_roots=None, scratch_roots=None, output_cap_bytes=67108864, scratch_cap_bytes=2147483648):
    """Pure descriptor validation: no Store, ledger, unit or native source probe."""
    start=_finite(start_epoch);end=_finite(deadline_epoch)
    if start<0 or end!=start+3600:
        raise ValueError("one immutable 3600-second parent ceiling required")
    if (type(cumulative_limit_bytes) is not int or type(prior_effective_bytes) is not int
            or not 0<=prior_effective_bytes<=cumulative_limit_bytes):
        raise ValueError("exact cumulative source accounting required")
    if (start_monotonic is None)!=(boot_id is None):
        raise ValueError("paired parent monotonic/boot binding required")
    if start_monotonic is not None:
        start_monotonic=_finite(start_monotonic)
        if start_monotonic<0 or not isinstance(boot_id,str) or not boot_id:
            raise ValueError("valid immutable parent boot/monotonic required")
    grant=metadata_document(root,_descriptor(grant_ref,"coastal-authenticated-policy-v1"),"coastal-authenticated-policy-v1")
    if grant.get("schema")!="coastal-authenticated-policy-v1":raise ValueError("grant schema mismatch")
    _source_identity(grant["source"])
    sr=grant.get("source_root");leaf=grant.get("source_relative_path")
    if (not isinstance(sr,str) or sr!=os.path.abspath(sr) or not isinstance(leaf,str)
            or Path(leaf).name!=leaf or Path(leaf).suffix.lower()!=".bag"):
        raise ValueError("lexical exact source root/BAG leaf required")
    domain=grant_identity(grant)
    continuation=grant.get("saved_area_continuation_contract")
    if continuation is not None:
        from .saved_area import validate_adoption
        validate_adoption(root,grant["saved_area_adoption"],grant,now=start,horizon=end)
        if (prior_effective_bytes,cumulative_limit_bytes)!=(895006524,1115551932):
            raise ValueError("exact nonrefundable continuation source carry required")
    review=validate_scope_review(root,grant,now=start,horizon=end)
    windows=domain["window_set"]
    # The verified 32-cell trial stays pinned to its four historical windows so it
    # reproduces the prior 4,096 pairs byte-identically. 64 and 128 admit their own
    # windows inside the same supported-side gate (128 is further bound by the
    # larger-scope review above); this is a trial-preservation guard, not a size pin.
    if domain["window_side"]==32 and windows!=WINDOWS:
        raise ValueError("fixed ordered four-window scope required")
    from ..authenticated_v1.source_reuse import source_volume_cap
    source_cap=source_volume_cap(grant)
    if review is not None:
        code,deps=implementation_hashes(root)
        if grant.get("code_sha")!=code or grant.get("deps_sha")!=deps:
            raise ValueError("larger grant code/dependency identity differs from current snapshot")
    if not isinstance(request_refs,list) or len(request_refs)!=4:
        raise ValueError("four byte-bound acquisition requests required")
    for window,descriptor in zip(windows,request_refs):
        packet=metadata_document(root,_descriptor(descriptor,INPUT_CONTRACT),INPUT_CONTRACT)
        validate_grant_packet(grant,packet)
        validate_scope_packet(root,grant,packet,now=start,horizon=end,review=review)
        if packet.get("source_reuse_contract")!=grant.get("source_reuse_contract"):
            raise ValueError("packet source reuse differs from immutable grant")
        if review is not None:
            from .authenticated import validate_input
            from ..authenticated_v1.policy import policy_for_profile,policy_sha
            segment=metadata_document(root,packet["segment"],"coastal-segment-v1")
            validate_input(root,descriptor,stage="acquire",segment=segment,code_sha=code,deps_sha=deps,
                now=start,mission_deadline=end,expected_source=grant["source"],
                source_root=grant["source_root"],source_relative_path=grant["source_relative_path"])
            if (packet.get("scientific_policy")!=policy_for_profile(CONTAINED,packet)
                    or packet.get("policy_sha256")!=policy_sha(CONTAINED,packet)):
                raise ValueError("larger full scientific policy content changed")
        if packet.get("stage")!="acquire" or packet["fixed_center_plan"]["native_window"]!=window:
            raise ValueError("ordered acquisition request mismatch")
    roots=_roots(output_roots if output_roots is not None else [str(Path(root).absolute())],sr)
    scratch=_roots(scratch_roots if scratch_roots is not None else [],sr,empty=True)
    if any(Path(a)==Path(b) or Path(a).is_relative_to(Path(b)) or Path(b).is_relative_to(Path(a)) for a in roots for b in scratch):
        raise ValueError("output and scratch inventory roots must be disjoint")
    if not _inventoried(root,roots):raise ValueError("parent root must be inventoried")
    if review is not None and not any(Path(grant["output_root"])==Path(a)
            or Path(grant["output_root"]).is_relative_to(Path(a)) for a in roots):
        raise ValueError("managed output root must be inventoried by immutable parent")

    for cap,maximum in ((output_cap_bytes,67108864),(scratch_cap_bytes,2147483648)):
        if type(cap) is not int or not 0<cap<=maximum:raise ValueError("bounded immutable aggregate cap required")
    prepared=dict(schema=PREPARATION,execution_authorized=False,budget_created=False,native_operations=0,
        grant=grant_ref,grant_identity=domain,requests=request_refs,window_set=windows,
        start_monotonic=start_monotonic,boot_id=boot_id,native_clock_bound=start_monotonic is not None,
        start_epoch=start,deadline_epoch=end,source_cutoff_epoch=start+2400,
        source_launch_deadline_epoch=start+2220,
        cumulative_limit_bytes=cumulative_limit_bytes,prior_effective_bytes=prior_effective_bytes,
        proposed_source_cap_bytes=source_cap,
        source_allowance_sufficient=source_cap<=cumulative_limit_bytes-prior_effective_bytes,
        output_roots=roots,scratch_roots=scratch,output_cap_bytes=output_cap_bytes,scratch_cap_bytes=scratch_cap_bytes,
        max_acquired_unreviewed=1,max_qualified_waiting=2,max_native_attempts=1)
    if review is not None:
        prepared.update(ordered_scope_contract=LARGER_SCOPE,geographic_review=grant["geographic_review"],
            larger_execution_ready=False,
            output_retention=grant["output_retention"],managed_output_root=grant["output_root"])
        if validate_larger_runtime(grant):
            prepared['larger_runtime_contract']=LARGER_RUNTIME
            prepared['larger_execution_ready']=True
    if grant.get("source_reuse_contract") is not None:
        prepared.update(source_reuse_contract=grant["source_reuse_contract"],
            source_reuse_execution_ready=False)
    if continuation is not None:
        prepared.update(saved_area_continuation_contract=continuation,saved_area_adoption=grant["saved_area_adoption"],max_native_admissions=6,source_volume_cap_bytes=220545408)
    return prepared

def prepare_continuation(root,grant_ref,request_refs,**kwargs):
    result=prepare(root,grant_ref,request_refs,**kwargs)
    if result.get("saved_area_continuation_contract")!="coastal-saved-area-continuation-v1":
        raise ValueError("explicit continuation preparation required")
    return result

def select_next(preparation, windows, now):
    """Bounded scheduling decision from durable per-window states."""
    now=_finite(now)
    if now>=preparation["deadline_epoch"]:return dict(state="deadline")
    if len(windows)!=4:raise ValueError("four durable window states required")
    if any(s in COMMON_STOP for row in windows for s in row.values()):
        return dict(state="stopped",reason="common_or_uncertain_failure")
    waiting=[i for i,r in enumerate(windows) if r.get("qualify")=="done" and r.get("map") not in TERMINAL]
    if len(waiting)>2: return dict(state="stopped",reason="qualified_backlog_bound")
    acquired=[i for i,r in enumerate(windows) if r.get("acquire")=="done" and r.get("qualify") not in TERMINAL]
    if len(acquired)>1:return dict(state="stopped",reason="acquired_backlog_bound")
    if len(waiting)>=2:return dict(state="ready",stage="map",index=waiting[0])
    for i,row in enumerate(windows):
        if row.get("acquire")=="held" or row.get("qualify") in TERMINAL:continue
        if now+180>preparation["source_cutoff_epoch"]:
            return dict(state="ready",stage="map",index=waiting[0]) if waiting else dict(state="native_cutoff")
        stage="qualify" if row.get("acquire")=="done" else "acquire"
        if row.get(stage) in {"queued","claimed","running"}:return dict(state="recovery_required",stage=stage,index=i)
        return dict(state="ready",stage=stage,index=i)
    if waiting:return dict(state="ready",stage="map",index=waiting[0])
    return dict(state="complete")

class RealAdapter:
    """Production authority is the existing Store/Coordinator, never a callback."""
    def __init__(self,native_store,mapping_store=None):
        if type(native_store) is not Store or (mapping_store is not None and type(mapping_store) is not Store):
            raise TypeError("existing real Store authority required")
        self.native=native_store;self.mapping=mapping_store

    def saved_area_acceptance(self,preparation):
        from .saved_area import acceptance
        return acceptance(self.native,preparation)

    def states(self,preparation):
        windows=preparation["window_set"]
        rows=[{} for _ in windows];domain=preparation["grant_identity"]
        if preparation.get("saved_area_continuation_contract"):
            self.saved_area_acceptance(preparation)
            rows[0].update(acquire="done",qualify="done")
        for phase in self.native.db.execute(
                "SELECT p.window_key,p.stage,j.state,j.record_json FROM authenticated_window_phases p JOIN jobs j USING(job_id)"):
            record=json.loads(phase["record_json"])
            if record.get("source_domain_grant")!=domain:
                raise ValueError("foreign native mission cannot satisfy ordered parent")
            if phase["window_key"] not in [digest(w) for w in windows]:
                raise ValueError("extraneous native scope in ordered Store")
            for i,w in enumerate(windows):
                if phase["window_key"]==digest(w):rows[i][phase["stage"]]=phase["state"]
        if self.mapping:
            for job in self.mapping.db.execute("SELECT state,record_json FROM jobs WHERE stage='map'"):
                record=json.loads(job["record_json"])
                if not record.get("sourcefree_contract"):continue
                from .source_free import validate_input
                archived=self.mapping.clock()>=preparation["deadline_epoch"]
                if archived:
                    # Historical SQL state is not a fresh scientific acceptance.
                    # Read only sealed manifest/proof metadata after the deadline.
                    doc=load(self.mapping.root,record["input_manifest"],contract="coastal-sourcefree-map-manifest-v1")
                    registered=self.mapping.db.execute("SELECT record_json FROM sourcefree_imports WHERE manifest_sha=?",
                        (record["input_manifest"]["sha256"],)).fetchone()
                    if not registered or json.loads(registered[0])!=doc:raise ValueError("archived manifest registration changed")
                    proof=load(self.mapping.root,doc["producer_proofs"][record["params"]["core_index"]],
                        contract="coastal-retained-producer-proof-v1")
                    win=proof["window"]
                else:
                    doc,items=validate_input(self.mapping,record["input_manifest"],now=self.mapping.clock(),
                        horizon=min(self.mapping.clock()+1,preparation["deadline_epoch"]))
                    win=items[record["params"]["core_index"]]["facts"]["header"]["window"]
                if doc.get("parent_window_set")!=windows or doc.get("execution_grant_identity",grant_identity(load(self.mapping.root,doc["parent_grant"],contract="coastal-authenticated-policy-v1")))!=domain:
                    raise ValueError("foreign mapping parent cannot satisfy ordered scope")
                if win not in windows:raise ValueError("mapping scope outside parent")
                rows[windows.index(win)]["map"]=job["state"]
        return rows

    def accounting(self,preparation):
        """Observe existing ledger without creating/resetting Budget."""
        missions=list(self.native.db.execute("SELECT * FROM authenticated_missions"))
        if not missions:return dict(native_budget_created=False,effective_source_bytes=0)
        if len(missions)!=1:raise ValueError("one exact native mission required")
        mission=missions[0]
        if (mission["started_monotonic"]!=preparation["start_monotonic"]
                or mission["boot_id"]!=preparation["boot_id"]
                or mission["started_utc"]!=preparation["start_epoch"]
                or mission["deadline_utc"]!=preparation["deadline_epoch"]
                or mission["limits_sha"]!=digest(preparation["grant_identity"])):
            raise ValueError("native mission clock/domain differs from parent")
        budget_path=self.native.path.parent/("budget-"+digest([self.native.path.name,mission["region"]])+".json")
        if not budget_path.exists():raise ValueError("existing mission authoritative ledger missing; no reset")
        authority=self.native.budget_for(mission["region"])
        with authority._lock():effective=authority._effective(authority._read())["bytes"]
        if effective>preparation["proposed_source_cap_bytes"]:
            raise ValueError("authoritative native source cap exceeded")
        cumulative=preparation["prior_effective_bytes"]+effective
        if cumulative>preparation["cumulative_limit_bytes"]:
            raise ValueError("immutable cumulative allowance exceeded")
        return dict(native_budget_created=True,effective_source_bytes=effective,cumulative_effective_bytes=cumulative,
                    budget_path=str(authority.path),uncertain_reservations_retained=True)

    def review_hold(self,preparation,index,hold_ref,*,validate_only=False):
        """A reviewed rejection is a terminal metadata hold, never a qualification."""
        windows=preparation["window_set"]
        from .authenticated import committed_document
        from ..handoff.common import epoch
        hold=load(self.native.root,_descriptor(hold_ref,"coastal-ordered-review-hold-v1"),
                  contract="coastal-ordered-review-hold-v1")
        if (hold.get("schema")!="coastal-ordered-review-hold-v1"
                or hold.get("parent_grant_identity")!=preparation["grant_identity"]
                or hold.get("native_window")!=windows[index]):
            raise ValueError("rejected review exact parent/window binding required")
        phase=self.native.db.execute(
            "SELECT j.* FROM authenticated_window_phases p JOIN jobs j USING(job_id) WHERE p.window_key=? AND p.stage='acquire'",
            (digest(windows[index]),)).fetchone()
        rr=_descriptor(hold["acquisition_result"],"coastal-authenticated-stage-result-v1")
        if (not phase or not rr["path"].startswith("var/coastal/jobs/"+phase["job_id"].replace(":","-")+"/")
                or not rr["path"].endswith("/output/result.json")):
            raise ValueError("owned committed acquisition result namespace required")
        result=load(self.native.root,rr,contract="coastal-authenticated-stage-result-v1")
        expected_path="var/coastal/jobs/"+phase["job_id"].replace(":","-")+"/"+str(result.get("lease_token"))+"/output/result.json"
        if rr["path"]!=expected_path:raise ValueError("exact committed acquisition lease namespace required")
        if (not phase or phase["state"]!="done" or phase["result_sha"]!=hold["acquisition_result"]["sha256"]
                or phase["job_id"]!=result.get("job_id") or result.get("stage")!="acquire"
                or result.get("state")!="done" or result.get("rc")!=0):
            raise ValueError("exact committed acquisition required for reviewed hold")
        record=json.loads(phase["record_json"])
        if record.get("source_domain_grant")!=preparation["grant_identity"]:
            raise ValueError("reviewed hold producer parent differs")
        obs=committed_document(self.native.db,self.native.root,result["observation"],
                               "coastal-authenticated-observation-v1")
        if (obs["facts_digest"]!=digest(obs["native_facts"])
                or obs["window"]!=windows[index] or hold.get("facts_digest")!=obs["facts_digest"]):
            raise ValueError("reviewed hold acquisition facts/window differ")
        review=load(self.native.root,_descriptor(hold["review"],"coastal-private-input-review-v2"),contract="coastal-private-input-review-v2")
        holds=review.get("holds_added")
        if (review.get("schema")!="coastal-private-input-review-v2" or review.get("independent") is not True
                or not isinstance(review.get("reviewer_id"),str) or not review["reviewer_id"]
                or review["reviewer_id"].startswith("coastal.") or review.get("facts_digest")!=obs["facts_digest"]
                or review.get("decision") not in {"held","hold","reject"} or review.get("quality_accepted") is not False
                or not isinstance(holds,list) or not holds or any(not isinstance(v,str) or not v for v in holds)
                or not epoch(review["checked_at"])<=self.native.clock()<epoch(review["valid_until"])
                or epoch(review["valid_until"])<=preparation["deadline_epoch"]):
            raise ValueError("fresh independent rejected review required")
        local={"native_support_empty","bounded_patch_nominal_support_incomplete",
               "bounded_patch_nominal_depth_out_of_range","bounded_patch_uncertainty_quality_failed"}
        if hold.get("hold_scope") not in {"window_quality","common_source"}:
            raise ValueError("explicit bounded review hold scope required")
        if hold["hold_scope"]=="window_quality" and any(h not in local for h in holds):
            raise ValueError("local quality hold cannot hide common source/header failures")
        if validate_only:return dict(state="validated_review_hold",source_volume_bytes=0)
        code,deps=implementation_hashes(self.native.root)
        with self.native.transaction():
            previous=self.native.db.execute(
                "SELECT j.job_id,j.record_json FROM authenticated_window_phases p JOIN jobs j USING(job_id) WHERE p.region=? AND p.window_key=? AND p.stage='qualify'",
                (record["region"] if "region" in record else self.native.db.execute("SELECT region FROM segments WHERE segment_id=?",(phase["segment_id"],)).fetchone()[0],digest(windows[index]))).fetchone()
            if previous:
                if json.loads(previous["record_json"]).get("review_hold")!=hold_ref:
                    raise ValueError("terminal qualification/hold cannot be overwritten")
                return previous["job_id"],self.native
            job=self.native._enqueue(phase["segment_id"],"qualify",code_sha=code,deps_sha=deps,
                input_manifest=hold_ref,params=dict(review_hold=True,window_key=digest(windows[index])),
                budget=dict(wall_s=1,memory_bytes=1073741824,bytes=0,requests=0),max_attempts=1)
            stored=json.loads(self.native.db.execute("SELECT record_json FROM jobs WHERE job_id=?",(job,)).fetchone()[0])
            stored.update(review_hold=hold_ref,source_domain_grant=preparation["grant_identity"],
                          native_phase_executed=False,measurement_credited=False,hold_scope=hold["hold_scope"])
            self.native.db.execute("UPDATE jobs SET state='held',holds_json=?,record_json=? WHERE job_id=?",
                (json.dumps(holds),json.dumps(stored,sort_keys=True),job))
            region=self.native.db.execute("SELECT region FROM segments WHERE segment_id=?",(phase["segment_id"],)).fetchone()[0]
            self.native.db.execute("INSERT INTO authenticated_window_phases VALUES(?,?,?,?)",
                (region,digest(windows[index]),"qualify",job))
            self.native.event(job,"ordered_review_hold",dict(review_hold=hold_ref,native_operations=0,
                             source_volume_bytes=0,measurement_credited=False))
        return job,self.native

    def preflight(self,preparation,decision,action):
        """All metadata/actual-unit admission checks precede durable intent."""
        windows=preparation["window_set"]
        if preparation.get("source_reuse_contract") is not None:
            raise ValueError("ordered source reuse FD transport is not implemented; execution held")
        require_larger_runtime(preparation)
        if preparation.get("larger_runtime_contract")==LARGER_RUNTIME:
            prepared=metadata_document(self.native.root,preparation["grant"],"coastal-authenticated-policy-v1")
            manager=self.native.managed_outputs
            if (prepared.get("execution_authorized") is not True
                    or prepared!=self.native.policy.get("authenticated")
                    or manager is None or manager.grant_digest!=digest(prepared)
                    or str(manager.root)!=prepared["output_root"]):
                raise ValueError("exact released managed preparation/Store grant required")
            if self.mapping is not None and (self.mapping.managed_outputs is None
                    or self.mapping.managed_outputs.grant_digest!=digest(prepared)):
                raise ValueError("mapping Store managed grant differs from released parent")
        stage,index=decision["stage"],decision["index"]
        if preparation.get("saved_area_continuation_contract") and stage in {"acquire","qualify"} and index==0:
            raise ValueError("adopted A cannot receive a new native phase")
        if stage=="qualify" and "review_hold" in action:
            return self.review_hold(preparation,index,action["review_hold"],validate_only=True)
        if stage not in {"acquire","qualify"}:return
        from .authenticated import validate_input
        released=metadata_document(self.native.root,_descriptor(action["released_grant"],"coastal-authenticated-policy-v1"),
                                   "coastal-authenticated-policy-v1")
        if released.get("execution_authorized") is not True or grant_identity(released)!=preparation["grant_identity"]:
            raise ValueError("externally released exact source grant required")
        if self.native.policy.get("authenticated")!=released:raise ValueError("Store policy release mismatch")
        carry=metadata_document(self.native.root,action["carry"],"coastal-authenticated-carry-v1")
        if (carry.get("cumulative_limit_bytes")!=preparation["cumulative_limit_bytes"]
                or carry.get("prior_effective_bytes")!=preparation["prior_effective_bytes"]):
            raise ValueError("parent cumulative carry mismatch")
        unit=metadata_document(self.native.root,action["unit"],"coastal-authenticated-unit-v1")
        if not preparation["native_clock_bound"] or unit["boot_id"]!=preparation["boot_id"]:
            raise ValueError("first actual unit parent clock unbound or changed")
        if (unit["phase_unit_start_utc"]+180>preparation["source_cutoff_epoch"]
                or unit["phase_unit_start_monotonic"]+180>preparation["start_monotonic"]+2400):
            raise ValueError("actual unit phase horizon exceeds native cutoff")
        mission=self.native.db.execute("SELECT * FROM authenticated_missions").fetchone()
        if mission is None and (unit["phase_unit_start_utc"]!=preparation["start_epoch"]
                or unit["phase_unit_start_monotonic"]!=preparation["start_monotonic"]):
            raise ValueError("first actual unit must start exact frozen parent clock")
        if mission is not None:self.accounting(preparation)
        actual_unit_check(dict(root=str(self.native.root),unit_context=action["unit"],
            source_grant=released["source"],phase_unit_start_monotonic=unit["phase_unit_start_monotonic"]))
        packet=metadata_document(self.native.root,action["request"],INPUT_CONTRACT)
        validate_grant_packet(released,packet)
        if packet["stage"]!=stage or packet["fixed_center_plan"]["native_window"]!=windows[index]:
            raise ValueError("action stage/window mismatch")
        if stage=="acquire" and action["request"]!=preparation["requests"][index]:
            raise ValueError("prepared acquisition bytes changed")
        segment=metadata_document(self.native.root,packet["segment"],"coastal-segment-v1")
        code,deps=implementation_hashes(self.native.root)
        validate_input(self.native.root,action["request"],stage=stage,segment=segment,code_sha=code,deps_sha=deps,
            now=self.native.clock(),mission_deadline=preparation["deadline_epoch"],connection=self.native.db,
            expected_source=released["source"],source_root=released["source_root"],
            source_relative_path=released["source_relative_path"])

    def submit(self,preparation,decision,action):
        windows=preparation["window_set"]
        if preparation.get("source_reuse_contract") is not None:
            raise ValueError("ordered source reuse FD transport is not implemented; execution held")
        require_larger_runtime(preparation)
        stage,index=decision["stage"],decision["index"]
        if preparation.get("saved_area_continuation_contract") and stage in {"acquire","qualify"} and index==0:
            raise ValueError("adopted A cannot receive a new native phase")
        if stage=="qualify" and "review_hold" in action:
            return self.review_hold(preparation,index,action["review_hold"])
        code,deps=implementation_hashes(self.native.root)
        if stage in {"acquire","qualify"}:
            released=load(self.native.root,action["released_grant"],contract="coastal-authenticated-policy-v1")
            if released.get("execution_authorized") is not True or grant_identity(released)!=preparation["grant_identity"]:
                raise ValueError("externally released exact source grant required")
            if self.native.policy.get("authenticated")!=released:
                raise ValueError("Store policy must bind exact released grant")
            carry=metadata_document(self.native.root,action["carry"],"coastal-authenticated-carry-v1")
            if (carry["cumulative_limit_bytes"]!=preparation["cumulative_limit_bytes"]
                    or carry["prior_effective_bytes"]!=preparation["prior_effective_bytes"]):
                raise ValueError("immutable cumulative carry differs from parent")
            unit=metadata_document(self.native.root,action["unit"],"coastal-authenticated-unit-v1")
            if not preparation["native_clock_bound"]:
                raise ValueError("parent native boot/monotonic clock remains unbound")
            if (unit["phase_unit_start_utc"]+180>preparation["source_cutoff_epoch"]
                    or unit["phase_unit_start_monotonic"]+180>preparation["start_monotonic"]+2400):
                raise ValueError("actual unit phase horizon exceeds native cutoff")
            if unit["boot_id"]!=preparation["boot_id"]:
                raise ValueError("unit boot differs from immutable parent")
            mission=self.native.db.execute("SELECT * FROM authenticated_missions").fetchone()
            if mission is None and (unit["phase_unit_start_utc"]!=preparation["start_epoch"]
                    or unit["phase_unit_start_monotonic"]!=preparation["start_monotonic"]):
                raise ValueError("first actual unit must start exact frozen parent clock")
            if mission is not None:self.accounting(preparation)
            if unit["phase_unit_start_utc"]<preparation["start_epoch"]:
                raise ValueError("unit predates parent")
            actual_unit_check(dict(root=str(self.native.root),unit_context=action["unit"],
                source_grant=released["source"],phase_unit_start_monotonic=unit["phase_unit_start_monotonic"]))
            packet=load(self.native.root,action["request"],contract=INPUT_CONTRACT)
            validate_grant_packet(released,packet)
            if packet["stage"]!=stage or packet["fixed_center_plan"]["native_window"]!=windows[index]:
                raise ValueError("action request stage/scope differs")
            if stage=="acquire" and action["request"]!=preparation["requests"][index]:
                raise ValueError("acquisition request differs from prepared bytes")
            segment=load(self.native.root,packet["segment"],contract="coastal-segment-v1")
            self.native.add_segment(segment)
            job=self.native.enqueue_authenticated(segment["segment_id"],stage,code_sha=code,deps_sha=deps,
                input_manifest=action["request"],unit_ref=action["unit"],carry_ref=action["carry"])
            self.accounting(preparation)
            return job,self.native
        if not self.mapping:raise ValueError("existing source-free Store required")
        from .source_free import import_retained,validate_input
        adopted=preparation.get("saved_area_continuation_contract") and index==0
        adoption=self.saved_area_acceptance(preparation) if adopted else None
        manifest=action.get("mapping_manifest")
        if adopted and manifest is None:
            if action.get("saved_area_adoption")!=preparation["saved_area_adoption"]:
                raise ValueError("explicit mapping adoption proof required")
            from .source_free import import_adopted
            manifest=import_adopted(self.mapping,adoption,native_store=self.native,now=self.mapping.clock(),deadline=preparation["deadline_epoch"])
        if manifest is None:
            plan=load(self.native.root,action["mapping_plan"],contract="coastal-contained-mapping-plan-v1")
            parent=grant_identity(load(self.native.root,plan["parent_grant"],contract="coastal-authenticated-policy-v1"))
            if parent!=preparation["grant_identity"]:raise ValueError("mapping parent differs")
            # A consistent owned SQLite backup permits immutable reads while
            # the current coordinator Store remains open. Never checkpoint or
            # rewrite an originating closed evidence database.
            from ..handoff.common import resolve
            snapshot=self.native.root/"control/producer-snapshots"/(action["mapping_plan"]["sha256"]+".sqlite")
            receipt=snapshot.with_suffix(".json")
            if snapshot.exists():
                proof=load(self.native.root,ref(self.native.root,receipt,"coastal-ordered-producer-snapshot-v1"),
                           contract="coastal-ordered-producer-snapshot-v1")
                if proof.get("source_store")!=str(self.native.path) or proof.get("mapping_plan")!=action["mapping_plan"]:
                    raise ValueError("owned producer snapshot contract changed")
                resolve(self.native.root,proof["snapshot"],contract="coastal-ordered-producer-snapshot-sqlite-v1",cap=4194304)
            else:
                if self.native.managed_outputs is not None:
                    connection=sqlite3.connect(':memory:')
                    try:
                        self.native.db.backup(connection)
                        payload=connection.serialize()
                    finally:connection.close()
                    if len(payload)>524288:raise ValueError('managed producer snapshot512KiB bound')
                    managed=self.native.managed_outputs
                    managed.write_bytes(managed.relative_path(snapshot),payload,role='control',max_bytes=len(payload),
                        intent=digest(['producer-snapshot',action['mapping_plan']]))
                else:
                    snapshot.parent.mkdir(parents=True,exist_ok=True)
                    fd,temp=tempfile.mkstemp(dir=snapshot.parent,prefix=".producer-");os.close(fd)
                    try:
                        connection=sqlite3.connect(temp)
                        try:self.native.db.backup(connection)
                        finally:connection.close()
                        if Path(temp).stat().st_size>4194304:raise ValueError("producer snapshot4MiB bound")
                        with open(temp,"rb") as stream:os.fsync(stream.fileno())
                        os.link(temp,snapshot)
                    finally:Path(temp).unlink(missing_ok=True)
                self.native.write_artifact(receipt,dict(schema="coastal-ordered-producer-snapshot-v1",source_store=str(self.native.path),
                    mapping_plan=action["mapping_plan"],source_arrays_read=False,
                    snapshot=ref(self.native.root,snapshot,"coastal-ordered-producer-snapshot-sqlite-v1")),
                    max_bytes=8192 if self.native.managed_outputs is not None else 131072)
            manifest=import_retained(self.mapping,source_root=self.native.root,source_db=snapshot,
                plan_ref=action["mapping_plan"],now=self.mapping.clock(),deadline=preparation["deadline_epoch"])
        doc,items=validate_input(self.mapping,manifest,now=self.mapping.clock(),horizon=self.mapping.clock()+120)
        if (doc.get("parent_window_set")!=windows
                or doc.get("execution_grant_identity",grant_identity(load(self.mapping.root,doc["parent_grant"],contract="coastal-authenticated-policy-v1")))!=preparation["grant_identity"]):
            raise ValueError("mapping exact full parent lineage required")
        indices=[i for i,item in enumerate(items) if item["facts"]["header"]["window"]==windows[index]]
        if len(indices)!=1:raise ValueError("exact accepted core membership required")
        selected=items[indices[0]]
        phase=self.native.db.execute(
            "SELECT j.job_id,j.state,j.result_sha FROM authenticated_window_phases p JOIN jobs j USING(job_id) WHERE p.window_key=? AND p.stage='qualify'",
            (digest(windows[index]),)).fetchone()
        if adopted:
            if selected["result_ref"]!=adoption["qualified_result"] or selected["result"]["job_id"]!=adoption["original_job"]["job_id"]:
                raise ValueError("mapping original producer differs from registered adoption")
        elif (not phase or phase["state"]!="done" or phase["job_id"]!=selected["result"]["job_id"]
                or phase["result_sha"]!=selected["result_ref"]["sha256"]):
            raise ValueError("mapping producer must match current committed native phase")
        mc,md=implementation_hashes(self.mapping.root)
        job=self.mapping.enqueue_sourcefree(manifest,indices[0],code_sha=mc,deps_sha=md)
        return job,self.mapping

class Controller:
    def __init__(self,root,preparation_ref,*,clock=time.time,monotonic=time.monotonic,boot=current_boot_id):
        self.root=Path(root).absolute();self.descriptor=preparation_ref;self.clock=clock;self.monotonic=monotonic;self.boot=boot
        self.preparation=load(self.root,_descriptor(preparation_ref,PREPARATION),contract=PREPARATION)
        p=self.preparation
        checked=prepare(self.root,p["grant"],p["requests"],start_epoch=p["start_epoch"],
            deadline_epoch=p["deadline_epoch"],cumulative_limit_bytes=p["cumulative_limit_bytes"],
            prior_effective_bytes=p["prior_effective_bytes"],start_monotonic=p["start_monotonic"],boot_id=p["boot_id"],
            output_roots=p["output_roots"],scratch_roots=p["scratch_roots"],
            output_cap_bytes=p["output_cap_bytes"],scratch_cap_bytes=p["scratch_cap_bytes"])
        if checked!=p:raise ValueError("prepared parent contract changed")
        self.path=self.root/"control"/("ordered-"+preparation_ref["sha256"]+".json")

    def _save_state(self,state):
        if self.preparation.get('ordered_scope_contract')!=LARGER_SCOPE:
            return write(self.path,state)
        from ..receipts import managed_writes,atomic_json
        grant=metadata_document(self.root,self.preparation['grant'],'coastal-authenticated-policy-v1')
        with managed_writes(dict(grant=grant,grant_digest=digest(grant),role='control',max_bytes=131072)):
            return atomic_json(self.path,state)

    def _state(self):
        if not self.path.exists():return dict(schema=STATE,preparation=self.descriptor,intents=[],stop_reason=None)
        state=json.loads(self.path.read_text())
        if state.get("preparation")!=self.descriptor:raise ValueError("durable parent binding changed")
        return state

    def _clock_gate(self,state,*,native=False):
        p=self.preparation;now=_finite(self.clock());mono=_finite(self.monotonic())
        if not p["native_clock_bound"]:
            raise ValueError("parent boot/monotonic remains unbound; execution held")
        if self.boot()!=p["boot_id"] or not p["start_monotonic"]<=mono<p["start_monotonic"]+3600:
            raise ValueError("immutable parent boot/monotonic deadline")
        if not p["start_epoch"]<=now<p["deadline_epoch"]:
            raise ValueError("immutable parent UTC deadline")
        if now<state.get("last_epoch",now) or mono<state.get("last_monotonic",mono):
            raise ValueError("parent clock moved backwards")
        if native and (now+180>p["source_cutoff_epoch"] or mono+180>p["start_monotonic"]+2400):
            raise ValueError("immutable native admission cutoff")
        return now,mono

    def status(self,adapter):
        if type(adapter) is not RealAdapter:raise TypeError("sealed production adapter required")
        state=self._state();rows=adapter.states(self.preparation)
        observed=inventory(self.preparation)
        return dict(schema=STATE,preparation=self.descriptor,windows=rows,intents=state["intents"],
            accounting=adapter.accounting(self.preparation),inventory=observed,next=select_next(self.preparation,rows,self.clock()),
            stop_reason=state["stop_reason"],archived=self.clock()>=self.preparation["deadline_epoch"])

    def step(self,adapter,action_ref):
        if type(adapter) is not RealAdapter:raise TypeError("sealed production adapter required")
        action=load(self.root,_descriptor(action_ref,ACTION),contract=ACTION)
        if action.get("preparation")!=self.descriptor:raise ValueError("action parent mismatch")
        with controller_lock(self.path.with_suffix(".lock")):
            state=self._state()
            if not _inventoried(adapter.native.root,self.preparation["output_roots"]) or (
                    adapter.mapping is not None and not _inventoried(adapter.mapping.root,self.preparation["output_roots"])):
                raise ValueError("all active Store roots must be inventoried")
            inventory(self.preparation)
            if self.preparation.get("source_reuse_contract") is not None:
                raise ValueError("ordered source reuse FD transport is not implemented; execution held")
            require_larger_runtime(self.preparation)
            if state["stop_reason"]:return dict(state="stopped",reason=state["stop_reason"])
            previous=next((x for x in state["intents"] if x["action"]==action_ref),None)
            if previous:
                return previous.get("outcome",dict(state="recovery_required",reason="durable interrupted admission"))
            if any("outcome" not in x for x in state["intents"]):
                return dict(state="recovery_required",reason="unresolved durable admission")
            adapter.accounting(self.preparation)
            rows=adapter.states(self.preparation);decision=select_next(self.preparation,rows,self.clock())
            if state.get("native_fenced") and decision.get("stage") in {"acquire","qualify"}:
                waiting=[i for i,row in enumerate(rows) if row.get("qualify")=="done" and row.get("map") not in TERMINAL]
                decision=dict(state="ready",stage="map",index=waiting[0]) if waiting else dict(state="native_fenced")
            if decision["state"]!="ready":return decision
            if action.get("stage")!=decision["stage"] or action.get("index")!=decision["index"]:
                raise ValueError("action differs from current bounded ordered decision")
            # Refuse proposed native authority before even writing an admission intent.
            if decision["stage"] in {"acquire","qualify"} and "review_hold" not in action:
                if not self.preparation["source_allowance_sufficient"]:
                    raise ValueError("parent source allowance remains insufficient")
                grant=metadata_document(adapter.native.root,_descriptor(action["released_grant"],"coastal-authenticated-policy-v1"),"coastal-authenticated-policy-v1")
                if grant.get("execution_authorized") is not True:raise ValueError("source grant remains proposed/held")
            now,mono=self._clock_gate(state,native=decision["stage"] in {"acquire","qualify"} and "review_hold" not in action)
            adapter.preflight(self.preparation,decision,action)
            state.update(last_epoch=now,last_monotonic=mono)
            intent=dict(action=action_ref,decision=decision,created_epoch=now,created_monotonic=mono)
            state["intents"].append(intent);self._save_state(state)
            try:
                job,store=adapter.submit(self.preparation,decision,action)
                intent["job_id"]=job;intent["store_path"]=str(store.path);self._save_state(state)
                existing=store.db.execute("SELECT state FROM jobs WHERE job_id=?",(job,)).fetchone()[0]
                if existing in TERMINAL:outcome=dict(state=existing,job_id=job,reused=True)
                elif existing=="queued":
                    outcome=Coordinator(store,clock=self.clock).tick(until=self.preparation["deadline_epoch"],job_id=job)
                    current=store.db.execute("SELECT state,holds_json FROM jobs WHERE job_id=?",(job,)).fetchone()
                    if outcome.get("state")=="idle" and current["state"]=="held":
                        outcome=dict(state="held",job_id=job,holds=json.loads(current["holds_json"]))
                    if outcome.get("job_id")!=job:raise ValueError("coordinator dispatched unrelated job")
                else:outcome=dict(state="recovery_required",job_id=job)
                intent["outcome"]=outcome
                adapter.accounting(self.preparation)
                intent["inventory"]=inventory(self.preparation)
                if outcome["state"] in COMMON_STOP:state["stop_reason"]=outcome["state"]
                if outcome["state"]=="held":
                    held=store.db.execute("SELECT holds_json FROM jobs WHERE job_id=?",(job,)).fetchone()
                    holds=json.loads(held["holds_json"])
                    local={"native_support_empty","bounded_patch_nominal_support_incomplete",
                        "bounded_patch_nominal_depth_out_of_range","bounded_patch_uncertainty_quality_failed"}
                    record=json.loads(store.db.execute("SELECT record_json FROM jobs WHERE job_id=?",(job,)).fetchone()[0])
                    if record.get("hold_scope")=="common_source" or not holds or any(h not in local for h in holds):
                        state["stop_reason"]="common_hold"
                    intent["measurement_credited"]=False
                self._save_state(state);return outcome
            except BaseException as exc:
                state["stop_reason"]="conservative_interrupted_or_contract_failure"
                intent["failure"]=type(exc).__name__+":"+str(exc);self._save_state(state)
                raise

    def recover_mapping(self,adapter,job_id,recovery_ref):
        """Explicit stopped-lease proof only; never recover or retry a native job."""
        if type(adapter) is not RealAdapter or not adapter.mapping:raise TypeError("real mapping Store required")
        if self.preparation.get("source_reuse_contract") is not None:
            raise ValueError("ordered source reuse FD transport is not implemented; execution held")
        require_larger_runtime(self.preparation)
        with controller_lock(self.path.with_suffix(".lock")):
            state=self._state()
            if not _inventoried(adapter.native.root,self.preparation["output_roots"]) or not _inventoried(adapter.mapping.root,self.preparation["output_roots"]):
                raise ValueError("all active Store roots must be inventoried")
            inventory(self.preparation)
            now,mono=self._clock_gate(state)
            intents=[i for i in state["intents"] if i.get("job_id")==job_id and i["decision"]["stage"]=="map"]
            if len(intents)!=1:raise ValueError("exact interrupted source-free intent required")
            if str(adapter.mapping.path)!=intents[0]["store_path"]:
                raise ValueError("recovery Store differs from durable source-free intent")
            adapter.accounting(self.preparation)
            state.update(last_epoch=now,last_monotonic=mono)
            from .source_free import recover_completion
            changed=recover_completion(adapter.mapping,job_id,recovery_ref)
            job=adapter.mapping.db.execute("SELECT state FROM jobs WHERE job_id=?",(job_id,)).fetchone()
            if job["state"]!="done":raise ValueError("only proven completed source-free recovery accepted")
            intents[0]["outcome"]=dict(state="done",job_id=job_id,recovered=True,recovery=recovery_ref)
            # Preserve historical failure; only source-free drain may continue.
            state["stop_reason"]=None;state["native_fenced"]=True;state["inventory"]=inventory(self.preparation);self._save_state(state)
            return dict(recovered=changed,native_fenced=True)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare",))
    parser.add_argument("--root",required=True)
    parser.add_argument("--grant-ref",required=True,help="JSON descriptor, not source bytes")
    parser.add_argument("--requests",required=True,help="JSON list of four descriptors")
    parser.add_argument("--start-epoch",type=float,required=True)
    parser.add_argument("--deadline-epoch",type=float,required=True)
    parser.add_argument("--cumulative-limit-bytes",type=int,required=True)
    parser.add_argument("--prior-effective-bytes",type=int,required=True)
    parser.add_argument("--start-monotonic",type=float)
    parser.add_argument("--boot-id")
    a=parser.parse_args(argv)
    print(json.dumps(prepare(a.root,json.loads(a.grant_ref),json.loads(a.requests),
        start_epoch=a.start_epoch,deadline_epoch=a.deadline_epoch,
        cumulative_limit_bytes=a.cumulative_limit_bytes,prior_effective_bytes=a.prior_effective_bytes,
        start_monotonic=a.start_monotonic,boot_id=a.boot_id),sort_keys=True))
    return 0

if __name__=="__main__":raise SystemExit(main())
