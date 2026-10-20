"""Prospective four128 metadata outside the managed mission. No runtime authority."""
import argparse,copy,json,sys,time
from pathlib import Path

# Project root from the operator's home (no literal home path: scripts/check_repository.py).
B=Path.home()/"skippercast-data"/"2026-10-07-pge-south"
W=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(W/"src"),str(B/"work/combined-coastal-integration-20261009/var/python-integration-dependencies"),str(Path(__file__).resolve().parent)]
from coastal_four128_resources import budget_limits,FRESH_SOURCE
from skippercast.coastal.handoff.common import ref,write,load
from skippercast.coastal.coordinator.loop import implementation_hashes
from skippercast.coastal.coordinator.packet_release import build_acquisition_package,validate_acquisition_package
from skippercast.coastal.coordinator.ordered_trial import LARGER_SCOPE,LARGER_RUNTIME,LARGER_WINDOWS
from skippercast.coastal.output_writer import declaration,COMPACT_V3_PROFILE

def main():
 a=argparse.ArgumentParser()
 a.add_argument("--staging-root",type=Path,required=True)
 a.add_argument("--mission-root",type=Path,required=True)
 # Fresh independent four128 role documents (scope, rights, strict trial policy,
 # scientific preflight). The expired 2026-10-11 copies are never re-admitted.
 a.add_argument("--evidence-root",type=Path,required=True)
 # Retained-output authority is an owner decision: no defaults.
 a.add_argument("--cumulative-cap-bytes",type=int,required=True)
 a.add_argument("--prior-retained-bytes",type=int,required=True)
 # Cumulative source-read and scratch accounting: one signed delegated-authority
 # amendment that carries the failed 2026-10-11 charges. No defaults, no constants.
 a.add_argument("--budget-amendment",type=Path,required=True)
 a.add_argument("--prospective-released-bytes",action="store_true")
 x=a.parse_args()
 root=x.staging_root.absolute();mission=x.mission_root.absolute()
 if (not root.is_relative_to(B/"scratch") or root.exists() or mission.exists()
     or not mission.is_relative_to(B/"outputs") or root.is_relative_to(mission)):
  raise ValueError("fresh external scratch metadata stage and absent future mission required")
 historical=B/"outputs/source-reuse-admission-engineering-20261011"
 evidence=x.evidence_root.absolute()
 if evidence==historical or not evidence.is_dir() or evidence.is_symlink():
  raise ValueError("fresh independent evidence root required; expired 2026-10-11 documents are not re-admitted")
 retention=declaration(x.prior_retained_bytes,x.cumulative_cap_bytes,profile=COMPACT_V3_PROFILE)
 amendment_path=x.budget_amendment.absolute()
 if amendment_path.is_symlink() or not amendment_path.is_file():
  raise ValueError("signed budget amendment file required")
 limits=budget_limits(json.loads(amendment_path.read_text()))
 prior,limit=limits["source_prior_bytes"],limits["source_limit_bytes"]
 root.mkdir(parents=True)
 old=B/"outputs/ordered-coastal-rehearsed-live-20261010/execution/metadata"
 def put(name,doc):
  path=root/"metadata"/name
  if path.exists():raise ValueError("preserve metadata candidate")
  write(path,doc);return ref(root,path,doc["schema"])
 def copy_role(name,base=evidence):
  source=base/name
  if source.is_symlink():raise ValueError("evidence link")
  doc=json.loads(source.read_text())
  path=root/"metadata"/name;path.parent.mkdir(parents=True,exist_ok=True)
  path.write_bytes(source.read_bytes())
  return ref(root,path,doc["schema"])
 # Segment geometry and the budget arithmetic are retained facts, not expiring reviews.
 segment=copy_role("independent-four128-segment.json",historical)
 scope=copy_role("independent-four128-scope-review.json")
 rights=copy_role("independent-four128-rights-review.json")
 trial=copy_role("independent-four128-strict-trial-policy.json")
 science=copy_role("independent-four128-scientific-preflight.json")
 arithmetic=copy_role("approved-trial-budget-arithmetic-v1.json",historical)
 amendment=copy_role(amendment_path.name,amendment_path.parent)
 code,deps=implementation_hashes(root)
 carry=put("carry.json",dict(schema="coastal-authenticated-carry-v1",
  cumulative_limit_bytes=limit,prior_effective_bytes=prior,
  remaining_bytes=limit-prior,synthetic=False,refunds=False,budget_amendment=amendment,
  meaning="New eight-copy authority; failed 2026-10-11 charges carried, previous settled ledgers preserved. No clock or source reservation."))
 grant=json.loads((old/"grant-real-released.json").read_text())
 for field in ("owner_authorization","carry","meaning","independent_preflight"):
  grant.pop(field,None)
 grant.update(execution_authorized=False,code_sha=code,deps_sha=deps,
  ordered_scope_contract=LARGER_SCOPE,larger_runtime_contract=LARGER_RUNTIME,
  window_side=128,window_count=4,window_set=copy.deepcopy(LARGER_WINDOWS),
  geographic_review=scope,independent_preflight=science,carry=carry,
  source_volume_cap_bytes=FRESH_SOURCE,prior_effective_bytes=prior,
  prior_effective_source_bytes=prior,cumulative_limit_bytes=limit,
  approved_budget_arithmetic=arithmetic,approved_budget_amendment=amendment,
  output_retention=retention,
  output_root=str(mission),publication=False,
  meaning="Prospective approved four128 native-grid target. Source and all pixel quality remain unverified; no historical-support promotion.")
 held=put("grant-held.json",grant)
 seg=load(root,segment);scope_doc=load(root,scope)
 templates=[]
 for label,window in zip("ABCD",LARGER_WINDOWS):
  packet=json.loads((old/("acquire_"+label+"_real_released.json")).read_text())
  col,row,side,_=window
  safety=scope_doc["safety_bbox_native"]
  packet["fixed_center_plan"]=dict(schema="coastal-contained-native-window-spec-v3",
   source_sha256=grant["source"]["sha256"],execution_profile=grant["execution_profile"],
   ordered_scope_contract=LARGER_SCOPE,scope_basis="new_native_grid_target",
   historical_support_qualified=False,native_interest=dict(crs="EPSG:26910",bbox=safety),
   center_native=[721091+2*(col+side/2),3826155-2*(row+side/2)],
   native_window=window,window_side=side,window_count=4,window_shape=[side,side],
   halo=0,minimum_margin_m=0.1,safety_bbox_native=safety,segment=seg)
  packet.update(execution_authorized=False,window_side=128,window_count=4,
   independent_preflight=science)
  packet["source_row"]["notes"]="Retained original source provenance only; new four128 pixels unobserved, no habitat or continuous coverage claim."
  templates.append(put("template-"+label+".json",packet))
 now=time.time()
 package=build_acquisition_package(root,held,templates,rights=[rights],trial=trial,segment=segment,
  now=now,horizon=now+3600,prefix="held-four128")
 if package["status"]!="PASS_METADATA_ONLY":raise ValueError(package)
 finalgrant=held;requests=package["requests"];validation=package["validation"]
 if x.prospective_released_bytes:
  grant["execution_authorized"]=True;finalgrant=put("grant-prospective-released.json",grant)
  requests=[]
  for label,d in zip("ABCD",package["requests"]):
   packet=load(root,d);packet["execution_authorized"]=True
   requests.append(put("acquire-"+label+"-prospective-released.json",packet))
  now=time.time()
  checked=validate_acquisition_package(root,finalgrant,requests,now=now,horizon=now+3600,validation_mode="released")
  validation=put("prospective-released-validation.json",checked)
  if checked["status"]!="PASS_METADATA_ONLY":raise ValueError(checked)
 index=put("prospective-index.json",dict(schema="coastal-ordered-live-index-v1",
  grant=finalgrant,requests=requests,carry=carry,independent_preflight=science,
  code_sha=code,deps_sha=deps,release_validator=validation,
  source_volume_cap_bytes=FRESH_SOURCE,prior_effective_bytes=prior,
  cumulative_limit_bytes=limit,budget_amendment=amendment,
  prior_scratch_bytes=limits["scratch_prior_bytes"],scratch_limit_bytes=limits["scratch_limit_bytes"],synthetic=False,
  runtime_review_pending=True,execution_authorized=False,
  status="PROSPECTIVE_ONLY_NO_RUNTIME_AUTHORITY"))
 catalog=[]
 for path in sorted((root/"metadata").iterdir()):
  doc=json.loads(path.read_text());catalog.append(ref(root,path,doc["schema"]))
 out=dict(schema="coastal-four128-prospective-package-v1",status="PASS_METADATA_ONLY",
  staging_root=str(root),mission_root=str(mission),index=index,files=catalog,
  initial_metadata_bytes=sum(d["bytes"] for d in catalog),
  acquisition_packet_bytes=[d["bytes"] for d in requests],
  source_row_preserved_fields=sorted(load(root,requests[0])["source_row"]),
  runtime_review_pending=True,managed_ledger_created=False,Store_created=False,Budget_created=False,
  clocks_created=False,units_started=0,original_source_reads=0)
 write(root/"prospective-package.json",out)
 print(json.dumps(out,sort_keys=True))

if __name__=="__main__":main()
